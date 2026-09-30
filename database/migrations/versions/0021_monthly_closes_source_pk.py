"""월말 종가의 기본키에 원천을 넣는다 — 같은 달의 블룸버그 값과 Yahoo 값을 둘 다 둔다 (C3)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-26

★왜: 수익률은 **같은 원천 안에서만** 낸다(0020 머리 주석). 2026-09 의 Yahoo 수익률을
  내려면 Yahoo 의 2026-08 종가가 필요한데, 그 달에는 이미 블룸버그 종가가 있다.
  (series, month) 가 키면 둘 중 하나가 다른 하나를 덮는다 — 조용히.
  겹치는 달을 둘 다 남기면 두 원천의 월 수익률 차이도 잴 수 있다(계획 §C 저장).
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("monthly_closes_pkey", "monthly_closes", type_="primary")
    op.create_primary_key("monthly_closes_pkey", "monthly_closes", ["series", "month", "source"])


def downgrade() -> None:
    # 되돌리려면 겹치는 달이 없어야 한다 — Yahoo 행을 먼저 지운다.
    op.execute("DELETE FROM monthly_closes WHERE source <> 'bloomberg'")
    op.drop_constraint("monthly_closes_pkey", "monthly_closes", type_="primary")
    op.create_primary_key("monthly_closes_pkey", "monthly_closes", ["series", "month"])
