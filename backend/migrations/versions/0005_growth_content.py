"""Create learning plans, library items, and content entries.

Revision ID: 0005_growth_content
Revises: 0004_finance
Create Date: 2026-08-04
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_growth_content"
down_revision: str | None = "0004_finance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("learning_plans", "library_items", "content_items")


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True)


def _public_id() -> sa.Column:
    return sa.Column("public_id", sa.Uuid(), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()"))


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _updated_at() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "learning_plans",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_id", sa.String(160)),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="waiting_for_hermes"),
        sa.Column("completed_lessons", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_lessons", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("details_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("resources", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "legacy_id", name="learning_plans_workspace_legacy_id_key"),
        sa.CheckConstraint("status in ('waiting_for_hermes', 'active', 'paused', 'completed')", name="learning_plans_status_check"),
        sa.CheckConstraint("completed_lessons >= 0", name="learning_plans_completed_check"),
        sa.CheckConstraint("total_lessons >= 0", name="learning_plans_total_check"),
    )
    op.create_index("learning_plans_workspace_status_updated_idx", "learning_plans", ["workspace_id", "status", "updated_at", "id"])

    op.create_table(
        "library_items",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_id", sa.String(160)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="want"),
        sa.Column("progress_percent", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("current_position", sa.String(240), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("reflection", sa.Text(), nullable=False, server_default=""),
        sa.Column("agent_comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("organized_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "legacy_id", name="library_items_workspace_legacy_id_key"),
        sa.CheckConstraint("kind in ('book', 'movie', 'documentary')", name="library_items_kind_check"),
        sa.CheckConstraint("status in ('want', 'in_progress', 'done')", name="library_items_status_check"),
        sa.CheckConstraint("progress_percent between 0 and 100", name="library_items_progress_check"),
    )
    op.create_index("library_items_workspace_kind_status_idx", "library_items", ["workspace_id", "kind", "status", "updated_at", "id"])

    op.create_table(
        "content_items",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_id", sa.String(160)),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("details_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text()),
        sa.Column("media_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("thumbnail_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("platform", sa.String(80), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="hermes"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "legacy_id", name="content_items_workspace_legacy_id_key"),
        sa.UniqueConstraint("workspace_id", "source_url", name="content_items_workspace_source_url_key"),
        sa.CheckConstraint("category in ('video_trend', 'ai_news', 'topic_idea')", name="content_items_category_check"),
    )
    op.create_index("content_items_workspace_category_updated_idx", "content_items", ["workspace_id", "category", "updated_at", "id"])
    op.create_index("content_items_workspace_deleted_idx", "content_items", ["workspace_id", "deleted_at", "id"])

    workspace_expression = "nullif(current_setting('app.current_workspace_id', true), '')::bigint"
    for table_name in TENANT_TABLES:
        op.execute(f'alter table "{table_name}" enable row level security')
        op.execute(f'alter table "{table_name}" force row level security')
        op.execute(
            f'''create policy "{table_name}_workspace_isolation" on "{table_name}"
                for all using (workspace_id = {workspace_expression})
                with check (workspace_id = {workspace_expression})'''
        )

    op.execute(
        """
        do $grant_runtime$
        begin
          if exists (select 1 from pg_roles where rolname = 'workbench_runtime') then
            execute 'grant select, insert, update, delete on learning_plans, library_items, content_items to workbench_runtime';
            execute 'grant usage, select on all sequences in schema public to workbench_runtime';
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.drop_table(table_name)
