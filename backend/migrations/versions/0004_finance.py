"""Create finance transactions, budgets, goals, and monthly summaries.

Revision ID: 0004_finance
Revises: 0003_health_history
Create Date: 2026-08-04
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_finance"
down_revision: str | None = "0003_health_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_TABLES = (
    "finance_accounts",
    "finance_categories",
    "finance_recurring_rules",
    "finance_transactions",
    "finance_budgets",
    "savings_goals",
    "finance_monthly_summaries",
    "finance_insights",
)


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
        "finance_accounts",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("account_type", sa.String(16), nullable=False, server_default="other"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("opening_balance_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "name", name="finance_accounts_workspace_name_key"),
        sa.CheckConstraint("account_type in ('cash', 'wechat', 'alipay', 'bank', 'other')", name="finance_accounts_type_check"),
        sa.CheckConstraint("status in ('active', 'archived')", name="finance_accounts_status_check"),
    )
    op.create_index("finance_accounts_workspace_status_idx", "finance_accounts", ["workspace_id", "status", "id"])

    op.create_table(
        "finance_categories",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger()),
        sa.Column("category_type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("system_key", sa.String(80)),
        sa.Column("icon", sa.String(40), nullable=False, server_default=""),
        sa.Column("color", sa.String(16), nullable=False, server_default=""),
        sa.Column("sort_order", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["finance_categories.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workspace_id", "category_type", "name", name="finance_categories_workspace_type_name_key"),
        sa.UniqueConstraint("workspace_id", "system_key", name="finance_categories_workspace_system_key_key"),
        sa.CheckConstraint("category_type in ('income', 'expense')", name="finance_categories_type_check"),
    )
    op.create_index("finance_categories_workspace_type_active_idx", "finance_categories", ["workspace_id", "category_type", "active", "sort_order"])
    op.create_index("finance_categories_parent_id_idx", "finance_categories", ["parent_id"])

    op.create_table(
        "finance_recurring_rules",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("transaction_type", sa.String(16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("category_id", sa.BigInteger()),
        sa.Column("account_id", sa.BigInteger()),
        sa.Column("to_account_id", sa.BigInteger()),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("interval_count", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("next_due_date", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(240), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["finance_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["finance_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_account_id"], ["finance_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint("transaction_type in ('income', 'expense', 'transfer')", name="finance_recurring_rules_type_check"),
        sa.CheckConstraint("amount_minor > 0", name="finance_recurring_rules_amount_check"),
        sa.CheckConstraint("frequency in ('weekly', 'monthly', 'yearly')", name="finance_recurring_rules_frequency_check"),
        sa.CheckConstraint("interval_count between 1 and 60", name="finance_recurring_rules_interval_check"),
    )
    op.create_index("finance_recurring_rules_workspace_next_idx", "finance_recurring_rules", ["workspace_id", "active", "next_due_date", "id"])
    op.create_index("finance_recurring_rules_category_id_idx", "finance_recurring_rules", ["category_id"])
    op.create_index("finance_recurring_rules_account_id_idx", "finance_recurring_rules", ["account_id"])
    op.create_index("finance_recurring_rules_to_account_id_idx", "finance_recurring_rules", ["to_account_id"])

    op.create_table(
        "finance_transactions",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_id", sa.String(160)),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("transaction_type", sa.String(16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("category_id", sa.BigInteger()),
        sa.Column("account_id", sa.BigInteger()),
        sa.Column("to_account_id", sa.BigInteger()),
        sa.Column("refund_of_id", sa.BigInteger()),
        sa.Column("recurring_rule_id", sa.BigInteger()),
        sa.Column("merchant", sa.String(160), nullable=False, server_default=""),
        sa.Column("purpose", sa.String(240), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", postgresql.ARRAY(sa.String(40)), nullable=False, server_default=sa.text("ARRAY[]::varchar[]")),
        sa.Column("source", sa.String(16), nullable=False, server_default="user"),
        sa.Column("is_fixed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_necessary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["finance_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["finance_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_account_id"], ["finance_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["refund_of_id"], ["finance_transactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recurring_rule_id"], ["finance_recurring_rules.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workspace_id", "legacy_id", name="finance_transactions_workspace_legacy_id_key"),
        sa.UniqueConstraint("workspace_id", "idempotency_key", name="finance_transactions_workspace_idempotency_key"),
        sa.CheckConstraint("transaction_type in ('income', 'expense', 'transfer', 'refund')", name="finance_transactions_type_check"),
        sa.CheckConstraint("amount_minor > 0", name="finance_transactions_amount_check"),
        sa.CheckConstraint("(transaction_type <> 'transfer') or (account_id is not null and to_account_id is not null and account_id <> to_account_id)", name="finance_transactions_transfer_accounts_check"),
        sa.CheckConstraint("(transaction_type <> 'refund') or refund_of_id is not null", name="finance_transactions_refund_reference_check"),
    )
    op.create_index("finance_transactions_workspace_date_idx", "finance_transactions", ["workspace_id", "local_date", "occurred_at", "id"])
    op.create_index("finance_transactions_workspace_type_date_idx", "finance_transactions", ["workspace_id", "transaction_type", "local_date", "id"])
    op.create_index("finance_transactions_workspace_category_date_idx", "finance_transactions", ["workspace_id", "category_id", "local_date", "id"])
    op.create_index("finance_transactions_workspace_deleted_idx", "finance_transactions", ["workspace_id", "deleted_at", "id"])
    op.create_index("finance_transactions_category_id_idx", "finance_transactions", ["category_id"])
    op.create_index("finance_transactions_account_id_idx", "finance_transactions", ["account_id"])
    op.create_index("finance_transactions_to_account_id_idx", "finance_transactions", ["to_account_id"])
    op.create_index("finance_transactions_refund_of_id_idx", "finance_transactions", ["refund_of_id"])
    op.create_index("finance_transactions_recurring_rule_id_idx", "finance_transactions", ["recurring_rule_id"])

    op.create_table(
        "finance_budgets",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger()),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("rollover", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["finance_categories.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "period_start", "period_end", "category_id", name="finance_budgets_period_category_key"),
        sa.CheckConstraint("amount_minor > 0", name="finance_budgets_amount_check"),
        sa.CheckConstraint("period_end >= period_start", name="finance_budgets_period_check"),
        sa.CheckConstraint("status in ('active', 'archived')", name="finance_budgets_status_check"),
    )
    op.create_index("finance_budgets_workspace_period_idx", "finance_budgets", ["workspace_id", "period_start", "period_end", "id"])
    op.create_index("finance_budgets_category_id_idx", "finance_budgets", ["category_id"])
    op.create_index(
        "finance_budgets_one_general_period_idx",
        "finance_budgets",
        ["workspace_id", "period_start", "period_end"],
        unique=True,
        postgresql_where=sa.text("category_id is null"),
    )

    op.create_table(
        "savings_goals",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("target_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("current_amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("target_date", sa.Date()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint("target_amount_minor > 0", name="savings_goals_target_check"),
        sa.CheckConstraint("current_amount_minor >= 0", name="savings_goals_current_check"),
        sa.CheckConstraint("status in ('active', 'completed', 'paused')", name="savings_goals_status_check"),
    )
    op.create_index("savings_goals_workspace_status_idx", "savings_goals", ["workspace_id", "status", "target_date", "id"])

    op.create_table(
        "finance_monthly_summaries",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("month_start", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("income_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("expense_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("refund_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("net_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("savings_rate", sa.Numeric(7, 4)),
        sa.Column("category_breakdown", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("budget_status", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "month_start", name="finance_monthly_summaries_workspace_month_key"),
        sa.CheckConstraint("extract(day from month_start) = 1", name="finance_monthly_summaries_month_start_check"),
        sa.CheckConstraint("revision >= 1", name="finance_monthly_summaries_revision_check"),
    )
    op.create_index("finance_monthly_summaries_workspace_month_idx", "finance_monthly_summaries", ["workspace_id", "month_start", "id"])
    op.create_index("finance_monthly_summaries_workspace_stale_idx", "finance_monthly_summaries", ["workspace_id", "stale", "month_start"])

    op.create_table(
        "finance_insights",
        _id(), _public_id(),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("finding", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False, server_default=""),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("next_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="hermes"),
        _created_at(), _updated_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint("period_end >= period_start", name="finance_insights_period_check"),
    )
    op.create_index("finance_insights_workspace_period_idx", "finance_insights", ["workspace_id", "period_end", "period_start", "id"])

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
            execute 'grant select, insert, update, delete on finance_accounts, finance_categories, finance_recurring_rules, finance_transactions, finance_budgets, savings_goals, finance_monthly_summaries, finance_insights to workbench_runtime';
            execute 'grant usage, select on all sequences in schema public to workbench_runtime';
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.drop_table(table_name)
