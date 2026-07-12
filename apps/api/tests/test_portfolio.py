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

    # purchase_amount_local is deliberately NOT (market_value - pnl): Kiwoom's pnl is
    # net of fees/taxes, so the old `securities - pnl` derivation overstated the
    # purchase total. Real purchase here is 595,000 + 548,000 = 1,143,000, while the
    # old derivation would give 1,200,000 - 50,000 = 1,150,000.
    pos_samsung = CurrentPosition(
        account_id=account.id,
        asset_id=samsung.id,
        quantity=Decimal("10"),
        purchase_amount_local=Decimal("595000"),
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
        purchase_amount_local=Decimal("548000"),
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
        # Kiwoom's 추정예탁자산 (account-level: cash + securities). Cash must IGNORE it —
        # summing it as cash double-counts the securities and doubles 총자산.
        total_evaluation_amount_krw=Decimal("6597287"),
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
    # Real stored purchase total (595,000 + 548,000) — the old `securities - pnl`
    # derivation would have produced 1,150,000 here.
    assert summary["total_purchase_amount_krw"] == 1143000.0
    assert summary["total_purchase_amount_krw"] != 1150000.0
    assert summary["unrealized_return_pct"] == pytest.approx(50000 / 1143000 * 100)
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
    cash = body["cash_balances"][0]
    assert cash["currency"] == "KRW"
    assert cash["cash_balance"] == 300000.0
    assert cash["exchange_rate"] == 1.0
    assert cash["cash_krw"] == 300000.0
    # Surfaced for reconciliation only — never folded into cash_value/total_assets.
    assert cash["estimated_total_assets_krw"] == 6597287.0

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


def _make_account(db, seeded, external_id):
    now = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)
    account = Account(
        broker_id=seeded["broker_id"],
        brokerage_connection_id=seeded["connection_id"],
        external_account_id=external_id,
        base_currency="KRW",
        last_synced_at=now,
    )
    db.add(account)
    db.flush()
    return account, now


def _seed_us_holdings(db, account_id):
    """US position + USD cash row. All KRW values come FROM Kiwoom (contract §10)."""
    now = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)
    alphabet = Asset(country="US", market="US", ticker="GOOGL", name="Alphabet", currency="USD")
    db.add(alphabet)
    db.flush()
    db.add_all(
        [
            CurrentPosition(
                account_id=account_id,
                asset_id=alphabet.id,
                quantity=Decimal("5"),
                purchase_amount_local=Decimal("1000.00"),  # USD
                market_value_local=Decimal("5390.00"),  # USD
                market_value_krw=Decimal("8000000"),  # Kiwoom evlt_amt_krw
                unrealized_pnl_krw=Decimal("500000"),  # Kiwoom pl_amt_krw
                exchange_rate=Decimal("1484.10"),  # Kiwoom exch_rate
                as_of=now,
            ),
            AccountBalance(
                account_id=account_id,
                currency="USD",
                cash_balance=Decimal("1000.00"),
                exchange_rate=Decimal("1484.10"),  # Kiwoom usd_exch_rate
                # 추정예탁자산 for the US side (cash + securities) — must be ignored by
                # cash_value_krw; only cash_balance x exchange_rate counts.
                total_evaluation_amount_krw=Decimal("32700000.00"),
                as_of=now,
            ),
        ]
    )
    db.commit()


def test_summary_purchase_total_is_real_not_derived(client, seeded, db):
    """Regression: `securities - pnl` overstated the purchase total by 15,248 KRW on
    the live account, because Kiwoom's pnl is already net of fees/taxes."""
    account, now = _make_account(db, seeded, "ACC-FEES")
    asset = Asset(country="KR", market="KRX", ticker="005930", name="삼성전자", currency="KRW")
    db.add(asset)
    db.flush()
    db.add(
        CurrentPosition(
            account_id=account.id,
            asset_id=asset.id,
            quantity=Decimal("100"),
            purchase_amount_local=Decimal("6972900"),  # Kiwoom 총매입금액
            market_value_krw=Decimal("7000000"),
            unrealized_pnl_krw=Decimal("11852"),  # net of fees/taxes
            exchange_rate=Decimal("1.0"),
            as_of=now,
        )
    )
    db.commit()

    summary = client.get("/api/v1/portfolio/overview").json()["summary"]
    assert summary["total_purchase_amount_krw"] == 6972900.0  # real stored value
    assert summary["total_purchase_amount_krw"] != 6988148.0  # the old derivation
    assert 6988148.0 - summary["total_purchase_amount_krw"] == 15248.0


