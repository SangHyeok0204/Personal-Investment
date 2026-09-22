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


# ── 비중(allocation) ─────────────────────────────────────────────────────────

def test_allocation_empty_without_accounts(client):
    body = client.get("/api/v1/portfolio/allocation?dimension=sector").json()
    assert body["items"] == []
    assert body["total_market_value_krw"] is None
    assert body["unclassified_market_value_krw"] is None


def test_allocation_rejects_unknown_dimension(client, kiwoom):
    r = client.get("/api/v1/portfolio/allocation?dimension=주가")
    assert r.status_code == 400
    assert "allowed" in r.json()["error"]["details"]


def test_allocation_by_country_weights_sum_to_one(client, kiwoom):
    """★2026-09-22 사용자 지정: **자산에 예수금을 포함**한다.

    ⚠️분모에만 더하고 조각에서 빼면 비중 합이 100% 가 안 된다 — 현금도
      한 조각으로 넣는다.
    """
    body = client.get("/api/v1/portfolio/allocation?dimension=country").json()
    labels = {i["label"]: i for i in body["items"]}
    # ⚠️예수금 조각은 **key 로 찾는다**. 라벨에는 통화가 붙어("예수금 (KRW)")
    #   라벨로 찾으면 통화가 바뀔 때 조용히 못 찾는다.
    cash = next(i for i in body["items"] if i["key"] == "__CASH__")
    # 국내 800,000 / 미국 1,680,000 / 예수금 500,000 → 합 2,980,000
    assert Decimal(body["total_market_value_krw"]) == Decimal("2980000")
    assert Decimal(cash["market_value_krw"]) == Decimal("500000.00")
    # ★통화를 라벨에 적는다 — "예수금 3.5%" 만 보이면 원화인지 달러인지 모른다.
    assert cash["label"] == "예수금 (KRW)"
    assert Decimal(labels["미국"]["market_value_krw"]) == Decimal("1680000.00")
    assert Decimal(labels["한국"]["market_value_krw"]) == Decimal("800000.00")
    assert sum(Decimal(i["weight"]) for i in body["items"]).quantize(
        Decimal("0.0001")
    ) == Decimal("1.0000")
    # 큰 것부터
    assert body["items"][0]["label"] == "미국"


def test_untracked_holdings_carry_name_and_weight(client, kiwoom):
    """일지를 안 쓴 보유 종목은 **이름과 비중**까지 준다.

    ⚠️티커만 주면 이 화면만 "AAPL" 이라고 적혀 다른 화면과 같은 종목으로
      읽히지 않는다. 그리고 **무엇부터 적어야 하는지**도 알 수 없다 —
      20% 짜리를 안 적은 것과 0.3% 짜리를 안 적은 것은 다르다.

    ⚠️분모는 **주식 평가액**이다(예수금 제외). 여기서 묻는 것은 "안 적은 종목이
      내 주식에서 얼마나 되나"라서 자산 현황의 총자산 기준 비중과는 다르다.
    """
    body = client.get("/api/v1/journal/untracked").json()
    by_ticker = {h["ticker"]: h for h in body}

    # 큰 것부터 — 무엇을 먼저 적어야 하는지가 순서로 드러나야 한다.
    assert [h["ticker"] for h in body] == ["AAPL", "005930"]

    assert by_ticker["AAPL"]["name"] == "Apple"
    # 미국 1,680,000 ÷ 주식 2,480,000 (예수금 500,000 은 분모에 없다)
    assert Decimal(by_ticker["AAPL"]["weight"]) == Decimal("0.677419")
    assert Decimal(by_ticker["005930"]["weight"]) == Decimal("0.322581")
    assert sum(Decimal(h["weight"]) for h in body).quantize(
        Decimal("0.0001")
    ) == Decimal("1.0000")


