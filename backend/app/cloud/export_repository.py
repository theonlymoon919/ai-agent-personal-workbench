from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import tempfile
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ContentItem,
    DailyMessage,
    DataExport,
    FinanceAccount,
    FinanceBudget,
    FinanceCategory,
    FinanceInsight,
    FinanceTransaction,
    HealthAnalysis,
    HealthDailySummary,
    HealthRecord,
    LearningPlan,
    LibraryItem,
    Project,
    SavingsGoal,
    StoredObject,
    Suggestion,
    Task,
    TaskOccurrence,
    WaterEntry,
    WeightEntry,
    WorkspaceSettings,
)
from .storage import LocalPrivateObjectStore


EXPORT_MODELS = (
    WorkspaceSettings,
    Project,
    Task,
    TaskOccurrence,
    DailyMessage,
    Suggestion,
    WaterEntry,
    WeightEntry,
    HealthRecord,
    HealthAnalysis,
    HealthDailySummary,
    FinanceAccount,
    FinanceCategory,
    FinanceTransaction,
    FinanceBudget,
    SavingsGoal,
    FinanceInsight,
    LearningPlan,
    LibraryItem,
    ContentItem,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        return None
    return value


def _record_payload(record: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in record.__table__.columns:
        if column.name in {"id", "workspace_id", "object_key"}:
            continue
        if column.name.endswith("_id") and column.name not in {"public_id", "legacy_id"}:
            continue
        result[column.name] = _json_value(getattr(record, column.name))
    return result


def _markdown_body(table_name: str, record: dict[str, Any]) -> tuple[str, str]:
    title = str(record.get("title") or record.get("name") or record.get("public_id") or table_name)
    body_fields = (
        "note",
        "details_markdown",
        "goal",
        "reason",
        "reflection",
        "agent_comment",
        "organized_notes",
        "summary",
        "advice",
        "finding",
        "evidence",
        "risk",
        "action",
        "next_goal",
    )
    sections = [f"# {title}"]
    labels = {
        "note": "备注",
        "details_markdown": "详情",
        "goal": "目标",
        "reason": "理由",
        "reflection": "我的心得",
        "agent_comment": "AI Agent 意见",
        "organized_notes": "整理后的笔记",
        "summary": "总结",
        "advice": "建议",
        "finding": "发现",
        "evidence": "依据",
        "risk": "风险",
        "action": "行动",
        "next_goal": "下一目标",
    }
    for field in body_fields:
        value = record.get(field)
        if value:
            sections.append(f"## {labels[field]}\n\n{value}")
    return title, "\n\n".join(sections)


def _write_export_zip(
    destination: Path,
    data: dict[str, list[dict[str, Any]]],
    attachments: list[tuple[str, Path]],
) -> None:
    manifest = {
        "format": "personal-workbench-export-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tables": {name: len(rows) for name, rows in data.items()},
        "attachment_count": len(attachments),
    }
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("data/all.json", json.dumps(data, ensure_ascii=False, indent=2))
        for table_name, rows in data.items():
            archive.writestr(
                f"data/{table_name}.json",
                json.dumps(rows, ensure_ascii=False, indent=2),
            )
            for index, row in enumerate(rows):
                title, body = _markdown_body(table_name, row)
                metadata = {key: value for key, value in row.items() if key not in {"details_markdown", "note", "reflection", "agent_comment", "organized_notes"}}
                frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
                filename = str(row.get("public_id") or row.get("legacy_id") or f"record-{index + 1}")
                archive.writestr(
                    f"markdown/{table_name}/{filename}.md",
                    f"---\n{frontmatter}\n---\n\n{body}\n",
                )

        transactions = data.get("finance_transactions", [])
        csv_buffer = io.StringIO(newline="")
        writer = csv.DictWriter(
            csv_buffer,
            fieldnames=["public_id", "local_date", "transaction_type", "amount_minor", "currency", "merchant", "purpose", "note", "source"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(transactions)
        archive.writestr("csv/finance_transactions.csv", "\ufeff" + csv_buffer.getvalue())

        for archive_name, source_path in attachments:
            archive.write(source_path, archive_name)


class ExportRepository:
    def __init__(
        self,
        session: AsyncSession,
        workspace_id: int,
        workspace_public_id: uuid.UUID,
        object_store: LocalPrivateObjectStore,
    ) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self.workspace_public_id = workspace_public_id
        self.object_store = object_store

    async def list_exports(self) -> list[dict]:
        exports = list(
            (
                await self.session.scalars(
                    select(DataExport)
                    .where(DataExport.workspace_id == self.workspace_id)
                    .order_by(DataExport.id.desc())
                    .limit(20)
                )
            ).all()
        )
        return [self.payload(item) for item in exports]

    @staticmethod
    def payload(item: DataExport) -> dict:
        return {
            "id": str(item.public_id),
            "status": item.status,
            "formats": list(item.formats),
            "created_at": item.created_at.isoformat(),
            "completed_at": item.completed_at.isoformat() if item.completed_at else None,
            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
            "download_url": f"/api/exports/{item.public_id}/download" if item.status == "ready" else None,
            "error_code": item.error_code,
        }

    async def create_export(self) -> dict:
        export = DataExport(
            workspace_id=self.workspace_id,
            status="running",
            formats=["json", "markdown", "csv"],
        )
        self.session.add(export)
        await self.session.flush()

        data: dict[str, list[dict[str, Any]]] = {}
        for model in EXPORT_MODELS:
            records = list(
                (
                    await self.session.scalars(
                        select(model).where(model.workspace_id == self.workspace_id)
                    )
                ).all()
            )
            data[model.__tablename__] = [_record_payload(record) for record in records]

        stored_objects = list(
            (
                await self.session.scalars(
                    select(StoredObject).where(
                        StoredObject.workspace_id == self.workspace_id,
                        StoredObject.status == "ready",
                        StoredObject.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        attachments: list[tuple[str, Path]] = []
        for stored in stored_objects:
            try:
                path = self.object_store.path_for_read(stored.object_key)
            except KeyError:
                continue
            attachments.append((f"attachments/{stored.public_id}{path.suffix}", path))

        handle = tempfile.NamedTemporaryFile(prefix="workbench-export-", suffix=".zip", delete=False)
        temporary_path = Path(handle.name)
        handle.close()
        try:
            await asyncio.to_thread(_write_export_zip, temporary_path, data, attachments)
            object_public_id = uuid.uuid4()
            object_key = self.object_store.build_key(
                self.workspace_public_id,
                object_public_id,
                "application/zip",
            )
            saved = await asyncio.to_thread(self.object_store.put_file, object_key, temporary_path)
            stored_export = StoredObject(
                public_id=object_public_id,
                workspace_id=self.workspace_id,
                object_key=saved.object_key,
                original_filename=f"个人工作台导出-{datetime.now():%Y%m%d-%H%M}.zip",
                content_type="application/zip",
                size_bytes=saved.size_bytes,
                sha256=saved.sha256,
                status="ready",
            )
            self.session.add(stored_export)
            await self.session.flush()
            export.status = "ready"
            export.stored_object_id = stored_export.id
            export.completed_at = datetime.now(timezone.utc)
            export.expires_at = export.completed_at + timedelta(days=7)
            await self.session.flush()
            return self.payload(export)
        finally:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass

    async def export_file(self, public_id: uuid.UUID) -> tuple[DataExport, StoredObject, Path]:
        export = await self.session.scalar(
            select(DataExport).where(
                DataExport.workspace_id == self.workspace_id,
                DataExport.public_id == public_id,
                DataExport.status == "ready",
            )
        )
        if export is None or export.stored_object_id is None:
            raise KeyError(str(public_id))
        stored = await self.session.scalar(
            select(StoredObject).where(
                StoredObject.workspace_id == self.workspace_id,
                StoredObject.id == export.stored_object_id,
                StoredObject.status == "ready",
            )
        )
        if stored is None:
            raise KeyError(str(public_id))
        return export, stored, self.object_store.path_for_read(stored.object_key)
