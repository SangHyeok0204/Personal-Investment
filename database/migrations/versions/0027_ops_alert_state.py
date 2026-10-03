"""운영 트립와이어 상태 — 서버가 스스로 잡는 이상(하네스 O1)

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-03

★API 의 `ops_alert_loop`(core/ops_alerts.py)가 5분마다 조건을 보고 **전이만** 적는다.
  · key        — `JOB_STUCK:<job id>` · `SOURCE_ERROR:<source>` · `LLM_CAP_80PCT` · `LLM_ESCALATION:<패킷 파일명>`
  · 열림 = `resolved_at IS NULL`. 처음 잡히면 넣고, 계속 잡히면 last_seen 만, 풀리면 resolved_at.
  · 열린 key 는 다시 알리지 않는다. 풀린 뒤 또 잡히면 같은 행을 다시 연다(first_seen·acked_at 새로).
  · acked_at — 종에서 '확인'을 누른 시각. 열려 있어도 종에는 안 나온다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ops_alert_state",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ops_alert_state")
