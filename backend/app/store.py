from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

from .china_calendar import calendar_days
from .index import MarkdownIndex


QUADRANTS = {
    "important_urgent": "重要·紧急",
    "important_not_urgent": "重要·不紧急",
    "not_important_urgent": "不重要·紧急",
    "not_important_not_urgent": "不重要·不紧急",
}

UPLOAD_KINDS = {
    "meal": ("饮食", "饮食记录", "meal"),
    "weight": ("体重", "体重记录", "weight_photo"),
    "exercise": ("运动", "运动记录明细", "exercise"),
}

MEAL_SLOTS = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "afternoon_tea": "下午茶",
    "dinner": "晚餐",
    "snack": "零食",
    "late_night": "夜宵",
}
MEAL_SLOT_ORDER = {slot: index for index, slot in enumerate(MEAL_SLOTS)}
MEAL_SLOT_TIMES = {
    "breakfast": "08:00:00",
    "lunch": "12:30:00",
    "afternoon_tea": "15:30:00",
    "dinner": "18:30:00",
    "snack": "20:00:00",
    "late_night": "22:30:00",
}

HEALTH_RECORD_FOLDERS = {
    "meal": "💪 减肥健身专栏/饮食记录",
    "weight_photo": "💪 减肥健身专栏/体重记录",
    "exercise": "💪 减肥健身专栏/运动记录明细",
}

LEARNING_PLAN_FOLDER = "📈 个人成长专栏/新技能学习计划"
AGENT_JOB_FOLDER = "🤖 AI Agent/任务队列"
SETTINGS_FOLDER = "⚙️ 工作台设置"
PROJECT_FOLDER = "📂 项目进度"
DAILY_MESSAGE_FOLDER = "🤖 AI Agent/每日寄语"
DAILY_HEALTH_ADVICE_FOLDER = "🤖 AI Agent/健康建议"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_text() -> str:
    return date.today().isoformat()


def infer_meal_slot(recorded_at: str | None = None) -> str:
    try:
        moment = datetime.fromisoformat(str(recorded_at or now_iso()).replace("Z", "+00:00"))
        hour = moment.hour + moment.minute / 60
    except ValueError:
        hour = datetime.now().hour
    if hour < 10:
        return "breakfast"
    if hour < 15:
        return "lunch"
    if hour < 17.5:
        return "afternoon_tea"
    if hour < 21:
        return "dinner"
    return "late_night"


def clean_health_advice_text(value: str) -> str:
    cleaned = re.sub(r"\*\*", "", str(value or "")).strip()
    cleaned = re.sub(r"(?<!\n)\s+-\s+", "\n• ", cleaned)
    cleaned = re.sub(r"(?m)^\s*-\s+", "• ", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def split_health_advice(value: str) -> dict[str, Any]:
    content = str(value or "").strip()
    content = "\n".join(line for line in content.splitlines() if not line.startswith("# ")).strip()
    buckets = {"overall": "", "diet": "", "hydration": "", "exercise": ""}

    def category(label: str) -> str:
        if "饮水" in label or "补水" in label:
            return "hydration"
        if "饮食" in label or "餐" in label or "热量" in label:
            return "diet"
        if "运动" in label or "训练" in label:
            return "exercise"
        return "overall"

    heading_matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", content))
    if heading_matches:
        prefix = content[: heading_matches[0].start()].strip()
        if prefix:
            buckets["overall"] = prefix
        for index, match in enumerate(heading_matches):
            end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(content)
            section = content[match.end():end].strip()
            key = category(match.group(1))
            buckets[key] = "\n\n".join(part for part in (buckets[key], section) if part)
    else:
        marker_pattern = re.compile(
            r"\*\*(?:\d+[.、]\s*)?(饮食|饮水|补水|运动|训练|今日结论|全天总结|总体建议|第一阶段预期)[^*]*\*\*"
        )
        markers = list(marker_pattern.finditer(content))
        if markers:
            prefix = content[: markers[0].start()].strip()
            if prefix:
                buckets["overall"] = prefix
            for index, marker in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(content)
                section = content[marker.end():end].strip()
                key = category(marker.group(1))
                buckets[key] = "\n\n".join(part for part in (buckets[key], section) if part)
        elif content:
            buckets["overall"] = content

    labels = {
        "overall": "今日结论",
        "diet": "全天饮食",
        "hydration": "饮水进度",
        "exercise": "运动总结",
    }
    sections = [
        {"key": key, "label": labels[key], "content": clean_health_advice_text(buckets[key])}
        for key in ("overall", "diet", "hydration", "exercise")
        if clean_health_advice_text(buckets[key])
    ]
    return {
        "overall_summary": clean_health_advice_text(buckets["overall"]),
        "diet_summary": clean_health_advice_text(buckets["diet"]),
        "hydration_summary": clean_health_advice_text(buckets["hydration"]),
        "exercise_summary": clean_health_advice_text(buckets["exercise"]),
        "sections": sections,
    }


def safe_slug(value: str, fallback: str = "record") -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip(), flags=re.UNICODE).strip("-")
    return cleaned[:48] or fallback


ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
}


