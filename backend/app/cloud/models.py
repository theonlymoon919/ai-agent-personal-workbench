from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("status in ('active', 'suspended', 'deleting')", name="workspaces_status_check"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'Asia/Shanghai'"))


class InstanceState(Base):
    __tablename__ = "instance_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="instance_state_singleton_check"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="users_workspace_id_key"),
        UniqueConstraint("username_normalized", name="users_username_normalized_key"),
        CheckConstraint("status in ('active', 'locked', 'deleting')", name="users_status_check"),
        Index("users_workspace_id_idx", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    can_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class RegistrationInvite(Base):
    __tablename__ = "registration_invites"
    __table_args__ = (
        Index("registration_invites_secret_hash_idx", "secret_hash", unique=True),
        Index("registration_invites_creator_expires_idx", "created_by_user_id", "expires_at"),
        Index("registration_invites_used_by_user_id_idx", "used_by_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    created_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class WorkspaceSettings(TimestampMixin, Base):
    __tablename__ = "workspace_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="workspace_settings_workspace_id_key"),
        Index("workspace_settings_workspace_id_idx", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    health: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ip_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    notification_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("user_sessions_workspace_expires_idx", "workspace_id", "expires_at"),
        Index("user_sessions_user_id_idx", "user_id"),
        Index("user_sessions_token_hash_idx", "token_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    csrf_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    user_agent_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentCredential(Base):
    __tablename__ = "agent_credentials"
    __table_args__ = (
        Index("agent_credentials_workspace_id_idx", "workspace_id"),
        Index("agent_credentials_secret_hash_idx", "secret_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    token_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    secret_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), nullable=False, server_default=text("ARRAY[]::varchar[]")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoredObject(Base):
    __tablename__ = "stored_objects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "object_key", name="stored_objects_workspace_object_key_key"),
        CheckConstraint("status in ('pending', 'ready', 'deleted')", name="stored_objects_status_check"),
        CheckConstraint("size_bytes >= 0", name="stored_objects_size_bytes_check"),
        Index("stored_objects_workspace_created_idx", "workspace_id", "created_at", "id"),
        Index("stored_objects_workspace_sha256_idx", "workspace_id", "sha256"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    backend: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'local_private'"))
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentJob(Base):
    __tablename__ = "agent_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="agent_jobs_workspace_idempotency_key"),
        CheckConstraint(
            "status in ('pending', 'in_progress', 'completed', 'failed', 'cancelled')",
            name="agent_jobs_status_check",
        ),
        CheckConstraint("attempts >= 0", name="agent_jobs_attempts_check"),
        Index("agent_jobs_workspace_status_available_idx", "workspace_id", "status", "available_at", "id"),
        Index("agent_jobs_workspace_subject_idx", "workspace_id", "subject_type", "subject_key"),
        Index("agent_jobs_claimed_by_id_idx", "claimed_by_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    claimed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("agent_credentials.id", ondelete="SET NULL")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkspaceEvent(Base):
    __tablename__ = "workspace_events"
    __table_args__ = (
        Index("workspace_events_workspace_cursor_idx", "workspace_id", "id"),
        Index("workspace_events_workspace_created_idx", "workspace_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_type in ('user', 'agent', 'system')", name="audit_events_actor_type_check"),
        Index("audit_events_workspace_created_idx", "workspace_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_public_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", "operation", "idempotency_key", name="idempotency_operation_key"),
        Index("idempotency_records_workspace_expires_idx", "workspace_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    response_status: Mapped[int | None] = mapped_column(BigInteger)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("workspace_id", "device_key", name="devices_workspace_device_key"),
        CheckConstraint("platform in ('android', 'web', 'windows')", name="devices_platform_check"),
        CheckConstraint("status in ('active', 'revoked')", name="devices_status_check"),
        Index("devices_workspace_status_idx", "workspace_id", "status"),
        Index("devices_user_id_idx", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_key: Mapped[str] = mapped_column(String(160), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    push_provider: Mapped[str | None] = mapped_column(String(32))
    push_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DataExport(Base):
    __tablename__ = "data_exports"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'running', 'ready', 'failed', 'expired')", name="data_exports_status_check"),
        Index("data_exports_workspace_created_idx", "workspace_id", "created_at", "id"),
        Index("data_exports_stored_object_id_idx", "stored_object_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    formats: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), nullable=False, server_default=text("ARRAY['json','markdown']::varchar[]")
    )
    stored_object_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stored_objects.id", ondelete="SET NULL")
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint("status in ('pending', 'cancelled', 'running', 'completed', 'failed')", name="deletion_requests_status_check"),
        Index("deletion_requests_workspace_status_idx", "workspace_id", "status"),
        Index("deletion_requests_requested_by_user_id_idx", "requested_by_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    execute_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("progress_percent between 0 and 100", name="projects_progress_check"),
        CheckConstraint("status in ('active', 'paused', 'completed')", name="projects_status_check"),
        UniqueConstraint("workspace_id", "legacy_id", name="projects_workspace_legacy_id_key"),
        Index("projects_workspace_status_updated_idx", "workspace_id", "status", "updated_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    start_date: Mapped[date | None] = mapped_column(Date)
    current_stage: Mapped[str] = mapped_column(String(200), nullable=False, server_default=text("'准备中'"))
    progress_percent: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    next_milestone: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectPhase(TimestampMixin, Base):
    __tablename__ = "project_phases"
    __table_args__ = (
        CheckConstraint("status in ('active', 'paused', 'completed')", name="project_phases_status_check"),
        CheckConstraint(
            "end_date is null or start_date is null or end_date >= start_date",
            name="project_phases_date_check",
        ),
        Index(
            "project_phases_workspace_project_order_idx",
            "workspace_id",
            "project_id",
            "order_index",
            "id",
        ),
        Index("project_phases_project_id_idx", "project_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))
    order_index: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "quadrant in ('important_urgent', 'important_not_urgent', 'not_important_urgent', 'not_important_not_urgent')",
            name="tasks_quadrant_check",
        ),
        CheckConstraint("recurrence in ('none', 'yearly')", name="tasks_recurrence_check"),
        CheckConstraint(
            "status in ('planned', 'in_progress', 'blocked', 'completed', 'cancelled')",
            name="tasks_status_check",
        ),
        CheckConstraint("progress_percent between 0 and 100", name="tasks_progress_check"),
        CheckConstraint(
            "end_date is null or start_date is null or end_date >= start_date",
            name="tasks_schedule_date_check",
        ),
        UniqueConstraint("workspace_id", "legacy_id", name="tasks_workspace_legacy_id_key"),
        Index("tasks_workspace_due_idx", "workspace_id", "due_at", "id"),
        Index("tasks_workspace_quadrant_updated_idx", "workspace_id", "quadrant", "updated_at", "id"),
        Index("tasks_workspace_deleted_idx", "workspace_id", "deleted_at", "id"),
        Index(
            "tasks_workspace_project_schedule_idx",
            "workspace_id",
            "project_id",
            "start_date",
            "end_date",
            "order_index",
            "id",
        ),
        Index("tasks_project_id_idx", "project_id"),
        Index("tasks_phase_id_idx", "phase_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(160))
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL")
    )
    phase_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("project_phases.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    quadrant: Mapped[str] = mapped_column(String(40), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    recurrence: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'none'"))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'planned'"))
    progress_percent: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    is_milestone: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    order_index: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "task_id",
            "predecessor_task_id",
            name="task_dependencies_unique_edge",
        ),
        CheckConstraint("task_id <> predecessor_task_id", name="task_dependencies_not_self_check"),
        Index("task_dependencies_workspace_task_idx", "workspace_id", "task_id", "id"),
        Index("task_dependencies_task_id_idx", "task_id"),
        Index("task_dependencies_predecessor_task_id_idx", "predecessor_task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    predecessor_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskOccurrence(Base):
    __tablename__ = "task_occurrences"
    __table_args__ = (
        UniqueConstraint("workspace_id", "task_id", "occurrence_date", name="task_occurrences_unique_day"),
        Index("task_occurrences_workspace_date_idx", "workspace_id", "occurrence_date", "id"),
        Index("task_occurrences_task_id_idx", "task_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))


class DailyMessage(Base):
    __tablename__ = "daily_messages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "target_date", name="daily_messages_workspace_date_key"),
        CheckConstraint("tone in ('encouraging', 'comforting', 'mixed')", name="daily_messages_tone_check"),
        Index("daily_messages_workspace_date_idx", "workspace_id", "target_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    message: Mapped[str] = mapped_column(String(120), nullable=False)
    tone: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'mixed'"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'hermes'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Suggestion(TimestampMixin, Base):
    __tablename__ = "suggestions"
    __table_args__ = (
        Index("suggestions_workspace_updated_idx", "workspace_id", "updated_at", "id"),
        Index("suggestions_workspace_deleted_idx", "workspace_id", "deleted_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    action_label: Mapped[str] = mapped_column(String(60), nullable=False, server_default=text("''"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'hermes'"))
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WaterEntry(Base):
    __tablename__ = "water_entries"
    __table_args__ = (
        CheckConstraint("amount_ml between 1 and 5000", name="water_entries_amount_check"),
        Index("water_entries_workspace_date_idx", "workspace_id", "record_date", "occurred_at", "id"),
        Index("water_entries_workspace_deleted_idx", "workspace_id", "deleted_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_ml: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeightEntry(Base):
    __tablename__ = "weight_entries"
    __table_args__ = (
        CheckConstraint("weight_kg between 20 and 400", name="weight_entries_weight_check"),
        Index("weight_entries_workspace_date_idx", "workspace_id", "record_date", "occurred_at", "id"),
        Index("weight_entries_workspace_deleted_idx", "workspace_id", "deleted_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HealthRecord(TimestampMixin, Base):
    __tablename__ = "health_records"
    __table_args__ = (
        CheckConstraint("kind in ('meal', 'weight_photo', 'exercise')", name="health_records_kind_check"),
        CheckConstraint(
            "meal_slot is null or meal_slot in ('breakfast', 'lunch', 'afternoon_tea', 'dinner', 'snack', 'late_night')",
            name="health_records_meal_slot_check",
        ),
        CheckConstraint(
            "analysis_status in ('queued', 'in_progress', 'analyzed', 'failed')",
            name="health_records_analysis_status_check",
        ),
        UniqueConstraint("workspace_id", "legacy_id", name="health_records_workspace_legacy_id_key"),
        UniqueConstraint("workspace_id", "idempotency_key", name="health_records_workspace_idempotency_key"),
        Index("health_records_workspace_date_kind_idx", "workspace_id", "record_date", "kind", "id"),
        Index("health_records_workspace_status_idx", "workspace_id", "analysis_status", "created_at", "id"),
        Index("health_records_workspace_deleted_idx", "workspace_id", "deleted_at", "id"),
        Index("health_records_object_id_idx", "object_id"),
        Index("health_records_thumbnail_object_id_idx", "thumbnail_object_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(160))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    meal_slot: Mapped[str | None] = mapped_column(String(24))
    object_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stored_objects.id", ondelete="RESTRICT"), nullable=False
    )
    thumbnail_object_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stored_objects.id", ondelete="RESTRICT"), nullable=False
    )
    analysis_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'queued'"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HealthAnalysis(Base):
    __tablename__ = "health_analyses"
    __table_args__ = (
        UniqueConstraint("workspace_id", "health_record_id", name="health_analyses_record_key"),
        CheckConstraint("calories_kcal is null or calories_kcal between 0 and 10000", name="health_analyses_calories_check"),
        CheckConstraint("exercise_kcal is null or exercise_kcal between 0 and 10000", name="health_analyses_exercise_check"),
        CheckConstraint("weight_kg is null or weight_kg between 20 and 400", name="health_analyses_weight_check"),
        Index("health_analyses_workspace_analyzed_idx", "workspace_id", "analyzed_at", "id"),
        Index("health_analyses_health_record_id_idx", "health_record_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    health_record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("health_records.id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    advice: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    calories_kcal: Mapped[int | None] = mapped_column(BigInteger)
    exercise_kcal: Mapped[int | None] = mapped_column(BigInteger)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    model_name: Mapped[str | None] = mapped_column(String(120))
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HealthDailySummary(Base):
    __tablename__ = "health_daily_summaries"
    __table_args__ = (
        UniqueConstraint("workspace_id", "summary_date", name="health_daily_summaries_workspace_date_key"),
        CheckConstraint("status in ('on_track', 'attention', 'celebrate', 'neutral')", name="health_daily_summaries_status_check"),
        CheckConstraint("revision >= 1", name="health_daily_summaries_revision_check"),
        Index("health_daily_summaries_workspace_date_idx", "workspace_id", "summary_date", "id"),
        Index("health_daily_summaries_workspace_stale_idx", "workspace_id", "stale", "summary_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    water_ml: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    calories_kcal: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    exercise_kcal: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    meal_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    photo_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'neutral'"))
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    thumbnail_object_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    generated_by: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'system'"))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FinanceAccount(TimestampMixin, Base):
    __tablename__ = "finance_accounts"
    __table_args__ = (
        CheckConstraint("account_type in ('cash', 'wechat', 'alipay', 'bank', 'other')", name="finance_accounts_type_check"),
        CheckConstraint("status in ('active', 'archived')", name="finance_accounts_status_check"),
        UniqueConstraint("workspace_id", "name", name="finance_accounts_workspace_name_key"),
        Index("finance_accounts_workspace_status_idx", "workspace_id", "status", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'other'"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    opening_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))


class FinanceCategory(TimestampMixin, Base):
    __tablename__ = "finance_categories"
    __table_args__ = (
        CheckConstraint("category_type in ('income', 'expense')", name="finance_categories_type_check"),
        UniqueConstraint("workspace_id", "category_type", "name", name="finance_categories_workspace_type_name_key"),
        UniqueConstraint("workspace_id", "system_key", name="finance_categories_workspace_system_key_key"),
        Index("finance_categories_workspace_type_active_idx", "workspace_id", "category_type", "active", "sort_order"),
        Index("finance_categories_parent_id_idx", "parent_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_categories.id", ondelete="SET NULL")
    )
    category_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    system_key: Mapped[str | None] = mapped_column(String(80))
    icon: Mapped[str] = mapped_column(String(40), nullable=False, server_default=text("''"))
    color: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("''"))
    sort_order: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class FinanceRecurringRule(TimestampMixin, Base):
    __tablename__ = "finance_recurring_rules"
    __table_args__ = (
        CheckConstraint("transaction_type in ('income', 'expense', 'transfer')", name="finance_recurring_rules_type_check"),
        CheckConstraint("amount_minor > 0", name="finance_recurring_rules_amount_check"),
        CheckConstraint("frequency in ('weekly', 'monthly', 'yearly')", name="finance_recurring_rules_frequency_check"),
        CheckConstraint("interval_count between 1 and 60", name="finance_recurring_rules_interval_check"),
        Index("finance_recurring_rules_workspace_next_idx", "workspace_id", "active", "next_due_date", "id"),
        Index("finance_recurring_rules_category_id_idx", "category_id"),
        Index("finance_recurring_rules_account_id_idx", "account_id"),
        Index("finance_recurring_rules_to_account_id_idx", "to_account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_categories.id", ondelete="SET NULL")
    )
    account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_accounts.id", ondelete="SET NULL")
    )
    to_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_accounts.id", ondelete="SET NULL")
    )
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    interval_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    next_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str] = mapped_column(String(240), nullable=False, server_default=text("''"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class FinanceTransaction(TimestampMixin, Base):
    __tablename__ = "finance_transactions"
    __table_args__ = (
        CheckConstraint("transaction_type in ('income', 'expense', 'transfer', 'refund')", name="finance_transactions_type_check"),
        CheckConstraint("amount_minor > 0", name="finance_transactions_amount_check"),
        CheckConstraint(
            "(transaction_type <> 'transfer') or (account_id is not null and to_account_id is not null and account_id <> to_account_id)",
            name="finance_transactions_transfer_accounts_check",
        ),
        CheckConstraint(
            "(transaction_type <> 'refund') or refund_of_id is not null",
            name="finance_transactions_refund_reference_check",
        ),
        UniqueConstraint("workspace_id", "legacy_id", name="finance_transactions_workspace_legacy_id_key"),
        UniqueConstraint("workspace_id", "idempotency_key", name="finance_transactions_workspace_idempotency_key"),
        Index("finance_transactions_workspace_date_idx", "workspace_id", "local_date", "occurred_at", "id"),
        Index("finance_transactions_workspace_type_date_idx", "workspace_id", "transaction_type", "local_date", "id"),
        Index("finance_transactions_workspace_category_date_idx", "workspace_id", "category_id", "local_date", "id"),
        Index("finance_transactions_workspace_deleted_idx", "workspace_id", "deleted_at", "id"),
        Index("finance_transactions_category_id_idx", "category_id"),
        Index("finance_transactions_account_id_idx", "account_id"),
        Index("finance_transactions_to_account_id_idx", "to_account_id"),
        Index("finance_transactions_refund_of_id_idx", "refund_of_id"),
        Index("finance_transactions_recurring_rule_id_idx", "recurring_rule_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(160))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_categories.id", ondelete="SET NULL")
    )
    account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_accounts.id", ondelete="SET NULL")
    )
    to_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_accounts.id", ondelete="SET NULL")
    )
    refund_of_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_transactions.id", ondelete="SET NULL")
    )
    recurring_rule_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_recurring_rules.id", ondelete="SET NULL")
    )
    merchant: Mapped[str] = mapped_column(String(160), nullable=False, server_default=text("''"))
    purpose: Mapped[str] = mapped_column(String(240), nullable=False, server_default=text("''"))
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("ARRAY[]::varchar[]")
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_necessary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceBudget(TimestampMixin, Base):
    __tablename__ = "finance_budgets"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="finance_budgets_amount_check"),
        CheckConstraint("period_end >= period_start", name="finance_budgets_period_check"),
        CheckConstraint("status in ('active', 'archived')", name="finance_budgets_status_check"),
        UniqueConstraint("workspace_id", "period_start", "period_end", "category_id", name="finance_budgets_period_category_key"),
        Index("finance_budgets_workspace_period_idx", "workspace_id", "period_start", "period_end", "id"),
        Index("finance_budgets_category_id_idx", "category_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("finance_categories.id", ondelete="CASCADE")
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    rollover: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))


class SavingsGoal(TimestampMixin, Base):
    __tablename__ = "savings_goals"
    __table_args__ = (
        CheckConstraint("target_amount_minor > 0", name="savings_goals_target_check"),
        CheckConstraint("current_amount_minor >= 0", name="savings_goals_current_check"),
        CheckConstraint("status in ('active', 'completed', 'paused')", name="savings_goals_status_check"),
        Index("savings_goals_workspace_status_idx", "workspace_id", "status", "target_date", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    target_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))


class FinanceMonthlySummary(Base):
    __tablename__ = "finance_monthly_summaries"
    __table_args__ = (
        UniqueConstraint("workspace_id", "month_start", name="finance_monthly_summaries_workspace_month_key"),
        CheckConstraint("extract(day from month_start) = 1", name="finance_monthly_summaries_month_start_check"),
        CheckConstraint("revision >= 1", name="finance_monthly_summaries_revision_check"),
        Index("finance_monthly_summaries_workspace_month_idx", "workspace_id", "month_start", "id"),
        Index("finance_monthly_summaries_workspace_stale_idx", "workspace_id", "stale", "month_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'CNY'"))
    income_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    expense_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    refund_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    savings_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    category_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    budget_status: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FinanceInsight(TimestampMixin, Base):
    __tablename__ = "finance_insights"
    __table_args__ = (
        CheckConstraint("period_end >= period_start", name="finance_insights_period_check"),
        Index("finance_insights_workspace_period_idx", "workspace_id", "period_end", "period_start", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    finding: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    risk: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    next_goal: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'hermes'"))


class LearningPlan(TimestampMixin, Base):
    __tablename__ = "learning_plans"
    __table_args__ = (
        CheckConstraint(
            "status in ('waiting_for_hermes', 'active', 'paused', 'completed')",
            name="learning_plans_status_check",
        ),
        CheckConstraint("completed_lessons >= 0", name="learning_plans_completed_check"),
        CheckConstraint("total_lessons >= 0", name="learning_plans_total_check"),
        UniqueConstraint("workspace_id", "legacy_id", name="learning_plans_workspace_legacy_id_key"),
        Index("learning_plans_workspace_status_updated_idx", "workspace_id", "status", "updated_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'waiting_for_hermes'"))
    completed_lessons: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_lessons: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    details_markdown: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    resources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LibraryItem(TimestampMixin, Base):
    __tablename__ = "library_items"
    __table_args__ = (
        CheckConstraint("kind in ('book', 'movie', 'documentary')", name="library_items_kind_check"),
        CheckConstraint("status in ('want', 'in_progress', 'done')", name="library_items_status_check"),
        CheckConstraint("progress_percent between 0 and 100", name="library_items_progress_check"),
        UniqueConstraint("workspace_id", "legacy_id", name="library_items_workspace_legacy_id_key"),
        Index("library_items_workspace_kind_status_idx", "workspace_id", "kind", "status", "updated_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'want'"))
    progress_percent: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    current_position: Mapped[str] = mapped_column(String(240), nullable=False, server_default=text("''"))
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    reflection: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    agent_comment: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    organized_notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'user'"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContentItem(TimestampMixin, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        CheckConstraint(
            "category in ('video_trend', 'ai_news', 'topic_idea')",
            name="content_items_category_check",
        ),
        UniqueConstraint("workspace_id", "legacy_id", name="content_items_workspace_legacy_id_key"),
        UniqueConstraint(
            "workspace_id",
            "category",
            "source_url",
            name="content_items_workspace_source_url_key",
        ),
        Index("content_items_workspace_category_updated_idx", "workspace_id", "category", "updated_at", "id"),
        Index("content_items_workspace_deleted_idx", "workspace_id", "deleted_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True, default=uuid.uuid4)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    legacy_id: Mapped[str | None] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    details_markdown: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    source_url: Mapped[str | None] = mapped_column(Text)
    media_url: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    platform: Mapped[str] = mapped_column(String(80), nullable=False, server_default=text("''"))
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'hermes'"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


FOUNDATION_TENANT_MODELS = (
    WorkspaceSettings,
    UserSession,
    AgentCredential,
    StoredObject,
    AgentJob,
    WorkspaceEvent,
    AuditEvent,
    IdempotencyRecord,
    Device,
    DataExport,
    DeletionRequest,
)

CORE_TENANT_MODELS = (
    Project,
    ProjectPhase,
    Task,
    TaskDependency,
    TaskOccurrence,
    DailyMessage,
    Suggestion,
)

HEALTH_TENANT_MODELS = (
    WaterEntry,
    WeightEntry,
    HealthRecord,
    HealthAnalysis,
    HealthDailySummary,
)

FINANCE_TENANT_MODELS = (
    FinanceAccount,
    FinanceCategory,
    FinanceRecurringRule,
    FinanceTransaction,
    FinanceBudget,
    SavingsGoal,
    FinanceMonthlySummary,
    FinanceInsight,
)

GROWTH_TENANT_MODELS = (
    LearningPlan,
    LibraryItem,
    ContentItem,
)

TENANT_MODELS = (
    FOUNDATION_TENANT_MODELS
    + CORE_TENANT_MODELS
    + HEALTH_TENANT_MODELS
    + FINANCE_TENANT_MODELS
    + GROWTH_TENANT_MODELS
)
