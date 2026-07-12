"""initial schema: jobs, job_logs, imports

Revision ID: 0001
Revises:
Create Date: 2026-07-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])

    op.create_table(
        "job_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("step", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_job_logs_job_id_created_at", "job_logs", ["job_id", "created_at"])

    op.create_table(
        "imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("stored_filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_imports_job_id", "imports", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_imports_job_id", table_name="imports")
    op.drop_table("imports")
    op.drop_index("ix_job_logs_job_id_created_at", table_name="job_logs")
    op.drop_table("job_logs")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_table("jobs")
