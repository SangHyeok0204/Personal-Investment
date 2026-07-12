import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import Account, AccountBalance, Asset, CurrentPosition

EMPTY_SUMMARY = {
    "total_assets_krw": 0.0,
    "securities_value_krw": 0.0,
    "cash_value_krw": 0.0,
    "total_purchase_amount_krw": 0.0,
    "total_unrealized_pnl_krw": 0.0,
    "unrealized_return_pct": None,
    "position_count": 0,
    "account_count": 0,
}


def test_overview_empty_state(client, seeded):
    response = client.get("/api/v1/portfolio/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == EMPTY_SUMMARY
    assert body["accounts"] == []
    assert body["positions"] == []
    assert body["cash_balances"] == []
    assert body["market_breakdown"] == []
    assert body["last_synced_at"] is None
    assert body["sync_status"] == "NEVER_SYNCED"
    assert body["connection"]["id"] == str(seeded["connection_id"])
    assert body["connection"]["status"] == "CONFIGURED"
    assert body["connection"]["credentials_configured"] is False
    assert body["connection"]["last_error"] is None


def test_overview_empty_without_connection(client):
    response = client.get("/api/v1/portfolio/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == EMPTY_SUMMARY
    assert body["sync_status"] == "NEVER_SYNCED"
    assert body["connection"] is None


def _seed_portfolio(db, seeded):
    now = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)
    account = Account(
        broker_id=seeded["broker_id"],
        brokerage_connection_id=seeded["connection_id"],
        external_account_id="ACC1",
        account_name="주식계좌",
        account_number_masked="1234****",
        account_type="위탁",
        base_currency="KRW",
        last_synced_at=now,
    )
    db.add(account)
    db.flush()

    samsung = Asset(country="KR", market="KRX", ticker="005930", name="삼성전자", currency="KRW")
    hynix = Asset(country="KR", market="KRX", ticker="000660", name="SK하이닉스", currency="KRW")
    db.add_all([samsung, hynix])
    db.flush()

    pos_samsung = CurrentPosition(
        account_id=account.id,
        asset_id=samsung.id,
        quantity=Decimal("10"),
        market_value_local=Decimal("700000"),
        market_value_krw=Decimal("700000"),
        unrealized_pnl_krw=Decimal("100000"),
        exchange_rate=Decimal("1.0"),
        as_of=now,
    )
    pos_hynix = CurrentPosition(
        account_id=account.id,
        asset_id=hynix.id,
        quantity=Decimal("5"),
        market_value_local=Decimal("500000"),
        market_value_krw=Decimal("500000"),
        unrealized_pnl_krw=Decimal("-50000"),
        exchange_rate=Decimal("1.0"),
        as_of=now,
    )
    balance = AccountBalance(
        account_id=account.id,
        currency="KRW",
        cash_balance=Decimal("300000"),
        exchange_rate=Decimal("1.0"),
        as_of=now,
    )
    db.add_all([pos_samsung, pos_hynix, balance])
    db.commit()
    return account.id


def test_overview_populated(client, seeded, db):
    account_id = _seed_portfolio(db, seeded)

    body = client.get("/api/v1/portfolio/overview").json()
    summary = body["summary"]
    assert summary["securities_value_krw"] == 1200000.0
    assert summary["cash_value_krw"] == 300000.0
    assert summary["total_assets_krw"] == 1500000.0
    assert summary["total_unrealized_pnl_krw"] == 50000.0
    assert summary["total_purchase_amount_krw"] == 1150000.0
    assert summary["unrealized_return_pct"] == pytest.approx(50000 / 1150000 * 100)
    assert summary["position_count"] == 2
    assert summary["account_count"] == 1

    # Positions sorted by market_value_krw DESC, joined to asset + broker.
    assert [p["ticker"] for p in body["positions"]] == ["005930", "000660"]
    assert body["positions"][0]["broker"] == "KIWOOM"
    assert body["positions"][0]["asset_name"] == "삼성전자"
    assert body["positions"][0]["market_value_krw"] == 700000.0

    assert body["market_breakdown"] == [
        {"country": "KR", "securities_value_krw": 1200000.0, "position_count": 2}
    ]
    assert body["accounts"][0]["id"] == str(account_id)
    assert body["accounts"][0]["total_assets_krw"] == 1500000.0
    assert len(body["cash_balances"]) == 1
    assert body["cash_balances"][0]["currency"] == "KRW"
    assert body["last_synced_at"] is not None
    assert body["sync_status"] == "NEVER_SYNCED"


def test_positions_empty(client):
    response = client.get("/api/v1/portfolio/positions")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_positions_filters(client, seeded, db):
    account_id = _seed_portfolio(db, seeded)

    all_items = client.get("/api/v1/portfolio/positions").json()
    assert all_items["total"] == 2

    kr = client.get("/api/v1/portfolio/positions?country=KR").json()
    assert kr["total"] == 2

    us = client.get("/api/v1/portfolio/positions?country=US").json()
    assert us["total"] == 0

    krw = client.get("/api/v1/portfolio/positions?currency=KRW").json()
    assert krw["total"] == 2

    by_account = client.get(f"/api/v1/portfolio/positions?account_id={account_id}").json()
    assert by_account["total"] == 2


def test_positions_invalid_country(client):
    response = client.get("/api/v1/portfolio/positions?country=JP")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_positions_invalid_currency(client):
    response = client.get("/api/v1/portfolio/positions?currency=EUR")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_positions_malformed_account_id(client):
    response = client.get("/api/v1/portfolio/positions?account_id=not-a-uuid")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_account_portfolio(client, seeded, db):
    account_id = _seed_portfolio(db, seeded)
    response = client.get(f"/api/v1/accounts/{account_id}/portfolio")
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["id"] == str(account_id)
    assert body["account"]["total_assets_krw"] == 1500000.0
    assert len(body["positions"]) == 2
    assert len(body["cash_balances"]) == 1
    assert body["last_synced_at"] is not None


def test_account_portfolio_not_found(client):
    response = client.get(f"/api/v1/accounts/{uuid.uuid4()}/portfolio")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_account_portfolio_malformed_uuid(client):
    response = client.get("/api/v1/accounts/not-a-uuid/portfolio")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
