"""Allow one source to back content in different categories.

Revision ID: 0007_content_source_category
Revises: 0006_account_deletion
Create Date: 2026-08-04
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0007_content_source_category"
down_revision: str | None = "0006_account_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "content_items_workspace_source_url_key",
        "content_items",
        type_="unique",
    )
    op.create_unique_constraint(
        "content_items_workspace_source_url_key",
        "content_items",
        ["workspace_id", "category", "source_url"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "content_items_workspace_source_url_key",
        "content_items",
        type_="unique",
    )
    op.create_unique_constraint(
        "content_items_workspace_source_url_key",
        "content_items",
        ["workspace_id", "source_url"],
    )