def test_fx_exposure_counts_foreign_cash(client, db, kiwoom, monkeypatch):
    """**외화 예수금도 환노출이다.** 그리고 분모는 총자산이다.

    ⚠️예전에는 주식만 세서, 달러로 남아 있는 돈이 민감도 표에서 통째로 빠졌다
      (실계좌 실측 $982.92 = ₩1,320,356). 분모도 주식만이라 배분 화면의 통화
      축과 갈렸다.

    ⚠️예수금에는 '얼마에 샀나'가 없다. 그래서 노출·민감도에는 넣되 **평가
      환차손익 추정에는 넣지 않는다** — 없는 매입 환율을 지어내지 않는다.
    """
    from app.models import AccountBalance

    # 이 엔드포인트는 환율 시계열을 받아오는데, 시험에서 바깥을 부르지 않는다.
    monkeypatch.setattr("app.api.portfolio.fetch_history", lambda *a, **k: {})

    body = client.get("/api/v1/portfolio/fx-exposure").json()
    # 외화 주식 1,680,000 ÷ 총자산 2,980,000(주식 2,480,000 + 원화 예수금 500,000)
    assert Decimal(body["exposed_value_krw"]) == Decimal("1680000.00")
    assert Decimal(body["exposure_ratio"]) == Decimal("0.563758")
    assert body["foreign_cash_krw"] is None  # 아직 외화 예수금이 없다

    db.add(AccountBalance(
        id=uuid.uuid4(), account_id=kiwoom["account"].id, currency="USD",
        cash_balance=Decimal("100"), exchange_rate=Decimal("1400"), as_of=NOW,
    ))
    db.commit()

    body = client.get("/api/v1/portfolio/fx-exposure").json()
    assert Decimal(body["foreign_cash_krw"]) == Decimal("140000.00")
    # 노출 1,680,000 + 140,000 = 1,820,000 ÷ 총자산 3,120,000
    assert Decimal(body["exposed_value_krw"]) == Decimal("1820000.00")
    assert Decimal(body["exposure_ratio"]) == Decimal("0.583333")
    # 민감도도 예수금을 포함한 노출액에 붙는다.
    shock = next(s for s in body["shocks"] if Decimal(s["move"]) == Decimal("0.10"))
    assert Decimal(shock["delta_krw"]) == Decimal("182000.00")
    # 평가 환차손익 추정에는 안 들어간다 — 환율 시계열이 없으니 아예 None 이다.
    assert body["unrealized_fx_krw"] is None


def test_allocation_by_currency_folds_cash_into_its_currency(client, db, kiwoom):
    """통화 축에서는 예수금을 **그 통화에 합친다.**

    ⚠️따로 떼어 놓으면 그 축이 재려는 것을 못 재게 된다. 실계좌에서 예수금
      전액이 USD($982.92)인데 화면은 "USD 96.50% · 예수금 3.50%" 라고 적고
      있었다 — 사실은 USD 100% 다. 통화 비중을 보는 사람은 "내 돈의 몇 %가
      달러인가"를 묻는 것이고, 달러 예수금은 그 답에 들어가야 한다.
    """
    from app.models import AccountBalance

    # 환산 가능한 USD 예수금을 하나 더 넣는다(환율이 있어야 합계에 들어간다).
    db.add(AccountBalance(
        id=uuid.uuid4(), account_id=kiwoom["account"].id, currency="USD",
        cash_balance=Decimal("100"), exchange_rate=Decimal("1400"), as_of=NOW,
    ))
    db.commit()

    body = client.get("/api/v1/portfolio/allocation?dimension=currency").json()
    by_key = {i["key"]: i for i in body["items"]}

    # 예수금이 따로 떨어진 조각으로 남아 있으면 안 된다.
    assert "__CASH__" not in by_key

    # USD 주식 1,680,000 + USD 예수금 140,000 = 1,820,000
    assert Decimal(by_key["USD"]["market_value_krw"]) == Decimal("1820000.00")
    # KRW 주식 800,000 + KRW 예수금 500,000 = 1,300,000
    assert Decimal(by_key["KRW"]["market_value_krw"]) == Decimal("1300000.00")
    assert sum(Decimal(i["weight"]) for i in body["items"]).quantize(
        Decimal("0.0001")
    ) == Decimal("1.0000")


def test_allocation_surfaces_unclassified_instead_of_hiding_it(client, kiwoom):
    """섹터가 비어 있으면 숨기지 않고 key=null 조각으로 드러낸다.

    숨기면 비중 합이 100% 로 보여 분류가 끝난 것처럼 착각하게 된다.
    """
    body = client.get("/api/v1/portfolio/allocation?dimension=sector").json()
    # 미분류 한 조각 + 예수금 한 조각.
    assert len(body["items"]) == 2
    only = next(i for i in body["items"] if i["key"] != "__CASH__")
    assert only["key"] is None
    assert only["label"] == "미분류"
    assert Decimal(body["unclassified_market_value_krw"]) == Decimal("2480000.00")


