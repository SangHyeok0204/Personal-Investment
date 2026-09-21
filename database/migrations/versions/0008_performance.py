"""일별 계좌 성과 + 실현손익

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-21

두 화면의 원천을 만든다:
  · 자산 추이 / 수익률 추이  ← account_daily_performance (키움 usa21670)
  · 실현손익                ← realized_pnl (키움 ust21530)

설계 결정:

1. **스냅샷 배치를 만들지 않는다.** portfolio_snapshots 는 "오늘 잔고를 매일 찍어
   쌓는" 방식이라 오늘부터 시작해야 하고 과거가 없다. usa21670 은 증권사가 이미
   들고 있는 **과거 일별 계좌 시계열**을 그대로 준다(실측 360일). 같은 그림을 위해
   우리가 새로 쌓을 이유가 없다.

2. **외화·원화를 둘 다 저장한다.** ust21530 은 fc_krw_tp 로 외화/원화 버전을 따로
   주는데, 두 번 호출해 양쪽을 받아 둔다. 우리가 환율을 곱해 만들지 않는다 —
   매입환율과 매도환율이 달라서(실측: 매입 1,428.63 / 매도 1,543.00) 단일 환율로는
   증권사 값을 재현할 수 없다.

3. **환차손익(krw_chg_dfrn_pl_amt)을 따로 보관한다.** 주가 손익과 환 손익은 다른
   사건이다. 합쳐 버리면 "종목이 올라서 번 건지 환율로 번 건지" 구분이 사라진다.
   실측에서 SGOV 는 외화 기준 -$7.58 인데 환차손익이 +₩195,692 다.

4. 두 테이블 모두 자연키에 계좌를 포함한다 — 계좌가 늘어도 섞이지 않는다.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_daily_performance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("base_date", sa.Date(), nullable=False),
        # dast(예탁자산) = 현금 + 주식. 총자산 곡선의 원천이다.
        sa.Column("deposit_assets_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("stock_value_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("pnl_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("cumulative_pnl_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("dividend_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("commission_tax_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("buy_amount_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("sell_amount_krw", sa.Numeric(20, 2), nullable=True),
        # 입출금 — 수익률(MWR)을 제대로 계산하려면 반드시 있어야 한다.
        sa.Column("deposit_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("withdrawal_krw", sa.Numeric(20, 2), nullable=True),
        # 증권사가 준 당일 수익률(비율). 우리가 다시 계산하지 않는다.
        sa.Column("return_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("exchange_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("account_id", "base_date", name="uq_daily_perf_account_date"),
    )
    op.create_index(
        "ix_daily_perf_account_date", "account_daily_performance", ["account_id", "base_date"]
    )

    op.create_table(
        "realized_pnl",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        # 이미 판 종목이라 마스터가 없을 수 있다.
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id"),
            nullable=True,
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("asset_name", sa.String(), nullable=True),
        # 증권사가 매도일×종목으로 집계해 준다(매도평균가). 그래서 이게 자연키다.
        sa.Column("sell_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("avg_buy_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("avg_sell_price", sa.Numeric(20, 6), nullable=True),
        sa.Column("buy_amount_local", sa.Numeric(20, 4), nullable=True),
        sa.Column("sell_amount_local", sa.Numeric(20, 4), nullable=True),
        sa.Column("commission_tax_local", sa.Numeric(20, 4), nullable=True),
        sa.Column("pnl_local", sa.Numeric(20, 4), nullable=True),
        # 원화 버전(fc_krw_tp=1). 우리가 환산한 값이 아니라 증권사가 준 값이다.
        sa.Column("buy_amount_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("sell_amount_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("commission_tax_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("pnl_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("pnl_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("buy_exchange_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("sell_exchange_rate", sa.Numeric(12, 4), nullable=True),
        # 환차손익 — 주가 손익과 별개다. 합치면 무엇으로 벌었는지 알 수 없다.
        sa.Column("fx_pnl_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "account_id", "sell_date", "ticker", name="uq_realized_account_date_ticker"
        ),
    )
    op.create_index("ix_realized_account_date", "realized_pnl", ["account_id", "sell_date"])


def downgrade() -> None:
    op.drop_index("ix_realized_account_date", table_name="realized_pnl")
    op.drop_table("realized_pnl")
    op.drop_index("ix_daily_perf_account_date", table_name="account_daily_performance")
    op.drop_table("account_daily_performance")
