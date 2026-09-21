"""포트폴리오 읽기 API.

여기서 지키려는 불변식은 두 가지다.
  1) 계좌가 없을 때 **0 이 아니라 null** 을 내보낸다. 0원과 미연동은 다른 상태다.
  2) 합계는 DB 에 적재된 KRW 환산값을 더하고, 환산할 수 없는 값은 합계에서 뺀다.
     (0 으로 세면 수익률이 부풀려진다.)
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import (
    Account,
    AccountBalance,
    Asset,
    Broker,
    BrokerageConnection,
    CurrentPosition,
    PortfolioSnapshot,
)

NOW = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)


@pytest.fixture()
def kiwoom(db):
    """키움 주계좌 하나 — 국내 1종목(원화) + 미국 1종목(달러)."""
    # id 를 명시한다 — `default=uuid.uuid4` 는 flush 시점에 채워지므로, 생성 직후의
    # `broker.id` 는 아직 None 이라 FK 로 못 쓴다.
    broker_id, conn_id = uuid.uuid4(), uuid.uuid4()
    broker = Broker(id=broker_id, code="KIWOOM", name="키움증권")
    conn = BrokerageConnection(
        id=conn_id,
        broker_id=broker_id,
        connection_name="주계좌",
        environment="REAL",
        status="CONNECTED",
        last_synced_at=NOW,
    )
    account = Account(
        id=uuid.uuid4(),
        broker_id=broker_id,
        brokerage_connection_id=conn_id,
        external_account_id="1234567890",
        account_number_masked="12345678-**",
        account_name="키움 주계좌",
        account_type="STOCK",
        base_currency="KRW",
        is_active=True,
        last_synced_at=NOW,
    )
    samsung = Asset(
        id=uuid.uuid4(),
        country="KR", market="KOSPI", ticker="005930", name="삼성전자",
        asset_type="STOCK", currency="KRW",
    )
    apple = Asset(
        id=uuid.uuid4(),
        country="US", market="NASDAQ", ticker="AAPL", name="Apple",
        asset_type="STOCK", currency="USD",
    )
    # 의존 순서대로 나눠 flush 한다 — relationship() 을 안 건 매핑이라 SQLAlchemy 가
    # 한 번의 add_all 로는 삽입 순서를 FK 순서로 정렬해 주지 않는다.
    db.add(broker)
    db.flush()
    db.add(conn)
    db.flush()
    db.add_all([account, samsung, apple])
    db.flush()

    db.add_all([
        # 국내: 매입 700,000 / 평가 800,000 → +100,000
        CurrentPosition(
            id=uuid.uuid4(),
            account_id=account.id, asset_id=samsung.id,
            quantity=Decimal("10"), average_purchase_price=Decimal("70000"),
            purchase_amount_local=Decimal("700000"),
            current_price=Decimal("80000"),
            market_value_local=Decimal("800000"),
            market_value_krw=Decimal("800000"),
            unrealized_pnl_local=Decimal("100000"),
            unrealized_pnl_krw=Decimal("100000"),
            unrealized_return=Decimal("0.1429"),
            as_of=NOW,
        ),
        # 미국: 매입 $1,000 @1,400 = 1,400,000 / 평가 $1,200 @1,400 = 1,680,000
        CurrentPosition(
            id=uuid.uuid4(),
            account_id=account.id, asset_id=apple.id,
            quantity=Decimal("5"), average_purchase_price=Decimal("200"),
            purchase_amount_local=Decimal("1000"),
            current_price=Decimal("240"),
            market_value_local=Decimal("1200"),
            exchange_rate=Decimal("1400"),
            market_value_krw=Decimal("1680000"),
            unrealized_pnl_local=Decimal("200"),
            unrealized_pnl_krw=Decimal("280000"),
            unrealized_return=Decimal("0.2000"),
            as_of=NOW,
        ),
        AccountBalance(
            id=uuid.uuid4(),
            account_id=account.id, currency="KRW",
            cash_balance=Decimal("500000"), available_cash=Decimal("450000"),
            as_of=NOW,
        ),
    ])
    db.commit()
    return {"account": account, "samsung": samsung, "apple": apple}


def test_accounts_empty_reports_not_connected(client):
    body = client.get("/api/v1/portfolio/accounts").json()
    assert body == {"items": [], "connected": False}


def test_summary_without_accounts_returns_nulls_not_zeros(client):
    """0원과 미연동은 다른 상태다 — 합계는 null 이어야 한다."""
    body = client.get("/api/v1/portfolio/summary").json()
    assert body["account_count"] == 0
    assert body["total_assets_krw"] is None
    assert body["cash_krw"] is None
    assert body["unrealized_return"] is None


def test_accounts_listed_once_connected(client, kiwoom):
    body = client.get("/api/v1/portfolio/accounts").json()
    assert body["connected"] is True
    assert len(body["items"]) == 1
    assert body["items"][0]["broker_code"] == "KIWOOM"
    assert body["items"][0]["account_name"] == "키움 주계좌"
    # 계좌번호는 마스킹된 것만 나간다.
    assert body["items"][0]["account_number_masked"] == "12345678-**"


def test_summary_sums_krw_values(client, kiwoom):
    body = client.get("/api/v1/portfolio/summary").json()

    # 평가액 = 800,000(국내) + 1,680,000(미국)
    assert Decimal(body["securities_value_krw"]) == Decimal("2480000")
    # 예수금 500,000 → 총자산 2,980,000
    assert Decimal(body["cash_krw"]) == Decimal("500000")
    assert Decimal(body["available_cash_krw"]) == Decimal("450000")
    assert Decimal(body["total_assets_krw"]) == Decimal("2980000")
    # 매입원가 = 700,000 + ($1,000 × 1,400) = 2,100,000
    assert Decimal(body["purchase_amount_krw"]) == Decimal("2100000")
    # 평가손익 = 100,000 + 280,000 = 380,000
    assert Decimal(body["unrealized_pnl_krw"]) == Decimal("380000")
    # 수익률 = 380,000 / 2,100,000
    assert Decimal(body["unrealized_return"]).quantize(Decimal("0.0001")) == Decimal("0.1810")
    assert body["position_count"] == 2
    assert body["account_count"] == 1


def test_summary_quantizes_money_and_ratio(client, kiwoom):
    """Decimal 곱셈의 자릿수가 그대로 JSON 에 실리지 않게 고정한다.

    고정하지 않으면 매입원가가 "2100000.0000" 처럼 나가고, 수익률은
    "0.1809523809523809523809523810" 같은 28자리가 그대로 실린다.
    """
    body = client.get("/api/v1/portfolio/summary").json()
    assert body["purchase_amount_krw"] == "2100000.00"
    assert body["total_assets_krw"] == "2980000.00"
    assert body["unrealized_return"] == "0.180952"


def test_summary_excludes_unconvertible_purchase_amount(client, db, kiwoom):
    """외화 종목에 환율이 없으면 매입원가 합계에서 빠진다 — 0 으로 세지 않는다."""
    position = db.query(CurrentPosition).filter(
        CurrentPosition.asset_id == kiwoom["apple"].id
    ).one()
    position.exchange_rate = None
    db.commit()

    body = client.get("/api/v1/portfolio/summary").json()
    # 국내 700,000 만 남는다 (미국분 1,400,000 은 환산 불가라 제외).
    assert Decimal(body["purchase_amount_krw"]) == Decimal("700000")


def test_holdings_sorted_by_market_value_desc(client, kiwoom):
    body = client.get("/api/v1/portfolio/holdings").json()
    tickers = [i["ticker"] for i in body["items"]]
    # 미국(1,680,000) > 국내(800,000)
    assert tickers == ["AAPL", "005930"]
    assert Decimal(body["total_market_value_krw"]) == Decimal("2480000")
    assert body["items"][0]["currency"] == "USD"
    assert body["items"][0]["account_name"] == "키움 주계좌"


def test_holdings_filtered_by_account(client, db, kiwoom):
    other = uuid.uuid4()
    body = client.get(f"/api/v1/portfolio/holdings?account_id={other}").json()
    assert body["items"] == []
    assert body["total_market_value_krw"] is None


def test_history_collapses_to_one_point_per_day(client, db, kiwoom):
    """같은 날 여러 번 동기화해도 그날의 마지막 스냅샷 하나만 쓴다."""
    account_id = kiwoom["account"].id
    db.add_all([
        PortfolioSnapshot(
            id=uuid.uuid4(),
            account_id=account_id, snapshot_at=NOW - timedelta(days=1),
            total_assets_krw=Decimal("2000000"),
            securities_value_krw=Decimal("1500000"),
            cash_value_krw=Decimal("500000"),
        ),
        # 같은 날 이른 스냅샷 — 뒤의 것에 밀려야 한다.
        PortfolioSnapshot(
            id=uuid.uuid4(),
            account_id=account_id, snapshot_at=NOW - timedelta(hours=5),
            total_assets_krw=Decimal("2900000"),
            securities_value_krw=Decimal("2400000"),
            cash_value_krw=Decimal("500000"),
        ),
        PortfolioSnapshot(
            id=uuid.uuid4(),
            account_id=account_id, snapshot_at=NOW - timedelta(hours=1),
            total_assets_krw=Decimal("2980000"),
            securities_value_krw=Decimal("2480000"),
            cash_value_krw=Decimal("500000"),
        ),
    ])
    db.commit()

    body = client.get("/api/v1/portfolio/history?days=30").json()
    assert len(body["items"]) == 2
    assert Decimal(body["items"][-1]["total_assets_krw"]) == Decimal("2980000")


def test_connections_expose_status_and_error(client, kiwoom):
    body = client.get("/api/v1/portfolio/connections").json()
    assert len(body) == 1
    assert body[0]["broker_name"] == "키움증권"
    assert body[0]["status"] == "CONNECTED"
    assert body[0]["last_error"] is None
