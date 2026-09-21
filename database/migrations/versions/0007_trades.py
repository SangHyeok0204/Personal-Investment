"""매매(체결) 내역 테이블

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-21

0002 가 만든 포트폴리오 스키마에는 **거래 이력이 없다** — 현재 보유(current_positions)와
잔고 스냅샷만 있다. 사용자가 모니터링 1순위로 꼽은 항목 중 유일하게 원천이 없던 자리다.

원천: 키움 `ust21100`(미국주식 거래내역). 실측(2026-09-21)에서 확인한 것들:

  · `deal_no` 는 **일자별로 리셋되는 일련번호**다. 69건에 고유값이 5개뿐이고
    매수/매도 간에도 겹친다 — 단독 유일키로 쓸 수 없다.
    → 자연키는 (account_id, trade_date, trade_no).
  · 매수/매도 구분은 `deal_kind_nm`(전부 "매매")이 아니라 **`rmrk_nm`**(적요명)이다.
  · 해외 거래는 원화 금액 필드(deal_amt/exct_amt/tax_tot_amt)가 **전부 0** 이고
    실제 값은 fc_* (외화) 필드에 있다.
    → 0 을 KRW 금액으로 저장하지 않는다. 없으면 NULL 이다.
  · 조회 기간은 **1년 이내**만 허용된다(초과 시 return_code=20 / 501058).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        # 이미 판 종목도 이력에 남는다. 종목 마스터가 없을 수 있어 nullable 이고,
        # ticker 를 함께 보관해 마스터 없이도 무엇을 거래했는지 읽을 수 있게 한다.
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id"),
            nullable=True,
        ),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("asset_name", sa.String(), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("trade_no", sa.String(), nullable=False),
        # BUY / SELL. 증권사 문구(rmrk_nm)를 그대로 쓰지 않고 코드로 정규화한다 —
        # 증권사가 늘면 문구가 갈린다.
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("price", sa.Numeric(20, 6), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("amount_local", sa.Numeric(20, 4), nullable=True),
        # 정산금액 = 거래금액 ± 수수료·세금. 실제로 계좌에서 나가고 들어온 돈이다.
        sa.Column("settlement_amount_local", sa.Numeric(20, 4), nullable=True),
        sa.Column("commission_local", sa.Numeric(20, 4), nullable=True),
        sa.Column("tax_local", sa.Numeric(20, 4), nullable=True),
        # 원화 금액은 증권사가 줄 때만 채운다(해외 거래는 0 으로 온다 → NULL).
        sa.Column("amount_krw", sa.Numeric(20, 2), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("processed_at", sa.String(), nullable=True),
        sa.Column("source_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "account_id", "trade_date", "trade_no", name="uq_trades_account_date_no"
        ),
    )
    op.create_index("ix_trades_account_date", "trades", ["account_id", "trade_date"])
    op.create_index("ix_trades_ticker", "trades", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_trades_ticker", table_name="trades")
    op.drop_index("ix_trades_account_date", table_name="trades")
    op.drop_table("trades")