def test_manual_sector_patch_is_marked_manual(client, db, kiwoom):
    from app.models import Asset

    asset_id = kiwoom["samsung"].id
    r = client.patch(
        f"/api/v1/portfolio/assets/{asset_id}/sector",
        json={"sector": "반도체", "industry": "메모리"},
    )
    assert r.status_code == 200
    assert r.json() == {"sector": "반도체", "industry": "메모리"}

    db.expire_all()
    asset = db.get(Asset, asset_id)
    assert asset.sector == "반도체"
    # 사람이 고친 값이라는 표식 — 자동 분류가 덮지 않게 한다.
    assert asset.sector_source == "MANUAL"
    assert asset.classified_at is not None

    body = client.get("/api/v1/portfolio/allocation?dimension=sector").json()
    by_label = {i["label"]: i for i in body["items"]}
    assert Decimal(by_label["반도체"]["market_value_krw"]) == Decimal("800000.00")
    # 나머지는 여전히 미분류로 남아 있어야 한다.
    assert Decimal(body["unclassified_market_value_krw"]) == Decimal("1680000.00")


def test_manual_sector_patch_rejects_unknown_asset(client, kiwoom):
    r = client.patch(
        f"/api/v1/portfolio/assets/{uuid.uuid4()}/sector", json={"sector": "반도체"}
    )
    assert r.status_code == 404


def test_summary_exposes_foreign_cash_that_cannot_be_converted(client, db, kiwoom):
    """환율 없는 외화 예수금은 KRW 합계에서 빠지지만 **사라지지는 않는다**.

    실계좌(2026-09-21)에 USD 예수금 $1,180.81 이 환율 없이 들어 있었다. 합계에만
    의존하면 그 돈이 화면에서 통째로 안 보인다.
    """
    from app.models import AccountBalance

    db.add(AccountBalance(
        id=uuid.uuid4(), account_id=kiwoom["account"].id, currency="USD",
        cash_balance=Decimal("1180.81"), as_of=NOW,
    ))
    db.commit()

    body = client.get("/api/v1/portfolio/summary").json()
    # KRW 합계는 환산 가능한 것만 — 원화 예수금 그대로다.
    assert Decimal(body["cash_krw"]) == Decimal("500000")

    by_ccy = {c["currency"]: c for c in body["cash_by_currency"]}
    assert Decimal(by_ccy["USD"]["cash_balance"]) == Decimal("1180.81")
    # 환율이 없으니 KRW 환산은 null 이다 — 0 이 아니다.
    assert by_ccy["USD"]["krw_value"] is None
    assert Decimal(by_ccy["KRW"]["krw_value"]) == Decimal("500000")


# ── 매매(체결) 내역 ──────────────────────────────────────────────────────────

def _add_trade(db, account_id, **kw):
    from app.models import Trade
    from datetime import date as _date

    defaults = dict(
        id=uuid.uuid4(), account_id=account_id, ticker="SCHD",
        asset_name="미국배당주슈왑ETF", trade_date=_date(2026, 9, 16),
        trade_no="000000001", side="BUY", quantity=Decimal("10"),
        price=Decimal("30.00"), currency="USD", amount_local=Decimal("300.00"),
        settlement_amount_local=Decimal("300.75"),
        commission_local=Decimal("0.75"), tax_local=Decimal("0.00"),
    )
    defaults.update(kw)
    trade = Trade(**defaults)
    db.add(trade)
    db.commit()
    return trade


def test_trades_empty_without_accounts(client):
    body = client.get("/api/v1/portfolio/trades").json()
    assert body == {
        "items": [], "total": 0, "stats": [],
        "first_trade_date": None, "last_trade_date": None,
    }


def test_trades_rejects_unknown_side(client, kiwoom):
    r = client.get("/api/v1/portfolio/trades?side=LONG")
    assert r.status_code == 400
    assert r.json()["error"]["details"]["allowed"] == ["BUY", "SELL"]


def test_trades_listed_newest_first_with_account_name(client, db, kiwoom):
    from datetime import date as _date

    account_id = kiwoom["account"].id
    _add_trade(db, account_id, trade_date=_date(2026, 9, 10), trade_no="000000001")
    _add_trade(db, account_id, trade_date=_date(2026, 9, 16), trade_no="000000002",
               ticker="HUT", asset_name="허트8")

    body = client.get("/api/v1/portfolio/trades").json()
    assert body["total"] == 2
    assert [i["ticker"] for i in body["items"]] == ["HUT", "SCHD"]
    assert body["items"][0]["account_name"] == "키움 주계좌"
    assert body["first_trade_date"] == "2026-09-10"
    assert body["last_trade_date"] == "2026-09-16"


