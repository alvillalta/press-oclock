"""replace source composite index with user_id index

Revision ID: df90478acabb
Revises: ba98fa2db2f1
Create Date: 2026-09-30 17:18:38.500257

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'df90478acabb'
down_revision = 'ba98fa2db2f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(op.f("ix_source_user_id"), "source", ["user_id"], unique=False)
    op.drop_index("ix_source_user_origin", table_name="source")


def downgrade():
    op.create_index(
        "ix_source_user_origin", "source", ["user_id", "origin"], unique=False
    )
    op.drop_index(op.f("ix_source_user_id"), table_name="source")