def test_overview_with_us_positions_and_usd_cash(client, seeded, db):
    account_id = _seed_portfolio(db, seeded)
    _seed_us_holdings(db, account_id)

    body = client.get("/api/v1/portfolio/overview").json()
    summary = body["summary"]

    # Stored KRW values from Kiwoom -> exact.
    assert summary["securities_value_krw"] == 9200000.0  # 700k + 500k + 8.0M
    assert summary["total_unrealized_pnl_krw"] == 550000.0
    # Cash = KRW 300,000 (rate 1.0) + USD 1,000 x 1,484.10. Neither row's
    # 추정예탁자산 (6,597,287 / 32,700,000) may leak in.
    assert summary["cash_value_krw"] == pytest.approx(1784100.0)
    assert summary["total_assets_krw"] == pytest.approx(10984100.0)
    assert summary["cash_value_krw"] < 6597287.0
    # Purchase = KR 1,143,000 + US (1,000 USD x 1,484.10).
    assert summary["total_purchase_amount_krw"] == pytest.approx(2627100.0)
    assert summary["unrealized_return_pct"] == pytest.approx(550000 / 2627100 * 100)
    assert summary["position_count"] == 3

    # market_breakdown lists BOTH countries, highest value first.
    assert [row["country"] for row in body["market_breakdown"]] == ["US", "KR"]
    breakdown = {row["country"]: row for row in body["market_breakdown"]}
    assert breakdown["US"]["securities_value_krw"] == 8000000.0
    assert breakdown["US"]["position_count"] == 1
    assert breakdown["KR"]["securities_value_krw"] == 1200000.0
    assert breakdown["KR"]["position_count"] == 2

    assert {c["currency"] for c in body["cash_balances"]} == {"KRW", "USD"}
    # The USD card's KRW sub-line comes from cash_krw — the UI never invents FX.
    usd_cash = next(c for c in body["cash_balances"] if c["currency"] == "USD")
    assert usd_cash["cash_balance"] == 1000.0
    assert usd_cash["exchange_rate"] == pytest.approx(1484.10)
    assert usd_cash["cash_krw"] == pytest.approx(1484100.0)
    assert usd_cash["estimated_total_assets_krw"] == 32700000.0

    us_only = client.get("/api/v1/portfolio/positions?country=US").json()
    assert us_only["total"] == 1
    assert us_only["items"][0]["ticker"] == "GOOGL"


def test_cash_ignores_estimated_total_assets(client, seeded, db):
    """Regression (live account): the KRW row carries cash_balance 2,495 while
    total_evaluation_amount_krw is 6,597,287 — Kiwoom's 추정예탁자산 (cash + securities).
    Summing that as cash double-counts the securities and ~doubles 총자산 (13.2M vs 6.6M).
    """
    account, now = _make_account(db, seeded, "ACC-EST")
    asset = Asset(country="KR", market="KRX", ticker="005930", name="삼성전자", currency="KRW")
    db.add(asset)
    db.flush()
    db.add_all(
        [
            CurrentPosition(
                account_id=account.id,
                asset_id=asset.id,
                quantity=Decimal("100"),
                purchase_amount_local=Decimal("6500000"),
                market_value_krw=Decimal("6609000"),
                unrealized_pnl_krw=Decimal("109000"),
                exchange_rate=Decimal("1.0"),
                as_of=now,
            ),
            AccountBalance(
                account_id=account.id,
                currency="KRW",
                cash_balance=Decimal("2495"),  # real settled D+2 cash
                exchange_rate=Decimal("1.0"),
                total_evaluation_amount_krw=Decimal("6597287"),  # 추정예탁자산 trap
                as_of=now,
            ),
        ]
    )
    db.commit()

    body = client.get("/api/v1/portfolio/overview").json()
    summary = body["summary"]
    assert summary["cash_value_krw"] == 2495.0  # NOT 6,597,287
    assert summary["securities_value_krw"] == 6609000.0
    assert summary["total_assets_krw"] == 6611495.0  # NOT ~13.2M
    assert body["accounts"][0]["total_assets_krw"] == 6611495.0

    cash = body["cash_balances"][0]
    assert cash["cash_krw"] == 2495.0
    assert cash["estimated_total_assets_krw"] == 6597287.0  # reconciliation only