def test_trades_stats_split_by_currency(client, db, kiwoom):
    """USD 거래와 KRW 거래를 한 숫자로 더하지 않는다 — 환산 환율이 없다."""
    from datetime import date as _date

    account_id = kiwoom["account"].id
    _add_trade(db, account_id, trade_no="000000001", side="BUY",
               currency="USD", amount_local=Decimal("300.00"),
               commission_local=Decimal("0.75"))
    _add_trade(db, account_id, trade_no="000000002", side="SELL",
               currency="USD", amount_local=Decimal("500.00"),
               commission_local=Decimal("1.25"), tax_local=Decimal("0.05"))
    _add_trade(db, account_id, trade_no="000000003", side="BUY",
               currency="KRW", ticker="005930", amount_local=Decimal("700000"),
               commission_local=Decimal("105"), tax_local=Decimal("0"))

    body = client.get("/api/v1/portfolio/trades").json()
    stats = {s["currency"]: s for s in body["stats"]}
    assert set(stats) == {"KRW", "USD"}

    usd = stats["USD"]
    assert usd["buy_count"] == 1 and usd["sell_count"] == 1
    assert Decimal(usd["buy_amount"]) == Decimal("300.00")
    assert Decimal(usd["sell_amount"]) == Decimal("500.00")
    assert Decimal(usd["commission"]) == Decimal("2.00")
    assert Decimal(usd["tax"]) == Decimal("0.05")

    krw = stats["KRW"]
    assert krw["buy_count"] == 1 and krw["sell_count"] == 0
    assert Decimal(krw["buy_amount"]) == Decimal("700000")


def test_trades_filter_by_side_and_ticker(client, db, kiwoom):
    account_id = kiwoom["account"].id
    _add_trade(db, account_id, trade_no="000000001", side="BUY", ticker="SCHD")
    _add_trade(db, account_id, trade_no="000000002", side="SELL", ticker="HUT")

    sells = client.get("/api/v1/portfolio/trades?side=SELL").json()
    assert [i["ticker"] for i in sells["items"]] == ["HUT"]

    by_ticker = client.get("/api/v1/portfolio/trades?ticker=schd").json()
    assert [i["ticker"] for i in by_ticker["items"]] == ["SCHD"]


def test_trades_respect_day_window(client, db, kiwoom):
    """days 보다 오래된 체결은 빠진다."""
    from datetime import date as _date, timedelta as _td

    account_id = kiwoom["account"].id
    _add_trade(db, account_id, trade_no="000000001",
               trade_date=_date.today() - _td(days=400))
    _add_trade(db, account_id, trade_no="000000002", trade_date=_date.today())

    year = client.get("/api/v1/portfolio/trades?days=365").json()
    assert year["total"] == 1


def test_window_never_reaches_before_the_investment_start(client, db, kiwoom):
    """★2026-09-22 사용자 지정: 투자 기간은 시작일부터다.

    ⚠️화면에서 '전체'를 눌러도 그 앞은 끌어오지 않는다. 예전에는 days=3000 이면
      전부 나왔다 — 이제는 시작일이 바닥이다.
    """
    from datetime import date as _date, timedelta as _td

    from app.core.investing import INVESTMENT_START

    account_id = kiwoom["account"].id
    _add_trade(db, account_id, trade_no="000000001",
               trade_date=INVESTMENT_START - _td(days=1))
    _add_trade(db, account_id, trade_no="000000002",
               trade_date=INVESTMENT_START + _td(days=1))

    body = client.get("/api/v1/portfolio/trades?days=3000").json()
    assert body["total"] == 1
    assert body["items"][0]["trade_date"] > INVESTMENT_START.isoformat()


def test_trades_carry_sector_when_asset_is_known(client, db, kiwoom):
    """이미 판 종목은 asset 이 없을 수 있다 — 그래도 목록에는 남아야 한다."""
    account_id = kiwoom["account"].id
    _add_trade(db, account_id, trade_no="000000001", ticker="005930",
               asset_id=kiwoom["samsung"].id)
    _add_trade(db, account_id, trade_no="000000002", ticker="QLD",
               asset_name="QQQ2배프로셰어즈ETF", asset_id=None)

    body = client.get("/api/v1/portfolio/trades").json()
    by_ticker = {i["ticker"]: i for i in body["items"]}
    assert set(by_ticker) == {"005930", "QLD"}
    # 마스터가 없는 종목도 이름은 체결 기록 자체에 남아 있다.
    assert by_ticker["QLD"]["asset_name"] == "QQQ2배프로셰어즈ETF"
    assert by_ticker["QLD"]["sector"] is None


# ── 일별 성과 / 실현손익 ─────────────────────────────────────────────────────

