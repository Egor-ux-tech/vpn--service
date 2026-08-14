"""add vless protocol support

Revision ID: a1c9e7f3b246
Revises: dfef610f2c74
Create Date: 2026-08-14 14:05:00.000000

Adds VLESS as a second, parallel VPN protocol alongside the existing WireGuard path —
see docs/vless.md. Nothing here alters WireGuard-specific columns on `vpn_servers` or
`devices`; `vless_credentials`/`vless_server_configs` are entirely new tables, not
reused/repurposed `vpn_peers`/`vpn_profiles` rows.

`protocol` on both `vpn_servers` and `devices` is added NOT NULL with
server_default='wireguard' — Postgres and SQLite both backfill every existing row to
'wireguard' as part of the same ALTER TABLE, so no separate data-migration/UPDATE step
is needed and no existing row is ever left with a NULL protocol.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c9e7f3b246"
down_revision: str | None = "dfef610f2c74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VPN_PROTOCOL_ENUM = sa.Enum("WIREGUARD", "VLESS", name="vpnprotocol", native_enum=False)
_VLESS_CREDENTIAL_STATUS_ENUM = sa.Enum(
    "ACTIVE", "DISABLED", "REVOKED", name="vlesscredentialstatus", native_enum=False
)


def upgrade() -> None:
    # batch_alter_table: SQLite has no ALTER-based column support at all and requires
    # the copy-and-move "batch" strategy; on PostgreSQL, batch mode transparently emits
    # a normal ALTER TABLE ADD COLUMN. See 3073258ed68f for the same rationale.
    with op.batch_alter_table("vpn_servers") as batch_op:
        batch_op.add_column(
            sa.Column("protocol", _VPN_PROTOCOL_ENUM, nullable=False, server_default="WIREGUARD")
        )
    op.create_index(op.f("ix_vpn_servers_protocol"), "vpn_servers", ["protocol"], unique=False)

    with op.batch_alter_table("devices") as batch_op:
        batch_op.add_column(
            sa.Column("protocol", _VPN_PROTOCOL_ENUM, nullable=False, server_default="WIREGUARD")
        )

    op.create_table(
        "vless_server_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("xray_agent_base_url", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("reality_public_key", sa.String(length=64), nullable=False),
        sa.Column("reality_short_ids", sa.JSON(), nullable=False),
        sa.Column("sni", sa.String(length=255), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("flow", sa.String(length=32), nullable=False),
        sa.Column("network_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["vpn_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_vless_server_configs_server_id"),
        "vless_server_configs",
        ["server_id"],
        unique=True,
    )

    op.create_table(
        "vless_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", _VLESS_CREDENTIAL_STATUS_ENUM, nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["server_id"], ["vpn_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "server_id", name="uq_vless_credential_device_server"),
    )
    op.create_index(
        op.f("ix_vless_credentials_device_id"), "vless_credentials", ["device_id"], unique=False
    )
    op.create_index(op.f("ix_vless_credentials_uuid"), "vless_credentials", ["uuid"], unique=True)
    op.create_index(
        op.f("ix_vless_credentials_status"), "vless_credentials", ["status"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_vless_credentials_status"), table_name="vless_credentials")
    op.drop_index(op.f("ix_vless_credentials_uuid"), table_name="vless_credentials")
    op.drop_index(op.f("ix_vless_credentials_device_id"), table_name="vless_credentials")
    op.drop_table("vless_credentials")

    op.drop_index(op.f("ix_vless_server_configs_server_id"), table_name="vless_server_configs")
    op.drop_table("vless_server_configs")

    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_column("protocol")

    op.drop_index(op.f("ix_vpn_servers_protocol"), table_name="vpn_servers")
    with op.batch_alter_table("vpn_servers") as batch_op:
        batch_op.drop_column("protocol")
