"""체결일 복원 — 해외 체결 원장의 날짜는 체결일이 아니라 결제일이다

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-05

★왜 필요한가: ust21100 '미국주식 거래내역'의 `deal_dt` 는 **결제(현금 원장)일**이다.
  실측(2026-10-05): 실현손익의 매도일 vs 체결 원장 날짜 — SOXL 10-01 vs 10-05,
  AMD 09-24 vs 09-28, NVDA 09-18→09-22·09-24→09-28, BE 09-09→09-11 (T+1~T+2 영업일).
  명세(ust21100)에 체결일 필드는 없다. 주문 원장(orders)의 주문일이 실제 체결일이다.

  · `settlement_date` — 증권사가 준 날짜 그대로(deal_dt / 국내 trde_dt).
  · `trade_date`      — 체결일. 해외는 주문 원장과 짝지어 채운다(워커 history.resolve_us_trade_dates).
  · `trade_date_source` — 'order'(주문과 짝지음) · 'broker'(증권사가 체결일을 줌, 국내 cntr_dt)
                          · 'settlement'(못 짝지음 — 결제일을 그대로 둔 것. 추측하지 않는다).

⚠️**자연키를 결제일로 옮긴다.** `trade_no` 는 deal_dt 기준으로 일자별 1 부터 리셋된다
  (0018 실측). 체결일로 키를 두면 ① 같은 체결일에 결제일이 다른 두 체결이 같은 번호
  `000000001` 을 가질 수 있어 한쪽이 덮이고 ② 짝짓기 결과에 따라 키가 바뀌어 재동기화
  때 같은 원본 행이 **다른 DB 행**으로 들어간다(중복). 결제일은 원본 그대로라 매번 같다.

⚠️이 마이그레이션은 기존 행을 전부 'settlement' 로 둔다(지금의 trade_date 가 곧 결제일).
  체결일 복원은 워커 동기화가 매번 DB 의 주문 원장으로 다시 짝짓는다(다음 동기화가 채운다).
  ★2026-10-05 dev DB 에는 한 번 손으로 돌렸다 — apps/worker 에서
    `history.resolve_us_trade_dates(conn, account_id)` → 92건 중 order 92 · settlement 0.
    결제 지연 2일 57 · 4일 32 · 5일 3. 매도 20건 전부 실현손익 매도일과 일치.
"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("settlement_date", sa.Date(), nullable=True))
    op.add_column("trades", sa.Column("trade_date_source", sa.String(), nullable=True))
    # 지금까지의 trade_date 는 전부 증권사가 준 날짜(= 결제일)다.
    op.execute(
        "UPDATE trades SET settlement_date = trade_date, trade_date_source = 'settlement'"
    )
    # ★자연키의 일부라 비면 안 된다 — 비면 유일키가 걸리지 않아 재동기화마다 행이 는다.
    op.alter_column("trades", "settlement_date", nullable=False)
    op.drop_constraint("uq_trades_account_market_date_no", "trades", type_="unique")
    op.create_unique_constraint(
        "uq_trades_account_market_settle_no",
        "trades",
        ["account_id", "market", "settlement_date", "trade_no"],
    )


def downgrade() -> None:
    # 체결일로 되돌리면 옛 키(trade_date)에서 번호가 겹칠 수 있다 — 결제일로 되돌린다.
    op.execute("UPDATE trades SET trade_date = settlement_date")
    op.drop_constraint("uq_trades_account_market_settle_no", "trades", type_="unique")
    op.create_unique_constraint(
        "uq_trades_account_market_date_no",
        "trades",
        ["account_id", "market", "trade_date", "trade_no"],
    )
    op.drop_column("trades", "trade_date_source")
    op.drop_column("trades", "settlement_date")
