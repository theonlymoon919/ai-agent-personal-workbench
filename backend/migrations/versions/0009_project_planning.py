"""Add project phases, task scheduling, dependencies, and agent attachment scope.

Revision ID: 0009_project_planning
Revises: 0008_invite_registration
Create Date: 2026-08-10
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_project_planning"
down_revision: str | None = "0008_invite_registration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = ("project_phases", "task_dependencies")


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


def upgrade() -> None:
    op.add_column("projects", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("start_date", sa.Date()))

    op.create_table(
        "project_phases",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("order_index", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.CheckConstraint("status in ('active', 'paused', 'completed')", name="project_phases_status_check"),
        sa.CheckConstraint("end_date is null or start_date is null or end_date >= start_date", name="project_phases_date_check"),
    )
    op.create_index("project_phases_workspace_project_order_idx", "project_phases", ["workspace_id", "project_id", "order_index", "id"])
    op.create_index("project_phases_project_id_idx", "project_phases", ["project_id"])

    op.add_column("tasks", sa.Column("project_id", sa.BigInteger()))
    op.add_column("tasks", sa.Column("phase_id", sa.BigInteger()))
    op.add_column("tasks", sa.Column("start_date", sa.Date()))
    op.add_column("tasks", sa.Column("end_date", sa.Date()))
    op.add_column("tasks", sa.Column("status", sa.String(20), nullable=False, server_default="planned"))
    op.add_column("tasks", sa.Column("progress_percent", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("is_milestone", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("tasks", sa.Column("order_index", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_foreign_key("tasks_project_id_fkey", "tasks", "projects", ["project_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("tasks_phase_id_fkey", "tasks", "project_phases", ["phase_id"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("tasks_status_check", "tasks", "status in ('planned', 'in_progress', 'blocked', 'completed', 'cancelled')")
    op.create_check_constraint("tasks_progress_check", "tasks", "progress_percent between 0 and 100")
    op.create_check_constraint("tasks_schedule_date_check", "tasks", "end_date is null or start_date is null or end_date >= start_date")
    op.create_index("tasks_workspace_project_schedule_idx", "tasks", ["workspace_id", "project_id", "start_date", "end_date", "order_index", "id"])
    op.create_index("tasks_project_id_idx", "tasks", ["project_id"])
    op.create_index("tasks_phase_id_idx", "tasks", ["phase_id"])
    op.execute(
        """
        update tasks
           set status = case when done then 'completed' else 'planned' end,
               progress_percent = case when done then 100 else 0 end,
               end_date = coalesce(end_date, due_at::date)
        """
    )

    op.create_table(
        "task_dependencies",
        _id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("predecessor_task_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["predecessor_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "task_id", "predecessor_task_id", name="task_dependencies_unique_edge"),
        sa.CheckConstraint("task_id <> predecessor_task_id", name="task_dependencies_not_self_check"),
    )
    op.create_index("task_dependencies_workspace_task_idx", "task_dependencies", ["workspace_id", "task_id", "id"])
    op.create_index("task_dependencies_task_id_idx", "task_dependencies", ["task_id"])
    op.create_index("task_dependencies_predecessor_task_id_idx", "task_dependencies", ["predecessor_task_id"])

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
        update agent_credentials
           set scopes = array_append(scopes, 'attachments:write')
         where not ('attachments:write' = any(scopes));

        do $grant_runtime$
        begin
          if exists (select 1 from pg_roles where rolname = 'workbench_runtime') then
            execute 'grant select, insert, update, delete on project_phases, task_dependencies to workbench_runtime';
            execute 'grant usage, select on all sequences in schema public to workbench_runtime';
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    op.drop_table("task_dependencies")
    op.drop_index("tasks_phase_id_idx", table_name="tasks")
    op.drop_index("tasks_project_id_idx", table_name="tasks")
    op.drop_index("tasks_workspace_project_schedule_idx", table_name="tasks")
    op.drop_constraint("tasks_schedule_date_check", "tasks", type_="check")
    op.drop_constraint("tasks_progress_check", "tasks", type_="check")
    op.drop_constraint("tasks_status_check", "tasks", type_="check")
    op.drop_constraint("tasks_phase_id_fkey", "tasks", type_="foreignkey")
    op.drop_constraint("tasks_project_id_fkey", "tasks", type_="foreignkey")
    for column in ("order_index", "is_milestone", "progress_percent", "status", "end_date", "start_date", "phase_id", "project_id"):
        op.drop_column("tasks", column)
    op.drop_table("project_phases")
    op.drop_column("projects", "start_date")
    op.drop_column("projects", "description")
