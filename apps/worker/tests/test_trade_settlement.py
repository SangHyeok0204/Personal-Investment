"""체결일 복원(alembic 0028) — 체결 원장 날짜는 결제일이다.

★2026-10-05 실측: ust21100 deal_dt 가 실현손익 매도일보다 T+1~T+2 영업일 늦다
  (SOXL 10-01→10-05, AMD 09-24→09-28, NVDA 09-18→09-22·09-24→09-28, BE 09-09→09-11).
  주문 원장의 주문일로 체결일을 되살리고, 못 짝지으면 결제일 그대로 + 'settlement' 표시.
"""
import os
import sys
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brokers.base import OrderRow, TradeRow
from brokers.kiwoom.broker import _to_domestic_trade_row, _to_trade_row
from repositories import history as history_repo
from sqlalchemy import text
from tests.test_history_repo import _account

# ── 파서 ────────────────────────────────────────────────────────────────────

def test_us_parser_keeps_deal_dt_as_settlement_date():
    row = _to_trade_row({
        "deal_dt": "20261005", "deal_no": "000000001", "rmrk_nm": "매도",
        "stk_cd": "SOXL", "deal_qty": "6", "uv_exrt": "157.62",
    })
    assert row.settlement_date == date(2026, 10, 5)
    # 적재 전에는 체결일을 모른다 — 결제일을 두고 그렇다고 표시한다.
    assert row.trade_date == date(2026, 10, 5)
    assert row.trade_date_source == "settlement"


def test_domestic_parser_uses_cntr_dt_when_given():
    base = {
        "trde_dt": "20260922", "trde_no": "000000001", "rmrk_nm": "현금매수",
        "stk_cd": "A005930", "trde_qty_jwa_cnt": "10", "trde_unit": "71500",
    }
    row = _to_domestic_trade_row({**base, "cntr_dt": "20260918"})
    assert (row.trade_date, row.settlement_date, row.trade_date_source) == (
        date(2026, 9, 18), date(2026, 9, 22), "broker"
    )
    # 빈 날짜("00000000")는 체결일이 아니다 — 결제일 그대로 + 표시.
    row = _to_domestic_trade_row({**base, "cntr_dt": "00000000"})
    assert (row.trade_date, row.trade_date_source) == (date(2026, 9, 22), "settlement")


# ── 짝짓기 ──────────────────────────────────────────────────────────────────

def _t(settle, no, ticker, side, qty, price):
    return SimpleNamespace(
        id=f"{ticker}-{settle}-{no}", settlement_date=settle, trade_no=no,
        ticker=ticker, side=side, quantity=Decimal(qty), price=Decimal(price),
    )


def _o(order_date, no, ticker, side, qty, price):
    return SimpleNamespace(
        order_date=order_date, order_no=no, ticker=ticker, side=side,
        filled_quantity=Decimal(qty), filled_price=Decimal(price),
    )


#: 실측 주문(2026-10-05 dev DB orders) — 체결 원장 행과 체결가·수량이 같다.
_ORDERS = [
    _o(date(2026, 9, 9), "000034478", "BE", "SELL", "1", "278.01"),
    _o(date(2026, 9, 18), "000021757", "NVDA", "SELL", "4", "219.31"),
    _o(date(2026, 9, 24), "000018227", "NVDA", "SELL", "4", "223.19"),
    _o(date(2026, 9, 24), "000018248", "AMD", "SELL", "1", "602"),
    _o(date(2026, 10, 1), "000004637", "SOXL", "SELL", "6", "157.62"),
]


