"""add staged mail attachments

Revision ID: 41a6f09b72cd
Revises: df90478acabb
Create Date: 2026-10-02 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "41a6f09b72cd"
down_revision = "df90478acabb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mail",
        sa.Column("external_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_mail_user_external_id", "mail", ["user_id", "external_id"]
    )

    op.create_table(
        "mail_stage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "external_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "subject", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "sender", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=30),
            server_default="receiving",
            nullable=False,
        ),
        sa.Column("total_size_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mail_id", sa.Uuid(), nullable=True),
        sa.Column(
            "result_summary",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mail_id"], ["mail.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "external_id", name="uq_mail_stage_user_external_id"
        ),
    )
    op.create_index("ix_mail_stage_user_id", "mail_stage", ["user_id"], unique=False)
    op.create_index("ix_mail_stage_mail_id", "mail_stage", ["mail_id"], unique=False)

    op.create_table(
        "attachment_stage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mail_stage_id", sa.Uuid(), nullable=False),
        sa.Column(
            "external_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "filename", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "mime_type", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=30),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("storage_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["mail_stage_id"], ["mail_stage.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mail_stage_id", "external_id", name="uq_attachment_stage_mail_external_id"
        ),
    )
    op.create_index(
        "ix_attachment_stage_mail_stage_id",
        "attachment_stage",
        ["mail_stage_id"],
        unique=False,
    )

    op.create_table(
        "storage_cleanup",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("storage_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_storage_cleanup_storage_path",
        "storage_cleanup",
        ["storage_path"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_storage_cleanup_storage_path", table_name="storage_cleanup")
    op.drop_table("storage_cleanup")
    op.drop_index(
        "ix_attachment_stage_mail_stage_id", table_name="attachment_stage"
    )
    op.drop_table("attachment_stage")
    op.drop_index("ix_mail_stage_mail_id", table_name="mail_stage")
    op.drop_index("ix_mail_stage_user_id", table_name="mail_stage")
    op.drop_table("mail_stage")
    op.drop_constraint("uq_mail_user_external_id", "mail", type_="unique")
    op.drop_column("mail", "external_id")
