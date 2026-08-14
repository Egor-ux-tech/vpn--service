"""add subscription links

Revision ID: dfef610f2c74
Revises: 3073258ed68f
Create Date: 2026-08-14 11:09:26.491400

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dfef610f2c74"
down_revision: str | None = "3073258ed68f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscription_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=12), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "REVOKED", name="subscriptionlinkstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_subscription_links_device_id"), "subscription_links", ["device_id"], unique=True
    )
    op.create_index(
        op.f("ix_subscription_links_status"), "subscription_links", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_subscription_links_token_hash"), "subscription_links", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_subscription_links_token_hash"), table_name="subscription_links")
    op.drop_index(op.f("ix_subscription_links_status"), table_name="subscription_links")
    op.drop_index(op.f("ix_subscription_links_device_id"), table_name="subscription_links")
    op.drop_table("subscription_links")