def test_matching_restores_execution_dates_from_orders():
    trades = [
        _t(date(2026, 9, 11), "000000001", "BE", "SELL", "1", "278.01"),
        _t(date(2026, 9, 22), "000000001", "NVDA", "SELL", "4", "219.31"),
        _t(date(2026, 9, 28), "000000002", "NVDA", "SELL", "4", "223.19"),
        _t(date(2026, 9, 28), "000000001", "AMD", "SELL", "1", "602.00"),
        _t(date(2026, 10, 5), "000000001", "SOXL", "SELL", "6", "157.62"),
    ]
    got = history_repo.match_execution_dates(trades, _ORDERS)
    assert got == {
        "BE-2026-09-11-000000001": date(2026, 9, 9),
        "NVDA-2026-09-22-000000001": date(2026, 9, 18),
        # 09-18 주문도 4주라 수량만 보면 후보다 — 이미 쓴 주문은 다시 안 쓴다.
        "NVDA-2026-09-28-000000002": date(2026, 9, 24),
        "AMD-2026-09-28-000000001": date(2026, 9, 24),
        "SOXL-2026-10-05-000000001": date(2026, 10, 1),
    }


def test_matching_nearest_order_wins_when_same_qty_and_price_repeat():
    """같은 (종목, 수량, 가격)이 여러 날 있으면 결제일 바로 앞 주문이다."""
    orders = [
        _o(date(2026, 9, 1), "1", "SCHD", "BUY", "10", "27.00"),
        _o(date(2026, 9, 3), "2", "SCHD", "BUY", "10", "27.00"),
    ]
    trades = [
        _t(date(2026, 9, 3), "000000001", "SCHD", "BUY", "10", "27.00"),
        _t(date(2026, 9, 7), "000000001", "SCHD", "BUY", "10", "27.00"),
    ]
    got = history_repo.match_execution_dates(trades, orders)
    # 결제일 순으로 짝짓는다 — 09-03 결제분이 먼저 가장 가까운 앞(09-03) 주문을 쓴다.
    assert got == {
        "SCHD-2026-09-03-000000001": date(2026, 9, 3),
        "SCHD-2026-09-07-000000001": date(2026, 9, 1),
    }


def test_matching_sums_same_day_orders_settled_as_one_line():
    """실측: EETH 2주·32주를 09-14 에 따로 주문 → 09-16 에 34주 한 줄."""
    orders = [
        _o(date(2026, 9, 14), "000001", "EETH", "BUY", "2", "30.47"),
        _o(date(2026, 9, 14), "000002", "EETH", "BUY", "32", "30.47"),
    ]
    trades = [_t(date(2026, 9, 16), "000000001", "EETH", "BUY", "34", "30.47")]
    got = history_repo.match_execution_dates(trades, orders)
    assert got == {"EETH-2026-09-16-000000001": date(2026, 9, 14)}


def test_matching_leaves_unmatched_out_instead_of_guessing():
    trades = [
        # 가격이 다르다 — 같은 수량 주문이 있어도 다른 체결이다.
        _t(date(2026, 10, 5), "000000001", "SOXL", "SELL", "6", "150.00"),
        # 주문이 아예 없다.
        _t(date(2026, 10, 5), "000000002", "TSLA", "BUY", "1", "250.00"),
        # 주문이 결제일보다 **뒤**다.
        _t(date(2026, 9, 23), "000000003", "AMD", "SELL", "1", "602.00"),
    ]
    assert history_repo.match_execution_dates(trades, _ORDERS) == {}


# ── DB: 복원 · 재동기화 멱등 ─────────────────────────────────────────────────

def _raw_trade(settle, no, ticker, side, qty, price):
    """파서가 만드는 모양 그대로 — 체결일을 모르는 상태."""
    return TradeRow(
        trade_date=settle, settlement_date=settle, trade_date_source="settlement",
        trade_no=no, market="US", side=side, ticker=ticker, name=None, currency="USD",
        quantity=Decimal(qty), price=Decimal(price),
    )


def _order_row(o):
    return OrderRow(
        order_date=o.order_date, order_no=o.order_no, side=o.side, ticker=o.ticker,
        name=None, currency="USD", filled_quantity=o.filled_quantity,
        filled_price=o.filled_price,
    )