def test_cash_value_is_cash_balance_times_rate(client, seeded, db):
    account, now = _make_account(db, seeded, "ACC-RATES")
    db.add_all(
        [
            # USD cash converts with Kiwoom's stored rate.
            AccountBalance(
                account_id=account.id,
                currency="USD",
                cash_balance=Decimal("1000.00"),
                exchange_rate=Decimal("1484.10"),
                as_of=now,
            ),
            # KRW cash with no rate -> defaults to 1.0.
            AccountBalance(
                account_id=account.id,
                currency="KRW",
                cash_balance=Decimal("250000.00"),
                as_of=now,
            ),
            # Foreign cash with NO rate -> contributes 0. FX is never guessed.
            AccountBalance(
                account_id=account.id,
                currency="JPY",
                cash_balance=Decimal("50000.00"),
                as_of=now,
            ),
        ]
    )
    db.commit()

    body = client.get("/api/v1/portfolio/overview").json()
    assert body["summary"]["cash_value_krw"] == pytest.approx(1484100.0 + 250000.0)

    by_currency = {c["currency"]: c for c in body["cash_balances"]}
    assert by_currency["USD"]["cash_krw"] == pytest.approx(1484100.0)
    assert by_currency["KRW"]["cash_krw"] == 250000.0
    # Null rate -> null cash_krw, so the UI omits the KRW sub-line instead of faking it.
    assert by_currency["JPY"]["exchange_rate"] is None
    assert by_currency["JPY"]["cash_krw"] is None


# ---------------------------------------------------------------------------
# Asset class breakdown (round 3) — portfolio-detail-spec §3.
# ---------------------------------------------------------------------------

DONUT_ORDER = ["STOCK", "BOND", "DERIVATIVE", "OTHER", "CASH"]


def _load_migration_seed():
    """The classification map that migration 0003 actually applies.

    Imported from the migration itself (not copied) so a typo there fails a test
    rather than silently shipping a wrong donut.
    """
    from importlib import util
    from pathlib import Path

    for parent in Path(__file__).resolve().parents:
        candidate = (
            parent / "database" / "migrations" / "versions" / "0003_asset_classification.py"
        )
        if candidate.exists():
            spec = util.spec_from_file_location("migration_0003", candidate)
            module = util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.ASSET_TYPE_BY_TICKER
    return None


def test_asset_class_breakdown_empty_state(client, seeded):
    breakdown = client.get("/api/v1/portfolio/overview").json()["asset_class_breakdown"]
    # The legend always has five slots in a fixed order, even with nothing held.
    assert [row["asset_class"] for row in breakdown] == DONUT_ORDER
    assert all(row["value_krw"] == 0.0 for row in breakdown)
    assert all(row["weight_pct"] == 0.0 for row in breakdown)
    assert breakdown[-1]["position_count"] is None


