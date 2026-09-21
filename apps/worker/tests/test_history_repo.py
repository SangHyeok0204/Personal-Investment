"""이력 적재는 **여러 번 돌려도 행이 늘지 않아야** 한다.

동기화를 하루에 여러 번 돌리는 것은 정상이고(장중에 다시 보고 싶다), 같은 기간을
다시 조회하는 것도 정상이다(증권사가 정산을 사후 확정한다). 그때 체결이 두 배로
보이면 화면의 모든 합계가 틀어진다 — 예외 없이 조용히.
"""
import os
import sys
import uuid
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from brokers.base import DailyPerformanceRow, RealizedPnlRow, TradeRow
from repositories import history as history_repo


def _account(db):
    """브로커 → 연결 → 계좌. FK 순서대로."""
    broker_id, conn_id, account_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with db.begin() as conn:
        conn.execute(
            text("INSERT INTO brokers (id, code, name) VALUES (:i,'KIWOOM','키움증권')"),
            {"i": broker_id},
        )
        conn.execute(
            text(
                "INSERT INTO brokerage_connections (id, broker_id, connection_name, environment)"
                " VALUES (:i,:b,'주계좌','REAL')"
            ),
            {"i": conn_id, "b": broker_id},
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, broker_id, brokerage_connection_id,"
                " external_account_id) VALUES (:i,:b,:c,'6210')"
            ),
            {"i": account_id, "b": broker_id, "c": conn_id},
        )
    return account_id


def _trade(**kw):
    defaults = dict(
        trade_date=date(2026, 9, 16), trade_no="000000001", side="BUY",
        ticker="HUT", name="허트8", currency="USD", quantity=Decimal("1"),
        price=Decimal("95.43"), amount_local=Decimal("95.43"),
    )
    defaults.update(kw)
    return TradeRow(**defaults)


def test_trades_upsert_is_idempotent(db):
    account_id = _account(db)
    rows = [_trade(), _trade(trade_no="000000002", ticker="EETH")]

    for _ in range(3):
        with db.begin() as conn:
            history_repo.upsert_trades(conn, account_id, rows)

    with db.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM trades")).scalar()
    assert count == 2


def test_trade_no_resets_daily_so_same_no_on_another_date_is_a_new_row(db):
    """trade_no 는 일자별로 리셋된다 — 날짜가 다르면 같은 번호라도 다른 체결이다."""
    account_id = _account(db)
    with db.begin() as conn:
        history_repo.upsert_trades(
            conn, account_id,
            [_trade(trade_date=date(2026, 9, 16)), _trade(trade_date=date(2026, 9, 10))],
        )
    with db.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM trades")).scalar()
    assert count == 2


def test_trade_upsert_updates_changed_values(db):
    """증권사가 값을 사후 정정하면 최신 값으로 갱신되어야 한다."""
    account_id = _account(db)
    with db.begin() as conn:
        history_repo.upsert_trades(conn, account_id, [_trade(amount_local=Decimal("95.43"))])
    with db.begin() as conn:
        history_repo.upsert_trades(conn, account_id, [_trade(amount_local=Decimal("99.99"))])

    with db.begin() as conn:
        amount = conn.execute(text("SELECT amount_local FROM trades")).scalar()
    assert amount == Decimal("99.9900")


def test_daily_performance_upsert_is_idempotent(db):
    account_id = _account(db)
    rows = [
        DailyPerformanceRow(base_date=date(2026, 9, 19), deposit_assets_krw=Decimal("100")),
        DailyPerformanceRow(base_date=date(2026, 9, 20), deposit_assets_krw=Decimal("200")),
    ]
    for _ in range(2):
        with db.begin() as conn:
            history_repo.upsert_daily_performance(conn, account_id, rows)

    with db.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM account_daily_performance")).scalar()
    assert count == 2


def test_realized_upsert_is_idempotent_and_keyed_by_date_and_ticker(db):
    """증권사가 매도일×종목으로 집계해 준다 — 그 조합이 자연키다."""
    account_id = _account(db)
    rows = [
        RealizedPnlRow(sell_date=date(2026, 9, 18), ticker="NVDA", name="엔비디아",
                       currency="USD", quantity=Decimal("4"), pnl_krw=Decimal("50682")),
        RealizedPnlRow(sell_date=date(2026, 9, 18), ticker="SKHY", name="SK하이닉스",
                       currency="USD", quantity=Decimal("2"), pnl_krw=Decimal("29234")),
    ]
    for _ in range(2):
        with db.begin() as conn:
            history_repo.upsert_realized_pnl(conn, account_id, rows)

    with db.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM realized_pnl")).scalar()
    assert count == 2


def test_history_links_asset_when_master_exists_and_tolerates_missing(db):
    """이미 판 종목은 마스터가 없을 수 있다 — asset_id 가 비어도 행은 남아야 한다."""
    account_id = _account(db)
    asset_id = uuid.uuid4()
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO assets (id, country, market, ticker, currency)"
                " VALUES (:i,'US','NASDAQ','NVDA','USD')"
            ),
            {"i": asset_id},
        )
        history_repo.upsert_trades(
            conn, account_id,
            [_trade(ticker="NVDA"), _trade(trade_no="000000002", ticker="QLD")],
        )

    with db.begin() as conn:
        rows = dict(
            conn.execute(text("SELECT ticker, asset_id FROM trades")).all()
        )
    assert rows["NVDA"] == asset_id
    assert rows["QLD"] is None
