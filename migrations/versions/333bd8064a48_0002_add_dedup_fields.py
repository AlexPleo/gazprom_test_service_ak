"""0002_add_dedup_fields

Revision ID: 333bd8064a48
Revises: 0089914acf3a
Create Date: 2026-06-19 13:05:55.710015

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '333bd8064a48'
down_revision: Union[str, Sequence[str], None] = '0089914acf3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("archive_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "dedup_hit_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "dedup_eligible",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )

    op.create_index(
        op.f("ix_tasks_archive_sha256"), "tasks", ["archive_sha256"], unique=False
    )
    op.create_index(
        "uq_tasks_archive_sha256_active",
        "tasks",
        ["archive_sha256"],
        unique=True,
        sqlite_where=sa.text("status != 'ERROR' AND dedup_eligible = 1"),
    )

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_tasks_archive_sha256_active",
        table_name="tasks",
        sqlite_where=sa.text("status != 'ERROR' AND dedup_eligible = 1"),
    )
    op.drop_index(op.f("ix_tasks_archive_sha256"), table_name="tasks")

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_column("dedup_eligible")
        batch_op.drop_column("dedup_hit_count")
        batch_op.drop_column("archive_sha256")

