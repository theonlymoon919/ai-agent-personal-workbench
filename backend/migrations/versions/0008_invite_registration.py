"""Add invite-only self-registration and username management.

Revision ID: 0008_invite_registration
Revises: 0007_content_source_category
Create Date: 2026-08-06
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_invite_registration"
down_revision: str | None = "0007_content_source_category"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("can_invite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        """
        update users
        set can_invite = true
        where id = (select id from users order by created_at, id limit 1)
          and not exists (select 1 from users where can_invite = true)
        """
    )
    op.create_table(
        "registration_invites",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", sa.Uuid(), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_prefix", sa.String(8), nullable=False),
        sa.Column("secret_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("used_by_user_id", sa.BigInteger()),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "registration_invites_secret_hash_idx",
        "registration_invites",
        ["secret_hash"],
        unique=True,
    )
    op.create_index(
        "registration_invites_creator_expires_idx",
        "registration_invites",
        ["created_by_user_id", "expires_at"],
    )
    op.create_index(
        "registration_invites_used_by_user_id_idx",
        "registration_invites",
        ["used_by_user_id"],
    )
    op.execute(
        """
        do $grant_runtime$
        begin
          if exists (select 1 from pg_roles where rolname = 'workbench_runtime') then
            grant select, insert, update on registration_invites to workbench_runtime;
            grant usage, select on sequence registration_invites_id_seq to workbench_runtime;
          end if;
        end
        $grant_runtime$;
        """
    )


def downgrade() -> None:
    op.drop_table("registration_invites")
    op.drop_column("users", "can_invite")