def _rows(db):
    with db.begin() as conn:
        return {
            (r.ticker, r.settlement_date): (r.trade_date, r.trade_date_source)
            for r in conn.execute(text(
                "SELECT ticker, settlement_date, trade_date, trade_date_source FROM trades"
            )).all()
        }


def test_resync_is_idempotent_and_keeps_restored_dates(db):
    account_id = _account(db)
    trades = [
        _raw_trade(date(2026, 9, 22), "000000001", "NVDA", "SELL", "4", "219.31"),
        _raw_trade(date(2026, 9, 28), "000000002", "NVDA", "SELL", "4", "223.19"),
        _raw_trade(date(2026, 9, 28), "000000001", "AMD", "SELL", "1", "602.00"),
        _raw_trade(date(2026, 10, 5), "000000001", "SOXL", "SELL", "6", "157.62"),
        # 주문이 없는 체결 — 결제일 그대로 + 'settlement'.
        _raw_trade(date(2026, 10, 5), "000000002", "TSLA", "BUY", "1", "250.00"),
    ]
    expected = {
        ("NVDA", date(2026, 9, 22)): (date(2026, 9, 18), "order"),
        ("NVDA", date(2026, 9, 28)): (date(2026, 9, 24), "order"),
        ("AMD", date(2026, 9, 28)): (date(2026, 9, 24), "order"),
        ("SOXL", date(2026, 10, 5)): (date(2026, 10, 1), "order"),
        ("TSLA", date(2026, 10, 5)): (date(2026, 10, 5), "settlement"),
    }
    for _ in range(3):
        with db.begin() as conn:
            history_repo.upsert_trades(conn, account_id, trades)
            history_repo.upsert_orders(conn, account_id, [_order_row(o) for o in _ORDERS])
            counts = history_repo.resolve_us_trade_dates(conn, account_id)
        assert (counts["order"], counts["settlement"]) == (4, 1)
        assert _rows(db) == expected

    # 주문 조회가 실패한 회차(짝짓기 전 upsert 만) — 복원한 체결일이 결제일로 안 돌아간다.
    with db.begin() as conn:
        history_repo.upsert_trades(conn, account_id, trades)
    assert _rows(db) == expected


def test_same_execution_date_different_settlement_dates_do_not_collide(db):
    """번호는 결제일마다 리셋된다 — 체결일이 같아져도 두 행이 덮이지 않는다."""
    account_id = _account(db)
    orders = [
        _o(date(2026, 9, 18), "1", "NVDA", "SELL", "4", "219.31"),
        _o(date(2026, 9, 18), "2", "XLB", "BUY", "15", "50.68"),
    ]
    trades = [
        _raw_trade(date(2026, 9, 22), "000000001", "NVDA", "SELL", "4", "219.31"),
        _raw_trade(date(2026, 9, 23), "000000001", "XLB", "BUY", "15", "50.68"),
    ]
    for _ in range(2):
        with db.begin() as conn:
            history_repo.upsert_trades(conn, account_id, trades)
            history_repo.upsert_orders(conn, account_id, [_order_row(o) for o in orders])
            history_repo.resolve_us_trade_dates(conn, account_id)
    rows = _rows(db)
    assert len(rows) == 2
    assert {v for v in rows.values()} == {(date(2026, 9, 18), "order")}


def test_resolve_ignores_other_accounts_orders(db):
    account_id = _account(db)
    other = uuid.uuid4()
    with db.begin() as conn:
        history_repo.upsert_trades(conn, account_id, [
            _raw_trade(date(2026, 10, 5), "000000001", "SOXL", "SELL", "6", "157.62"),
        ])
        conn.execute(
            text(
                "INSERT INTO orders (id, account_id, ticker, order_date, order_no, side,"
                " currency, filled_quantity, filled_price) VALUES"
                " (:i, :a, 'SOXL', '2026-10-01', '1', 'SELL', 'USD', 6, 157.62)"
            ),
            {"i": uuid.uuid4(), "a": other},
        )
        counts = history_repo.resolve_us_trade_dates(conn, account_id)
    assert counts["settlement"] == 1
