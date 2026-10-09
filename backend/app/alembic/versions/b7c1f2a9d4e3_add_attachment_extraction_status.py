"""add attachment extraction status

Revision ID: b7c1f2a9d4e3
Revises: 41a6f09b72cd
Create Date: 2026-10-07 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "b7c1f2a9d4e3"
down_revision = "41a6f09b72cd"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "attachment",
        sa.Column(
            "extraction_status",
            sqlmodel.sql.sqltypes.AutoString(length=30),
            server_default="pending",
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column("attachment", "extraction_status")