def test_performance_empty_without_accounts(client):
    body = client.get("/api/v1/portfolio/performance").json()
    assert body["items"] == []
    assert body["gain_krw"] is None


def test_performance_excludes_deposits_from_gain(client, db, kiwoom):
    """(끝자산 − 시작자산)을 수익이라 부르지 않는다 — 그 사이 입금이 수익으로 보인다."""
    from app.models import AccountDailyPerformance
    from datetime import date as _date, timedelta as _td

    account_id = kiwoom["account"].id
    today = _date.today()
    # 시작 100만 → 끝 300만. 그 사이 150만을 입금했다.
    db.add_all([
        AccountDailyPerformance(
            id=uuid.uuid4(), account_id=account_id, base_date=today - _td(days=2),
            deposit_assets_krw=Decimal("1000000"), deposit_krw=Decimal("1000000"),
        ),
        AccountDailyPerformance(
            id=uuid.uuid4(), account_id=account_id, base_date=today - _td(days=1),
            deposit_assets_krw=Decimal("2600000"), deposit_krw=Decimal("1500000"),
        ),
        AccountDailyPerformance(
            id=uuid.uuid4(), account_id=account_id, base_date=today,
            deposit_assets_krw=Decimal("3000000"),
        ),
    ])
    db.commit()

    body = client.get("/api/v1/portfolio/performance?days=10").json()
    assert len(body["items"]) == 3
    assert Decimal(body["start_assets_krw"]) == Decimal("1000000")
    assert Decimal(body["end_assets_krw"]) == Decimal("3000000")
    # 첫날 입금은 시작 잔고에 이미 반영돼 있으므로 순입금에서 제외된다.
    assert Decimal(body["net_deposit_krw"]) == Decimal("1500000")
    # 3,000,000 − 1,000,000 − 1,500,000 = 500,000 (단순 차액 2,000,000 이 아니다)
    assert Decimal(body["gain_krw"]) == Decimal("500000.00")


def _add_realized(db, account_id, **kw):
    from app.models import RealizedPnl
    from datetime import date as _date

    defaults = dict(
        id=uuid.uuid4(), account_id=account_id, ticker="NVDA", asset_name="엔비디아",
        sell_date=_date(2026, 9, 18), quantity=Decimal("4"), currency="USD",
        pnl_krw=Decimal("50682"), fx_pnl_krw=Decimal("-121201"),
        pnl_rate=Decimal("0.0437"),
    )
    defaults.update(kw)
    row = RealizedPnl(**defaults)
    db.add(row)
    db.commit()
    return row


def test_realized_separates_price_pnl_from_fx_pnl(client, db, kiwoom):
    """주가 손익과 환 손익을 합치지 않는다 — 무엇으로 벌었는지가 사라진다."""
    account_id = kiwoom["account"].id
    _add_realized(db, account_id, ticker="NVDA",
                  pnl_krw=Decimal("50682"), fx_pnl_krw=Decimal("-121201"))
    _add_realized(db, account_id, ticker="SGOV", asset_name="미국초단기국채ETF",
                  pnl_krw=Decimal("-10505"), fx_pnl_krw=Decimal("195692"))

    body = client.get("/api/v1/portfolio/realized?days=3000").json()
    assert body["total"] == 2
    assert Decimal(body["pnl_krw"]) == Decimal("40177")      # 50682 - 10505
    assert Decimal(body["fx_pnl_krw"]) == Decimal("74491")   # -121201 + 195692
    # 승패는 **주가 손익** 기준 — 환차를 섞으면 매매 판단의 성적이 흐려진다.
    assert body["win_count"] == 1
    assert body["loss_count"] == 1


def test_realized_empty_without_accounts(client):
    body = client.get("/api/v1/portfolio/realized").json()
    assert body["total"] == 0
    assert body["pnl_krw"] is None


# ── 배당 ────────────────────────────────────────────────────────────────────

def _add_dividend(db, account_id, **kw):
    from app.models import Dividend
    from datetime import date as _date

    defaults = dict(
        id=uuid.uuid4(), account_id=account_id, ticker="SCHD",
        asset_name="SCHWAB STRATEGIC", pay_date=_date(2026, 6, 30),
        amount_krw=Decimal("31107"), currency="KRW",
    )
    defaults.update(kw)
    row = Dividend(**defaults)
    db.add(row)
    db.commit()
    return row


def test_dividends_empty_without_accounts(client):
    body = client.get("/api/v1/portfolio/dividends").json()
    assert body["total"] == 0
    assert body["total_amount_krw"] is None
    assert body["monthly"] == []


