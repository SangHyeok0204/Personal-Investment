from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import (
    Account,
    AccountBalance,
    Asset,
    CurrentPosition,
    PortfolioSnapshot,
    PositionSnapshot,
)


def _utc_at(days_ago: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """A UTC timestamp on (today - days_ago), so tests never age out of the window."""
    day = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date()
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=timezone.utc)


def _kst_day_of(moment: datetime) -> str:
    return (moment + timedelta(hours=9)).date().isoformat()


def _account(db, seeded, external_id):
    account = Account(
        broker_id=seeded["broker_id"],
        brokerage_connection_id=seeded["connection_id"],
        external_account_id=external_id,
        base_currency="KRW",
    )
    db.add(account)
    db.flush()
    return account


def _asset(db, ticker):
    asset = Asset(
        country="KR",
        market="KRX",
        ticker=ticker,
        name=ticker,
        asset_type="STOCK",
        currency="KRW",
    )
    db.add(asset)
    db.flush()
    return asset


def _snapshot(db, account_id, snapshot_at, *, securities, cash, purchase="0", pnl="0"):
    snapshot = PortfolioSnapshot(
        account_id=account_id,
        snapshot_at=snapshot_at,
        base_currency="KRW",
        securities_value_krw=Decimal(securities),
        cash_value_krw=Decimal(cash),
        total_assets_krw=Decimal(securities) + Decimal(cash),
        total_purchase_amount_krw=Decimal(purchase),
        total_unrealized_pnl_krw=Decimal(pnl),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _position_snapshot(
    db, snapshot, account_id, asset, *, quantity, avg_price, market_value_krw, pnl_krw
):
    db.add(
        PositionSnapshot(
            portfolio_snapshot_id=snapshot.id,
            account_id=account_id,
            asset_id=asset.id,
            currency="KRW",
            quantity=Decimal(quantity),
            average_purchase_price=Decimal(avg_price),
            market_value_krw=Decimal(market_value_krw),
            unrealized_pnl_krw=Decimal(pnl_krw),
            exchange_rate=Decimal("1.0"),
        )
    )


def test_history_empty(client, seeded):
    response = client.get("/api/v1/portfolio/history")
    assert response.status_code == 200  # accumulating, not an error
    assert response.json() == {
        "points": [],
        "distinct_days": 0,
        "first_snapshot_at": None,
        "last_snapshot_at": None,
        "excluded_tickers": [],
    }


def test_history_collapses_a_day_to_its_last_snapshot(client, seeded, db):
    account = _account(db, seeded, "ACC-DAY")
    first, middle, last = _utc_at(1, 0), _utc_at(1, 4), _utc_at(1, 8)
    _snapshot(db, account.id, first, securities="1000000", cash="100000")
    _snapshot(db, account.id, middle, securities="2000000", cash="100000")
    _snapshot(db, account.id, last, securities="3000000", cash="100000")
    db.commit()

    body = client.get("/api/v1/portfolio/history").json()
    assert body["distinct_days"] == 1
    assert len(body["points"]) == 1

    point = body["points"][0]
    # Syncing several times a day still yields one point: the day's LAST sync.
    assert point["securities_value_krw"] == 3000000.0
    assert point["total_assets_krw"] == 3100000.0
    assert point["date"] == _kst_day_of(last)

    # The span still covers every snapshot, not just the chosen one.
    assert datetime.fromisoformat(body["first_snapshot_at"]) == first
    assert datetime.fromisoformat(body["last_snapshot_at"]) == last


def test_history_kst_day_boundary(client, seeded, db):
    account = _account(db, seeded, "ACC-KST")
    before_midnight = _utc_at(2, 14, 59, 59)  # KST 23:59:59 that day
    after_midnight = _utc_at(2, 15, 0, 0)  # KST 00:00:00 the NEXT day
    _snapshot(db, account.id, before_midnight, securities="1000000", cash="0")
    _snapshot(db, account.id, after_midnight, securities="2000000", cash="0")
    db.commit()

    body = client.get("/api/v1/portfolio/history").json()
    # UTC 15:00 is KST midnight, so these fall on different days.
    assert body["distinct_days"] == 2
    assert [p["date"] for p in body["points"]] == [
        _kst_day_of(before_midnight),
        _kst_day_of(after_midnight),
    ]
    assert body["points"][0]["date"] != body["points"][1]["date"]
    # Ascending, past -> present.
    assert body["points"][0]["total_assets_krw"] == 1000000.0
    assert body["points"][1]["total_assets_krw"] == 2000000.0


def test_history_sums_accounts_on_the_same_day(client, seeded, db):
    first = _account(db, seeded, "ACC-A")
    second = _account(db, seeded, "ACC-B")
    at = _utc_at(1, 6)
    _snapshot(db, first.id, at, securities="1000000", cash="500000")
    _snapshot(db, second.id, at, securities="2000000", cash="300000")
    db.commit()

    body = client.get("/api/v1/portfolio/history").json()
    assert body["distinct_days"] == 1
    point = body["points"][0]
    assert point["securities_value_krw"] == 3000000.0
    assert point["cash_value_krw"] == 800000.0
    assert point["total_assets_krw"] == 3800000.0


def test_history_exclude_tickers(client, seeded, db):
    account = _account(db, seeded, "ACC-EXCL")
    snapshot = _snapshot(
        db,
        account.id,
        _utc_at(1, 6),
        securities="10000000",
        cash="1000000",
        purchase="9500000",
        pnl="500000",
    )
    keep, drop = _asset(db, "AAA"), _asset(db, "BBB")
    # purchase derives from quantity x average_purchase_price x exchange_rate —
    # position_snapshots has no purchase-amount column.
    _position_snapshot(
        db, snapshot, account.id, keep,
        quantity="10", avg_price="600000",
        market_value_krw="7000000", pnl_krw="400000",
    )
    _position_snapshot(
        db, snapshot, account.id, drop,
        quantity="5", avg_price="700000",
        market_value_krw="3000000", pnl_krw="100000",
    )
    db.commit()

    unfiltered = client.get("/api/v1/portfolio/history").json()["points"][0]
    assert unfiltered["securities_value_krw"] == 10000000.0
    assert unfiltered["total_assets_krw"] == 11000000.0
    assert unfiltered["total_purchase_amount_krw"] == 9500000.0
    assert unfiltered["total_unrealized_pnl_krw"] == 500000.0

    body = client.get("/api/v1/portfolio/history?exclude_tickers=BBB").json()
    assert body["excluded_tickers"] == ["BBB"]
    point = body["points"][0]
    assert point["securities_value_krw"] == 7000000.0  # 10M - 3M
    assert point["total_purchase_amount_krw"] == 6000000.0  # 10 x 600,000
    assert point["total_unrealized_pnl_krw"] == 400000.0  # 500k - 100k
    assert point["cash_value_krw"] == 1000000.0  # cash is untouched by a ticker filter
    assert point["total_assets_krw"] == 8000000.0  # securities + cash
    assert point["unrealized_return_pct"] == pytest.approx(400000 / 6000000 * 100)


def test_history_exclude_every_ticker_leaves_cash(client, seeded, db):
    account = _account(db, seeded, "ACC-ALLEX")
    snapshot = _snapshot(
        db, account.id, _utc_at(1, 6), securities="5000000", cash="1000000"
    )
    only = _asset(db, "AAA")
    _position_snapshot(
        db, snapshot, account.id, only,
        quantity="10", avg_price="400000",
        market_value_krw="5000000", pnl_krw="1000000",
    )
    db.commit()

    point = client.get(
        "/api/v1/portfolio/history?exclude_tickers=AAA"
    ).json()["points"][0]
    assert point["securities_value_krw"] == 0.0
    assert point["total_assets_krw"] == 1000000.0  # cash only
    assert point["unrealized_return_pct"] is None  # no purchase left to divide by


def test_history_total_matches_overview_total(client, seeded, db):
    """The invariant: history and overview must never state a different total for the
    same facts. A silent disagreement between two numbers is this project's recurring
    failure mode."""
    account = _account(db, seeded, "ACC-INV")
    asset = _asset(db, "005930")
    now = datetime.now(timezone.utc)

    # Live state -> what /overview computes.
    db.add_all(
        [
            CurrentPosition(
                account_id=account.id,
                asset_id=asset.id,
                quantity=Decimal("10"),
                purchase_amount_local=Decimal("5800000"),
                market_value_krw=Decimal("6000000"),
                unrealized_pnl_krw=Decimal("200000"),
                exchange_rate=Decimal("1.0"),
                as_of=now,
            ),
            AccountBalance(
                account_id=account.id,
                currency="KRW",
                cash_balance=Decimal("1000000"),
                exchange_rate=Decimal("1.0"),
                as_of=now,
            ),
        ]
    )
    # The snapshot the worker wrote from that same state -> what /history reads.
    _snapshot(
        db, account.id, now,
        securities="6000000", cash="1000000",
        purchase="5800000", pnl="200000",
    )
    db.commit()

    overview_total = client.get("/api/v1/portfolio/overview").json()["summary"][
        "total_assets_krw"
    ]
    history = client.get("/api/v1/portfolio/history").json()
    assert history["points"][-1]["total_assets_krw"] == overview_total == 7000000.0


def test_history_days_out_of_range(client):
    too_small = client.get("/api/v1/portfolio/history?days=0")
    assert too_small.status_code == 422
    assert too_small.json()["error"]["code"] == "VALIDATION_ERROR"

    too_large = client.get("/api/v1/portfolio/history?days=731")
    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "VALIDATION_ERROR"