def test_asset_class_breakdown(client, seeded, db):
    account, now = _make_account(db, seeded, "ACC-CLASSES")
    holdings = [
        ("SCHD", "STOCK", Decimal("5000000")),
        ("SGOV", "BOND", Decimal("2000000")),
        ("TSL", "DERIVATIVE", Decimal("1000000")),
        ("GLD", "OTHER", Decimal("1000000")),
    ]
    for ticker, asset_type, market_value_krw in holdings:
        asset = Asset(
            country="US",
            market="US",
            ticker=ticker,
            name=ticker,
            asset_type=asset_type,
            currency="USD",
        )
        db.add(asset)
        db.flush()
        db.add(
            CurrentPosition(
                account_id=account.id,
                asset_id=asset.id,
                quantity=Decimal("1"),
                market_value_krw=market_value_krw,
                exchange_rate=Decimal("1484.10"),
                as_of=now,
            )
        )
    db.add(
        AccountBalance(
            account_id=account.id,
            currency="KRW",
            cash_balance=Decimal("1000000"),
            exchange_rate=Decimal("1.0"),
            as_of=now,
        )
    )
    db.commit()

    body = client.get("/api/v1/portfolio/overview").json()
    assert body["summary"]["total_assets_krw"] == 10000000.0

    breakdown = body["asset_class_breakdown"]
    assert [row["asset_class"] for row in breakdown] == DONUT_ORDER
    by_class = {row["asset_class"]: row for row in breakdown}

    assert by_class["STOCK"]["value_krw"] == 5000000.0
    assert by_class["STOCK"]["weight_pct"] == 50.0
    assert by_class["STOCK"]["position_count"] == 1
    assert by_class["BOND"]["value_krw"] == 2000000.0
    assert by_class["BOND"]["weight_pct"] == 20.0
    assert by_class["DERIVATIVE"]["value_krw"] == 1000000.0
    assert by_class["DERIVATIVE"]["weight_pct"] == 10.0
    assert by_class["OTHER"]["value_krw"] == 1000000.0
    # Cash is not a holding, so it carries no position count.
    assert by_class["CASH"]["value_krw"] == 1000000.0
    assert by_class["CASH"]["weight_pct"] == 10.0
    assert by_class["CASH"]["position_count"] is None

    # The donut must account for every won of total assets.
    assert sum(row["value_krw"] for row in breakdown) == body["summary"]["total_assets_krw"]
    assert sum(row["weight_pct"] for row in breakdown) == pytest.approx(100.0)


def test_asset_class_breakdown_unclassified_falls_into_other(client, seeded, db):
    account, now = _make_account(db, seeded, "ACC-UNCLASSIFIED")
    asset = Asset(
        country="KR",
        market="KRX",
        ticker="999999",
        name="미분류",
        asset_type=None,
        currency="KRW",
    )
    db.add(asset)
    db.flush()
    db.add(
        CurrentPosition(
            account_id=account.id,
            asset_id=asset.id,
            quantity=Decimal("1"),
            market_value_krw=Decimal("3000000"),
            exchange_rate=Decimal("1.0"),
            as_of=now,
        )
    )
    db.commit()

    body = client.get("/api/v1/portfolio/overview").json()
    breakdown = body["asset_class_breakdown"]
    by_class = {row["asset_class"]: row for row in breakdown}
    # Unclassified value lands in OTHER instead of vanishing from the donut.
    assert by_class["OTHER"]["value_krw"] == 3000000.0
    assert by_class["OTHER"]["position_count"] == 1
    assert by_class["STOCK"]["value_krw"] == 0.0
    assert sum(row["value_krw"] for row in breakdown) == body["summary"]["total_assets_krw"]


def test_migration_seed_classification_produces_expected_donut(client, seeded, db):
    """The 12 holdings migration 0003 seeds must land as 9 STOCK / 1 BOND /
    1 DERIVATIVE / 1 OTHER (portfolio-detail-spec §2)."""
    seed = _load_migration_seed()
    assert seed is not None, "migration 0003 not found from the test tree"
    assert len(seed) == 12

    account, now = _make_account(db, seeded, "ACC-SEED")
    for ticker, asset_type in seed.items():
        domestic = ticker.isdigit()
        asset = Asset(
            country="KR" if domestic else "US",
            market="KRX" if domestic else "US",
            ticker=ticker,
            name=ticker,
            asset_type=asset_type,
            currency="KRW" if domestic else "USD",
        )
        db.add(asset)
        db.flush()
        db.add(
            CurrentPosition(
                account_id=account.id,
                asset_id=asset.id,
                quantity=Decimal("1"),
                market_value_krw=Decimal("1000000"),
                exchange_rate=Decimal("1.0"),
                as_of=now,
            )
        )
    db.commit()

    breakdown = client.get("/api/v1/portfolio/overview").json()["asset_class_breakdown"]
    counts = {row["asset_class"]: row["position_count"] for row in breakdown}
    assert counts["STOCK"] == 9
    assert counts["BOND"] == 1  # SGOV
    assert counts["DERIVATIVE"] == 1  # TSL
    assert counts["OTHER"] == 1  # GLD
    assert counts["CASH"] is None