def test_dividends_aggregate_by_month_and_ticker(client, db, kiwoom):
    from datetime import date as _date

    account_id = kiwoom["account"].id
    _add_dividend(db, account_id, ticker="SCHD", pay_date=_date(2026, 6, 30),
                  amount_krw=Decimal("31107"))
    _add_dividend(db, account_id, ticker="SGOV", pay_date=_date(2026, 6, 5),
                  amount_krw=Decimal("39835"))
    _add_dividend(db, account_id, ticker="SGOV", pay_date=_date(2026, 7, 8),
                  amount_krw=Decimal("31601"))

    body = client.get("/api/v1/portfolio/dividends?days=3000").json()
    assert body["total"] == 3
    assert Decimal(body["total_amount_krw"]) == Decimal("102543")

    monthly = {m["month"]: m for m in body["monthly"]}
    # 6월은 두 건이 합쳐져야 한다.
    assert Decimal(monthly["2026-06"]["amount_krw"]) == Decimal("70942")
    assert monthly["2026-06"]["count"] == 2
    assert Decimal(monthly["2026-07"]["amount_krw"]) == Decimal("31601")

    by_ticker = {t["ticker"]: t for t in body["by_ticker"]}
    # 금액 큰 순 — SGOV 가 위
    assert body["by_ticker"][0]["ticker"] == "SGOV"
    assert Decimal(by_ticker["SGOV"]["amount_krw"]) == Decimal("71436")
    assert by_ticker["SGOV"]["count"] == 2


def test_dividends_newest_first_and_carry_sector(client, db, kiwoom):
    from datetime import date as _date

    account_id = kiwoom["account"].id
    # ⚠️날짜는 투자 기간(2026-06-04~) 안이어야 한다 — 그 앞은 조회되지 않는다.
    _add_dividend(db, account_id, ticker="005930", pay_date=_date(2026, 7, 1),
                  asset_id=kiwoom["samsung"].id)
    _add_dividend(db, account_id, ticker="SGOV", pay_date=_date(2026, 8, 7))

    body = client.get("/api/v1/portfolio/dividends?days=3000").json()
    assert [i["ticker"] for i in body["items"]] == ["SGOV", "005930"]
    # 마스터가 없는 종목은 섹터가 비어도 목록에는 남는다.
    assert body["items"][0]["sector"] is None


def test_dividends_respect_day_window(client, db, kiwoom):
    from datetime import date as _date, timedelta as _td

    account_id = kiwoom["account"].id
    _add_dividend(db, account_id, ticker="OLD", pay_date=_date.today() - _td(days=400))
    _add_dividend(db, account_id, ticker="NEW", pay_date=_date.today())

    assert client.get("/api/v1/portfolio/dividends?days=365").json()["total"] == 1
    # ⚠️days 를 늘려도 **투자 기간 앞으로는 가지 않는다**(2026-09-22 규칙 변경).
    assert client.get("/api/v1/portfolio/dividends?days=3000").json()["total"] == 1


# ── 월별 현금흐름 ────────────────────────────────────────────────────────────

def _add_daily(db, account_id, day, **kw):
    from app.models import AccountDailyPerformance

    db.add(AccountDailyPerformance(id=uuid.uuid4(), account_id=account_id, base_date=day, **kw))


def test_monthly_cashflow_empty_without_accounts(client):
    body = client.get("/api/v1/portfolio/monthly-cashflow").json()
    assert body["rows"] == []
    assert body["months_total"] == 0


def test_monthly_cashflow_keeps_the_three_layers_apart(client, db, kiwoom):
    """입금과 배당을 **더하지 않는다** — 입금은 수익이 아니라 위치 이동이다."""
    from datetime import date as _date, timedelta as _td

    account_id = kiwoom["account"].id
    # ⚠️`.replace(day=15)` 는 오늘이 월초면 **미래 날짜**가 된다. 1일로 고정한다.
    today = _date.today().replace(day=1)
    _add_daily(
        db, account_id, today,
        deposit_krw=Decimal("1000000"), withdrawal_krw=Decimal("200000"),
        dividend_krw=Decimal("30000"), commission_tax_krw=Decimal("12000"),
        buy_amount_krw=Decimal("5000000"), sell_amount_krw=Decimal("3000000"),
        pnl_krw=Decimal("40000"), deposit_assets_krw=Decimal("9000000"),
    )
    db.commit()

    body = client.get("/api/v1/portfolio/monthly-cashflow?days=1095").json()
    row = body["rows"][0]
    # 외부 흐름 — 그 자체로 닫힌다.
    assert Decimal(row["net_flow_krw"]) == Decimal("800000")
    # 계좌가 만든 현금 — 배당 − 비용. 입금이 섞이지 않았다.
    assert Decimal(row["net_cash_generated_krw"]) == Decimal("18000")
    # 매매 회전은 합계를 내지 않는다(손익이 아니므로 더할 이유가 없다).
    assert Decimal(row["buy_krw"]) == Decimal("5000000")
    assert Decimal(row["sell_krw"]) == Decimal("3000000")
    # 세 층 어디에도 "1,048,000" 같은 합계가 없다.
    assert Decimal(body["net_cash_generated_krw"]) == Decimal("18000")


