"""Create projects, tasks, daily messages, and suggestions.

Revision ID: 0002_core_workbench
Revises: 0001_cloud_foundation
Create Date: 2026-08-04
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_core_workbench"
down_revision: str | None = "0001_cloud_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = (
    "projects",
    "tasks",
    "task_occurrences",
    "daily_messages",
    "suggestions",
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
        "projects",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_id", sa.String(160)),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("current_stage", sa.String(200), nullable=False, server_default="准备中"),
        sa.Column("progress_percent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("next_milestone", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_date", sa.Date()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "legacy_id", name="projects_workspace_legacy_id_key"),
        sa.CheckConstraint("progress_percent between 0 and 100", name="projects_progress_check"),
        sa.CheckConstraint("status in ('active', 'paused', 'completed')", name="projects_status_check"),
    )
    op.create_index("projects_workspace_status_updated_idx", "projects", ["workspace_id", "status", "updated_at", "id"])

    op.create_table(
        "tasks",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_id", sa.String(160)),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("quadrant", sa.String(40), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("recurrence", sa.String(16), nullable=False, server_default="none"),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "legacy_id", name="tasks_workspace_legacy_id_key"),
        sa.CheckConstraint(
            "quadrant in ('important_urgent', 'important_not_urgent', 'not_important_urgent', 'not_important_not_urgent')",
            name="tasks_quadrant_check",
        ),
        sa.CheckConstraint("recurrence in ('none', 'yearly')", name="tasks_recurrence_check"),
    )
    op.create_index("tasks_workspace_due_idx", "tasks", ["workspace_id", "due_at", "id"])
    op.create_index("tasks_workspace_quadrant_updated_idx", "tasks", ["workspace_id", "quadrant", "updated_at", "id"])
    op.create_index("tasks_workspace_deleted_idx", "tasks", ["workspace_id", "deleted_at", "id"])

    op.create_table(
        "task_occurrences",
        _id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "task_id", "occurrence_date", name="task_occurrences_unique_day"),
    )
    op.create_index("task_occurrences_workspace_date_idx", "task_occurrences", ["workspace_id", "occurrence_date", "id"])
    op.create_index("task_occurrences_task_id_idx", "task_occurrences", ["task_id"])

    op.create_table(
        "daily_messages",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("message", sa.String(120), nullable=False),
        sa.Column("tone", sa.String(16), nullable=False, server_default="mixed"),
        sa.Column("source", sa.String(16), nullable=False, server_default="hermes"),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "target_date", name="daily_messages_workspace_date_key"),
        sa.CheckConstraint("tone in ('encouraging', 'comforting', 'mixed')", name="daily_messages_tone_check"),
    )
    op.create_index("daily_messages_workspace_date_idx", "daily_messages", ["workspace_id", "target_date"])

    op.create_table(
        "suggestions",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("action_label", sa.String(60), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="hermes"),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index("suggestions_workspace_updated_idx", "suggestions", ["workspace_id", "updated_at", "id"])
    op.create_index("suggestions_workspace_deleted_idx", "suggestions", ["workspace_id", "deleted_at", "id"])

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

    op.execute(
        """
        do $grant_runtime$
        begin
          if exists (select 1 from pg_roles where rolname = 'workbench_runtime') then
            execute 'grant select, insert, update, delete on projects, tasks, task_occurrences, daily_messages, suggestions to workbench_runtime';
            execute 'grant usage, select on all sequences in schema public to workbench_runtime';
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.drop_table(table_name)
