"""계절성 — 지수·섹터 월말 종가와 그 원천(C1)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-26

★docs/plans/2026-09-26-integration-13f-earnings-seasonality.md 계획 C.
  원본(`Downloads/계절성`)은 블룸버그 BDH 엑셀을 사람이 매달 갱신했다. 여기서는
  2026-08 까지는 그 엑셀을 **한 번 적재**(source='bloomberg')하고, 그 뒤 달은
  Yahoo 로 이어 붙인다(C3, source='yahoo').

⚠️수준(close)끼리 잇지 않는다. XLK 와 S5INFT, ASHR(달러·보수)와 CSI300(위안)은
  값의 크기부터 다르다 — 수익률은 **같은 원천 안에서만** 계산하고 정해진 달에
  원천을 바꾼다. 그래서 행마다 `source` 를 적는다.

`month` 는 'YYYY-MM' 문자열이다. Yahoo 는 월초 날짜로, 블룸버그는 월말 날짜로
찍혀 와서 날짜로 두면 같은 달이 두 행이 된다.
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seasonality_series",
        sa.Column("key", sa.String(), primary_key=True),          # 'SPX', 'IT' …(원본 이름 그대로)
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("grp", sa.String(), nullable=False),            # 'index' | 'sector'
        sa.Column("bbg_ticker", sa.String(), nullable=True),      # 'SPX Index'
        sa.Column("yahoo_symbol", sa.String(), nullable=True),    # None = 이어 붙일 원천 없음(동결)
        # 'proxy' = 지수가 아니라 추종 ETF 로 잇는다(ASHR), 'frozen' = 갱신 중단(창업판)
        sa.Column("continuation", sa.String(), nullable=False, server_default="direct"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "monthly_closes",
        sa.Column("series", sa.String(), sa.ForeignKey("seasonality_series.key"), primary_key=True),
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("close", sa.Numeric(20, 6), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("monthly_closes")
    op.drop_table("seasonality_series")
