"""작업 큐를 나누고, 죽은 작업을 되살리고, 원천별 상태를 한곳에 적는다

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-26

★왜 필요한가(docs/plans/2026-09-26-integration-13f-earnings-seasonality.md, P0):
  worker 는 한 번에 한 작업만 집는다. 13F·공시 수집(수 초)과 LLM 요약(수 분)이
  한 줄에 서면 LLM 한 건이 공시 수집을 통째로 막는다. → `queue` 로 줄을 나누고
  큐마다 따로 worker 를 띄운다.

⚠️작업이 도중에 죽으면(프로세스 종료·맥 재시동) 그 행은 **영원히 RUNNING** 이다.
  `claim_job` 은 PENDING 만 집으므로 아무도 다시 보지 않는다. → `heartbeat_at` 을
  작업 중에 주기적으로 갱신하고, 끊긴 행을 PENDING 으로 되돌린다. 되살리기를
  무한히 하면 매번 죽는 작업이 영원히 돈다 → `attempts` 로 상한을 둔다.

`source_status` 는 원천(SEC·Nasdaq·Yahoo…)과 worker 자신의 마지막 성공/실패를
한 표에 적는다. 실패는 **종류**(403 / 429 / 무응답 / 기타)로 나눠 적는다 —
Nasdaq 은 막을 때 403 이 아니라 응답 없이 붙잡아서, 종류를 안 적으면
"그냥 느렸다"로 읽힌다(§D-2).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 작업은 전부 한 줄(default)에 서 있던 것이다.
    op.add_column(
        "jobs",
        sa.Column("queue", sa.String(), nullable=False, server_default="default"),
    )
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_jobs_queue_status_created_at", "jobs", ["queue", "status", "created_at"])

    op.create_table(
        "source_status",
        sa.Column("source", sa.String(), primary_key=True),
        # "worker" = 수집기 프로세스의 생존 신호, "source" = 외부 원천
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        # "403" | "429" | "timeout" | "other"
        sa.Column("last_error_kind", sa.String(), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("source_status")
    op.drop_index("ix_jobs_queue_status_created_at", table_name="jobs")
    op.drop_column("jobs", "attempts")
    op.drop_column("jobs", "heartbeat_at")
    op.drop_column("jobs", "queue")
