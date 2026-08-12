from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .core_repository import CoreRepository
from .image_processing import NormalizedImage
from .jobs import enqueue_job
from .models import (
    HealthAnalysis,
    HealthDailySummary,
    HealthRecord,
    StoredObject,
    WaterEntry,
    WeightEntry,
    WorkspaceSettings,
)
from .storage import LocalPrivateObjectStore


MEAL_LABELS = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "afternoon_tea": "下午茶",
    "dinner": "晚餐",
    "snack": "零食",
    "late_night": "夜宵",
}
MEAL_SLOT_TIMES = {
    "breakfast": "08:00:00",
    "lunch": "12:30:00",
    "afternoon_tea": "15:30:00",
    "dinner": "18:30:00",
    "snack": "20:00:00",
    "late_night": "22:30:00",
}
ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
}


def _float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def compact_history_points(points: list[dict], water_target: int) -> tuple[str, list[dict]]:
    """Keep long-range chart payloads bounded without changing full-range metrics."""
    if len(points) <= 120:
        return "day", points
    granularity = "week" if len(points) <= 730 else "month"
    grouped: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        point_date = date.fromisoformat(point["date"])
        key = (
            f"{point_date.isocalendar().year}-W{point_date.isocalendar().week:02d}"
            if granularity == "week"
            else point["date"][:7]
        )
        grouped[key].append(point)
    display_points: list[dict] = []
    for group_points in grouped.values():
        group_weights = [item["weight_kg"] for item in group_points if item["weight_kg"] is not None]
        display_points.append(
            {
                "date": group_points[-1]["date"],
                "period_start": group_points[0]["date"],
                "period_end": group_points[-1]["date"],
                "water_ml": round(sum(item["water_ml"] for item in group_points) / len(group_points)),
                "water_target_ml": water_target,
                "weight_kg": group_weights[-1] if group_weights else None,
                "calories_kcal": round(
                    sum(item["calories_kcal"] for item in group_points) / len(group_points)
                ),
                "exercise_kcal": sum(item["exercise_kcal"] for item in group_points),
                "meal_count": sum(item["meal_count"] for item in group_points),
                "has_record": any(item["has_record"] for item in group_points),
            }
        )
    return granularity, display_points