class MarkdownStore:
    def __init__(self, root: Path, cache_dir: Path, default_water_target_ml: int = 2000) -> None:
        self.root = root.resolve()
        self.cache_dir = cache_dir.resolve()
        self.default_water_target_ml = default_water_target_ml
        self.lock = threading.RLock()
        self.index = MarkdownIndex(self.cache_dir)
        self.ensure_structure()

    def ensure_structure(self) -> None:
        directories = [
            "📅 每日任务/记录",
            "💪 减肥健身专栏/健康记录",
            "💪 减肥健身专栏/饮食记录",
            "💪 减肥健身专栏/运动记录明细",
            "💪 减肥健身专栏/体重记录",
            "📈 个人成长专栏/新技能学习计划",
            "📈 个人成长专栏/书单观影记录/条目",
            "📱 个人IP专栏/内容索引",
            PROJECT_FOLDER,
            SETTINGS_FOLDER,
            "🤖 AI Agent/建议",
            DAILY_MESSAGE_FOLDER,
            DAILY_HEALTH_ADVICE_FOLDER,
            "🤖 AI Agent/操作日志",
            AGENT_JOB_FOLDER,
            "附件/饮食",
            "附件/体重",
            "附件/运动",
        ]
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            for item in directories:
                self._safe_path(item).mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative: str | Path) -> Path:
        target = (self.root / relative).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Path escaped the workbench directory") from exc
        return target

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
        """Return a transparent starting estimate, not a clinical prescription."""
        ages = [age] if age is not None else [25, 55]
        factors = [ACTIVITY_FACTORS[activity_level]] if activity_level else [1.2, 1.375]
        sex_adjustment = 5 if gender == "male" else -161
        estimates: list[int] = []
        for candidate_age in ages:
            resting_energy = (
                10 * current_weight_kg + 6.25 * height_cm - 5 * candidate_age + sex_adjustment
            )
            for factor in factors:
                maintenance = resting_energy * factor
                deficit = min(500, max(200, maintenance * 0.15)) if current_weight_kg > target_weight_kg else 0
                estimates.append(cls._round_to_50(max(resting_energy, maintenance - deficit)))

        calorie_min = min(estimates)
        calorie_max = max(estimates)
        calorie_midpoint = cls._round_to_50((calorie_min + calorie_max) / 2)
        water_target = cls._round_to_50(max(1500, min(4000, current_weight_kg * 35)))
        missing = []
        if age is None:
            missing.append("年龄")
        if activity_level is None:
            missing.append("日常活动量")
        if missing:
            note = (
                f"未填写{'和'.join(missing)}，先按 25–55 岁、久坐至轻量活动给出参考区间；"
                "补充后会收窄为更个体化的起始值。"
            )
        else:
            note = "已结合年龄与日常活动量估算；建议再根据连续 2–4 周的体重趋势调整。"
        return {
            "calories_target_kcal": calorie_midpoint,
            "calories_target_min_kcal": calorie_min,
            "calories_target_max_kcal": calorie_max,
            "calculation_mode": "personalized" if not missing else "reference_range",
            "calculation_note": note,
            "exercise_target_minutes_week": 150,
            "strength_target_days_week": 2,
            "water_target_ml": water_target,
            "cups_per_day": round(water_target / cup_ml, 1),
        }

    @staticmethod
    def _short_daily_message(message: str) -> str:
        compact = " ".join(str(message).split()).strip()
        if not compact:
            return ""
        sentence = re.split(r"(?<=[。！？!?])\s*", compact, maxsplit=1)[0]
        return sentence if len(sentence) <= 48 else f"{sentence[:47]}…"

    @staticmethod
    def _split_markdown(text: str) -> tuple[dict[str, Any], str]:
        normalized = text.replace("\r\n", "\n")
        if not normalized.startswith("---\n"):
            return {}, normalized
        end = normalized.find("\n---\n", 4)
        if end < 0:
            return {}, normalized
        metadata = yaml.safe_load(normalized[4:end]) or {}
        return metadata, normalized[end + 5 :]

    def _read_markdown(self, path: Path) -> tuple[dict[str, Any], str]:
        if not path.exists():
            return {}, ""
        return self._split_markdown(path.read_text(encoding="utf-8"))

    def _write_markdown(self, path: Path, metadata: dict[str, Any], body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        content = f"---\n{frontmatter}\n---\n\n{body.strip()}\n"
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            for attempt in range(4):
                try:
                    os.replace(temporary_name, path)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _write_binary(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            for attempt in range(4):
                try:
                    os.replace(temporary_name, path)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def _log_event(self, action: str, summary: str, source: str) -> None:
        log_path = self._safe_path(Path("🤖 AI Agent/操作日志") / f"{today_text()}.md")
        existing_meta, existing_body = self._read_markdown(log_path)
        metadata = {
            "id": existing_meta.get("id", f"activity_{today_text()}"),
            "type": "activity_log",
            "date": today_text(),
            "updated_at": now_iso(),
        }
        entry = f"- {datetime.now().strftime('%H:%M:%S')} · {source} · {action} · {summary}"
        previous_entries = [line for line in existing_body.splitlines() if line.startswith("- ")][-199:]
        body = f"# {today_text()} 操作记录\n\n" + "\n".join([*previous_entries, entry])
        self._write_markdown(log_path, metadata, body)

    def scan_index_records(self) -> Iterable[dict[str, Any]]:
        for path in self.root.rglob("*.md"):
            if path.name.endswith(".conflict.md"):
                continue
            metadata, body = self._read_markdown(path)
            title = metadata.get("title")
            if not title:
                heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), "")
                title = heading or path.stem
            yield {
                "path": path.relative_to(self.root).as_posix(),
                "type": metadata.get("type", "note"),
                "title": title,
                "updated_at": str(metadata.get("updated_at", "")),
                "mtime_ns": path.stat().st_mtime_ns,
            }

    def rebuild_index(self) -> dict:
        with self.lock:
            count = self.index.rebuild(self.scan_index_records())
        return {"documents": count}

    def fingerprint(self) -> tuple[int, int]:
        files = list(self.root.rglob("*.md"))
        latest = max((path.stat().st_mtime_ns for path in files), default=0)
        return len(files), latest

    def _find_record(self, folder: str, record_id: str) -> Path | None:
        for path in self._safe_path(folder).rglob("*.md"):
            metadata, _ = self._read_markdown(path)
            if metadata.get("id") == record_id:
                return path
        return None

    def create_agent_job(
        self,
        job_type: str,
        subject_id: str,
        title: str,
        payload: dict[str, Any] | None = None,
        source: str = "system",
    ) -> dict[str, Any]:
        timestamp = now_iso()
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        path = self._safe_path(
            Path(AGENT_JOB_FOLDER) / date.today().strftime("%Y/%m") / f"{job_id}-{safe_slug(title)}.md"
        )
        metadata = {
            "id": job_id,
            "type": "agent_job",
            "job_type": job_type,
            "subject_id": subject_id,
            "title": title.strip(),
            "status": "pending",
            "attempts": 0,
            "payload": payload or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        body = (
            f"# {title.strip()}\n\n"
            "## 处理说明\n\n"
            "请 AI Agent 领取此任务，完成后通过工作台 MCP 工具写回结果。"
        )
        with self.lock:
            self._write_markdown(path, metadata, body)
            self._log_event("create_agent_job", title.strip(), source)
        return self.get_agent_job(job_id)

    def _agent_job_from_path(self, path: Path) -> dict[str, Any] | None:
        metadata, body = self._read_markdown(path)
        if metadata.get("type") != "agent_job":
            return None
        return {
            "id": metadata.get("id"),
            "job_type": metadata.get("job_type"),
            "subject_id": metadata.get("subject_id"),
            "title": metadata.get("title", path.stem),
            "status": metadata.get("status", "pending"),
            "attempts": int(metadata.get("attempts", 0)),
            "payload": metadata.get("payload") or {},
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "claimed_at": metadata.get("claimed_at"),
            "completed_at": metadata.get("completed_at"),
            "result_summary": metadata.get("result_summary", ""),
            "instructions": body.strip(),
        }

    def get_agent_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            path = self._find_record(AGENT_JOB_FOLDER, job_id)
            if path is None:
                raise KeyError(job_id)
            record = self._agent_job_from_path(path)
            if record is None:
                raise KeyError(job_id)
            return record

    def list_agent_jobs(
        self,
        status: str | None = None,
        job_type: str | None = None,
        subject_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        with self.lock:
            for path in self._safe_path(AGENT_JOB_FOLDER).rglob("*.md"):
                record = self._agent_job_from_path(path)
                if record is None:
                    continue
                if status and record["status"] != status:
                    continue
                if job_type and record["job_type"] != job_type:
                    continue
                if subject_id and record["subject_id"] != subject_id:
                    continue
                jobs.append(record)
        jobs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return jobs[: max(1, min(limit, 100))]

    def claim_agent_job(self, job_id: str, source: str = "hermes") -> dict[str, Any]:
        with self.lock:
            path = self._find_record(AGENT_JOB_FOLDER, job_id)
            if path is None:
                raise KeyError(job_id)
            metadata, body = self._read_markdown(path)
            if metadata.get("status") not in {"pending", "in_progress"}:
                raise ValueError("Only pending jobs can be claimed")
            metadata["status"] = "in_progress"
            metadata["claimed_at"] = metadata.get("claimed_at") or now_iso()
            metadata["attempts"] = int(metadata.get("attempts", 0)) + 1
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("claim_agent_job", metadata.get("title", job_id), source)
        return self.get_agent_job(job_id)

    def complete_agent_job(
        self,
        job_id: str,
        result_summary: str = "",
        succeeded: bool = True,
        source: str = "hermes",
    ) -> dict[str, Any]:
        with self.lock:
            path = self._find_record(AGENT_JOB_FOLDER, job_id)
            if path is None:
                raise KeyError(job_id)
            metadata, body = self._read_markdown(path)
            metadata["status"] = "completed" if succeeded else "failed"
            metadata["result_summary"] = result_summary.strip()
            metadata["completed_at"] = now_iso()
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("complete_agent_job", metadata.get("title", job_id), source)
        return self.get_agent_job(job_id)

    def _complete_jobs_for_subject(self, subject_id: str, job_type: str, summary: str, source: str) -> None:
        for job in self.list_agent_jobs(job_type=job_type, subject_id=subject_id, limit=100):
            if job["status"] in {"pending", "in_progress"}:
                self.complete_agent_job(job["id"], summary, source=source)

    def get_profile_settings(self) -> dict[str, Any]:
        path = self._safe_path(Path(SETTINGS_FOLDER) / "个人设置.md")
        with self.lock:
            metadata, _ = self._read_markdown(path)
        return {
            "nickname": str(metadata.get("nickname", "朋友")),
            "daily_message_style": str(metadata.get("daily_message_style", "mixed")),
            "updated_at": metadata.get("updated_at"),
        }

    def update_profile_settings(
        self,
        nickname: str,
        daily_message_style: str = "mixed",
        source: str = "user",
    ) -> dict[str, Any]:
        if daily_message_style not in {"mixed", "encouraging", "comforting"}:
            raise ValueError("Unsupported daily message style")
        path = self._safe_path(Path(SETTINGS_FOLDER) / "个人设置.md")
        timestamp = now_iso()
        metadata = {
            "id": "workbench_profile",
            "type": "workbench_settings",
            "nickname": nickname.strip(),
            "daily_message_style": daily_message_style,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        with self.lock:
            previous, _ = self._read_markdown(path)
            metadata["created_at"] = previous.get("created_at", timestamp)
            metadata["version"] = int(previous.get("version", 0)) + 1
            self._write_markdown(path, metadata, "# 个人设置\n\n这些设置由工作台和 AI Agent 共同读取。")
            self._log_event("update_profile_settings", nickname.strip(), source)
        return self.get_profile_settings()

    def get_health_goals(self) -> dict[str, Any]:
        path = self._safe_path(Path(SETTINGS_FOLDER) / "健康目标.md")
        with self.lock:
            metadata, _ = self._read_markdown(path)
        return {
            "gender": metadata.get("gender"),
            "height_cm": metadata.get("height_cm"),
            "current_weight_kg": metadata.get("current_weight_kg", metadata.get("start_weight_kg")),
            "target_weight_kg": metadata.get("target_weight_kg"),
            "start_weight_kg": metadata.get("start_weight_kg"),
            "calories_target_kcal": int(metadata.get("calories_target_kcal", 1800)),
            "calories_target_min_kcal": int(metadata.get("calories_target_min_kcal", metadata.get("calories_target_kcal", 1800))),
            "calories_target_max_kcal": int(metadata.get("calories_target_max_kcal", metadata.get("calories_target_kcal", 1800))),
            "exercise_target_kcal": int(metadata.get("exercise_target_kcal", 300)),
            "exercise_target_minutes_week": int(metadata.get("exercise_target_minutes_week", 150)),
            "strength_target_days_week": int(metadata.get("strength_target_days_week", 2)),
            "water_target_ml": int(metadata.get("water_target_ml", self.default_water_target_ml)),
            "cups_per_day": float(metadata.get("cups_per_day", 0)),
            "cup_ml": int(metadata.get("cup_ml", 250)),
            "age": metadata.get("age"),
            "activity_level": metadata.get("activity_level"),
            "calculation_mode": metadata.get("calculation_mode", "legacy"),
            "calculation_note": metadata.get("calculation_note", "填写基础信息后，系统会自动给出热量与运动参考。"),
            "updated_at": metadata.get("updated_at"),
        }

    def update_health_goals(
        self,
        gender: str,
        height_cm: float,
        current_weight_kg: float,
        target_weight_kg: float,
        cup_ml: int = 250,
        age: int | None = None,
        activity_level: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        if gender not in {"female", "male"}:
            raise ValueError("Unsupported gender")
        if activity_level is not None and activity_level not in ACTIVITY_FACTORS:
            raise ValueError("Unsupported activity level")
        path = self._safe_path(Path(SETTINGS_FOLDER) / "健康目标.md")
        timestamp = now_iso()
        plan = self.calculate_health_plan(
            gender, height_cm, current_weight_kg, target_weight_kg, cup_ml, age, activity_level
        )
        with self.lock:
            previous, _ = self._read_markdown(path)
            metadata = {
                "id": "health_goals",
                "type": "health_goals",
                "gender": gender,
                "height_cm": round(height_cm, 1),
                "current_weight_kg": round(current_weight_kg, 2),
                "target_weight_kg": round(target_weight_kg, 2),
                "start_weight_kg": previous.get("start_weight_kg") or round(current_weight_kg, 2),
                "age": age,
                "activity_level": activity_level,
                "exercise_target_kcal": int(previous.get("exercise_target_kcal", 300)),
                "cup_ml": cup_ml,
                **plan,
                "created_at": previous.get("created_at", timestamp),
                "updated_at": timestamp,
                "source": source,
                "version": int(previous.get("version", 0)) + 1,
            }
            self._write_markdown(
                path,
                metadata,
                "# 健康目标\n\n热量为基于身体信息的起始估算，不代替医疗或营养诊断。"
                "运动目标按每周分钟数记录；饮水按当前体重与杯子容量自动换算。",
            )
            existing = self.list_agent_jobs(
                status="pending", job_type="health_goal_review", subject_id="health_goals", limit=1
            )
            if not existing:
                self.create_agent_job(
                    "health_goal_review",
                    "health_goals",
                    "复核减重目标并给出第一阶段建议",
                    {**plan, "current_weight_kg": current_weight_kg, "target_weight_kg": target_weight_kg},
                    source=source,
                )
            self._log_event("update_health_goals", f"目标 {target_weight_kg:.1f} kg", source)
        return self.get_health_goals()

    def get_ip_preferences(self) -> dict[str, Any]:
        path = self._safe_path(Path(SETTINGS_FOLDER) / "IP关注设置.md")
        with self.lock:
            metadata, _ = self._read_markdown(path)
        return {
            "video_topics": list(metadata.get("video_topics") or ["AI效率", "个人成长"]),
            "ai_topics": list(metadata.get("ai_topics") or ["行业动态", "科技产品"]),
            "updated_at": metadata.get("updated_at"),
        }

    def update_ip_preferences(
        self,
        video_topics: list[str],
        ai_topics: list[str],
        source: str = "user",
    ) -> dict[str, Any]:
        clean_video = [item.strip() for item in video_topics if item.strip()][:20]
        clean_ai = [item.strip() for item in ai_topics if item.strip()][:20]
        path = self._safe_path(Path(SETTINGS_FOLDER) / "IP关注设置.md")
        timestamp = now_iso()
        with self.lock:
            previous, _ = self._read_markdown(path)
            metadata = {
                "id": "ip_preferences",
                "type": "ip_preferences",
                "video_topics": clean_video,
                "ai_topics": clean_ai,
                "created_at": previous.get("created_at", timestamp),
                "updated_at": timestamp,
                "source": source,
                "version": int(previous.get("version", 0)) + 1,
            }
            self._write_markdown(path, metadata, "# IP 关注设置\n\nAI Agent 每日按这里的方向筛选热点和资讯。")
            existing = self.list_agent_jobs(
                status="pending", job_type="content_research_refresh", subject_id="ip_preferences", limit=1
            )
            if not existing:
                self.create_agent_job(
                    "content_research_refresh",
                    "ip_preferences",
                    "按新关注方向刷新热点与资讯",
                    {"video_topics": clean_video, "ai_topics": clean_ai},
                    source=source,
                )
            self._log_event("update_ip_preferences", "、".join([*clean_video, *clean_ai])[:120], source)
        return self.get_ip_preferences()

    def get_daily_message(self, target_date: str | None = None) -> dict[str, Any]:
        target_date = target_date or today_text()
        path = self._safe_path(Path(DAILY_MESSAGE_FOLDER) / f"{target_date}.md")
        with self.lock:
            metadata, body = self._read_markdown(path)
        message = ""
        if body:
            message = "\n".join(line for line in body.splitlines() if not line.startswith("#")).strip()
        return {
            "date": target_date,
            "message": self._short_daily_message(message),
            "tone": metadata.get("tone", self.get_profile_settings()["daily_message_style"]),
            "generated_by": metadata.get("source"),
            "updated_at": metadata.get("updated_at"),
        }

    def save_daily_message(
        self,
        message: str,
        tone: str = "mixed",
        target_date: str | None = None,
        source: str = "hermes",
    ) -> dict[str, Any]:
        target_date = target_date or today_text()
        date.fromisoformat(target_date)
        if tone not in {"mixed", "encouraging", "comforting"}:
            raise ValueError("Unsupported daily message tone")
        short_message = self._short_daily_message(message)
        if not short_message:
            raise ValueError("Daily message cannot be empty")
        path = self._safe_path(Path(DAILY_MESSAGE_FOLDER) / f"{target_date}.md")
        timestamp = now_iso()
        with self.lock:
            previous, _ = self._read_markdown(path)
            metadata = {
                "id": f"daily_message_{target_date}",
                "type": "daily_message",
                "date": target_date,
                "tone": tone,
                "created_at": previous.get("created_at", timestamp),
                "updated_at": timestamp,
                "source": source,
                "version": int(previous.get("version", 0)) + 1,
            }
            self._write_markdown(path, metadata, f"# {target_date} 每日寄语\n\n{short_message}")
            self._complete_jobs_for_subject(
                f"daily_message_{target_date}", "daily_message_generation", "已写入今日寄语", source
            )
            self._log_event("save_daily_message", short_message, source)
        return self.get_daily_message(target_date)

    def ensure_daily_agent_jobs(self) -> None:
        target_date = today_text()
        message = self.get_daily_message(target_date)
        if not message["message"] and not self.list_agent_jobs(
            job_type="daily_message_generation", subject_id=f"daily_message_{target_date}", limit=1
        ):
            profile = self.get_profile_settings()
            self.create_agent_job(
                "daily_message_generation",
                f"daily_message_{target_date}",
                f"生成 {target_date} 的每日寄语",
                {"date": target_date, "tone": profile["daily_message_style"], "nickname": profile["nickname"]},
            )
        if not self.list_agent_jobs(job_type="daily_planning", subject_id=f"daily_plan_{target_date}", limit=1):
            self.create_agent_job(
                "daily_planning",
                f"daily_plan_{target_date}",
                f"整理 {target_date} 的项目进度与今日任务",
                {"date": target_date},
            )

    def create_project(
        self,
        name: str,
        current_stage: str = "准备中",
        progress_percent: int = 0,
        next_milestone: str = "",
        due_date: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        if due_date:
            date.fromisoformat(due_date[:10])
        record_id = f"project_{uuid.uuid4().hex[:10]}"
        timestamp = now_iso()
        path = self._safe_path(Path(PROJECT_FOLDER) / f"{record_id}-{safe_slug(name)}.md")
        metadata = {
            "id": record_id,
            "type": "project",
            "title": name.strip(),
            "current_stage": current_stage.strip() or "准备中",
            "progress_percent": max(0, min(progress_percent, 100)),
            "next_milestone": next_milestone.strip(),
            "due_date": due_date,
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        with self.lock:
            self._write_markdown(path, metadata, f"# {name.strip()}\n\n## 当前阶段\n\n{current_stage.strip() or '准备中'}")
            self._log_event("create_project", name.strip(), source)
        return self.get_project(record_id)

    def _project_from_path(self, path: Path) -> dict[str, Any] | None:
        metadata, body = self._read_markdown(path)
        if metadata.get("type") != "project":
            return None
        return {
            "id": metadata.get("id"),
            "name": metadata.get("title", path.stem),
            "current_stage": metadata.get("current_stage", "准备中"),
            "progress_percent": int(metadata.get("progress_percent", 0)),
            "next_milestone": metadata.get("next_milestone", ""),
            "due_date": metadata.get("due_date"),
            "status": metadata.get("status", "active"),
            "details": body.strip(),
            "updated_at": metadata.get("updated_at"),
        }

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self.lock:
            path = self._find_record(PROJECT_FOLDER, project_id)
            if path is None:
                raise KeyError(project_id)
            project = self._project_from_path(path)
            if project is None:
                raise KeyError(project_id)
            return project

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        with self.lock:
            for path in self._safe_path(PROJECT_FOLDER).glob("*.md"):
                project = self._project_from_path(path)
                if project:
                    projects.append(project)
        return sorted(projects, key=lambda item: (item["status"] != "active", -(item["progress_percent"])))

    def update_project(self, project_id: str, updates: dict[str, Any], source: str = "user") -> dict[str, Any]:
        with self.lock:
            path = self._find_record(PROJECT_FOLDER, project_id)
            if path is None:
                raise KeyError(project_id)
            metadata, body = self._read_markdown(path)
            for key in ("current_stage", "progress_percent", "next_milestone", "due_date", "status"):
                if key in updates and updates[key] is not None:
                    metadata[key] = updates[key]
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("update_project", metadata.get("title", project_id), source)
        return self.get_project(project_id)

    def _task_from_path(self, path: Path) -> dict[str, Any] | None:
        metadata, body = self._read_markdown(path)
        if metadata.get("type") != "task":
            return None
        quadrant = str(metadata.get("quadrant", "important_not_urgent"))
        note = "\n".join(line for line in body.splitlines() if not line.startswith("# ")).strip()
        return {
            "id": metadata.get("id"),
            "title": metadata.get("title", path.stem),
            "quadrant": quadrant,
            "quadrant_label": QUADRANTS.get(quadrant, "重要·不紧急"),
            "done": bool(metadata.get("done", False)),
            "due_at": metadata.get("due_at"),
            "recurrence": str(metadata.get("recurrence") or "none"),
            "completed_occurrences": list(metadata.get("completed_occurrences") or []),
            "deleted": bool(metadata.get("deleted", False)),
            "deleted_at": metadata.get("deleted_at"),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "note": note,
        }

    def list_tasks(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self.lock:
            for path in self._safe_path("📅 每日任务/记录").rglob("*.md"):
                record = self._task_from_path(path)
                if record is None or (record["deleted"] and not include_deleted):
                    continue
                records.append(record)
        return sorted(records, key=lambda item: (item["done"], item.get("due_at") or "9999", item["title"]))

    def create_task(
        self,
        title: str,
        quadrant: str,
        due_at: str | None = None,
        note: str = "",
        recurrence: str = "none",
        source: str = "user",
    ) -> dict[str, Any]:
        if quadrant not in QUADRANTS:
            raise ValueError("Unknown quadrant")
        if recurrence not in {"none", "yearly"}:
            raise ValueError("不支持的重复规则")
        if recurrence == "yearly" and not due_at:
            raise ValueError("每年重复的安排必须选择日期")
        timestamp = now_iso()
        record_id = f"task_{date.today().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        path = self._safe_path(Path("📅 每日任务/记录") / date.today().strftime("%Y/%m") / f"{record_id}.md")
        metadata = {
            "id": record_id,
            "type": "task",
            "title": title.strip(),
            "quadrant": quadrant,
            "done": False,
            "due_at": due_at,
            "recurrence": recurrence,
            "completed_occurrences": [],
            "deleted": False,
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        with self.lock:
            self._write_markdown(path, metadata, f"# {title.strip()}\n\n{note.strip()}")
            self._log_event("create_task", title.strip(), source)
        return next(task for task in self.list_tasks() if task["id"] == record_id)

    def update_task(self, task_id: str, updates: dict[str, Any], source: str = "user") -> dict[str, Any]:
        with self.lock:
            path = self._find_record("📅 每日任务/记录", task_id)
            if path is None:
                raise KeyError(task_id)
            metadata, body = self._read_markdown(path)
            recurrence = str(updates.get("recurrence", metadata.get("recurrence") or "none"))
            if recurrence not in {"none", "yearly"}:
                raise ValueError("不支持的重复规则")
            if "done" in updates and updates["done"] is not None:
                occurrence_date = updates.get("occurrence_date")
                if recurrence == "yearly" and occurrence_date:
                    occurrence_text = str(occurrence_date)[:10]
                    completed = set(str(item) for item in (metadata.get("completed_occurrences") or []))
                    if updates["done"]:
                        completed.add(occurrence_text)
                    else:
                        completed.discard(occurrence_text)
                    metadata["completed_occurrences"] = sorted(completed)
                else:
                    metadata["done"] = bool(updates["done"])
            for key in ("title", "quadrant", "due_at", "recurrence"):
                if key in updates and updates[key] is not None:
                    metadata[key] = updates[key]
            if "note" in updates and updates["note"] is not None:
                title = str(metadata.get("title", task_id))
                body = f"# {title}\n\n{str(updates['note']).strip()}"
            elif "title" in updates and updates["title"] is not None:
                body = re.sub(r"(?m)^# .+$", f"# {str(metadata['title']).strip()}", body, count=1)
            if str(metadata.get("recurrence") or "none") == "yearly" and not metadata.get("due_at"):
                raise ValueError("每年重复的安排必须选择日期")
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("update_task", metadata.get("title", task_id), source)
        return next(task for task in self.list_tasks(include_deleted=True) if task["id"] == task_id)

    def delete_task(self, task_id: str, source: str = "user") -> dict[str, Any]:
        with self.lock:
            path = self._find_record("📅 每日任务/记录", task_id)
            if path is None:
                raise KeyError(task_id)
            metadata, body = self._read_markdown(path)
            metadata["deleted"] = True
            metadata["deleted_at"] = now_iso()
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("delete_task", metadata.get("title", task_id), source)
        return next(task for task in self.list_tasks(include_deleted=True) if task["id"] == task_id)

    def restore_task(self, task_id: str, source: str = "user") -> dict[str, Any]:
        with self.lock:
            path = self._find_record("📅 每日任务/记录", task_id)
            if path is None:
                raise KeyError(task_id)
            metadata, body = self._read_markdown(path)
            metadata["deleted"] = False
            metadata.pop("deleted_at", None)
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("restore_task", metadata.get("title", task_id), source)
        return next(task for task in self.list_tasks() if task["id"] == task_id)

    @staticmethod
    def _task_occurrence(task: dict[str, Any], occurrence_date: date) -> dict[str, Any]:
        occurrence_text = occurrence_date.isoformat()
        recurring = task.get("recurrence") == "yearly"
        base_due_at = str(task.get("due_at") or "")
        scheduled_at = f"{occurrence_text}{base_due_at[10:]}" if len(base_due_at) > 10 else occurrence_text
        return {
            **task,
            "event_id": f"{task['id']}@{occurrence_text}",
            "occurrence_date": occurrence_text,
            "base_due_at": base_due_at,
            "due_at": scheduled_at,
            "done": occurrence_text in task.get("completed_occurrences", []) if recurring else bool(task.get("done")),
        }

    def task_occurrences(self, start_date: date, end_date: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        occurrences: list[dict[str, Any]] = []
        undated: list[dict[str, Any]] = []
        for task in self.list_tasks():
            due_at = str(task.get("due_at") or "")
            if not due_at:
                undated.append(task)
                continue
            try:
                due_date = date.fromisoformat(due_at[:10])
            except ValueError:
                continue
            if task.get("recurrence") == "yearly":
                for year in range(start_date.year, end_date.year + 1):
                    try:
                        current = date(year, due_date.month, due_date.day)
                    except ValueError:
                        continue
                    if start_date <= current <= end_date:
                        occurrences.append(self._task_occurrence(task, current))
            elif start_date <= due_date <= end_date:
                occurrences.append(self._task_occurrence(task, due_date))
        occurrences.sort(key=lambda item: (item["occurrence_date"], item.get("due_at") or "", item["title"]))
        return occurrences, undated

    def calendar(self, start_date: date, end_date: date) -> dict[str, Any]:
        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if (end_date - start_date).days > 370:
            raise ValueError("一次最多查看371天")
        tasks, undated = self.task_occurrences(start_date, end_date)
        days, notices = calendar_days(start_date, end_date)
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days,
            "tasks": tasks,
            "undated_tasks": undated,
            "holiday_notices": notices,
        }

    def _health_path(self, target_date: str | None = None) -> Path:
        target_date = target_date or today_text()
        parsed = date.fromisoformat(target_date)
        return self._safe_path(Path("💪 减肥健身专栏/健康记录") / parsed.strftime("%Y/%m") / f"{target_date}.md")

    def _health_record(self, target_date: str | None = None) -> tuple[dict[str, Any], str, Path]:
        path = self._health_path(target_date)
        metadata, body = self._read_markdown(path)
        if not metadata:
            timestamp = now_iso()
            metadata = {
                "id": f"health_{target_date or today_text()}",
                "type": "health_day",
                "date": target_date or today_text(),
                "water_target_ml": self.default_water_target_ml,
                "water_entries": [],
                "water_ml": 0,
                "calories_kcal": 0,
                "exercise_kcal": 0,
                "created_at": timestamp,
                "updated_at": timestamp,
                "version": 1,
            }
            body = f"# {target_date or today_text()} 健康记录"
        return metadata, body, path

    def record_water(self, ml: int, source: str = "user") -> dict[str, Any]:
        with self.lock:
            metadata, body, path = self._health_record()
            entries = list(metadata.get("water_entries") or [])
            entries.append({"ml": ml, "recorded_at": now_iso(), "source": source})
            metadata["water_entries"] = entries
            metadata["water_ml"] = sum(int(item.get("ml", 0)) for item in entries)
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("record_water", f"{ml} ml", source)
        return self.health_summary()

    def record_weight(self, kg: float, source: str = "user") -> dict[str, Any]:
        with self.lock:
            metadata, body, path = self._health_record()
            metadata["weight_kg"] = round(kg, 2)
            metadata["weight_recorded_at"] = now_iso()
            metadata["water_target_ml"] = round(max(1500, min(4000, kg * 35)) / 50) * 50
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            goals = self.get_health_goals()
            if (
                goals.get("target_weight_kg")
                and goals.get("start_weight_kg") is None
                and goals.get("gender")
                and goals.get("height_cm")
            ):
                self.update_health_goals(
                    str(goals["gender"]),
                    float(goals["height_cm"]),
                    kg,
                    float(goals["target_weight_kg"]),
                    int(goals["cup_ml"]),
                    int(goals["age"]) if goals.get("age") else None,
                    str(goals["activity_level"]) if goals.get("activity_level") else None,
                    source=source,
                )
            self._log_event("record_weight", f"{kg:.2f} kg", source)
        return self.health_summary()

    def health_summary(self) -> dict[str, Any]:
        goals = self.get_health_goals()
        with self.lock:
            metadata, _, _ = self._health_record()
            today_prefix = today_text()
            meal_count = 0
            analyzed_calories = 0
            analyzed_exercise = 0
            latest_weight: float | None = None
            latest_weight_at = ""
            recommendations: list[dict[str, str]] = []
            for path in self._safe_path("💪 减肥健身专栏/健康记录").rglob("*.md"):
                item, _ = self._read_markdown(path)
                weight = item.get("weight_kg")
                weight_at = str(item.get("weight_recorded_at") or item.get("updated_at") or "")
                if weight is not None and weight_at >= latest_weight_at:
                    latest_weight = float(weight)
                    latest_weight_at = weight_at
            for path in self._safe_path("💪 减肥健身专栏/饮食记录").rglob("*.md"):
                item, body = self._read_markdown(path)
                record_date = str(item.get("record_date") or item.get("recorded_at", ""))[:10]
                if record_date == today_prefix:
                    meal_count += 1
                    if item.get("analysis_status") == "analyzed":
                        analyzed_calories += int(item.get("calories_kcal", 0))
                        advice = body.split("## 今日建议", 1)[-1].strip() if "## 今日建议" in body else ""
                        if advice:
                            meal_slot = str(item.get("meal_slot") or infer_meal_slot(item.get("recorded_at")))
                            recommendations.append({
                                "kind": "meal",
                                "title": str(item.get("meal_label") or MEAL_SLOTS.get(meal_slot, "饮食记录")),
                                "meal_slot": meal_slot,
                                "record_date": record_date,
                                "advice": clean_health_advice_text(advice),
                            })
            for path in self._safe_path("💪 减肥健身专栏/运动记录明细").rglob("*.md"):
                item, body = self._read_markdown(path)
                record_date = str(item.get("record_date") or item.get("recorded_at", ""))[:10]
                if record_date == today_prefix and item.get("analysis_status") == "analyzed":
                    analyzed_exercise += int(item.get("exercise_kcal", 0))
                    advice = body.split("## 今日建议", 1)[-1].strip() if "## 今日建议" in body else ""
                    if advice:
                        recommendations.append({
                            "kind": "exercise",
                            "title": item.get("title", "运动记录"),
                            "record_date": record_date,
                            "advice": clean_health_advice_text(advice),
                        })
        hydration_weight = (
            float(metadata["weight_kg"])
            if metadata.get("weight_kg") is not None
            else latest_weight if latest_weight is not None else goals.get("current_weight_kg")
        )
        target = (
            round(max(1500, min(4000, hydration_weight * 35)) / 50) * 50
            if hydration_weight is not None else int(metadata.get("water_target_ml", self.default_water_target_ml))
        )
        current = int(metadata.get("water_ml", 0))
        current_weight = (
            float(metadata["weight_kg"])
            if metadata.get("weight_kg") is not None
            else latest_weight if latest_weight is not None else goals.get("current_weight_kg")
        )
        target_weight = goals.get("target_weight_kg")
        start_weight = goals.get("start_weight_kg")
        weight_goal_percent = 0
        distance_to_goal = None
        if current_weight is not None and target_weight is not None:
            distance_to_goal = round(abs(float(current_weight) - float(target_weight)), 2)
            if start_weight is not None and float(start_weight) != float(target_weight):
                weight_goal_percent = round(
                    ((float(start_weight) - float(current_weight)) / (float(start_weight) - float(target_weight))) * 100
                )
                weight_goal_percent = max(0, min(weight_goal_percent, 100))
            elif current_weight == float(target_weight):
                weight_goal_percent = 100
        calories_target = int(goals.get("calories_target_kcal", 1800))
        exercise_target = int(goals.get("exercise_target_kcal", 300))
        daily_advice = self.get_daily_health_advice()
        return {
            "water_ml": current,
            "water_target_ml": target,
            "water_percent": min(round((current / target) * 100) if target else 0, 100),
            "calories_kcal": analyzed_calories or int(metadata.get("calories_kcal", 0)),
            "calories_target_kcal": calories_target,
            "weight_kg": current_weight,
            "target_weight_kg": target_weight,
            "start_weight_kg": start_weight,
            "distance_to_goal_kg": distance_to_goal,
            "weight_goal_percent": weight_goal_percent,
            "exercise_kcal": analyzed_exercise or int(metadata.get("exercise_kcal", 0)),
            "exercise_target_kcal": exercise_target,
            "exercise_target_minutes_week": int(goals.get("exercise_target_minutes_week", 150)),
            "strength_target_days_week": int(goals.get("strength_target_days_week", 2)),
            "calories_target_min_kcal": int(goals.get("calories_target_min_kcal", calories_target)),
            "calories_target_max_kcal": int(goals.get("calories_target_max_kcal", calories_target)),
            "calculation_mode": goals.get("calculation_mode", "legacy"),
            "calculation_note": goals.get("calculation_note", ""),
            "meal_count": meal_count,
            "cup_ml": int(goals.get("cup_ml", 250)),
            "daily_advice": daily_advice,
            "recommendations": recommendations[:4],
        }

    def get_daily_health_advice(self, target_date: str | None = None) -> dict[str, Any]:
        target_date = target_date or today_text()
        path = self._safe_path(Path(DAILY_HEALTH_ADVICE_FOLDER) / f"{target_date}.md")
        with self.lock:
            metadata, body = self._read_markdown(path)
        summary = "\n".join(line for line in body.splitlines() if not line.startswith("# ")).strip()
        structured = split_health_advice(summary)
        return {
            "date": target_date,
            "summary": structured["overall_summary"] or clean_health_advice_text(summary),
            **structured,
            "status": metadata.get("status", "neutral"),
            "updated_at": metadata.get("updated_at"),
        }

    def save_daily_health_advice(
        self,
        summary: str,
        status: str = "neutral",
        target_date: str | None = None,
        source: str = "hermes",
        *,
        overall_summary: str = "",
        diet_summary: str = "",
        hydration_summary: str = "",
        exercise_summary: str = "",
    ) -> dict[str, Any]:
        target_date = target_date or today_text()
        date.fromisoformat(target_date)
        if status not in {"on_track", "attention", "celebrate", "neutral"}:
            raise ValueError("Unsupported health advice status")
        provided = {
            "overall": overall_summary.strip(),
            "diet": diet_summary.strip(),
            "hydration": hydration_summary.strip(),
            "exercise": exercise_summary.strip(),
        }
        if not any(provided.values()):
            legacy = split_health_advice(summary)
            provided = {
                "overall": legacy["overall_summary"],
                "diet": legacy["diet_summary"],
                "hydration": legacy["hydration_summary"],
                "exercise": legacy["exercise_summary"],
            }
        elif summary.strip() and not provided["overall"]:
            provided["overall"] = summary.strip()
        if not any(value.strip() for value in provided.values()):
            raise ValueError("健康建议至少需要填写一个分段")

        path = self._safe_path(Path(DAILY_HEALTH_ADVICE_FOLDER) / f"{target_date}.md")
        timestamp = now_iso()
        with self.lock:
            previous, _ = self._read_markdown(path)
            metadata = {
                "id": f"health_advice_{target_date}",
                "type": "daily_health_advice",
                "date": target_date,
                "status": status,
                "created_at": previous.get("created_at", timestamp),
                "updated_at": timestamp,
                "source": source,
                "format_version": 2,
                "version": int(previous.get("version", 0)) + 1,
            }
            headings = {
                "overall": "今日结论",
                "diet": "全天饮食",
                "hydration": "饮水进度",
                "exercise": "运动总结",
            }
            sections = [
                f"## {headings[key]}\n\n{value.strip()}"
                for key, value in provided.items()
                if value.strip()
            ]
            body = f"# {target_date} 健康建议\n\n" + "\n\n".join(sections)
            self._write_markdown(path, metadata, body)
            self._complete_jobs_for_subject(
                target_date,
                "health_daily_summary_refresh",
                f"已重新生成 {target_date} 健康总结",
                source,
            )
            log_summary = provided["overall"] or next(value for value in provided.values() if value)
            self._log_event("save_daily_health_advice", clean_health_advice_text(log_summary)[:80], source)
        return self.get_daily_health_advice(target_date)

    def health_history(
        self,
        days: int = 30,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        if (start_date is None) != (end_date is None):
            raise ValueError("自定义周期需要同时填写开始日期和结束日期")
        if start_date is not None and end_date is not None:
            if start_date > end_date:
                raise ValueError("开始日期不能晚于结束日期")
            if end_date > date.today():
                raise ValueError("结束日期不能晚于今天")
            days = (end_date - start_date).days + 1
            if days > 366:
                raise ValueError("一次最多查看一年（366天）的健康变化")
        else:
            days = max(1, min(days, 366))
            end_date = date.today()
            start_date = end_date - timedelta(days=days - 1)
        points_by_date: dict[str, dict[str, Any]] = {}
        for offset in range(days):
            current = start_date + timedelta(days=offset)
            key = current.isoformat()
            points_by_date[key] = {
                "date": key,
                "water_ml": 0,
                "water_target_ml": self.default_water_target_ml,
                "weight_kg": None,
                "calories_kcal": 0,
                "exercise_kcal": 0,
                "meal_count": 0,
                "has_record": False,
            }

        with self.lock:
            for path in self._safe_path("💪 减肥健身专栏/健康记录").rglob("*.md"):
                metadata, _ = self._read_markdown(path)
                if metadata.get("type") != "health_day":
                    continue
                record_date = str(metadata.get("date", ""))
                point = points_by_date.get(record_date)
                if point is None:
                    continue
                point.update({
                    "water_ml": int(metadata.get("water_ml", 0)),
                    "water_target_ml": int(metadata.get("water_target_ml", self.default_water_target_ml)),
                    "weight_kg": metadata.get("weight_kg"),
                    "calories_kcal": int(metadata.get("calories_kcal", 0)),
                    "exercise_kcal": int(metadata.get("exercise_kcal", 0)),
                    "has_record": True,
                })

            records = self.list_health_records(limit=max(100, days * 8))
            meal_calories: dict[str, int] = {}
            exercise_calories: dict[str, int] = {}
            for record in records:
                record_date = str(record.get("record_date") or record.get("recorded_at", ""))[:10]
                point = points_by_date.get(record_date)
                if point is None:
                    continue
                point["has_record"] = True
                if record["kind"] == "meal":
                    point["meal_count"] += 1
                    if record.get("analysis_status") == "analyzed":
                        meal_calories[record_date] = meal_calories.get(record_date, 0) + int(record.get("calories_kcal") or 0)
                elif record["kind"] == "exercise" and record.get("analysis_status") == "analyzed":
                    exercise_calories[record_date] = exercise_calories.get(record_date, 0) + int(record.get("exercise_kcal") or 0)
                elif record["kind"] == "weight_photo" and record.get("weight_kg") is not None:
                    point["weight_kg"] = record["weight_kg"]

            for record_date, calories in meal_calories.items():
                points_by_date[record_date]["calories_kcal"] = calories
            for record_date, calories in exercise_calories.items():
                points_by_date[record_date]["exercise_kcal"] = calories

        points = list(points_by_date.values())
        weight_values = [float(point["weight_kg"]) for point in points if point["weight_kg"] is not None]
        water_values = [int(point["water_ml"]) for point in points if point["water_ml"] > 0]
        calorie_values = [int(point["calories_kcal"]) for point in points if point["calories_kcal"] > 0]
        range_records = [
            record for record in records
            if start_date.isoformat() <= str(record.get("record_date") or record.get("recorded_at", ""))[:10] <= end_date.isoformat()
        ]
        cards_by_date: dict[str, dict[str, Any]] = {}
        for record in range_records:
            record_date = str(record.get("record_date") or record.get("recorded_at", ""))[:10]
            point = points_by_date[record_date]
            card = cards_by_date.setdefault(record_date, {
                "date": record_date,
                "water_ml": point["water_ml"],
                "water_target_ml": point["water_target_ml"],
                "calories_kcal": point["calories_kcal"],
                "exercise_kcal": point["exercise_kcal"],
                "weight_kg": point["weight_kg"],
                "meals": [],
                "exercise_records": [],
                "other_records": [],
            })
            if record["kind"] == "meal":
                card["meals"].append(record)
            elif record["kind"] == "exercise":
                card["exercise_records"].append(record)
            else:
                card["other_records"].append(record)

        for record_date, card in cards_by_date.items():
            card["meals"].sort(key=lambda item: (
                MEAL_SLOT_ORDER.get(str(item.get("meal_slot")), 99),
                str(item.get("recorded_at") or ""),
            ))
            card["exercise_records"].sort(key=lambda item: str(item.get("recorded_at") or ""))
            card["other_records"].sort(key=lambda item: str(item.get("recorded_at") or ""))
            card["daily_advice"] = self.get_daily_health_advice(record_date)
        daily_cards = sorted(cards_by_date.values(), key=lambda item: item["date"], reverse=True)
        return {
            "range_days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "points": points,
            "metrics": {
                "latest_weight_kg": weight_values[-1] if weight_values else None,
                "weight_change_kg": round(weight_values[-1] - weight_values[0], 2) if len(weight_values) > 1 else None,
                "average_water_ml": round(sum(water_values) / len(water_values)) if water_values else 0,
                "average_calories_kcal": round(sum(calorie_values) / len(calorie_values)) if calorie_values else 0,
                "exercise_total_kcal": sum(int(point["exercise_kcal"]) for point in points),
                "recorded_days": sum(1 for point in points if point["has_record"]),
            },
            "records": range_records,
            "daily_cards": daily_cards,
        }

    def create_learning_plan(self, name: str, goal: str = "", source: str = "user") -> dict[str, Any]:
        timestamp = now_iso()
        record_id = f"plan_{uuid.uuid4().hex[:10]}"
        path = self._safe_path(Path("📈 个人成长专栏/新技能学习计划") / f"{record_id}-{safe_slug(name)}.md")
        metadata = {
            "id": record_id,
            "type": "learning_plan",
            "title": name.strip(),
            "goal": goal.strip(),
            "status": "waiting_for_hermes",
            "completed_lessons": 0,
            "total_lessons": 0,
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        body = f"# {name.strip()}\n\n## 学习目标\n\n{goal.strip() or '等待补充'}\n\n## AI Agent 学习路径\n\n等待 AI Agent 生成并由你确认。"
        with self.lock:
            self._write_markdown(path, metadata, body)
            job = self.create_agent_job(
                "learning_plan_generation",
                record_id,
                f"制定学习计划：{name.strip()}",
                {"name": name.strip(), "goal": goal.strip()},
                source=source,
            )
            metadata["agent_job_id"] = job["id"]
            metadata["updated_at"] = now_iso()
            metadata["version"] = 2
            self._write_markdown(path, metadata, body)
            self._log_event("create_learning_plan", name.strip(), source)
        return self.get_learning_plan(record_id)

    @staticmethod
    def _extract_resources(body: str) -> list[dict[str, str]]:
        resources: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", body):
            title, url = match.group(1).strip(), match.group(2).strip()
            if url in seen:
                continue
            seen.add(url)
            domain = re.sub(r"^www\.", "", url.split("//", 1)[-1].split("/", 1)[0].lower())
            resource_type = "video" if any(
                host in domain for host in ("youtube.com", "youtu.be", "bilibili.com", "douyin.com", "xiaohongshu.com")
            ) else "article"
            resources.append({"title": title or domain, "url": url, "domain": domain, "type": resource_type})
        return resources

    def _learning_plan_from_path(self, path: Path) -> dict[str, Any] | None:
        metadata, body = self._read_markdown(path)
        if metadata.get("type") != "learning_plan":
            return None
        plan_id = str(metadata.get("id", ""))
        jobs = self.list_agent_jobs(subject_id=plan_id, job_type="learning_plan_generation", limit=1) if plan_id else []
        return {
            "id": plan_id,
            "name": metadata.get("title", path.stem),
            "goal": metadata.get("goal", ""),
            "status": metadata.get("status", "waiting_for_hermes"),
            "completed_lessons": int(metadata.get("completed_lessons", 0)),
            "total_lessons": int(metadata.get("total_lessons", 0)),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "details": body.strip(),
            "resources": self._extract_resources(body),
            "agent_job": jobs[0] if jobs else None,
        }

    def get_learning_plan(self, plan_id: str) -> dict[str, Any]:
        with self.lock:
            path = self._find_record(LEARNING_PLAN_FOLDER, plan_id)
            if path is None:
                raise KeyError(plan_id)
            plan = self._learning_plan_from_path(path)
            if plan is None:
                raise KeyError(plan_id)
            return plan

    def get_growth(self) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        with self.lock:
            for path in self._safe_path(LEARNING_PLAN_FOLDER).glob("*.md"):
                plan = self._learning_plan_from_path(path)
                if plan is not None:
                    plans.append(plan)
        return sorted(plans, key=lambda item: item.get("updated_at") or "", reverse=True)

    def update_learning_plan(
        self,
        plan_id: str,
        roadmap_markdown: str,
        status: str = "active",
        total_lessons: int = 0,
        completed_lessons: int = 0,
        source: str = "hermes",
    ) -> dict[str, Any]:
        with self.lock:
            path = self._find_record(LEARNING_PLAN_FOLDER, plan_id)
            if path is None:
                raise KeyError(plan_id)
            metadata, _ = self._read_markdown(path)
            metadata["status"] = status
            metadata["total_lessons"] = max(0, total_lessons)
            metadata["completed_lessons"] = max(0, min(completed_lessons, total_lessons or completed_lessons))
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            body = f"# {metadata.get('title', path.stem)}\n\n{roadmap_markdown.strip()}"
            self._write_markdown(path, metadata, body)
            self._complete_jobs_for_subject(
                plan_id,
                "learning_plan_generation",
                f"已生成 {metadata.get('title', plan_id)} 的学习路线",
                source,
            )
            self._log_event("update_learning_plan", metadata.get("title", plan_id), source)
        return self.get_learning_plan(plan_id)

    def update_learning_progress(
        self,
        plan_id: str,
        completed_lessons: int,
        status: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        with self.lock:
            path = self._find_record(LEARNING_PLAN_FOLDER, plan_id)
            if path is None:
                raise KeyError(plan_id)
            metadata, body = self._read_markdown(path)
            total = int(metadata.get("total_lessons", 0))
            completed = max(0, min(completed_lessons, total or completed_lessons))
            metadata["completed_lessons"] = completed
            if status:
                metadata["status"] = status
            elif total and completed >= total:
                metadata["status"] = "completed"
            elif metadata.get("status") == "completed" and completed < total:
                metadata["status"] = "active"
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            self._log_event("update_learning_progress", metadata.get("title", plan_id), source)
        return self.get_learning_plan(plan_id)

    def create_library_item(
        self,
        title: str,
        kind: str,
        reason: str = "",
        status: str = "want",
        source: str = "user",
    ) -> dict[str, Any]:
        if kind not in {"book", "movie", "documentary"}:
            raise ValueError("Unsupported library kind")
        if status not in {"want", "in_progress", "done"}:
            raise ValueError("Unsupported library status")
        record_id = f"library_{uuid.uuid4().hex[:10]}"
        timestamp = now_iso()
        path = self._safe_path(Path("📈 个人成长专栏/书单观影记录/条目") / f"{record_id}-{safe_slug(title)}.md")
        metadata = {
            "id": record_id,
            "type": "library_item",
            "title": title.strip(),
            "kind": kind,
            "status": status,
            "progress_percent": 0,
            "current_position": "",
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        body = (
            f"# {title.strip()}\n\n## 推荐理由\n\n{reason.strip() or '待补充'}\n\n"
            "## 当前进度\n\n还未开始\n\n## 我的心得\n\n\n\n"
            "## AI Agent 意见\n\n\n\n## 整理后的笔记\n\n"
        )
        with self.lock:
            self._write_markdown(path, metadata, body)
            self._log_event("create_library_item", title.strip(), source)
        return next(item for item in self.get_library() if item["id"] == record_id)

    def update_library_item(
        self,
        item_id: str,
        status: str | None = None,
        reflection: str | None = None,
        agent_comment: str | None = None,
        progress_percent: int | None = None,
        current_position: str | None = None,
        organized_notes: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        if status is not None and status not in {"want", "in_progress", "done"}:
            raise ValueError("Unsupported library status")
        with self.lock:
            path = self._find_record("📈 个人成长专栏/书单观影记录/条目", item_id)
            if path is None:
                raise KeyError(item_id)
            metadata, body = self._read_markdown(path)
            if status is not None:
                metadata["status"] = status
            if progress_percent is not None:
                metadata["progress_percent"] = max(0, min(progress_percent, 100))
                if progress_percent >= 100:
                    metadata["status"] = "done"
                elif progress_percent > 0 and metadata.get("status") == "want":
                    metadata["status"] = "in_progress"
            if current_position is not None:
                metadata["current_position"] = current_position.strip()
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            sections = self._markdown_sections(body)
            if reflection is not None:
                sections["我的心得"] = reflection.strip()
            if agent_comment is not None:
                sections["AI Agent 意见"] = agent_comment.strip()
            if organized_notes is not None:
                sections["整理后的笔记"] = organized_notes.strip()
            sections["当前进度"] = metadata.get("current_position") or (
                "已完成" if metadata.get("status") == "done" else "还未开始"
            )
            body = self._build_library_body(metadata.get("title", path.stem), sections)
            self._write_markdown(path, metadata, body)
            if source == "user" and reflection is not None and reflection.strip():
                existing = self.list_agent_jobs(
                    status="pending", job_type="library_discussion", subject_id=item_id, limit=1
                )
                if not existing:
                    self.create_agent_job(
                        "library_discussion",
                        item_id,
                        f"回应并整理：{metadata.get('title', item_id)}",
                        {
                            "title": metadata.get("title", ""),
                            "reflection": reflection.strip(),
                            "current_position": metadata.get("current_position", ""),
                        },
                        source=source,
                    )
            self._log_event("update_library_item", metadata.get("title", item_id), source)
        return self.get_library_item(item_id)

    @staticmethod
    def _markdown_sections(body: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        matches = list(re.finditer(r"^##\s+(.+?)\s*$", body, re.M))
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            sections[match.group(1).strip()] = body[start:end].strip()
        return sections

    @staticmethod
    def _build_library_body(title: str, sections: dict[str, str]) -> str:
        ordered = ["推荐理由", "当前进度", "我的心得", "AI Agent 意见", "整理后的笔记"]
        chunks = [f"# {title}"]
        for heading in ordered:
            chunks.append(f"## {heading}\n\n{sections.get(heading, '').strip()}")
        return "\n\n".join(chunks)

    def _library_item_from_path(self, path: Path) -> dict[str, Any] | None:
        metadata, body = self._read_markdown(path)
        if metadata.get("type") != "library_item":
            return None
        sections = self._markdown_sections(body)
        return {
            "id": metadata.get("id"),
            "title": metadata.get("title", path.stem),
            "kind": metadata.get("kind", "book"),
            "source": metadata.get("source", "user"),
            "status": metadata.get("status", "want"),
            "progress_percent": int(metadata.get("progress_percent", 100 if metadata.get("status") == "done" else 0)),
            "current_position": metadata.get("current_position", sections.get("当前进度", "")),
            "reason": sections.get("推荐理由", ""),
            "reflection": sections.get("我的心得", ""),
            "agent_comment": sections.get("AI Agent 意见", ""),
            "organized_notes": sections.get("整理后的笔记", ""),
            "updated_at": metadata.get("updated_at"),
            "details": body.strip(),
        }

    def get_library_item(self, item_id: str) -> dict[str, Any]:
        with self.lock:
            path = self._find_record("📈 个人成长专栏/书单观影记录/条目", item_id)
            if path is None:
                raise KeyError(item_id)
            item = self._library_item_from_path(path)
            if item is None:
                raise KeyError(item_id)
            return item

    def get_library(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        with self.lock:
            for path in self._safe_path("📈 个人成长专栏/书单观影记录/条目").glob("*.md"):
                item = self._library_item_from_path(path)
                if item:
                    items.append(item)
        return sorted(items, key=lambda item: item.get("updated_at") or "", reverse=True)

    def save_content_item(
        self,
        title: str,
        category: str,
        source_url: str = "",
        summary: str = "",
        details_markdown: str = "",
        media_url: str = "",
        thumbnail_url: str = "",
        platform: str = "",
        source: str = "hermes",
    ) -> dict[str, Any]:
        if category not in {"video_trend", "ai_news", "topic_idea"}:
            raise ValueError("Unsupported content category")
        record_id = f"content_{uuid.uuid4().hex[:10]}"
        timestamp = now_iso()
        path = self._safe_path(Path("📱 个人IP专栏/内容索引") / date.today().strftime("%Y/%m") / f"{record_id}.md")
        metadata = {
            "id": record_id,
            "type": "content_item",
            "category": category,
            "title": title.strip(),
            "source_url": source_url,
            "summary": summary.strip(),
            "media_url": media_url,
            "thumbnail_url": thumbnail_url,
            "platform": platform,
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        detail_content = details_markdown.strip() or summary.strip() or "等待 AI Agent 补充详情。"
        body = (
            f"# {title.strip()}\n\n## 内容摘要\n\n{summary.strip() or '待补充'}\n\n"
            f"## 完整详情\n\n{detail_content}\n\n## 原始来源\n\n{source_url or '待补充'}"
        )
        with self.lock:
            self._write_markdown(path, metadata, body)
            self._log_event("save_content_item", title.strip(), source)
        return self.get_content_item(record_id)

    def _content_item_from_path(self, path: Path) -> dict[str, Any] | None:
        metadata, body = self._read_markdown(path)
        if metadata.get("type") != "content_item":
            return None
        summary_match = re.search(r"## 内容摘要\n\n(.*?)(?=\n\n## 完整详情|\Z)", body, re.S)
        details_match = re.search(r"## 完整详情\n\n(.*?)(?=\n\n## 原始来源|\Z)", body, re.S)
        return {
            "id": metadata.get("id"),
            "category": metadata.get("category"),
            "title": metadata.get("title", path.stem),
            "summary": metadata.get("summary") or (summary_match.group(1).strip() if summary_match else ""),
            "details": details_match.group(1).strip() if details_match else body.strip(),
            "source_url": metadata.get("source_url", ""),
            "media_url": metadata.get("media_url", ""),
            "thumbnail_url": metadata.get("thumbnail_url", ""),
            "platform": metadata.get("platform", ""),
            "updated_at": metadata.get("updated_at", ""),
        }

    def get_content_item(self, item_id: str) -> dict[str, Any]:
        with self.lock:
            path = self._find_record("📱 个人IP专栏/内容索引", item_id)
            if path is None:
                raise KeyError(item_id)
            item = self._content_item_from_path(path)
            if item is None:
                raise KeyError(item_id)
            return item

    def _legacy_content(self, filename: str, category: str) -> list[dict[str, Any]]:
        path = self._safe_path(Path("📱 个人IP专栏") / filename)
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        items: list[dict[str, Any]] = []
        pattern = re.compile(r"^\s*\d+[\.、]\s*\*\*(.+?)\*\*[:：]?\s*(.*)$")
        for line in text.splitlines():
            match = pattern.match(line)
            if match:
                items.append(
                    {
                        "id": f"legacy_{category}_{len(items)}",
                        "category": category,
                        "title": match.group(1).strip("《》『』「」"),
                        "summary": match.group(2).strip(),
                        "source_url": "",
                        "updated_at": "",
                    }
                )
        return items[:6]

    def get_content(self) -> dict[str, list[dict[str, Any]]]:
        result = {"video_trend": [], "ai_news": [], "topic_idea": []}
        with self.lock:
            for path in self._safe_path("📱 个人IP专栏/内容索引").rglob("*.md"):
                item = self._content_item_from_path(path)
                if item is None:
                    continue
                category = item.get("category")
                if category not in result:
                    continue
                result[category].append(item)
            if not result["video_trend"]:
                result["video_trend"] = self._legacy_content("短视频热点选题.md", "video_trend")
            if not result["ai_news"]:
                result["ai_news"] = self._legacy_content("AI资讯整理.md", "ai_news")
        for values in result.values():
            values.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return result

    def save_suggestion(self, title: str, content: str, action_label: str = "", source: str = "hermes") -> dict[str, Any]:
        record_id = f"suggestion_{uuid.uuid4().hex[:10]}"
        timestamp = now_iso()
        path = self._safe_path(Path("🤖 AI Agent/建议") / date.today().strftime("%Y/%m") / f"{record_id}.md")
        metadata = {
            "id": record_id,
            "type": "agent_suggestion",
            "title": title.strip(),
            "action_label": action_label,
            "status": "new",
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
        }
        with self.lock:
            self._write_markdown(path, metadata, f"# {title.strip()}\n\n{content.strip()}")
            self._log_event("save_suggestion", title.strip(), source)
        return {**metadata, "content": content.strip()}

    def latest_suggestion(self) -> dict[str, Any] | None:
        records: list[dict[str, Any]] = []
        with self.lock:
            for path in self._safe_path("🤖 AI Agent/建议").rglob("*.md"):
                metadata, body = self._read_markdown(path)
                if metadata.get("type") != "agent_suggestion":
                    continue
                content = "\n".join(line for line in body.splitlines() if not line.startswith("#")).strip()
                records.append({**metadata, "content": content})
        records.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return records[0] if records else None

    def recent_activity(self, limit: int = 6) -> list[dict[str, str]]:
        path = self._safe_path(Path("🤖 AI Agent/操作日志") / f"{today_text()}.md")
        if not path.exists():
            return []
        _, body = self._read_markdown(path)
        items: list[dict[str, str]] = []
        for line in reversed(body.splitlines()):
            if not line.startswith("- "):
                continue
            parts = [part.strip() for part in line[2:].split("·", 3)]
            if len(parts) == 4:
                items.append({"time": parts[0], "source": parts[1], "action": parts[2], "summary": parts[3]})
            if len(items) >= limit:
                break
        return items

    def touch_hermes(self) -> None:
        marker = self.cache_dir / "hermes-last-seen"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

    def hermes_status(self) -> dict[str, Any]:
        marker = self.cache_dir / "hermes-last-seen"
        if not marker.exists():
            return {"connected": False, "label": "AI Agent 等待接入", "last_seen": None}
        modified = datetime.fromtimestamp(marker.stat().st_mtime).astimezone()
        age_seconds = (datetime.now().astimezone() - modified).total_seconds()
        connected = age_seconds < 300
        return {
            "connected": connected,
            "label": "AI Agent 已连接" if connected else "AI Agent 等待接入",
            "last_seen": modified.isoformat(timespec="seconds"),
        }

    def _find_health_record(self, record_id: str) -> Path | None:
        for folder in HEALTH_RECORD_FOLDERS.values():
            path = self._find_record(folder, record_id)
            if path is not None:
                return path
        return None

    def _queue_health_summary_refresh(self, target_date: str, source: str = "system") -> None:
        pending = self.list_agent_jobs(
            job_type="health_daily_summary_refresh",
            subject_id=target_date,
            limit=100,
        )
        if any(job["status"] in {"pending", "in_progress"} for job in pending):
            return
        self.create_agent_job(
            "health_daily_summary_refresh",
            target_date,
            f"重新生成 {target_date} 健康总结",
            {"target_date": target_date, "reason": "健康记录发生了日期、餐次或删除状态变更"},
            source=source,
        )

    def _queue_health_analysis(self, metadata: dict[str, Any], source: str = "system") -> None:
        record_id = str(metadata.get("id") or "")
        if not record_id or metadata.get("analysis_status") != "queued":
            return
        pending = self.list_agent_jobs(job_type="health_record_analysis", subject_id=record_id, limit=100)
        if any(job["status"] in {"pending", "in_progress"} for job in pending):
            return
        self.create_agent_job(
            "health_record_analysis",
            record_id,
            f"分析健康记录：{metadata.get('title', record_id)}",
            {
                "record_id": record_id,
                "kind": metadata.get("type"),
                "asset": metadata.get("asset"),
                "record_date": metadata.get("record_date"),
                "meal_slot": metadata.get("meal_slot"),
                "meal_label": metadata.get("meal_label"),
            },
            source=source,
        )

    def upload_record(
        self,
        kind: str,
        original_name: str,
        content: bytes,
        source: str = "user",
        record_date: str | None = None,
        meal_slot: str | None = None,
    ) -> dict[str, Any]:
        if kind not in UPLOAD_KINDS:
            raise ValueError("Unsupported upload kind")
        selected_date = date.fromisoformat(record_date or today_text())
        if selected_date > date.today():
            raise ValueError("记录日期不能晚于今天")
        if kind == "meal":
            meal_slot = meal_slot or infer_meal_slot()
            if meal_slot not in MEAL_SLOTS:
                raise ValueError("不支持的餐次类型")
        else:
            meal_slot = None
        asset_folder, record_folder, record_type = UPLOAD_KINDS[kind]
        extension = Path(original_name).suffix.lower()
        if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic"}:
            extension = ".jpg"
        record_id = f"{record_type}_{uuid.uuid4().hex[:12]}"
        asset_relative = Path("附件") / asset_folder / selected_date.strftime("%Y/%m") / f"{record_id}{extension}"
        asset_path = self._safe_path(asset_relative)
        selected_date_text = selected_date.isoformat()
        record_path = self._safe_path(Path(f"💪 减肥健身专栏/{record_folder}") / selected_date_text / f"{record_id}.md")
        timestamp = now_iso()
        if selected_date_text == today_text():
            recorded_at = timestamp
        else:
            local_timezone = datetime.now().astimezone().tzinfo
            selected_time = MEAL_SLOT_TIMES.get(str(meal_slot), datetime.now().strftime("%H:%M:%S"))
            recorded_at = datetime.fromisoformat(f"{selected_date_text}T{selected_time}").replace(tzinfo=local_timezone).isoformat(timespec="seconds")
        meal_label = MEAL_SLOTS.get(str(meal_slot), "")
        if kind == "meal":
            display_title = f"{selected_date.month}月{selected_date.day}日 {meal_label}"
        elif kind == "exercise":
            display_title = f"{selected_date.month}月{selected_date.day}日 运动报告"
        else:
            display_title = f"{selected_date.month}月{selected_date.day}日 体重记录"
        metadata = {
            "id": record_id,
            "type": record_type,
            "title": display_title,
            "original_name": original_name,
            "asset": asset_relative.as_posix(),
            "analysis_status": "queued",
            "record_date": selected_date_text,
            "recorded_at": recorded_at,
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": source,
            "version": 1,
            "deleted": False,
        }
        if meal_slot:
            metadata["meal_slot"] = meal_slot
            metadata["meal_label"] = meal_label
        body = f"# {display_title}\n\n![[{asset_relative.as_posix()}]]\n\n## AI Agent 分析\n\n等待分析。"
        with self.lock:
            self._write_binary(asset_path, content)
            self._write_markdown(record_path, metadata, body)
            self.create_agent_job(
                "health_record_analysis",
                record_id,
                f"分析健康记录：{display_title}",
                {
                    "record_id": record_id,
                    "kind": record_type,
                    "asset": asset_relative.as_posix(),
                    "record_date": selected_date_text,
                    "meal_slot": meal_slot,
                    "meal_label": meal_label,
                },
                source=source,
            )
            self._log_event("upload_record", f"{kind}: {display_title}", source)
        return metadata

    def list_health_records(
        self,
        status: str | None = None,
        limit: int = 20,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with self.lock:
            for kind, folder in HEALTH_RECORD_FOLDERS.items():
                for path in self._safe_path(folder).rglob("*.md"):
                    metadata, body = self._read_markdown(path)
                    if metadata.get("type") != kind:
                        continue
                    deleted = bool(metadata.get("deleted", False))
                    if deleted and not include_deleted:
                        continue
                    if status and metadata.get("analysis_status") != status:
                        continue
                    recorded_at = str(metadata.get("recorded_at") or "")
                    record_date = str(metadata.get("record_date") or recorded_at[:10])
                    meal_slot = str(metadata.get("meal_slot") or infer_meal_slot(recorded_at)) if kind == "meal" else ""
                    analysis = body.split("## AI Agent 分析", 1)[-1].strip() if "## AI Agent 分析" in body else ""
                    analysis_summary, analysis_advice = (
                        analysis.split("## 今日建议", 1) if "## 今日建议" in analysis else (analysis, "")
                    )
                    records.append({
                        "id": metadata.get("id"),
                        "kind": kind,
                        "title": metadata.get("title", path.stem),
                        "original_name": metadata.get("original_name", ""),
                        "asset": metadata.get("asset", ""),
                        "analysis_status": metadata.get("analysis_status", "queued"),
                        "calories_kcal": metadata.get("calories_kcal"),
                        "exercise_kcal": metadata.get("exercise_kcal"),
                        "weight_kg": metadata.get("weight_kg"),
                        "record_date": record_date,
                        "recorded_at": recorded_at,
                        "meal_slot": meal_slot,
                        "meal_label": str(metadata.get("meal_label") or MEAL_SLOTS.get(meal_slot, "")),
                        "analysis": analysis,
                        "analysis_summary": clean_health_advice_text(analysis_summary),
                        "analysis_advice": clean_health_advice_text(analysis_advice),
                        "deleted": deleted,
                        "deleted_at": metadata.get("deleted_at"),
                    })
        records.sort(key=lambda item: item.get("recorded_at") or "", reverse=True)
        return records[: max(1, min(limit, 4000))]

    def update_health_record(
        self,
        record_id: str,
        record_date: str | None = None,
        meal_slot: str | None = None,
        source: str = "user",
    ) -> dict[str, Any]:
        with self.lock:
            path = self._find_health_record(record_id)
            if path is None:
                raise KeyError(record_id)
            metadata, body = self._read_markdown(path)
            if bool(metadata.get("deleted", False)):
                raise ValueError("请先从回收站恢复这条记录")
            record_type = str(metadata.get("type", ""))
            old_date = str(metadata.get("record_date") or metadata.get("recorded_at", ""))[:10]
            selected_date = date.fromisoformat(record_date or old_date)
            if selected_date > date.today():
                raise ValueError("记录日期不能晚于今天")
            if record_type == "meal":
                selected_slot = meal_slot or str(metadata.get("meal_slot") or infer_meal_slot(metadata.get("recorded_at")))
                if selected_slot not in MEAL_SLOTS:
                    raise ValueError("不支持的餐次类型")
                metadata["meal_slot"] = selected_slot
                metadata["meal_label"] = MEAL_SLOTS[selected_slot]
                display_title = f"{selected_date.month}月{selected_date.day}日 {MEAL_SLOTS[selected_slot]}"
                selected_time = MEAL_SLOT_TIMES[selected_slot]
            elif record_type == "exercise":
                display_title = f"{selected_date.month}月{selected_date.day}日 运动报告"
                selected_time = str(metadata.get("recorded_at") or "T09:00:00").split("T")[-1][:8]
            else:
                display_title = f"{selected_date.month}月{selected_date.day}日 体重记录"
                selected_time = str(metadata.get("recorded_at") or "T09:00:00").split("T")[-1][:8]
            if len(selected_time) < 8:
                selected_time = "09:00:00"
            timezone = datetime.now().astimezone().tzinfo
            metadata["record_date"] = selected_date.isoformat()
            metadata["recorded_at"] = datetime.fromisoformat(
                f"{selected_date.isoformat()}T{selected_time}"
            ).replace(tzinfo=timezone).isoformat(timespec="seconds")
            metadata["title"] = display_title

            old_asset = str(metadata.get("asset") or "")
            if old_date != selected_date.isoformat() and old_asset:
                asset_prefix = {"meal": "饮食", "exercise": "运动", "weight_photo": "体重"}[record_type]
                old_asset_path = self._safe_path(old_asset)
                extension = old_asset_path.suffix or ".jpg"
                new_asset_relative = Path("附件") / asset_prefix / selected_date.strftime("%Y/%m") / f"{record_id}{extension}"
                new_asset_path = self._safe_path(new_asset_relative)
                new_asset_path.parent.mkdir(parents=True, exist_ok=True)
                if old_asset_path.exists() and old_asset_path != new_asset_path:
                    os.replace(old_asset_path, new_asset_path)
                metadata["asset"] = new_asset_relative.as_posix()
                body = body.replace(old_asset, new_asset_relative.as_posix())

            body = re.sub(r"(?m)^# .+$", f"# {display_title}", body, count=1)
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            target_path = self._safe_path(
                Path(HEALTH_RECORD_FOLDERS[record_type]) / selected_date.isoformat() / f"{record_id}.md"
            )
            self._write_markdown(target_path, metadata, body)
            if target_path != path and path.exists():
                path.unlink()
            if metadata.get("analysis_status") == "queued":
                self._complete_jobs_for_subject(
                    record_id,
                    "health_record_analysis",
                    "记录信息已修改，旧分析任务已替换",
                    source,
                )
                self._queue_health_analysis(metadata, source)
            self._queue_health_summary_refresh(old_date, source)
            if selected_date.isoformat() != old_date:
                self._queue_health_summary_refresh(selected_date.isoformat(), source)
            self._log_event("update_health_record", f"{record_id}: {old_date} → {selected_date.isoformat()}", source)
        return next(item for item in self.list_health_records(limit=4000) if item["id"] == record_id)

    def delete_health_record(self, record_id: str, source: str = "user") -> dict[str, Any]:
        with self.lock:
            path = self._find_health_record(record_id)
            if path is None:
                raise KeyError(record_id)
            metadata, body = self._read_markdown(path)
            metadata["deleted"] = True
            metadata["deleted_at"] = now_iso()
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            target_date = str(metadata.get("record_date") or metadata.get("recorded_at", ""))[:10]
            self._complete_jobs_for_subject(
                record_id,
                "health_record_analysis",
                "记录已移入回收站，分析任务已取消",
                source,
            )
            self._queue_health_summary_refresh(target_date, source)
            self._log_event("delete_health_record", metadata.get("title", record_id), source)
        return next(item for item in self.list_health_records(limit=4000, include_deleted=True) if item["id"] == record_id)

    def restore_health_record(self, record_id: str, source: str = "user") -> dict[str, Any]:
        with self.lock:
            path = self._find_health_record(record_id)
            if path is None:
                raise KeyError(record_id)
            metadata, body = self._read_markdown(path)
            metadata["deleted"] = False
            metadata.pop("deleted_at", None)
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            self._write_markdown(path, metadata, body)
            target_date = str(metadata.get("record_date") or metadata.get("recorded_at", ""))[:10]
            self._queue_health_analysis(metadata, source)
            self._queue_health_summary_refresh(target_date, source)
            self._log_event("restore_health_record", metadata.get("title", record_id), source)
        return next(item for item in self.list_health_records(limit=4000) if item["id"] == record_id)

    def analyze_health_record(
        self,
        record_id: str,
        summary: str,
        advice: str = "",
        calories_kcal: int | None = None,
        exercise_kcal: int | None = None,
        weight_kg: float | None = None,
        source: str = "hermes",
    ) -> dict[str, Any]:
        path: Path | None = None
        with self.lock:
            path = self._find_health_record(record_id)
            if path is None:
                raise KeyError(record_id)
            metadata, _ = self._read_markdown(path)
            record_type = str(metadata.get("type", ""))
            if calories_kcal is not None:
                metadata["calories_kcal"] = max(0, calories_kcal)
            if exercise_kcal is not None:
                metadata["exercise_kcal"] = max(0, exercise_kcal)
            if weight_kg is not None:
                metadata["weight_kg"] = round(weight_kg, 2)
            metadata["analysis_status"] = "analyzed"
            metadata["analyzed_at"] = now_iso()
            metadata["updated_at"] = now_iso()
            metadata["version"] = int(metadata.get("version", 1)) + 1
            asset = metadata.get("asset", "")
            body = (
                f"# {metadata.get('title', path.stem)}\n\n![[{asset}]]\n\n"
                f"## AI Agent 分析\n\n{summary.strip()}\n\n## 今日建议\n\n{advice.strip()}"
            )
            self._write_markdown(path, metadata, body)
            self._complete_jobs_for_subject(
                record_id, "health_record_analysis", f"已分析 {metadata.get('title', record_id)}", source
            )
            if record_type == "weight_photo" and weight_kg is not None:
                self.record_weight(weight_kg, source=source)
            self._log_event("analyze_health_record", metadata.get("title", record_id), source)
        return next(item for item in self.list_health_records(limit=100) if item["id"] == record_id)

    def dashboard(self) -> dict[str, Any]:
        self.ensure_daily_agent_jobs()
        all_tasks = self.list_tasks()
        target_date = today_text()
        today_date = date.fromisoformat(target_date)
        upcoming_end = today_date + timedelta(days=120)
        calendar_tasks, _ = self.task_occurrences(today_date, upcoming_end)
        tasks = []
        for task in all_tasks:
            if task.get("recurrence") == "yearly":
                occurrence = next((item for item in calendar_tasks if item["id"] == task["id"] and item["occurrence_date"] == target_date), None)
                if occurrence:
                    tasks.append(occurrence)
            elif not task.get("due_at") or str(task.get("due_at"))[:10] <= target_date:
                tasks.append(task)
        upcoming_tasks = [
            task for task in calendar_tasks
            if task["occurrence_date"] > target_date and not task["done"]
        ]
        grouped = {key: [] for key in QUADRANTS}
        for task in tasks:
            grouped[task["quadrant"]].append(task)
        completed = sum(1 for item in tasks if item["done"])
        return {
            "date": today_text(),
            "profile": self.get_profile_settings(),
            "greeting": self.get_daily_message(),
            "preferences": {
                "health": self.get_health_goals(),
                "ip": self.get_ip_preferences(),
            },
            "projects": self.list_projects(),
            "tasks": grouped,
            "upcoming_tasks": upcoming_tasks[:8],
            "task_progress": {"completed": completed, "total": len(tasks)},
            "health": self.health_summary(),
            "growth": self.get_growth(),
            "library": self.get_library(),
            "health_records": self.list_health_records(limit=8),
            "content": self.get_content(),
            "hermes": self.hermes_status(),
            "suggestion": self.latest_suggestion(),
            "activity": self.recent_activity(),
            "index": self.index.status(),
        }

    def seed_demo(self) -> None:
        if self.list_tasks():
            return
        self.create_task("完成今天的直播脚本初稿", "important_urgent", source="demo")
        self.create_task("个人IP内容选题规划", "important_not_urgent", source="demo")
        self.create_task("回复合作方消息", "not_important_urgent", source="demo")
        self.create_task("整理电脑文件", "not_important_not_urgent", source="demo")
        self.create_task("30分钟有氧运动", "important_not_urgent", source="demo")
        self.record_water(500, source="demo")
        self.record_water(700, source="demo")
        self.create_learning_plan("围棋入门", "掌握基本规则并完成12课入门路径", source="demo")
        self.save_content_item("普通人如何用AI提升日常效率", "video_trend", summary="适合结合真实工作流程拆解。", source="demo")
        self.save_content_item("今日行业动态速览", "ai_news", summary="按用户关注方向整理并保留可验证来源。", source="demo")
        self.save_suggestion("安排20分钟复盘", "今晚可以用20分钟整理今天的收获，帮助巩固记忆。", "去复盘", source="demo")
        self.rebuild_index()
