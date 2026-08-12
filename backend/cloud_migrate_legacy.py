from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .app.cloud.config import CloudSettings
from .app.cloud.database import CloudDatabase, tenant_transaction
from .app.cloud.image_processing import NormalizedImage, normalize_health_image
from .app.cloud.models import (
    AgentJob,
    AuditEvent,
    ContentItem,
    DailyMessage,
    DataExport,
    HealthAnalysis,
    HealthDailySummary,
    HealthRecord,
    LearningPlan,
    LibraryItem,
    Project,
    StoredObject,
    Suggestion,
    Task,
    TaskOccurrence,
    User,
    WaterEntry,
    WeightEntry,
    Workspace,
    WorkspaceEvent,
    WorkspaceSettings,
)
from .app.cloud.security import normalize_username
from .app.cloud.storage import LocalPrivateObjectStore
from .app.store import DAILY_HEALTH_ADVICE_FOLDER, DAILY_MESSAGE_FOLDER, MarkdownStore


LEGACY_NAMESPACE = uuid.UUID("8faeffe7-b7d1-45bf-bbd7-cb7c01e7c1bb")
SOURCE_LABEL = "legacy_import"


@dataclass(slots=True)
class LegacyDocument:
    path: Path
    metadata: dict[str, Any]
    body: str


@dataclass(slots=True)
class PreparedHealthImage:
    record: dict[str, Any]
    source_path: Path
    normalized: NormalizedImage


@dataclass(slots=True)
class LegacySnapshot:
    root: Path
    store: MarkdownStore
    fingerprint: str
    file_count: int
    total_bytes: int
    type_counts: dict[str, int]
    documents: list[LegacyDocument]
    projects: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    learning_plans: list[dict[str, Any]]
    library_items: list[dict[str, Any]]
    content_items: list[dict[str, Any]]
    health_records: list[dict[str, Any]]
    health_images: list[PreparedHealthImage]
    agent_jobs: list[dict[str, Any]]


def _parse_datetime(value: Any, timezone_name: str = "Asia/Shanghai") -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _deterministic_id(workspace_public_id: uuid.UUID, kind: str, legacy_key: str) -> uuid.UUID:
    return uuid.uuid5(LEGACY_NAMESPACE, f"{workspace_public_id}:{kind}:{legacy_key}")


def _source(value: Any, default: str = SOURCE_LABEL) -> str:
    cleaned = str(value or default).strip().lower()
    if cleaned in {"agent", "hermes", "user", "system"}:
        return "hermes" if cleaned == "agent" else cleaned
    return default


