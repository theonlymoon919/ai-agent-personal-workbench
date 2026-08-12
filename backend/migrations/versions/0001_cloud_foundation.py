"""Create the multi-user cloud foundation.

Revision ID: 0001_cloud_foundation
Revises:
Create Date: 2026-08-04
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_cloud_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = (
    "workspace_settings",
    "user_sessions",
    "agent_credentials",
    "stored_objects",
    "agent_jobs",
    "workspace_events",
    "audit_events",
    "idempotency_records",
    "devices",
    "data_exports",
    "deletion_requests",
)


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True)


def _public_id() -> sa.Column:
    return sa.Column(
        "public_id",
        sa.Uuid(),
        nullable=False,
        unique=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _updated_at() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "workspaces",
        _id(),
        _public_id(),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint("status in ('active', 'suspended', 'deleting')", name="workspaces_status_check"),
    )
    op.create_table(
        "users",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("username_normalized", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", name="users_workspace_id_key"),
        sa.UniqueConstraint("username_normalized", name="users_username_normalized_key"),
        sa.CheckConstraint("status in ('active', 'locked', 'deleting')", name="users_status_check"),
    )
    op.create_index("users_workspace_id_idx", "users", ["workspace_id"])

    op.create_table(
        "workspace_settings",
        _id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("profile", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("health", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip_preferences", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notification_preferences", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", name="workspace_settings_workspace_id_key"),
    )
    op.create_index("workspace_settings_workspace_id_idx", "workspace_settings", ["workspace_id"])

    op.create_table(
        "user_sessions",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("csrf_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("user_agent_hash", sa.LargeBinary(32)),
        _created_at(),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("user_sessions_workspace_expires_idx", "user_sessions", ["workspace_id", "expires_at"])
    op.create_index("user_sessions_user_id_idx", "user_sessions", ["user_id"])
    op.create_index("user_sessions_token_hash_idx", "user_sessions", ["token_hash"], unique=True)

    op.create_table(
        "agent_credentials",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("token_prefix", sa.String(8), nullable=False),
        sa.Column("secret_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(64)), nullable=False, server_default=sa.text("ARRAY[]::varchar[]")),
        _created_at(),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("agent_credentials_workspace_id_idx", "agent_credentials", ["workspace_id"])
    op.create_index("agent_credentials_secret_hash_idx", "agent_credentials", ["secret_hash"], unique=True)
    op.create_index(
        "agent_credentials_one_active_per_workspace_idx",
        "agent_credentials",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at is null"),
    )

    op.create_table(
        "stored_objects",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("backend", sa.String(24), nullable=False, server_default="local_private"),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        _created_at(),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "object_key", name="stored_objects_workspace_object_key_key"),
        sa.CheckConstraint("status in ('pending', 'ready', 'deleted')", name="stored_objects_status_check"),
        sa.CheckConstraint("size_bytes >= 0", name="stored_objects_size_bytes_check"),
    )
    op.create_index("stored_objects_workspace_created_idx", "stored_objects", ["workspace_id", "created_at", "id"])
    op.create_index("stored_objects_workspace_sha256_idx", "stored_objects", ["workspace_id", "sha256"])

    op.create_table(
        "agent_jobs",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("job_type", sa.String(80), nullable=False),
        sa.Column("subject_type", sa.String(80), nullable=False),
        sa.Column("subject_key", sa.String(160), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("claimed_by_id", sa.BigInteger()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_code", sa.String(80)),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claimed_by_id"], ["agent_credentials.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="agent_jobs_workspace_idempotency_key"),
        sa.CheckConstraint("status in ('pending', 'in_progress', 'completed', 'failed', 'cancelled')", name="agent_jobs_status_check"),
        sa.CheckConstraint("attempts >= 0", name="agent_jobs_attempts_check"),
    )
    op.create_index("agent_jobs_workspace_status_available_idx", "agent_jobs", ["workspace_id", "status", "available_at", "id"])
    op.create_index("agent_jobs_workspace_subject_idx", "agent_jobs", ["workspace_id", "subject_type", "subject_key"])
    op.create_index("agent_jobs_claimed_by_id_idx", "agent_jobs", ["claimed_by_id"])

    op.create_table(
        "workspace_events",
        _id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_key", sa.String(160), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("workspace_events_workspace_cursor_idx", "workspace_events", ["workspace_id", "id"])
    op.create_index("workspace_events_workspace_created_idx", "workspace_events", ["workspace_id", "created_at"])

    op.create_table(
        "audit_events",
        _id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_public_id", sa.Uuid()),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_key", sa.String(160), nullable=False),
        sa.Column("request_id", sa.String(100)),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint("actor_type in ('user', 'agent', 'system')", name="audit_events_actor_type_check"),
    )
    op.create_index("audit_events_workspace_created_idx", "audit_events", ["workspace_id", "created_at", "id"])

    op.create_table(
        "idempotency_records",
        _id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("response_status", sa.BigInteger()),
        sa.Column("response_body", postgresql.JSONB()),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "operation", "idempotency_key", name="idempotency_operation_key"),
    )
    op.create_index("idempotency_records_workspace_expires_idx", "idempotency_records", ["workspace_id", "expires_at"])

    op.create_table(
        "devices",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_key", sa.String(160), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("push_provider", sa.String(32)),
        sa.Column("push_token_encrypted", sa.LargeBinary()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "device_key", name="devices_workspace_device_key"),
        sa.CheckConstraint("platform in ('android', 'web', 'windows')", name="devices_platform_check"),
        sa.CheckConstraint("status in ('active', 'revoked')", name="devices_status_check"),
    )
    op.create_index("devices_workspace_status_idx", "devices", ["workspace_id", "status"])
    op.create_index("devices_user_id_idx", "devices", ["user_id"])

    op.create_table(
        "data_exports",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("formats", postgresql.ARRAY(sa.String(16)), nullable=False, server_default=sa.text("ARRAY['json','markdown']::varchar[]")),
        sa.Column("stored_object_id", sa.BigInteger()),
        sa.Column("error_code", sa.String(80)),
        _created_at(),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stored_object_id"], ["stored_objects.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status in ('pending', 'running', 'ready', 'failed', 'expired')", name="data_exports_status_check"),
    )
    op.create_index("data_exports_workspace_created_idx", "data_exports", ["workspace_id", "created_at", "id"])
    op.create_index("data_exports_stored_object_id_idx", "data_exports", ["stored_object_id"])

    op.create_table(
        "deletion_requests",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(80)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status in ('pending', 'cancelled', 'running', 'completed', 'failed')", name="deletion_requests_status_check"),
    )
    op.create_index("deletion_requests_workspace_status_idx", "deletion_requests", ["workspace_id", "status"])
    op.create_index("deletion_requests_requested_by_user_id_idx", "deletion_requests", ["requested_by_user_id"])

    workspace_expression = "nullif(current_setting('app.current_workspace_id', true), '')::bigint"
    for table_name in TENANT_TABLES:
        op.execute(f'alter table "{table_name}" enable row level security')
        op.execute(f'alter table "{table_name}" force row level security')
        op.execute(
            f'''create policy "{table_name}_workspace_isolation" on "{table_name}"
                for all
                using (workspace_id = {workspace_expression})
                with check (workspace_id = {workspace_expression})'''
        )

    op.execute("revoke all on all tables in schema public from public")
    op.execute(
        """
        do $grant_runtime$
        begin
          if exists (select 1 from pg_roles where rolname = 'workbench_runtime') then
            execute 'grant usage on schema public to workbench_runtime';
            execute 'grant select, insert, update on workspaces, users to workbench_runtime';
            execute 'grant select, insert, update, delete on ' ||
              'workspace_settings, user_sessions, agent_credentials, stored_objects, agent_jobs, ' ||
              'workspace_events, audit_events, idempotency_records, devices, data_exports, deletion_requests ' ||
              'to workbench_runtime';
            execute 'grant usage, select on all sequences in schema public to workbench_runtime';
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.drop_table(table_name)
    op.drop_table("users")
    op.drop_table("workspaces")
