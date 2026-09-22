"""매매일지에 '계획'을 구조로 남긴다 — 나중에 체결과 대조하려고

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-22

★리밸런싱 화면이 "SOXL 11주 매도"라는 계획을 낸다. 그걸 **제목 문자열로만**
  남기면 나중에 "계획 11주 중 몇 주가 체결됐나"를 물을 수 없다 — 문자열을
  파싱하는 코드는 제목을 한 글자만 고쳐도 깨진다. 그래서 구조로 남긴다.

⚠️세 칸 모두 nullable 이다. 계획 없이 적는 메모(생각·복기)가 대부분이고,
  거기에 0 을 채우면 "0주 계획"이라는 없는 사실이 생긴다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # BUY / SELL. 계획이 아닌 메모는 NULL.
    op.add_column("journal_entries", sa.Column("planned_side", sa.String(), nullable=True))
    op.add_column(
        "journal_entries", sa.Column("planned_quantity", sa.Numeric(20, 6), nullable=True)
    )
    # 계획을 세운 시점의 1주 가격(원화). 슬리피지를 재는 기준이다.
    op.add_column(
        "journal_entries", sa.Column("planned_price_krw", sa.Numeric(20, 4), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("journal_entries", "planned_price_krw")
    op.drop_column("journal_entries", "planned_quantity")
    op.drop_column("journal_entries", "planned_side")
