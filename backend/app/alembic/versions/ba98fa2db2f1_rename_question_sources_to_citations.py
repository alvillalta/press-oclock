"""Rename question sources to citations

Revision ID: ba98fa2db2f1
Revises: 9871170d6419
Create Date: 2026-09-29 18:47:50.197455

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "ba98fa2db2f1"
down_revision = "9871170d6419"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("question", "sources", new_column_name="citations")


def downgrade():
    op.alter_column("question", "citations", new_column_name="sources")