def test_monthly_cashflow_first_month_has_no_opening_balance(client, db, kiwoom):
    """첫 달 월초 잔액은 **null 이다.** 0 으로 두면 '무에서 시작했다'는 거짓이 된다."""
    from datetime import date as _date

    account_id = kiwoom["account"].id
    _add_daily(db, account_id, _date.today().replace(day=1),
               deposit_assets_krw=Decimal("5000000"), pnl_krw=Decimal("1000"))
    db.commit()

    row = client.get("/api/v1/portfolio/monthly-cashflow").json()["rows"][0]
    assert row["opening_assets_krw"] is None
    # 월초을 모르면 '그 외'도 계산할 수 없다 — 0 이 아니라 null 이어야 한다.
    assert row["unexplained_krw"] is None


def test_monthly_cashflow_unexplained_is_the_actual_residual(client, db, kiwoom):
    """월말 − 월초 − 순납입 − 손익. 이 값을 환차라고 부르지 않는다(이름 없음)."""
    from datetime import date as _date, timedelta as _td

    account_id = kiwoom["account"].id
    # 1일 ↔ 전월 말일. 미래로 가지 않고 두 달이 반드시 갈린다(dateutil 불필요).
    this_month = _date.today().replace(day=1)
    last_month = this_month - _td(days=1)

    _add_daily(db, account_id, last_month, deposit_assets_krw=Decimal("10000000"))
    _add_daily(db, account_id, this_month,
               deposit_assets_krw=Decimal("12000000"),
               deposit_krw=Decimal("1000000"), pnl_krw=Decimal("500000"))
    db.commit()

    rows = client.get("/api/v1/portfolio/monthly-cashflow").json()["rows"]
    latest = rows[0]
    # 12,000,000 − 10,000,000 − 1,000,000 − 500,000 = 500,000
    assert Decimal(latest["unexplained_krw"]) == Decimal("500000")
    assert Decimal(latest["opening_assets_krw"]) == Decimal("10000000")


def test_monthly_cashflow_does_not_count_an_empty_month_as_covered(client, db, kiwoom):
    """배당 0 · 비용 0 인 달은 '배당이 비용을 덮은 달'이 아니다."""
    from datetime import date as _date

    account_id = kiwoom["account"].id
    _add_daily(db, account_id, _date.today().replace(day=1),
               dividend_krw=Decimal("0"), commission_tax_krw=Decimal("0"),
               deposit_assets_krw=Decimal("1000000"))
    db.commit()

    body = client.get("/api/v1/portfolio/monthly-cashflow").json()
    assert body["months_total"] == 1
    assert body["months_dividend_covered_cost"] == 0


# ── 세금 (해외주식 양도소득) ─────────────────────────────────────────────────

def _add_sale(db, account_id, **kw):
    from app.models import RealizedPnl
    from datetime import date as _date

    defaults = dict(
        id=uuid.uuid4(), account_id=account_id, ticker="NVDA", asset_name="엔비디아",
        sell_date=_date(2026, 9, 18), quantity=Decimal("4"), currency="USD",
        buy_amount_local=Decimal("836.37"), sell_amount_local=Decimal("877.24"),
        commission_tax_local=Decimal("4.30"),
        buy_exchange_rate=Decimal("1524.85"), sell_exchange_rate=Decimal("1380.30"),
        # 증권사가 같은 환율로 환산해 준 값 — **취득가액이 아니다.**
        buy_amount_krw=Decimal("1147793"), sell_amount_krw=Decimal("1203880"),
        pnl_krw=Decimal("50182"), fx_pnl_krw=Decimal("-121201"),
    )
    defaults.update(kw)
    db.add(RealizedPnl(**defaults))
    db.commit()


