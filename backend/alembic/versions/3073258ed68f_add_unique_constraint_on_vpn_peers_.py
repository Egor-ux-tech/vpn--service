"""add unique constraint on vpn_peers server_id assigned_ip

Revision ID: 3073258ed68f
Revises: f74a5caeec68
Create Date: 2026-08-13 22:21:30.179174

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3073258ed68f'
down_revision: str | None = 'f74a5caeec68'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table (not a plain op.create_unique_constraint): SQLite has no ALTER-based
    # constraint support at all and requires the copy-and-move "batch" strategy; on
    # PostgreSQL, batch mode transparently emits a normal ALTER TABLE ADD CONSTRAINT. Using
    # batch mode here keeps this migration valid against both, which matters because the
    # test suite applies migrations against SQLite while production runs Postgres.
    with op.batch_alter_table("vpn_peers") as batch_op:
        batch_op.create_unique_constraint(
            "uq_vpn_peer_server_assigned_ip", ["server_id", "assigned_ip"]
        )


def downgrade() -> None:
    with op.batch_alter_table("vpn_peers") as batch_op:
        batch_op.drop_constraint("uq_vpn_peer_server_assigned_ip", type_="unique")
