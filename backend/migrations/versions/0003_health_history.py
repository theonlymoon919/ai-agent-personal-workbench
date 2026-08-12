"""Create tenant-scoped health records and daily history summaries.

Revision ID: 0003_health_history
Revises: 0002_core_workbench
Create Date: 2026-08-04
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_health_history"
down_revision: str | None = "0002_core_workbench"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = (
    "water_entries",
    "weight_entries",
    "health_records",
    "health_analyses",
    "health_daily_summaries",
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
        "water_entries",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_ml", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        _created_at(),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint("amount_ml between 1 and 5000", name="water_entries_amount_check"),
    )
    op.create_index("water_entries_workspace_date_idx", "water_entries", ["workspace_id", "record_date", "occurred_at", "id"])
    op.create_index("water_entries_workspace_deleted_idx", "water_entries", ["workspace_id", "deleted_at", "id"])

    op.create_table(
        "weight_entries",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        _created_at(),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint("weight_kg between 20 and 400", name="weight_entries_weight_check"),
    )
    op.create_index("weight_entries_workspace_date_idx", "weight_entries", ["workspace_id", "record_date", "occurred_at", "id"])
    op.create_index("weight_entries_workspace_deleted_idx", "weight_entries", ["workspace_id", "deleted_at", "id"])

    op.create_table(
        "health_records",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_id", sa.String(160)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meal_slot", sa.String(24)),
        sa.Column("object_id", sa.BigInteger(), nullable=False),
        sa.Column("thumbnail_object_id", sa.BigInteger(), nullable=False),
        sa.Column("analysis_status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["object_id"], ["stored_objects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["thumbnail_object_id"], ["stored_objects.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workspace_id", "legacy_id", name="health_records_workspace_legacy_id_key"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="health_records_workspace_idempotency_key"),
        sa.CheckConstraint("kind in ('meal', 'weight_photo', 'exercise')", name="health_records_kind_check"),
        sa.CheckConstraint(
            "meal_slot is null or meal_slot in ('breakfast', 'lunch', 'afternoon_tea', 'dinner', 'snack', 'late_night')",
            name="health_records_meal_slot_check",
        ),
        sa.CheckConstraint(
            "analysis_status in ('queued', 'in_progress', 'analyzed', 'failed')",
            name="health_records_analysis_status_check",
        ),
    )
    op.create_index("health_records_workspace_date_kind_idx", "health_records", ["workspace_id", "record_date", "kind", "id"])
    op.create_index("health_records_workspace_status_idx", "health_records", ["workspace_id", "analysis_status", "created_at", "id"])
    op.create_index("health_records_workspace_deleted_idx", "health_records", ["workspace_id", "deleted_at", "id"])
    op.create_index("health_records_object_id_idx", "health_records", ["object_id"])
    op.create_index("health_records_thumbnail_object_id_idx", "health_records", ["thumbnail_object_id"])

    op.create_table(
        "health_analyses",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("health_record_id", sa.BigInteger(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("advice", sa.Text(), nullable=False, server_default=""),
        sa.Column("calories_kcal", sa.BigInteger()),
        sa.Column("exercise_kcal", sa.BigInteger()),
        sa.Column("weight_kg", sa.Numeric(6, 2)),
        sa.Column("model_name", sa.String(120)),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["health_record_id"], ["health_records.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "health_record_id", name="health_analyses_record_key"),
        sa.CheckConstraint("calories_kcal is null or calories_kcal between 0 and 10000", name="health_analyses_calories_check"),
        sa.CheckConstraint("exercise_kcal is null or exercise_kcal between 0 and 10000", name="health_analyses_exercise_check"),
        sa.CheckConstraint("weight_kg is null or weight_kg between 20 and 400", name="health_analyses_weight_check"),
    )
    op.create_index("health_analyses_workspace_analyzed_idx", "health_analyses", ["workspace_id", "analyzed_at", "id"])
    op.create_index("health_analyses_health_record_id_idx", "health_analyses", ["health_record_id"])

    op.create_table(
        "health_daily_summaries",
        _id(),
        _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2)),
        sa.Column("water_ml", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("calories_kcal", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("exercise_kcal", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("meal_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("photo_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="neutral"),
        sa.Column("sections", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("thumbnail_object_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("generated_by", sa.String(16), nullable=False, server_default="system"),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "summary_date", name="health_daily_summaries_workspace_date_key"),
        sa.CheckConstraint("status in ('on_track', 'attention', 'celebrate', 'neutral')", name="health_daily_summaries_status_check"),
        sa.CheckConstraint("revision >= 1", name="health_daily_summaries_revision_check"),
    )
    op.create_index("health_daily_summaries_workspace_date_idx", "health_daily_summaries", ["workspace_id", "summary_date", "id"])
    op.create_index("health_daily_summaries_workspace_stale_idx", "health_daily_summaries", ["workspace_id", "stale", "summary_date"])

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
            execute 'grant select, insert, update, delete on water_entries, weight_entries, health_records, health_analyses, health_daily_summaries to workbench_runtime';
            execute 'grant usage, select on all sequences in schema public to workbench_runtime';
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.drop_table(table_name)