def test_tax_uses_trade_date_rates_not_the_brokers_common_rate(client, db, kiwoom):
    """취득가액은 **매수일 환율**로 환산한다.

    `buy_amount_krw`(1,147,793)를 쓰면 환율 1,372 로 환산한 값이라 세법상
    취득가액이 아니다. 매수일 환율 1,524.85 를 쓰면 1,275,322 다 — 12만원 차이고,
    이 한 건의 부호가 이익에서 손실로 뒤집힌다.
    """
    _add_sale(db, kiwoom["account"].id)

    body = client.get("/api/v1/portfolio/tax?year=2026").json()
    sale = body["current"]["sales"][0]
    # API 는 원 단위 소수 둘째 자리로 반올림한다.
    cents = Decimal("0.01")
    assert Decimal(sale["cost_basis_krw"]) == (
        Decimal("836.37") * Decimal("1524.85")
    ).quantize(cents)
    assert Decimal(sale["proceeds_krw"]) == (
        Decimal("877.24") * Decimal("1380.30")
    ).quantize(cents)
    # 주가로는 벌었지만(+50,182) 환율 때문에 양도차익은 **손실**이다.
    assert Decimal(sale["gain_krw"]) < 0


def test_tax_includes_fx_in_the_gain(client, db, kiwoom):
    """이 화면에서만 환차를 더한다 — 세법의 양도차익은 원화 기준이기 때문이다."""
    _add_sale(db, kiwoom["account"].id)

    current = client.get("/api/v1/portfolio/tax?year=2026").json()["current"]
    # 증권사 값(주가손익 + 환차손익)과 같은 방향이어야 한다. 주가손익만 봤다면 +다.
    assert Decimal(current["gain_krw_broker"]) == Decimal("50182") + Decimal("-121201")
    assert Decimal(current["gain_krw"]) < 0
    # 두 방식의 차이를 **숨기지 않는다.**
    assert Decimal(current["method_diff_krw"]) == (
        Decimal(current["gain_krw"]) - Decimal(current["gain_krw_broker"])
    )


def test_tax_base_is_never_negative_and_loss_does_not_carry(client, db, kiwoom):
    """손실이면 과세표준은 0 이다. 음수를 다음 해로 넘기지 않는다."""
    _add_sale(db, kiwoom["account"].id)

    current = client.get("/api/v1/portfolio/tax?year=2026").json()["current"]
    assert Decimal(current["gain_krw"]) < 0
    assert Decimal(current["taxable_base_krw"]) == Decimal("0")
    assert Decimal(current["tax_krw"]) == Decimal("0")
    # 공제 여유는 손실만큼 **늘어난다**(250만원보다 크다).
    assert Decimal(current["headroom_krw"]) > Decimal("2500000")


def test_tax_applies_deduction_then_rate(client, db, kiwoom):
    """양도차익 300만 → 과세표준 50만 → 세액 11만(22%)."""
    from datetime import date as _date

    _add_sale(
        db, kiwoom["account"].id, ticker="AVGO", asset_name="브로드컴",
        sell_date=_date(2026, 4, 14),
        buy_amount_local=Decimal("1000"), sell_amount_local=Decimal("4000"),
        commission_tax_local=Decimal("0"),
        buy_exchange_rate=Decimal("1000"), sell_exchange_rate=Decimal("1000"),
        pnl_krw=Decimal("3000000"), fx_pnl_krw=Decimal("0"),
    )

    current = client.get("/api/v1/portfolio/tax?year=2026").json()["current"]
    assert Decimal(current["gain_krw"]) == Decimal("3000000")
    assert Decimal(current["taxable_base_krw"]) == Decimal("500000")
    assert Decimal(current["tax_krw"]) == Decimal("110000")
    # 이미 과세 구간이면 여유는 음수다.
    assert Decimal(current["headroom_krw"]) == Decimal("-500000")


def test_tax_skips_a_sale_without_exchange_rates(client, db, kiwoom):
    """환율이 없으면 그 건은 **뺀다.** 오늘 환율로 메우면 과세표준이 거짓이 된다."""
    _add_sale(db, kiwoom["account"].id, buy_exchange_rate=None)

    current = client.get("/api/v1/portfolio/tax?year=2026").json()["current"]
    assert current["sale_count"] == 0
    assert Decimal(current["gain_krw"]) == Decimal("0")


def test_tax_empty_without_accounts(client):
    body = client.get("/api/v1/portfolio/tax").json()
    assert body["years"] == []
    assert body["current"] is None
    # 한계 문구는 계좌가 없어도 보여야 한다 — 빈 화면이 "세금 없음"으로 읽히면 안 된다.
    assert len(body["notes"]) > 0
