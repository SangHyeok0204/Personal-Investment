"""리밸런싱 목표 비중 — 어긋난 만큼 몇 주를 사고팔아야 하나

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-22

★알림 화면이 이미 "SOXL 비중 21.32% > 20%" 를 잡아 준다. 그런데 **그래서 몇 주를
  팔아야 하는지**에 답하는 자리가 없었다. 목표 비중을 적어 두면 지금 보유와의
  차이를 주수·금액으로 계산한다.

⚠️`assets` 를 FK 로 걸지 않는다. 관심종목·알림과 같은 이유 — **아직 사지 않은
  종목**에도 목표를 둘 수 있어야 한다(신규 편입 계획).

⚠️비중은 소수로 저장한다(0.20 = 20%). 화면에서만 퍼센트로 받는다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rebalance_targets",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("asset_name", sa.String(), nullable=True),
        # 0.20 = 20%. 합이 1을 넘을 수 있다 — 막지 않고 **화면이 말한다.**
        sa.Column("target_weight", sa.Numeric(9, 6), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("ticker", name="uq_rebalance_targets_ticker"),
    )


def downgrade() -> None:
    op.drop_table("rebalance_targets")
