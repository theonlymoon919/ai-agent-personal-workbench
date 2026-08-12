"""Add a tenant-checked account purge function.

Revision ID: 0006_account_deletion
Revises: 0005_growth_content
Create Date: 2026-08-04
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0006_account_deletion"
down_revision: str | None = "0005_growth_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        create or replace function purge_current_workspace()
        returns boolean
        language plpgsql
        security definer
        set search_path = public, pg_temp
        as $purge$
        declare
            target_workspace_id bigint;
        begin
            target_workspace_id := nullif(current_setting('app.current_workspace_id', true), '')::bigint;
            if target_workspace_id is null then
                raise exception 'tenant context is required';
            end if;
            if not exists (
                select 1
                from deletion_requests
                where workspace_id = target_workspace_id
                  and status = 'running'
                  and execute_after <= now()
            ) then
                raise exception 'approved deletion request is required';
            end if;
            delete from workspaces
            where id = target_workspace_id
              and status = 'deleting';
            return found;
        end
        $purge$;
        revoke all on function purge_current_workspace() from public;
        do $grant_runtime$
        begin
          if exists (select 1 from pg_roles where rolname = 'workbench_runtime') then
            grant execute on function purge_current_workspace() to workbench_runtime;
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    op.execute("drop function if exists purge_current_workspace()")