class HealthRepository:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: int,
        workspace_public_id: uuid.UUID,
        actor_type: str,
        actor_public_id: uuid.UUID | None,
        timezone_name: str = "Asia/Shanghai",
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.workspace_public_id = workspace_public_id
        self.timezone_name = timezone_name
        self.core = CoreRepository(
            session,
            workspace_id,
            actor_type,
            actor_public_id,
            timezone_name,
        )

    def now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone_name))

    @staticmethod
    def _round_to_50(value: float) -> int:
        return int(round(value / 50) * 50)

    @classmethod
    def calculate_health_plan(
        cls,
        gender: str,
        height_cm: float,
        current_weight_kg: float,
        target_weight_kg: float,
        cup_ml: int,
        age: int | None = None,
        activity_level: str | None = None,
    ) -> dict[str, Any]:
        ages = [age] if age is not None else [25, 55]
        factors = [ACTIVITY_FACTORS[activity_level]] if activity_level else [1.2, 1.375]
        sex_adjustment = 5 if gender == "male" else -161
        estimates: list[int] = []
        for candidate_age in ages:
            resting_energy = 10 * current_weight_kg + 6.25 * height_cm - 5 * candidate_age + sex_adjustment
            for factor in factors:
                maintenance = resting_energy * factor
                deficit = min(500, max(200, maintenance * 0.15)) if current_weight_kg > target_weight_kg else 0
                estimates.append(cls._round_to_50(max(resting_energy, maintenance - deficit)))
        calorie_min = min(estimates)
        calorie_max = max(estimates)
        water_target = cls._round_to_50(max(1500, min(4000, current_weight_kg * 35)))
        missing = [label for value, label in ((age, "年龄"), (activity_level, "日常活动量")) if value is None]
        return {
            "gender": gender,
            "height_cm": height_cm,
            "current_weight_kg": current_weight_kg,
            "target_weight_kg": target_weight_kg,
            "cup_ml": cup_ml,
            "age": age,
            "activity_level": activity_level,
            "calories_target_kcal": cls._round_to_50((calorie_min + calorie_max) / 2),
            "calories_target_min_kcal": calorie_min,
            "calories_target_max_kcal": calorie_max,
            "calculation_mode": "reference_range" if missing else "personalized",
            "calculation_note": (
                f"未填写{'和'.join(missing)}，先给出参考区间；补充后会收窄估算。"
                if missing
                else "已结合年龄与活动量估算，建议根据连续 2–4 周体重趋势调整。"
            ),
            "exercise_target_minutes_week": 150,
            "strength_target_days_week": 2,
            "water_target_ml": water_target,
            "cups_per_day": round(water_target / cup_ml, 1),
        }

    async def settings(self) -> WorkspaceSettings:
        record = await self.session.scalar(
            select(WorkspaceSettings).where(WorkspaceSettings.workspace_id == self.workspace_id)
        )
        if record is None:
            raise KeyError("workspace_settings")
        return record

    async def update_goals(self, **values: Any) -> dict:
        plan = self.calculate_health_plan(**values)
        settings = await self.settings()
        settings.health = plan
        self.core._changed("health.goals_updated", "workspace_settings", str(self.workspace_public_id), "update_health_goals")
        await self.record_weight(values["current_weight_kg"], source=self.core.actor_type)
        return plan

    async def _mark_day_stale(self, target_date: date) -> None:
        statement = (
            insert(HealthDailySummary)
            .values(
                public_id=uuid.uuid4(),
                workspace_id=self.workspace_id,
                summary_date=target_date,
                stale=True,
            )
            .on_conflict_do_update(
                constraint="health_daily_summaries_workspace_date_key",
                set_={"stale": True, "updated_at": func.now()},
            )
        )
        await self.session.execute(statement)

    @staticmethod
    def _weight_payload(entry: WeightEntry) -> dict:
        return {
            "id": str(entry.public_id),
            "record_date": entry.record_date.isoformat(),
            "occurred_at": entry.occurred_at.isoformat(),
            "weight_kg": _float(entry.weight_kg),
            "source": entry.source,
            "deleted": entry.deleted_at is not None,
            "created_at": entry.created_at.isoformat(),
        }

    async def record_water(self, amount_ml: int, source: str = "user") -> dict:
        if not 1 <= amount_ml <= 5000:
            raise ValueError("单次饮水量必须在 1–5000 ml 之间")
        now = self.now()
        self.session.add(
            WaterEntry(
                workspace_id=self.workspace_id,
                record_date=now.date(),
                occurred_at=now,
                amount_ml=amount_ml,
                source=source,
            )
        )
        await self._mark_day_stale(now.date())
        self.core._changed("health.water_recorded", "water_entry", now.isoformat(), "record_water")
        await self.session.flush()
        return await self.today_overview(now.date())

    async def record_weight(
        self,
        weight_kg: float,
        source: str = "user",
        record_date: date | None = None,
    ) -> dict:
        if not 20 < weight_kg <= 400:
            raise ValueError("体重必须在 20–400 kg 之间")
        now = self.now()
        target_date = record_date or now.date()
        if target_date > now.date():
            raise ValueError("不能记录未来日期的体重")
        occurred_at = (
            now
            if target_date == now.date()
            else datetime.combine(target_date, time(hour=12), tzinfo=ZoneInfo(self.timezone_name))
        )
        entry = WeightEntry(
            workspace_id=self.workspace_id,
            record_date=target_date,
            occurred_at=occurred_at,
            weight_kg=Decimal(str(weight_kg)),
            source=source,
        )
        self.session.add(entry)
        await self._mark_day_stale(target_date)
        await self.session.flush()
        self.core._changed("health.weight_recorded", "weight_entry", str(entry.public_id), "record_weight")
        overview = await self.today_overview(target_date)
        return {**overview, "entry": self._weight_payload(entry)}

    async def list_weight_entries(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        if not 1 <= limit <= 500:
            raise ValueError("体重记录条数必须在 1–500 之间")
        if start_date and end_date and start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        conditions = [WeightEntry.workspace_id == self.workspace_id]
        if start_date:
            conditions.append(WeightEntry.record_date >= start_date)
        if end_date:
            conditions.append(WeightEntry.record_date <= end_date)
        if not include_deleted:
            conditions.append(WeightEntry.deleted_at.is_(None))
        entries = list(
            await self.session.scalars(
                select(WeightEntry)
                .where(*conditions)
                .order_by(WeightEntry.record_date.desc(), WeightEntry.occurred_at.desc(), WeightEntry.id.desc())
                .limit(limit)
            )
        )
        return [self._weight_payload(entry) for entry in entries]

    async def get_weight_entry(self, public_id: uuid.UUID, include_deleted: bool = True) -> dict:
        conditions = [
            WeightEntry.workspace_id == self.workspace_id,
            WeightEntry.public_id == public_id,
        ]
        if not include_deleted:
            conditions.append(WeightEntry.deleted_at.is_(None))
        entry = await self.session.scalar(select(WeightEntry).where(*conditions))
        if entry is None:
            raise KeyError(str(public_id))
        return self._weight_payload(entry)

    async def set_weight_entry_deleted(self, public_id: uuid.UUID, deleted: bool) -> dict:
        entry = await self.session.scalar(
            select(WeightEntry).where(
                WeightEntry.workspace_id == self.workspace_id,
                WeightEntry.public_id == public_id,
            )
        )
        if entry is None:
            raise KeyError(str(public_id))
        entry.deleted_at = datetime.now(timezone.utc) if deleted else None
        await self._mark_day_stale(entry.record_date)
        self.core._changed(
            "health.weight_deleted" if deleted else "health.weight_restored",
            "weight_entry",
            str(public_id),
            "delete_weight_entry" if deleted else "restore_weight_entry",
        )
        await self.session.flush()
        return self._weight_payload(entry)

    async def today_overview(self, target_date: date | None = None) -> dict:
        target_date = target_date or self.now().date()
        settings = await self.settings()
        health = dict(settings.health)
        water_ml = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(WaterEntry.amount_ml), 0)).where(
                    WaterEntry.workspace_id == self.workspace_id,
                    WaterEntry.record_date == target_date,
                    WaterEntry.deleted_at.is_(None),
                )
            )
            or 0
        )
        weight = await self.session.scalar(
            select(WeightEntry.weight_kg)
            .where(
                WeightEntry.workspace_id == self.workspace_id,
                WeightEntry.record_date <= target_date,
                WeightEntry.deleted_at.is_(None),
            )
            .order_by(WeightEntry.occurred_at.desc(), WeightEntry.id.desc())
            .limit(1)
        )
        target_water = int(health.get("water_target_ml", 2000))
        target_weight = health.get("target_weight_kg")
        current_weight = _float(weight) if weight is not None else health.get("current_weight_kg")
        start_weight = health.get("current_weight_kg")
        distance = (
            round(float(current_weight) - float(target_weight), 2)
            if current_weight is not None and target_weight is not None
            else None
        )
        total_distance = (
            float(start_weight) - float(target_weight)
            if start_weight is not None and target_weight is not None
            else 0
        )
        progress = (
            max(0, min(100, round((float(start_weight) - float(current_weight)) / total_distance * 100)))
            if current_weight is not None and total_distance > 0
            else 0
        )
        return {
            "water_ml": water_ml,
            "water_target_ml": target_water,
            "water_percent": min(round(water_ml / target_water * 100), 100) if target_water else 0,
            "weight_kg": current_weight,
            "target_weight_kg": target_weight,
            "start_weight_kg": start_weight,
            "distance_to_goal_kg": distance,
            "weight_goal_percent": progress,
            "cup_ml": health.get("cup_ml", 250),
            **health,
        }

    async def create_upload(
        self,
        kind: str,
        original_filename: str,
        normalized: NormalizedImage,
        object_store: LocalPrivateObjectStore,
        idempotency_key: str,
        record_date: date,
        meal_slot: str | None,
        source: str = "user",
    ) -> dict:
        if kind not in {"meal", "weight", "exercise"}:
            raise ValueError("不支持的健康记录类型")
        stored_kind = "weight_photo" if kind == "weight" else kind
        if stored_kind == "meal":
            if meal_slot not in MEAL_LABELS:
                raise ValueError("请选择正确的餐次")
        else:
            meal_slot = None
        existing = await self.session.scalar(
            select(HealthRecord).where(
                HealthRecord.workspace_id == self.workspace_id,
                HealthRecord.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return await self.get_record(existing.public_id, include_deleted=True)

        display_public_id = uuid.uuid4()
        thumbnail_public_id = uuid.uuid4()
        display_key = object_store.build_key(
            self.workspace_public_id, display_public_id, normalized.content_type
        )
        thumbnail_key = object_store.build_key(
            self.workspace_public_id, thumbnail_public_id, normalized.content_type
        )
        display_result = object_store.put_bytes(display_key, normalized.display_content)
        thumbnail_result = object_store.put_bytes(thumbnail_key, normalized.thumbnail_content)
        safe_name = Path(original_filename).name[:255] or "health-image"
        display_object = StoredObject(
            public_id=display_public_id,
            workspace_id=self.workspace_id,
            object_key=display_key,
            original_filename=safe_name,
            content_type=normalized.content_type,
            size_bytes=display_result.size_bytes,
            sha256=display_result.sha256,
            status="ready",
        )
        thumbnail_object = StoredObject(
            public_id=thumbnail_public_id,
            workspace_id=self.workspace_id,
            object_key=thumbnail_key,
            original_filename=f"thumbnail-{safe_name}",
            content_type=normalized.content_type,
            size_bytes=thumbnail_result.size_bytes,
            sha256=thumbnail_result.sha256,
            status="ready",
        )
        self.session.add_all([display_object, thumbnail_object])
        await self.session.flush()
        local_time = MEAL_SLOT_TIMES.get(meal_slot or "", "12:00:00")
        occurred_at = datetime.fromisoformat(f"{record_date.isoformat()}T{local_time}").replace(
            tzinfo=ZoneInfo(self.timezone_name)
        )
        record = HealthRecord(
            workspace_id=self.workspace_id,
            idempotency_key=idempotency_key,
            kind=stored_kind,
            record_date=record_date,
            occurred_at=occurred_at,
            meal_slot=meal_slot,
            object_id=display_object.id,
            thumbnail_object_id=thumbnail_object.id,
            source=source,
        )
        self.session.add(record)
        await self.session.flush()
        await enqueue_job(
            self.session,
            self.workspace_id,
            "health_image_analysis",
            "health_record",
            str(record.public_id),
            f"分析 {record_date.isoformat()} 的健康图片",
            f"health-analysis:{record.public_id}",
            {
                "record_id": str(record.public_id),
                "kind": stored_kind,
                "record_date": record_date.isoformat(),
                "meal_slot": meal_slot,
            },
        )
        await self._mark_day_stale(record_date)
        self.core._changed(
            "health.record_uploaded",
            "health_record",
            str(record.public_id),
            "upload_health_record",
            {"analysis_status": "queued", "kind": stored_kind},
        )
        return await self.get_record(record.public_id)

    async def _record_rows(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        include_deleted: bool = False,
        public_id: uuid.UUID | None = None,
        kind: str | None = None,
        status: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> list[tuple]:
        display_object = aliased(StoredObject)
        thumbnail_object = aliased(StoredObject)
        statement = (
            select(HealthRecord, HealthAnalysis, display_object, thumbnail_object)
            .outerjoin(
                HealthAnalysis,
                (HealthAnalysis.workspace_id == HealthRecord.workspace_id)
                & (HealthAnalysis.health_record_id == HealthRecord.id),
            )
            .join(display_object, display_object.id == HealthRecord.object_id)
            .join(thumbnail_object, thumbnail_object.id == HealthRecord.thumbnail_object_id)
            .where(HealthRecord.workspace_id == self.workspace_id)
        )
        if start_date is not None:
            statement = statement.where(HealthRecord.record_date >= start_date)
        if end_date is not None:
            statement = statement.where(HealthRecord.record_date <= end_date)
        if public_id is not None:
            statement = statement.where(HealthRecord.public_id == public_id)
        if kind is not None:
            statement = statement.where(HealthRecord.kind == kind)
        if status is not None:
            statement = statement.where(HealthRecord.analysis_status == status)
        if not include_deleted:
            statement = statement.where(HealthRecord.deleted_at.is_(None))
        statement = statement.order_by(HealthRecord.occurred_at.desc(), HealthRecord.id.desc())
        if offset is not None:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        return list((await self.session.execute(statement)).all())

    @staticmethod
    def _record_payload(row: tuple) -> dict:
        record, analysis, display_object, thumbnail_object = row
        meal_label = MEAL_LABELS.get(record.meal_slot, "")
        kind_label = {"meal": meal_label or "饮食", "exercise": "运动", "weight_photo": "体重"}[record.kind]
        analysis_text = analysis.summary if analysis else ""
        advice_text = analysis.advice if analysis else ""
        return {
            "id": str(record.public_id),
            "kind": record.kind,
            "title": f"{record.record_date.month}月{record.record_date.day}日 {kind_label}",
            "original_name": display_object.original_filename,
            "asset": f"objects/{display_object.public_id}",
            "thumbnail_asset": f"objects/{thumbnail_object.public_id}",
            "analysis_status": record.analysis_status,
            "calories_kcal": analysis.calories_kcal if analysis else None,
            "exercise_kcal": analysis.exercise_kcal if analysis else None,
            "weight_kg": _float(analysis.weight_kg) if analysis else None,
            "record_date": record.record_date.isoformat(),
            "recorded_at": record.occurred_at.isoformat(),
            "meal_slot": record.meal_slot,
            "meal_label": meal_label,
            "analysis": "\n\n".join(value for value in (analysis_text, advice_text) if value),
            "analysis_summary": analysis_text,
            "analysis_advice": advice_text,
            "deleted": record.deleted_at is not None,
            "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
        }

    async def get_record(self, public_id: uuid.UUID, include_deleted: bool = False) -> dict:
        rows = await self._record_rows(include_deleted=include_deleted, public_id=public_id)
        if not rows:
            raise KeyError(str(public_id))
        return self._record_payload(rows[0])

    async def list_records(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        include_deleted: bool = False,
        status: str | None = None,
        kind: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        return [
            self._record_payload(row)
            for row in await self._record_rows(
                start_date,
                end_date,
                include_deleted,
                kind=kind,
                status=status,
                limit=limit,
            )
        ]

    async def list_records_page(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        include_deleted: bool = False,
        status: str | None = None,
        kind: str | None = None,
        page: int = 1,
        page_size: int = 8,
    ) -> dict:
        conditions = [HealthRecord.workspace_id == self.workspace_id]
        if start_date is not None:
            conditions.append(HealthRecord.record_date >= start_date)
        if end_date is not None:
            conditions.append(HealthRecord.record_date <= end_date)
        if not include_deleted:
            conditions.append(HealthRecord.deleted_at.is_(None))
        if status is not None:
            conditions.append(HealthRecord.analysis_status == status)
        if kind is not None:
            conditions.append(HealthRecord.kind == kind)
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(HealthRecord).where(*conditions)
            )
            or 0
        )
        rows = await self._record_rows(
            start_date,
            end_date,
            include_deleted,
            kind=kind,
            status=status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return {
            "items": [self._record_payload(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    async def update_record(
        self,
        public_id: uuid.UUID,
        record_date: date | None,
        meal_slot: str | None,
    ) -> dict:
        record = await self.session.scalar(
            select(HealthRecord).where(
                HealthRecord.workspace_id == self.workspace_id,
                HealthRecord.public_id == public_id,
            )
        )
        if record is None:
            raise KeyError(str(public_id))
        original_date = record.record_date
        if record_date is not None:
            record.record_date = record_date
        if record.kind == "meal" and meal_slot is not None:
            if meal_slot not in MEAL_LABELS:
                raise ValueError("餐次无效")
            record.meal_slot = meal_slot
        local_time = MEAL_SLOT_TIMES.get(record.meal_slot or "", record.occurred_at.strftime("%H:%M:%S"))
        record.occurred_at = datetime.fromisoformat(f"{record.record_date.isoformat()}T{local_time}").replace(
            tzinfo=ZoneInfo(self.timezone_name)
        )
        record.updated_at = datetime.now(timezone.utc)
        await self._mark_day_stale(original_date)
        await self._mark_day_stale(record.record_date)
        await enqueue_job(
            self.session,
            self.workspace_id,
            "health_daily_summary_refresh",
            "health_day",
            record.record_date.isoformat(),
            f"重做 {record.record_date.isoformat()} 的健康总结",
            f"health-summary-refresh:{record.record_date}:{record.updated_at.isoformat()}",
            {"record_date": record.record_date.isoformat()},
        )
        self.core._changed("health.record_updated", "health_record", str(public_id), "update_health_record")
        await self.session.flush()
        return await self.get_record(public_id, include_deleted=True)

    async def set_deleted(self, public_id: uuid.UUID, deleted: bool) -> dict:
        record = await self.session.scalar(
            select(HealthRecord).where(
                HealthRecord.workspace_id == self.workspace_id,
                HealthRecord.public_id == public_id,
            )
        )
        if record is None:
            raise KeyError(str(public_id))
        record.deleted_at = datetime.now(timezone.utc) if deleted else None
        record.updated_at = datetime.now(timezone.utc)
        await self._mark_day_stale(record.record_date)
        self.core._changed(
            "health.record_deleted" if deleted else "health.record_restored",
            "health_record",
            str(public_id),
            "delete_health_record" if deleted else "restore_health_record",
        )
        await self.session.flush()
        return await self.get_record(public_id, include_deleted=True)

    async def analyze_record(
        self,
        public_id: uuid.UUID,
        summary: str,
        advice: str = "",
        calories_kcal: int | None = None,
        exercise_kcal: int | None = None,
        weight_kg: float | None = None,
        model_name: str | None = None,
    ) -> dict:
        record = await self.session.scalar(
            select(HealthRecord).where(
                HealthRecord.workspace_id == self.workspace_id,
                HealthRecord.public_id == public_id,
                HealthRecord.deleted_at.is_(None),
            )
        )
        if record is None:
            raise KeyError(str(public_id))
        analysis = await self.session.scalar(
            select(HealthAnalysis).where(
                HealthAnalysis.workspace_id == self.workspace_id,
                HealthAnalysis.health_record_id == record.id,
            )
        )
        if analysis is None:
            analysis = HealthAnalysis(
                workspace_id=self.workspace_id,
                health_record_id=record.id,
                summary=summary.strip(),
            )
            self.session.add(analysis)
        analysis.summary = summary.strip()
        analysis.advice = advice.strip()
        analysis.calories_kcal = calories_kcal
        analysis.exercise_kcal = exercise_kcal
        analysis.weight_kg = Decimal(str(weight_kg)) if weight_kg is not None else None
        analysis.model_name = model_name
        analysis.updated_at = datetime.now(timezone.utc)
        record.analysis_status = "analyzed"
        record.failure_code = None
        record.updated_at = datetime.now(timezone.utc)
        await self._mark_day_stale(record.record_date)
        await enqueue_job(
            self.session,
            self.workspace_id,
            "health_daily_summary_refresh",
            "health_day",
            record.record_date.isoformat(),
            f"更新 {record.record_date.isoformat()} 的全天健康总结",
            f"health-summary-after-analysis:{record.public_id}",
            {"record_date": record.record_date.isoformat()},
        )
        self.core._changed(
            "health.record_analyzed",
            "health_record",
            str(public_id),
            "analyze_health_record",
            {"analysis_status": "analyzed"},
        )
        await self.session.flush()
        return await self.get_record(public_id)

    async def save_daily_advice(
        self,
        target_date: date,
        status: str,
        overall_summary: str,
        diet_summary: str,
        hydration_summary: str,
        exercise_summary: str,
        generated_by: str = "hermes",
    ) -> dict:
        if status not in {"on_track", "attention", "celebrate", "neutral"}:
            raise ValueError("健康总结状态无效")
        labels = {
            "overall": "今日结论",
            "diet": "全天饮食",
            "hydration": "饮水进度",
            "exercise": "运动总结",
        }
        values = {
            "overall": overall_summary.strip(),
            "diet": diet_summary.strip(),
            "hydration": hydration_summary.strip(),
            "exercise": exercise_summary.strip(),
        }
        sections = {
            "overall_summary": values["overall"],
            "diet_summary": values["diet"],
            "hydration_summary": values["hydration"],
            "exercise_summary": values["exercise"],
            "sections": [
                {"key": key, "label": labels[key], "content": content}
                for key, content in values.items()
                if content
            ],
        }
        one_day = await self.history(target_date, target_date)
        point = one_day["points"][0]
        day_records = one_day["records"]
        thumbnail_ids = [
            item["thumbnail_asset"].split("/")[-1]
            for item in day_records[:3]
            if item.get("thumbnail_asset")
        ]
        record = await self.session.scalar(
            select(HealthDailySummary).where(
                HealthDailySummary.workspace_id == self.workspace_id,
                HealthDailySummary.summary_date == target_date,
            )
        )
        if record is None:
            record = HealthDailySummary(workspace_id=self.workspace_id, summary_date=target_date)
            self.session.add(record)
        record.weight_kg = Decimal(str(point["weight_kg"])) if point["weight_kg"] is not None else None
        record.water_ml = point["water_ml"]
        record.calories_kcal = point["calories_kcal"]
        record.exercise_kcal = point["exercise_kcal"]
        record.meal_count = point["meal_count"]
        record.photo_count = len(day_records)
        record.status = status
        record.sections = sections
        record.thumbnail_object_ids = thumbnail_ids
        record.stale = False
        record.revision = (record.revision or 0) + 1
        record.generated_by = generated_by
        record.generated_at = datetime.now(timezone.utc)
        record.updated_at = record.generated_at
        self.core._changed(
            "health.daily_summary_updated",
            "health_day",
            target_date.isoformat(),
            "save_daily_health_advice",
            {"status": status},
        )
        await self.session.flush()
        return {"date": target_date.isoformat(), "status": status, **sections}

    async def _history_window(self, start_date: date, end_date: date) -> dict:
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if (end_date - start_date).days > 365:
            raise ValueError("一次最多查看366天")
        water_entries = list(
            (
                await self.session.scalars(
                    select(WaterEntry).where(
                        WaterEntry.workspace_id == self.workspace_id,
                        WaterEntry.record_date.between(start_date, end_date),
                        WaterEntry.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        weight_entries = list(
            (
                await self.session.scalars(
                    select(WeightEntry).where(
                        WeightEntry.workspace_id == self.workspace_id,
                        WeightEntry.record_date.between(start_date, end_date),
                        WeightEntry.deleted_at.is_(None),
                    ).order_by(WeightEntry.occurred_at)
                )
            ).all()
        )
        records = await self.list_records(start_date, end_date)
        summaries = list(
            (
                await self.session.scalars(
                    select(HealthDailySummary).where(
                        HealthDailySummary.workspace_id == self.workspace_id,
                        HealthDailySummary.summary_date.between(start_date, end_date),
                    )
                )
            ).all()
        )
        summary_by_date = {item.summary_date.isoformat(): item for item in summaries}
        water_by_date: dict[str, int] = defaultdict(int)
        for entry in water_entries:
            water_by_date[entry.record_date.isoformat()] += entry.amount_ml
        weight_by_date = {entry.record_date.isoformat(): _float(entry.weight_kg) for entry in weight_entries}
        records_by_date: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            records_by_date[record["record_date"]].append(record)
            if record.get("weight_kg") is not None:
                weight_by_date[record["record_date"]] = record["weight_kg"]
        health_settings = dict((await self.settings()).health)
        water_target = int(health_settings.get("water_target_ml", 2000))
        points: list[dict] = []
        cards: list[dict] = []
        current = start_date
        while current <= end_date:
            day = current.isoformat()
            day_records = records_by_date.get(day, [])
            meals = [item for item in day_records if item["kind"] == "meal"]
            exercises = [item for item in day_records if item["kind"] == "exercise"]
            others = [item for item in day_records if item["kind"] not in {"meal", "exercise"}]
            summary = summary_by_date.get(day)
            calories = sum(item.get("calories_kcal") or 0 for item in meals)
            exercise = sum(item.get("exercise_kcal") or 0 for item in exercises)
            point = {
                "date": day,
                "water_ml": water_by_date.get(day, 0),
                "water_target_ml": water_target,
                "weight_kg": weight_by_date.get(day),
                "calories_kcal": calories,
                "exercise_kcal": exercise,
                "meal_count": len(meals),
                "has_record": bool(day_records or water_by_date.get(day) or day in weight_by_date),
            }
            points.append(point)
            if point["has_record"] or summary is not None:
                cards.append(
                    {
                        **point,
                        "meals": meals,
                        "exercise_records": exercises,
                        "other_records": others,
                        "daily_advice": (
                            {"status": summary.status, **dict(summary.sections)}
                            if summary is not None
                            else None
                        ),
                    }
                )
            current += timedelta(days=1)
        weights = [point["weight_kg"] for point in points if point["weight_kg"] is not None]
        recorded = [point for point in points if point["has_record"]]
        point_granularity, display_points = compact_history_points(points, water_target)
        return {
            "range_days": (end_date - start_date).days + 1,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "point_granularity": point_granularity,
            "points": display_points,
            "metrics": {
                "latest_weight_kg": weights[-1] if weights else None,
                "weight_change_kg": round(weights[-1] - weights[0], 2) if len(weights) >= 2 else 0,
                "average_water_ml": round(sum(point["water_ml"] for point in points) / len(points)) if points else 0,
                "average_calories_kcal": round(sum(point["calories_kcal"] for point in points) / len(points)) if points else 0,
                "exercise_total_kcal": sum(point["exercise_kcal"] for point in points),
                "recorded_days": len(recorded),
            },
            "records": records,
            "daily_cards": list(reversed(cards)),
        }

    async def history(self, start_date: date, end_date: date) -> dict:
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if (end_date - start_date).days > 3660:
            raise ValueError("一次最多查看十年（3661天）")

        recent_start = max(start_date, end_date - timedelta(days=13))
        recent = await self._history_window(recent_start, end_date)

        water_rows = list(
            (
                await self.session.execute(
                    select(WaterEntry.record_date, func.sum(WaterEntry.amount_ml))
                    .where(
                        WaterEntry.workspace_id == self.workspace_id,
                        WaterEntry.record_date.between(start_date, end_date),
                        WaterEntry.deleted_at.is_(None),
                    )
                    .group_by(WaterEntry.record_date)
                )
            ).all()
        )
        weight_rows = list(
            (
                await self.session.execute(
                    select(WeightEntry.record_date, WeightEntry.weight_kg)
                    .where(
                        WeightEntry.workspace_id == self.workspace_id,
                        WeightEntry.record_date.between(start_date, end_date),
                        WeightEntry.deleted_at.is_(None),
                    )
                    .distinct(WeightEntry.record_date)
                    .order_by(
                        WeightEntry.record_date,
                        WeightEntry.occurred_at.desc(),
                        WeightEntry.id.desc(),
                    )
                )
            ).all()
        )
        record_rows = list(
            (
                await self.session.execute(
                    select(
                        HealthRecord.record_date,
                        func.count(HealthRecord.id).label("record_count"),
                        func.count(HealthRecord.id)
                        .filter(HealthRecord.kind == "meal")
                        .label("meal_count"),
                        func.count(HealthRecord.id)
                        .filter(HealthRecord.kind == "exercise")
                        .label("exercise_count"),
                        func.coalesce(
                            func.sum(HealthAnalysis.calories_kcal)
                            .filter(HealthRecord.kind == "meal"),
                            0,
                        ).label("calories_kcal"),
                        func.coalesce(
                            func.sum(HealthAnalysis.exercise_kcal)
                            .filter(HealthRecord.kind == "exercise"),
                            0,
                        ).label("exercise_kcal"),
                        func.max(HealthAnalysis.weight_kg).label("photo_weight_kg"),
                    )
                    .outerjoin(
                        HealthAnalysis,
                        (HealthAnalysis.workspace_id == HealthRecord.workspace_id)
                        & (HealthAnalysis.health_record_id == HealthRecord.id),
                    )
                    .where(
                        HealthRecord.workspace_id == self.workspace_id,
                        HealthRecord.record_date.between(start_date, end_date),
                        HealthRecord.deleted_at.is_(None),
                    )
                    .group_by(HealthRecord.record_date)
                )
            ).all()
        )

        water_by_date = {item.record_date.isoformat(): int(item[1] or 0) for item in water_rows}
        weight_by_date = {item.record_date.isoformat(): _float(item.weight_kg) for item in weight_rows}
        records_by_date = {
            item.record_date.isoformat(): {
                "record_count": int(item.record_count or 0),
                "meal_count": int(item.meal_count or 0),
                "exercise_count": int(item.exercise_count or 0),
                "calories_kcal": int(item.calories_kcal or 0),
                "exercise_kcal": int(item.exercise_kcal or 0),
                "photo_weight_kg": _float(item.photo_weight_kg),
            }
            for item in record_rows
        }
        health_settings = dict((await self.settings()).health)
        water_target = int(health_settings.get("water_target_ml", 2000))
        points: list[dict] = []
        monthly: dict[str, dict] = {}
        current = start_date
        while current <= end_date:
            day = current.isoformat()
            record_stats = records_by_date.get(day, {})
            weight = weight_by_date.get(day, record_stats.get("photo_weight_kg"))
            point = {
                "date": day,
                "water_ml": water_by_date.get(day, 0),
                "water_target_ml": water_target,
                "weight_kg": weight,
                "calories_kcal": record_stats.get("calories_kcal", 0),
                "exercise_kcal": record_stats.get("exercise_kcal", 0),
                "meal_count": record_stats.get("meal_count", 0),
                "has_record": bool(
                    record_stats.get("record_count")
                    or water_by_date.get(day)
                    or weight is not None
                ),
            }
            points.append(point)
            if current < recent_start and point["has_record"]:
                month = day[:7]
                item = monthly.setdefault(
                    month,
                    {
                        "month": month,
                        "recorded_days": 0,
                        "record_count": 0,
                        "meal_count": 0,
                        "exercise_count": 0,
                        "water_ml": 0,
                        "calories_kcal": 0,
                        "exercise_kcal": 0,
                        "latest_weight_kg": None,
                    },
                )
                item["recorded_days"] += 1
                item["record_count"] += record_stats.get("record_count", 0)
                item["meal_count"] += record_stats.get("meal_count", 0)
                item["exercise_count"] += record_stats.get("exercise_count", 0)
                item["water_ml"] += point["water_ml"]
                item["calories_kcal"] += point["calories_kcal"]
                item["exercise_kcal"] += point["exercise_kcal"]
                if point["weight_kg"] is not None:
                    item["latest_weight_kg"] = point["weight_kg"]
            current += timedelta(days=1)

        weights = [point["weight_kg"] for point in points if point["weight_kg"] is not None]
        recorded = [point for point in points if point["has_record"]]
        point_granularity, display_points = compact_history_points(points, water_target)
        return {
            "range_days": (end_date - start_date).days + 1,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "recent_start_date": recent_start.isoformat(),
            "point_granularity": point_granularity,
            "points": display_points,
            "metrics": {
                "latest_weight_kg": weights[-1] if weights else None,
                "weight_change_kg": round(weights[-1] - weights[0], 2) if len(weights) >= 2 else 0,
                "average_water_ml": round(sum(point["water_ml"] for point in points) / len(points)) if points else 0,
                "average_calories_kcal": round(sum(point["calories_kcal"] for point in points) / len(points)) if points else 0,
                "exercise_total_kcal": sum(point["exercise_kcal"] for point in points),
                "recorded_days": len(recorded),
            },
            "records": recent["records"],
            "daily_cards": recent["daily_cards"],
            "monthly_archive": [monthly[key] for key in sorted(monthly, reverse=True)],
        }
