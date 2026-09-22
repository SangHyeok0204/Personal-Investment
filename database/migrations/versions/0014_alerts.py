"""알림 규칙 — 조건을 세워 두고 지금 충족하는지 본다

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-22

★**전달(텔레그램 등)은 아직 없다.** 그래도 규칙을 세우고 "지금 조건을 만족하는
  것이 무엇인가"를 판정하는 부분은 지금 데이터로 전부 된다. 전달 경로가 생기면
  이 표를 읽어 보내기만 하면 된다 — 규칙을 그때 다시 만들지 않아도 된다.

⚠️`assets` 를 FK 로 걸지 않는다. 관심종목·매매일지와 같은 이유다 — **아직 사지
  않은 종목**에 알림을 걸 수 있어야 하는데, assets 행은 매수해야 생긴다.

⚠️`last_state` 를 두지만 이것을 **판정의 근거로 쓰지 않는다.** 판정은 언제나
  지금 시세로 다시 한다. 이 칸은 "언제부터 이 상태였나"를 보여 주기 위한
  기록일 뿐이다 — 캐시로 쓰면 시세가 바뀌어도 화면이 옛 상태를 말하게 된다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.String(), nullable=False),
        # NULL 이면 포트폴리오 전체에 거는 규칙이다(예: 미체결 방치).
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("threshold", sa.Numeric(20, 6), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("memo", sa.Text(), nullable=True),
        # 마지막으로 본 상태와 그 시각. **판정 근거가 아니라 기록이다.**
        sa.Column("last_state", sa.String(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_alert_rules_ticker", "alert_rules", ["ticker"])
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_ticker", table_name="alert_rules")
    op.drop_table("alert_rules")
