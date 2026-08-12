from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AgentJob, AuditEvent, WorkspaceEvent


async def enqueue_job(
    session: AsyncSession,
    workspace_id: int,
    job_type: str,
    subject_type: str,
    subject_key: str,
    title: str,
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
) -> AgentJob:
    public_id = uuid.uuid4()
    statement = (
        insert(AgentJob)
        .values(
            public_id=public_id,
            workspace_id=workspace_id,
            job_type=job_type,
            subject_type=subject_type,
            subject_key=subject_key,
            title=title,
            idempotency_key=idempotency_key,
            payload=payload or {},
        )
        .on_conflict_do_nothing(
            constraint="agent_jobs_workspace_idempotency_key",
        )
        .returning(AgentJob.id)
    )
    job_id = await session.scalar(statement)
    if job_id is None:
        job = await session.scalar(
            select(AgentJob).where(
                AgentJob.workspace_id == workspace_id,
                AgentJob.idempotency_key == idempotency_key,
            )
        )
        if job is None:
            raise RuntimeError("幂等任务写入失败")
        return job

    job = await session.get(AgentJob, job_id)
    if job is None:
        raise RuntimeError("任务写入后无法读取")
    session.add(
        WorkspaceEvent(
            workspace_id=workspace_id,
            event_type="agent_job.queued",
            entity_type="agent_job",
            entity_key=str(job.public_id),
            payload={"status": "pending", "job_type": job_type},
        )
    )
    return job


async def claim_next_job(
    session: AsyncSession,
    workspace_id: int,
    credential_id: int,
) -> AgentJob | None:
    now = datetime.now(timezone.utc)
    job = await session.scalar(
        select(AgentJob)
        .where(
            AgentJob.workspace_id == workspace_id,
            AgentJob.status == "pending",
            AgentJob.available_at <= now,
        )
        .order_by(AgentJob.available_at, AgentJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "in_progress"
    job.attempts += 1
    job.claimed_by_id = credential_id
    job.claimed_at = now
    job.updated_at = now
    session.add(
        WorkspaceEvent(
            workspace_id=workspace_id,
            event_type="agent_job.started",
            entity_type="agent_job",
            entity_key=str(job.public_id),
            payload={"status": "in_progress", "job_type": job.job_type},
        )
    )
    return job


async def complete_job(
    session: AsyncSession,
    workspace_id: int,
    credential_id: int,
    job_public_id: uuid.UUID,
    result_summary: str,
    succeeded: bool = True,
    error_code: str | None = None,
) -> AgentJob:
    job = await session.scalar(
        select(AgentJob)
        .where(
            AgentJob.workspace_id == workspace_id,
            AgentJob.public_id == job_public_id,
        )
        .with_for_update()
    )
    if job is None:
        raise KeyError(str(job_public_id))
    if job.status in {"completed", "failed"}:
        return job
    if job.status != "in_progress" or job.claimed_by_id != credential_id:
        raise ValueError("任务没有被当前 AI Agent 领取")
    now = datetime.now(timezone.utc)
    job.status = "completed" if succeeded else "failed"
    job.result_summary = result_summary[:4000]
    job.error_code = error_code[:80] if error_code else None
    job.completed_at = now
    job.updated_at = now
    session.add_all(
        [
            WorkspaceEvent(
                workspace_id=workspace_id,
                event_type=f"agent_job.{job.status}",
                entity_type="agent_job",
                entity_key=str(job.public_id),
                payload={"status": job.status, "job_type": job.job_type},
            ),
            AuditEvent(
                workspace_id=workspace_id,
                actor_type="agent",
                action="complete_agent_job",
                entity_type="agent_job",
                entity_key=str(job.public_id),
                details={"status": job.status, "error_code": job.error_code},
            ),
        ]
    )
    return job
