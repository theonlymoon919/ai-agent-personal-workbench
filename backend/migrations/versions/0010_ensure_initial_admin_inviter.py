"""Ensure an existing installation has one invitation administrator.

Revision ID: 0010_initial_admin_state
Revises: 0009_project_planning
Create Date: 2026-08-11
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_initial_admin_state"
down_revision: str | None = "0009_project_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instance_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="instance_state_singleton_check"),
    )
    op.execute(
        "insert into instance_state (id) select 1 where exists (select 1 from users)"
    )
    op.execute(
        """
        update users
        set can_invite = true
        where id = (select id from users order by created_at, id limit 1)
          and not exists (select 1 from users where can_invite = true)
        """
    )
    op.execute(
        """
        do $grant_runtime$
        begin
          if exists (select 1 from pg_roles where rolname = 'workbench_runtime') then
            grant select, insert on instance_state to workbench_runtime;
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    # Invitation permission is user-owned state and must not be revoked by a
    # schema downgrade.
    op.drop_table("instance_state")
