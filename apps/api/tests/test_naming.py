"""화면에 적을 종목 이름.

지키려는 것: **같은 종목이 화면마다 다른 이름으로 보이지 않는다.**
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.naming import display_names
from app.models import Account, Asset, Broker, BrokerageConnection, RealizedPnl


@pytest.fixture
def account(db):
    """실현손익은 계좌에 매여 있다 — 최소한의 계좌 하나만 만든다."""
    # id 를 명시한다 — `default=uuid.uuid4` 는 flush 때 채워져 FK 로 못 쓴다.
    broker_id, conn_id = uuid.uuid4(), uuid.uuid4()
    broker = Broker(id=broker_id, code="KIWOOM", name="키움증권")
    conn = BrokerageConnection(
        id=conn_id, broker_id=broker_id, connection_name="주계좌",
        environment="REAL", status="CONNECTED",
    )
    acc = Account(
        id=uuid.uuid4(), broker_id=broker_id, brokerage_connection_id=conn_id,
        external_account_id="0000", account_number_masked="0000-**",
        account_name="시험 계좌", base_currency="KRW", is_active=True,
    )
    db.add(broker)
    db.flush()
    db.add(conn)
    db.flush()
    db.add(acc)
    db.flush()
    return acc


def _sold(account, ticker: str, name: str | None) -> RealizedPnl:
    return RealizedPnl(
        id=uuid.uuid4(), account_id=account.id, ticker=ticker, asset_name=name,
        sell_date=date(2026, 9, 11), currency="USD",
        quantity=Decimal("1"), pnl_krw=Decimal("0"),
    )


def _held(ticker: str, name: str | None) -> Asset:
    return Asset(
        id=uuid.uuid4(), country="US", market="NASDAQ", ticker=ticker,
        name=name, asset_type="STOCK", currency="USD",
    )


def test_asset_name_wins_over_realized(db, account):
    """보유 중인 종목은 **잔고 TR 이름**이 최신이다 — 실현손익 이름으로 덮지 않는다.

    (일부만 팔고 남긴 종목은 양쪽에 다 있다.)
    """
    db.add(_held("BE", "블룸 에너지"))
    db.add(_sold(account, "BE", "옛날 이름"))
    db.commit()

    assert display_names(db, ["BE"]) == {"BE": "블룸 에너지"}


def test_realized_covers_sold_tickers(db, account):
    """**이미 판 종목은 자산 표에 없다.** 그때는 실현손익 표에서 이름을 가져온다.

    ⚠️실측: 매매한 25종목 중 8종목(AVGO·MNST·QCOM·QLD·SGOV·SKHY·SNDK·TSLL)이
      자산 표에 없다. 체결 원장 이름만 쓰면 이 8종목만 띄어쓰기 없이 찍힌다
      ("미국초단기국채아이셰어즈ETF" vs "미국 초단기 국채 아이셰어즈 ETF").
    """
    db.add(_sold(account, "SGOV", "미국 초단기 국채 아이셰어즈 ETF"))
    db.commit()

    assert display_names(db, ["SGOV"]) == {"SGOV": "미국 초단기 국채 아이셰어즈 ETF"}


def test_unknown_ticker_is_absent_not_invented(db):
    """어디에도 없으면 **빠진다.** 호출한 쪽이 원장 이름으로 떨어질 수 있어야 한다."""
    assert display_names(db, ["NOSUCH"]) == {}
    assert display_names(db, []) == {}
    assert display_names(db, [None, ""]) == {}


def test_blank_names_are_not_returned(db, account):
    """빈 이름을 돌려주면 화면이 이름 칸을 비운다 — 티커라도 찍히는 편이 낫다."""
    db.add(_held("BLANK", None))
    db.add(_sold(account, "ALSOBLANK", None))
    db.commit()

    names = display_names(db, ["BLANK", "ALSOBLANK"])
    assert names == {}
