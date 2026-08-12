from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from sqlalchemy import select, text

from .app.cloud.config import CloudSettings
from .app.cloud.database import CloudDatabase, set_tenant_context
from .app.cloud.finance_repository import FinanceRepository
from .app.cloud.models import DeletionRequest, Workspace
from .app.cloud.storage import LocalPrivateObjectStore


async def process_deletions(
    database: CloudDatabase,
    object_store: LocalPrivateObjectStore,
) -> int:
    async with database.session_factory() as session:
        deleting = list(
            (
                await session.execute(
                    select(Workspace.id, Workspace.public_id)
                    .where(Workspace.status == "deleting")
                    .order_by(Workspace.id)
                )
            ).all()
        )
    deleted = 0
    for workspace_id, workspace_public_id in deleting:
        request_id = None
        async with database.session_factory() as session:
            async with session.begin():
                await set_tenant_context(session, workspace_id)
                request = await session.scalar(
                    select(DeletionRequest)
                    .where(
                        DeletionRequest.workspace_id == workspace_id,
                        DeletionRequest.status.in_(("pending", "failed")),
                        DeletionRequest.execute_after <= datetime.now(timezone.utc),
                    )
                    .order_by(DeletionRequest.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if request is not None:
                    request.status = "running"
                    request.failure_code = None
                    request_id = request.id
        if request_id is None:
            continue
        try:
            object_store.delete_workspace(workspace_public_id)
            async with database.session_factory() as session:
                async with session.begin():
                    await set_tenant_context(session, workspace_id)
                    purged = await session.scalar(text("select purge_current_workspace()"))
                    if not purged:
                        raise RuntimeError("workspace purge did not delete a row")
            deleted += 1
        except Exception as exc:
            async with database.session_factory() as session:
                async with session.begin():
                    await set_tenant_context(session, workspace_id)
                    request = await session.get(DeletionRequest, request_id)
                    if request is not None:
                        request.status = "failed"
                        request.failure_code = type(exc).__name__[:80]
            raise
    return deleted


async def process_once(database: CloudDatabase) -> int:
    async with database.session_factory() as session:
        workspace_ids = list(
            (
                await session.scalars(
                    select(Workspace.id).where(Workspace.status == "active").order_by(Workspace.id)
                )
            ).all()
        )
    created = 0
    for workspace_id in workspace_ids:
        async with database.session_factory() as session:
            async with session.begin():
                await set_tenant_context(session, workspace_id)
                created += await FinanceRepository(
                    session,
                    workspace_id,
                    "system",
                    None,
                ).process_due_recurring_rules(date.today())
    return created


async def main() -> None:
    settings = CloudSettings.from_env()
    database = CloudDatabase.create(settings)
    object_store = LocalPrivateObjectStore(settings.data_root)
    try:
        while True:
            try:
                await process_once(database)
                await process_deletions(database, object_store)
            except Exception as exc:
                print(f"cloud worker cycle failed: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(60)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