def _safe_asset(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Legacy asset escaped the vault: {relative}") from exc
    if not target.is_file():
        raise FileNotFoundError(target)
    return target


def _read_documents(store: MarkdownStore) -> list[LegacyDocument]:
    documents: list[LegacyDocument] = []
    for path in sorted(store.root.rglob("*.md")):
        metadata, body = store._read_markdown(path)
        documents.append(LegacyDocument(path=path, metadata=metadata, body=body))
    return documents


def _fingerprint(files: Iterable[Path], root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(files):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        count += 1
        total += len(content)
    return digest.hexdigest(), count, total


def collect_legacy(vault: Path, cache_dir: Path) -> LegacySnapshot:
    root = vault.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    store = MarkdownStore(root, cache_dir)
    documents = _read_documents(store)
    all_files = [path for path in root.rglob("*") if path.is_file()]
    fingerprint, file_count, total_bytes = _fingerprint(all_files, root)
    type_counts = Counter(str(item.metadata.get("type", "note")) for item in documents)
    content_groups = store.get_content()
    content_items = [item for group in content_groups.values() for item in group]
    health_records = store.list_health_records(limit=4000, include_deleted=True)
    health_images: list[PreparedHealthImage] = []
    for record in health_records:
        asset = str(record.get("asset") or "").strip()
        if not asset:
            raise ValueError(f"Legacy health record has no asset: {record.get('id')}")
        source_path = _safe_asset(root, asset)
        health_images.append(
            PreparedHealthImage(
                record=record,
                source_path=source_path,
                normalized=normalize_health_image(source_path.read_bytes()),
            )
        )
    return LegacySnapshot(
        root=root,
        store=store,
        fingerprint=fingerprint,
        file_count=file_count,
        total_bytes=total_bytes,
        type_counts=dict(type_counts),
        documents=documents,
        projects=store.list_projects(),
        tasks=store.list_tasks(include_deleted=True),
        learning_plans=store.get_growth(),
        library_items=store.get_library(),
        content_items=content_items,
        health_records=health_records,
        health_images=health_images,
        agent_jobs=store.list_agent_jobs(limit=4000),
    )


def snapshot_summary(snapshot: LegacySnapshot) -> dict[str, Any]:
    return {
        "fingerprint": snapshot.fingerprint,
        "file_count": snapshot.file_count,
        "total_bytes": snapshot.total_bytes,
        "type_counts": snapshot.type_counts,
        "projects": len(snapshot.projects),
        "tasks": len(snapshot.tasks),
        "learning_plans": len(snapshot.learning_plans),
        "library_items": len(snapshot.library_items),
        "content_items": len(snapshot.content_items),
        "health_records": len(snapshot.health_records),
        "agent_jobs": len(snapshot.agent_jobs),
    }


COUNT_MODELS = {
    "projects": Project,
    "tasks": Task,
    "daily_messages": DailyMessage,
    "suggestions": Suggestion,
    "water_entries": WaterEntry,
    "weight_entries": WeightEntry,
    "health_records": HealthRecord,
    "health_analyses": HealthAnalysis,
    "health_daily_summaries": HealthDailySummary,
    "learning_plans": LearningPlan,
    "library_items": LibraryItem,
    "content_items": ContentItem,
    "agent_jobs": AgentJob,
    "audit_events": AuditEvent,
    "stored_objects": StoredObject,
    "data_exports": DataExport,
}


async def cloud_counts(session: Any, workspace_id: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for label, model in COUNT_MODELS.items():
        result[label] = int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
            )
            or 0
        )
    return result


async def _workspace_identity(database: CloudDatabase, username: str) -> tuple[int, uuid.UUID]:
    async with database.session_factory() as session:
        user = await session.scalar(
            select(User).where(User.username_normalized == normalize_username(username))
        )
        if user is None:
            raise ValueError("Cloud user does not exist")
        workspace = await session.get(Workspace, user.workspace_id)
        if workspace is None:
            raise ValueError("Cloud workspace does not exist")
        return workspace.id, workspace.public_id


def _legacy_documents(snapshot: LegacySnapshot, document_type: str) -> list[LegacyDocument]:
    return [item for item in snapshot.documents if item.metadata.get("type") == document_type]


async def _import_settings(session: Any, workspace_id: int, snapshot: LegacySnapshot) -> int:
    settings = await session.scalar(
        select(WorkspaceSettings).where(WorkspaceSettings.workspace_id == workspace_id)
    )
    if settings is None:
        settings = WorkspaceSettings(workspace_id=workspace_id)
        session.add(settings)
        await session.flush()
    profile = snapshot.store.get_profile_settings()
    health = snapshot.store.get_health_goals()
    ip_preferences = snapshot.store.get_ip_preferences()
    settings.profile = {**dict(settings.profile or {}), **profile}
    settings.health = {**dict(settings.health or {}), **health}
    settings.ip_preferences = {**dict(settings.ip_preferences or {}), **ip_preferences}
    settings.updated_at = datetime.now(timezone.utc)
    return 1


async def _import_projects(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for item in snapshot.projects:
        legacy_id = str(item["id"])
        record = await session.scalar(
            select(Project).where(Project.workspace_id == workspace_id, Project.legacy_id == legacy_id)
        )
        if record is None:
            record = await session.scalar(
                select(Project).where(Project.workspace_id == workspace_id, Project.name == item["name"])
            )
        if record is None:
            record = Project(
                public_id=_deterministic_id(workspace_public_id, "project", legacy_id),
                workspace_id=workspace_id,
                legacy_id=legacy_id,
                name=str(item["name"])[:160],
            )
            session.add(record)
        record.legacy_id = legacy_id
        record.name = str(item["name"])[:160]
        record.current_stage = str(item.get("current_stage") or "准备中")[:200]
        record.progress_percent = int(item.get("progress_percent") or 0)
        record.next_milestone = str(item.get("next_milestone") or "")
        record.due_date = _parse_date(item.get("due_date"))
        record.status = str(item.get("status") or "active")
        record.source = _source(item.get("source"))
        record.updated_at = _parse_datetime(item.get("updated_at")) or datetime.now(timezone.utc)
        count += 1
    return count


async def _import_tasks(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for item in snapshot.tasks:
        legacy_id = str(item["id"])
        record = await session.scalar(
            select(Task).where(Task.workspace_id == workspace_id, Task.legacy_id == legacy_id)
        )
        if record is None:
            record = Task(
                public_id=_deterministic_id(workspace_public_id, "task", legacy_id),
                workspace_id=workspace_id,
                legacy_id=legacy_id,
                title=str(item["title"])[:160],
                quadrant=str(item.get("quadrant") or "important_not_urgent"),
            )
            session.add(record)
            await session.flush()
        record.legacy_id = legacy_id
        record.title = str(item["title"])[:160]
        record.quadrant = str(item.get("quadrant") or "important_not_urgent")
        record.due_at = _parse_datetime(item.get("due_at"))
        record.note = str(item.get("note") or "")
        record.recurrence = str(item.get("recurrence") or "none")
        record.done = bool(item.get("done"))
        record.completed_at = (
            _parse_datetime(item.get("updated_at")) if record.done else None
        )
        record.source = SOURCE_LABEL
        record.deleted_at = _parse_datetime(item.get("deleted_at")) if item.get("deleted") else None
        now = datetime.now(timezone.utc)
        record.created_at = _parse_datetime(item.get("created_at")) or record.created_at or now
        record.updated_at = _parse_datetime(item.get("updated_at")) or record.updated_at or now
        for occurrence_text in item.get("completed_occurrences") or []:
            occurrence_date = _parse_date(occurrence_text)
            if occurrence_date is None:
                continue
            existing = await session.scalar(
                select(TaskOccurrence).where(
                    TaskOccurrence.workspace_id == workspace_id,
                    TaskOccurrence.task_id == record.id,
                    TaskOccurrence.occurrence_date == occurrence_date,
                )
            )
            if existing is None:
                session.add(
                    TaskOccurrence(
                        workspace_id=workspace_id,
                        task_id=record.id,
                        occurrence_date=occurrence_date,
                        source=SOURCE_LABEL,
                    )
                )
        count += 1
    return count


async def _import_daily_messages(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for document in _legacy_documents(snapshot, "daily_message"):
        target_date = _parse_date(document.metadata.get("date"))
        if target_date is None:
            continue
        payload = snapshot.store.get_daily_message(target_date.isoformat())
        record = await session.scalar(
            select(DailyMessage).where(
                DailyMessage.workspace_id == workspace_id,
                DailyMessage.target_date == target_date,
            )
        )
        if record is None:
            record = DailyMessage(
                public_id=_deterministic_id(
                    workspace_public_id, "daily_message", target_date.isoformat()
                ),
                workspace_id=workspace_id,
                target_date=target_date,
                message=str(payload.get("message") or "")[:120],
            )
            session.add(record)
        record.message = str(payload.get("message") or "")[:120]
        record.tone = str(payload.get("tone") or "mixed")
        record.source = _source(document.metadata.get("source"), "hermes")
        record.updated_at = _parse_datetime(document.metadata.get("updated_at")) or datetime.now(
            timezone.utc
        )
        count += 1
    return count


async def _import_suggestions(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for document in _legacy_documents(snapshot, "agent_suggestion"):
        metadata = document.metadata
        legacy_id = str(metadata.get("id") or document.path.stem)
        public_id = _deterministic_id(workspace_public_id, "suggestion", legacy_id)
        record = await session.scalar(
            select(Suggestion).where(
                Suggestion.workspace_id == workspace_id,
                Suggestion.public_id == public_id,
            )
        )
        if record is None:
            record = Suggestion(
                public_id=public_id,
                workspace_id=workspace_id,
                title=str(metadata.get("title") or document.path.stem)[:160],
                content=document.body.strip(),
            )
            session.add(record)
        record.title = str(metadata.get("title") or document.path.stem)[:160]
        record.content = document.body.strip()
        record.action_label = str(metadata.get("action_label") or "")[:60]
        record.source = _source(metadata.get("source"), "hermes")
        record.is_read = str(metadata.get("status") or "new") != "new"
        now = datetime.now(timezone.utc)
        record.created_at = _parse_datetime(metadata.get("created_at")) or record.created_at or now
        record.updated_at = _parse_datetime(metadata.get("updated_at")) or record.updated_at or now
        count += 1
    return count


async def _import_learning_plans(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for item in snapshot.learning_plans:
        legacy_id = str(item["id"])
        record = await session.scalar(
            select(LearningPlan).where(
                LearningPlan.workspace_id == workspace_id,
                LearningPlan.legacy_id == legacy_id,
            )
        )
        if record is None:
            record = await session.scalar(
                select(LearningPlan).where(
                    LearningPlan.workspace_id == workspace_id,
                    func.lower(LearningPlan.name) == str(item["name"]).lower(),
                    LearningPlan.deleted_at.is_(None),
                )
            )
        if record is None:
            record = LearningPlan(
                public_id=_deterministic_id(workspace_public_id, "learning_plan", legacy_id),
                workspace_id=workspace_id,
                legacy_id=legacy_id,
                name=str(item["name"])[:120],
            )
            session.add(record)
        record.legacy_id = legacy_id
        record.name = str(item["name"])[:120]
        record.goal = str(item.get("goal") or "")
        record.status = str(item.get("status") or "active")
        record.completed_lessons = int(item.get("completed_lessons") or 0)
        record.total_lessons = int(item.get("total_lessons") or 0)
        record.details_markdown = str(item.get("details") or "")
        record.resources = list(item.get("resources") or [])
        record.source = SOURCE_LABEL
        now = datetime.now(timezone.utc)
        record.created_at = _parse_datetime(item.get("created_at")) or record.created_at or now
        record.updated_at = _parse_datetime(item.get("updated_at")) or record.updated_at or now
        count += 1
    return count


async def _import_library(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for item in snapshot.library_items:
        legacy_id = str(item["id"])
        record = await session.scalar(
            select(LibraryItem).where(
                LibraryItem.workspace_id == workspace_id,
                LibraryItem.legacy_id == legacy_id,
            )
        )
        if record is None:
            record = await session.scalar(
                select(LibraryItem).where(
                    LibraryItem.workspace_id == workspace_id,
                    LibraryItem.title == str(item["title"]),
                    LibraryItem.kind == str(item["kind"]),
                    LibraryItem.deleted_at.is_(None),
                )
            )
        if record is None:
            record = LibraryItem(
                public_id=_deterministic_id(workspace_public_id, "library", legacy_id),
                workspace_id=workspace_id,
                legacy_id=legacy_id,
                title=str(item["title"])[:200],
                kind=str(item["kind"]),
            )
            session.add(record)
        record.legacy_id = legacy_id
        record.title = str(item["title"])[:200]
        record.kind = str(item["kind"])
        record.status = str(item.get("status") or "want")
        record.progress_percent = int(item.get("progress_percent") or 0)
        record.current_position = str(item.get("current_position") or "")[:240]
        record.reason = str(item.get("reason") or "")
        record.reflection = str(item.get("reflection") or "")
        record.agent_comment = str(item.get("agent_comment") or "")
        record.organized_notes = str(item.get("organized_notes") or "")
        record.source = _source(item.get("source"))
        record.updated_at = (
            _parse_datetime(item.get("updated_at"))
            or record.updated_at
            or datetime.now(timezone.utc)
        )
        count += 1
    return count


async def _import_content(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for item in snapshot.content_items:
        legacy_id = str(item["id"])
        source_url = str(item.get("source_url") or "").strip() or None
        record = await session.scalar(
            select(ContentItem).where(
                ContentItem.workspace_id == workspace_id,
                ContentItem.legacy_id == legacy_id,
            )
        )
        if record is None and source_url:
            record = await session.scalar(
                select(ContentItem).where(
                    ContentItem.workspace_id == workspace_id,
                    ContentItem.category == str(item["category"]),
                    ContentItem.source_url == source_url,
                )
            )
        if record is None:
            record = await session.scalar(
                select(ContentItem).where(
                    ContentItem.workspace_id == workspace_id,
                    ContentItem.category == str(item["category"]),
                    ContentItem.title == str(item["title"]),
                    ContentItem.deleted_at.is_(None),
                )
            )
        if record is None:
            record = ContentItem(
                public_id=_deterministic_id(workspace_public_id, "content", legacy_id),
                workspace_id=workspace_id,
                legacy_id=legacy_id,
                category=str(item["category"]),
                title=str(item["title"])[:300],
            )
            session.add(record)
        if record.legacy_id is None:
            record.legacy_id = legacy_id
        record.category = str(item["category"])
        record.title = str(item["title"])[:300]
        record.summary = str(item.get("summary") or "")
        record.details_markdown = str(item.get("details") or item.get("summary") or "")
        record.source_url = source_url
        record.media_url = str(item.get("media_url") or "")
        record.thumbnail_url = str(item.get("thumbnail_url") or "")
        record.platform = str(item.get("platform") or "")[:80]
        record.source = SOURCE_LABEL
        record.updated_at = (
            _parse_datetime(item.get("updated_at"))
            or record.updated_at
            or datetime.now(timezone.utc)
        )
        count += 1
    return count


async def _stored_object(
    session: Any,
    workspace_id: int,
    public_id: uuid.UUID,
    object_key: str,
    original_filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    created_at: datetime,
) -> StoredObject:
    record = await session.scalar(
        select(StoredObject).where(
            StoredObject.workspace_id == workspace_id,
            StoredObject.public_id == public_id,
        )
    )
    if record is None:
        record = StoredObject(
            public_id=public_id,
            workspace_id=workspace_id,
            object_key=object_key,
            original_filename=original_filename[:255],
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            status="ready",
            created_at=created_at,
        )
        session.add(record)
        await session.flush()
    else:
        record.object_key = object_key
        record.original_filename = original_filename[:255]
        record.content_type = content_type
        record.size_bytes = size_bytes
        record.sha256 = sha256
        record.status = "ready"
        record.deleted_at = None
    return record


async def _import_health(
    session: Any,
    workspace_id: int,
    workspace_public_id: uuid.UUID,
    snapshot: LegacySnapshot,
    object_store: LocalPrivateObjectStore,
) -> tuple[int, dict[date, list[str]]]:
    count = 0
    thumbnails_by_date: dict[date, list[str]] = {}
    for prepared in snapshot.health_images:
        item = prepared.record
        legacy_id = str(item["id"])
        record_date = _parse_date(item.get("record_date"))
        if record_date is None:
            raise ValueError(f"Legacy health record has no date: {legacy_id}")
        occurred_at = _parse_datetime(item.get("recorded_at")) or datetime.combine(
            record_date, time(12, 0), ZoneInfo("Asia/Shanghai")
        ).astimezone(timezone.utc)
        display_id = _deterministic_id(workspace_public_id, "health_display", legacy_id)
        thumbnail_id = _deterministic_id(workspace_public_id, "health_thumbnail", legacy_id)
        display_key = object_store.build_key(
            workspace_public_id, display_id, prepared.normalized.content_type, occurred_at
        )
        thumbnail_key = object_store.build_key(
            workspace_public_id, thumbnail_id, prepared.normalized.content_type, occurred_at
        )
        display_result = object_store.put_bytes(display_key, prepared.normalized.display_content)
        thumbnail_result = object_store.put_bytes(
            thumbnail_key, prepared.normalized.thumbnail_content
        )
        display_object = await _stored_object(
            session,
            workspace_id,
            display_id,
            display_key,
            str(item.get("original_name") or prepared.source_path.name),
            prepared.normalized.content_type,
            display_result.size_bytes,
            display_result.sha256,
            occurred_at,
        )
        thumbnail_object = await _stored_object(
            session,
            workspace_id,
            thumbnail_id,
            thumbnail_key,
            f"thumbnail-{str(item.get('original_name') or prepared.source_path.name)}",
            prepared.normalized.content_type,
            thumbnail_result.size_bytes,
            thumbnail_result.sha256,
            occurred_at,
        )
        record = await session.scalar(
            select(HealthRecord).where(
                HealthRecord.workspace_id == workspace_id,
                HealthRecord.legacy_id == legacy_id,
            )
        )
        if record is None:
            record = HealthRecord(
                public_id=_deterministic_id(workspace_public_id, "health_record", legacy_id),
                workspace_id=workspace_id,
                legacy_id=legacy_id,
                idempotency_key=f"legacy-import:{legacy_id}"[:160],
                kind=str(item["kind"]),
                record_date=record_date,
                occurred_at=occurred_at,
                object_id=display_object.id,
                thumbnail_object_id=thumbnail_object.id,
            )
            session.add(record)
            await session.flush()
        record.legacy_id = legacy_id
        record.kind = str(item["kind"])
        record.record_date = record_date
        record.occurred_at = occurred_at
        record.meal_slot = str(item.get("meal_slot") or "") or None
        record.object_id = display_object.id
        record.thumbnail_object_id = thumbnail_object.id
        record.analysis_status = (
            "analyzed"
            if item.get("analysis_status") == "analyzed" or item.get("analysis")
            else "failed"
        )
        record.source = SOURCE_LABEL
        record.deleted_at = _parse_datetime(item.get("deleted_at")) if item.get("deleted") else None
        record.created_at = _parse_datetime(item.get("recorded_at")) or record.created_at
        record.updated_at = _parse_datetime(item.get("recorded_at")) or record.updated_at
        summary = str(item.get("analysis_summary") or item.get("analysis") or "历史记录")
        advice = str(item.get("analysis_advice") or "")
        analysis = await session.scalar(
            select(HealthAnalysis).where(
                HealthAnalysis.workspace_id == workspace_id,
                HealthAnalysis.health_record_id == record.id,
            )
        )
        if analysis is None:
            analysis = HealthAnalysis(
                public_id=_deterministic_id(workspace_public_id, "health_analysis", legacy_id),
                workspace_id=workspace_id,
                health_record_id=record.id,
                summary=summary,
            )
            session.add(analysis)
        analysis.summary = summary
        analysis.advice = advice
        analysis.calories_kcal = item.get("calories_kcal")
        analysis.exercise_kcal = item.get("exercise_kcal")
        analysis.weight_kg = (
            Decimal(str(item["weight_kg"])) if item.get("weight_kg") is not None else None
        )
        analysis.model_name = "legacy-hermes"
        analysis.analyzed_at = _parse_datetime(item.get("recorded_at")) or occurred_at
        analysis.updated_at = _parse_datetime(item.get("recorded_at")) or occurred_at
        thumbnails_by_date.setdefault(record_date, []).append(str(thumbnail_id))
        count += 1
    return count, thumbnails_by_date


async def _import_health_days(
    session: Any,
    workspace_id: int,
    workspace_public_id: uuid.UUID,
    snapshot: LegacySnapshot,
    thumbnails_by_date: dict[date, list[str]],
) -> tuple[int, int, int]:
    water_count = 0
    weight_count = 0
    daily_metadata: dict[date, dict[str, Any]] = {}
    for document in _legacy_documents(snapshot, "health_day"):
        record_date = _parse_date(document.metadata.get("date"))
        if record_date is None:
            continue
        daily_metadata[record_date] = document.metadata
        entries = list(document.metadata.get("water_entries") or [])
        if not entries and int(document.metadata.get("water_ml") or 0) > 0:
            entries = [
                {
                    "ml": int(document.metadata["water_ml"]),
                    "recorded_at": f"{record_date.isoformat()}T12:00:00+08:00",
                    "source": SOURCE_LABEL,
                }
            ]
        for index, entry in enumerate(entries):
            public_id = _deterministic_id(
                workspace_public_id, "water", f"{record_date}:{index}:{entry.get('recorded_at')}"
            )
            record = await session.scalar(
                select(WaterEntry).where(
                    WaterEntry.workspace_id == workspace_id,
                    WaterEntry.public_id == public_id,
                )
            )
            if record is None:
                record = WaterEntry(
                    public_id=public_id,
                    workspace_id=workspace_id,
                    record_date=record_date,
                    occurred_at=_parse_datetime(entry.get("recorded_at"))
                    or datetime.combine(
                        record_date, time(12, 0), ZoneInfo("Asia/Shanghai")
                    ).astimezone(timezone.utc),
                    amount_ml=int(entry.get("ml") or 0),
                    source=SOURCE_LABEL,
                )
                session.add(record)
            water_count += 1
        if document.metadata.get("weight_kg") is not None:
            public_id = _deterministic_id(
                workspace_public_id, "weight", f"health-day:{record_date.isoformat()}"
            )
            record = await session.scalar(
                select(WeightEntry).where(
                    WeightEntry.workspace_id == workspace_id,
                    WeightEntry.public_id == public_id,
                )
            )
            if record is None:
                record = WeightEntry(
                    public_id=public_id,
                    workspace_id=workspace_id,
                    record_date=record_date,
                    occurred_at=_parse_datetime(document.metadata.get("weight_recorded_at"))
                    or datetime.combine(
                        record_date, time(8, 0), ZoneInfo("Asia/Shanghai")
                    ).astimezone(timezone.utc),
                    weight_kg=Decimal(str(document.metadata["weight_kg"])),
                    source=SOURCE_LABEL,
                )
                session.add(record)
            weight_count += 1

    advice_by_date: dict[date, dict[str, Any]] = {}
    for document in _legacy_documents(snapshot, "daily_health_advice"):
        summary_date = _parse_date(document.metadata.get("date"))
        if summary_date is not None:
            advice_by_date[summary_date] = snapshot.store.get_daily_health_advice(
                summary_date.isoformat()
            )
    record_dates = {
        _parse_date(item.get("record_date")) for item in snapshot.health_records
    } - {None}
    all_dates = set(daily_metadata) | set(advice_by_date) | set(record_dates)
    summary_count = 0
    for summary_date in sorted(all_dates):
        items = [
            item
            for item in snapshot.health_records
            if _parse_date(item.get("record_date")) == summary_date and not item.get("deleted")
        ]
        metadata = daily_metadata.get(summary_date, {})
        advice = advice_by_date.get(summary_date, {})
        calories = sum(int(item.get("calories_kcal") or 0) for item in items)
        exercise = sum(int(item.get("exercise_kcal") or 0) for item in items)
        weight_values = [item.get("weight_kg") for item in items if item.get("weight_kg") is not None]
        weight = weight_values[-1] if weight_values else metadata.get("weight_kg")
        sections = {
            "overall_summary": str(advice.get("overall_summary") or advice.get("summary") or ""),
            "diet_summary": str(advice.get("diet_summary") or ""),
            "hydration_summary": str(advice.get("hydration_summary") or ""),
            "exercise_summary": str(advice.get("exercise_summary") or ""),
        }
        record = await session.scalar(
            select(HealthDailySummary).where(
                HealthDailySummary.workspace_id == workspace_id,
                HealthDailySummary.summary_date == summary_date,
            )
        )
        if record is None:
            record = HealthDailySummary(
                public_id=_deterministic_id(
                    workspace_public_id, "health_day", summary_date.isoformat()
                ),
                workspace_id=workspace_id,
                summary_date=summary_date,
            )
            session.add(record)
        record.weight_kg = Decimal(str(weight)) if weight is not None else None
        record.water_ml = int(metadata.get("water_ml") or 0)
        record.calories_kcal = calories or int(metadata.get("calories_kcal") or 0)
        record.exercise_kcal = exercise or int(metadata.get("exercise_kcal") or 0)
        record.meal_count = sum(1 for item in items if item.get("kind") == "meal")
        record.photo_count = len(items)
        record.status = str(advice.get("status") or "neutral")
        record.sections = sections
        record.thumbnail_object_ids = thumbnails_by_date.get(summary_date, [])
        record.stale = False
        record.revision = max(int(record.revision or 1), 1)
        record.generated_by = SOURCE_LABEL
        record.generated_at = _parse_datetime(advice.get("updated_at")) or datetime.now(
            timezone.utc
        )
        record.updated_at = record.generated_at
        summary_count += 1
    return water_count, weight_count, summary_count


async def _import_agent_jobs(
    session: Any, workspace_id: int, workspace_public_id: uuid.UUID, snapshot: LegacySnapshot
) -> int:
    count = 0
    for item in snapshot.agent_jobs:
        legacy_id = str(item["id"])
        idempotency_key = f"legacy-import-job:{legacy_id}"[:160]
        record = await session.scalar(
            select(AgentJob).where(
                AgentJob.workspace_id == workspace_id,
                AgentJob.idempotency_key == idempotency_key,
            )
        )
        status = str(item.get("status") or "cancelled")
        if status not in {"completed", "failed", "cancelled"}:
            status = "cancelled"
        if record is None:
            record = AgentJob(
                public_id=_deterministic_id(workspace_public_id, "agent_job", legacy_id),
                workspace_id=workspace_id,
                job_type=str(item.get("job_type") or "legacy_history")[:80],
                subject_type="legacy_record",
                subject_key=str(item.get("subject_id") or legacy_id)[:160],
                title=str(item.get("title") or legacy_id)[:240],
                idempotency_key=idempotency_key,
            )
            session.add(record)
        record.payload = dict(item.get("payload") or {})
        record.status = status
        record.attempts = int(item.get("attempts") or 0)
        record.available_at = _parse_datetime(item.get("created_at")) or datetime.now(timezone.utc)
        record.claimed_at = _parse_datetime(item.get("claimed_at"))
        record.completed_at = _parse_datetime(item.get("completed_at")) or record.available_at
        record.result_summary = str(item.get("result_summary") or "历史任务已归档")
        record.error_code = "legacy_import_cancelled" if status == "cancelled" else None
        now = datetime.now(timezone.utc)
        record.created_at = _parse_datetime(item.get("created_at")) or record.created_at or now
        record.updated_at = _parse_datetime(item.get("updated_at")) or record.updated_at or now
        count += 1
    return count


async def _import_activity_logs(
    session: Any, workspace_id: int, snapshot: LegacySnapshot
) -> int:
    count = 0
    for document in _legacy_documents(snapshot, "activity_log"):
        log_date = _parse_date(document.metadata.get("date"))
        for line in document.body.splitlines():
            if not line.startswith("- "):
                continue
            digest = hashlib.sha256(
                f"{document.path.relative_to(snapshot.root).as_posix()}:{line}".encode("utf-8")
            ).hexdigest()[:32]
            request_id = f"legacy-log:{digest}"
            existing = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.request_id == request_id,
                )
            )
            if existing is not None:
                count += 1
                continue
            parts = [part.strip() for part in line[2:].split("·")]
            source = parts[1] if len(parts) > 1 else "system"
            action = parts[2] if len(parts) > 2 else "legacy_activity"
            summary = " · ".join(parts[3:]) if len(parts) > 3 else line[2:]
            created_at = None
            if log_date and parts:
                try:
                    created_at = datetime.combine(
                        log_date,
                        time.fromisoformat(parts[0]),
                        ZoneInfo("Asia/Shanghai"),
                    ).astimezone(timezone.utc)
                except ValueError:
                    created_at = None
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor_type="agent" if source.lower() in {"agent", "hermes"} else "system",
                    action=action[:100],
                    entity_type="legacy_activity",
                    entity_key=digest,
                    request_id=request_id,
                    details={"summary": summary, "source": source},
                    created_at=created_at or datetime.now(timezone.utc),
                )
            )
            count += 1
    return count


def _write_legacy_zip(snapshot: LegacySnapshot, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in snapshot.root.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(snapshot.root).as_posix())


async def _import_legacy_archive(
    session: Any,
    workspace_id: int,
    workspace_public_id: uuid.UUID,
    snapshot: LegacySnapshot,
    object_store: LocalPrivateObjectStore,
    archive_path: Path,
) -> int:
    public_id = _deterministic_id(
        workspace_public_id, "legacy_archive", snapshot.fingerprint
    )
    export_id = _deterministic_id(
        workspace_public_id, "legacy_export", snapshot.fingerprint
    )
    latest_mtime = max(
        datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        for path in snapshot.root.rglob("*")
        if path.is_file()
    )
    object_key = object_store.build_key(
        workspace_public_id, public_id, "application/zip", latest_mtime
    )
    result = object_store.put_file(object_key, archive_path)
    stored = await _stored_object(
        session,
        workspace_id,
        public_id,
        object_key,
        f"legacy-workbench-{snapshot.fingerprint[:12]}.zip",
        "application/zip",
        result.size_bytes,
        result.sha256,
        latest_mtime,
    )
    export = await session.scalar(
        select(DataExport).where(
            DataExport.workspace_id == workspace_id,
            DataExport.public_id == export_id,
        )
    )
    if export is None:
        export = DataExport(
            public_id=export_id,
            workspace_id=workspace_id,
            status="ready",
            formats=["legacy_markdown"],
            stored_object_id=stored.id,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(export)
    else:
        export.status = "ready"
        export.formats = ["legacy_markdown"]
        export.stored_object_id = stored.id
        export.error_code = None
        export.completed_at = datetime.now(timezone.utc)
        export.expires_at = None
    return 1


async def apply_snapshot(
    database: CloudDatabase,
    settings: CloudSettings,
    username: str,
    snapshot: LegacySnapshot,
) -> dict[str, Any]:
    workspace_id, workspace_public_id = await _workspace_identity(database, username)
    object_store = LocalPrivateObjectStore(settings.data_root)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temporary:
        archive_path = Path(temporary.name)
    try:
        _write_legacy_zip(snapshot, archive_path)
        async with database.session_factory() as session:
            async with tenant_transaction(session, workspace_id):
                before = await cloud_counts(session, workspace_id)
                imported: dict[str, int] = {}
                imported["settings"] = await _import_settings(session, workspace_id, snapshot)
                imported["projects"] = await _import_projects(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["tasks"] = await _import_tasks(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["daily_messages"] = await _import_daily_messages(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["suggestions"] = await _import_suggestions(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["learning_plans"] = await _import_learning_plans(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["library_items"] = await _import_library(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["content_items"] = await _import_content(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["health_records"], thumbnails_by_date = await _import_health(
                    session,
                    workspace_id,
                    workspace_public_id,
                    snapshot,
                    object_store,
                )
                (
                    imported["water_entries"],
                    imported["weight_entries"],
                    imported["health_daily_summaries"],
                ) = await _import_health_days(
                    session,
                    workspace_id,
                    workspace_public_id,
                    snapshot,
                    thumbnails_by_date,
                )
                imported["agent_jobs"] = await _import_agent_jobs(
                    session, workspace_id, workspace_public_id, snapshot
                )
                imported["activity_logs"] = await _import_activity_logs(
                    session, workspace_id, snapshot
                )
                imported["legacy_archive"] = await _import_legacy_archive(
                    session,
                    workspace_id,
                    workspace_public_id,
                    snapshot,
                    object_store,
                    archive_path,
                )
                event_key = f"legacy:{snapshot.fingerprint}"
                existing_event = await session.scalar(
                    select(WorkspaceEvent).where(
                        WorkspaceEvent.workspace_id == workspace_id,
                        WorkspaceEvent.event_type == "legacy.import_completed",
                        WorkspaceEvent.entity_key == event_key,
                    )
                )
                if existing_event is None:
                    session.add(
                        WorkspaceEvent(
                            workspace_id=workspace_id,
                            event_type="legacy.import_completed",
                            entity_type="legacy_archive",
                            entity_key=event_key,
                            payload={"source": snapshot_summary(snapshot)},
                        )
                    )
                await session.flush()
                after = await cloud_counts(session, workspace_id)
        return {
            "applied": True,
            "workspace_id": str(workspace_public_id),
            "source": snapshot_summary(snapshot),
            "imported": imported,
            "cloud_before": before,
            "cloud_after": after,
        }
    finally:
        archive_path.unlink(missing_ok=True)


async def dry_run(
    database: CloudDatabase,
    username: str,
    snapshot: LegacySnapshot,
) -> dict[str, Any]:
    workspace_id, workspace_public_id = await _workspace_identity(database, username)
    async with database.session_factory() as session:
        async with tenant_transaction(session, workspace_id):
            counts = await cloud_counts(session, workspace_id)
    return {
        "applied": False,
        "workspace_id": str(workspace_public_id),
        "source": snapshot_summary(snapshot),
        "cloud_before": counts,
    }


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Import a legacy Markdown workbench into one cloud tenant.")
    command.add_argument("--username", required=True)
    command.add_argument("--vault", type=Path, required=True)
    command.add_argument("--cache-dir", type=Path, default=Path("/tmp/legacy-migration-cache"))
    command.add_argument("--apply", action="store_true")
    command.add_argument("--confirm", default="")
    return command


async def run(args: argparse.Namespace) -> None:
    settings = CloudSettings.from_env()
    snapshot = collect_legacy(args.vault, args.cache_dir)
    database = CloudDatabase.create(settings)
    try:
        if args.apply:
            expected = f"IMPORT:{normalize_username(args.username)}:{snapshot.fingerprint[:12]}"
            if args.confirm != expected:
                raise SystemExit(f"Refusing to import. Pass --confirm {expected}")
            report = await apply_snapshot(database, settings, args.username, snapshot)
        else:
            report = await dry_run(database, args.username, snapshot)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    finally:
        await database.close()


def main() -> None:
    asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    main()
