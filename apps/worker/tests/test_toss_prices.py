"""토스 시세 파싱 규칙 고정. 네트워크를 타지 않는다.

이식본이 실제로 틀렸던 지점들을 박아 둔다 — 전부 2026-09-22 실측으로 드러났다.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.toss import TossPriceSource  # noqa: E402

TOKEN = {"access_token": "t", "expires_in": 3600}


def source(candles_by_symbol: dict[str, list[dict]], record: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json=TOKEN)
        symbol = request.url.params.get("symbol")
        if record is not None:
            record.append((request.url.path, symbol))
        bars = candles_by_symbol.get(symbol)
        if bars is None:
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"result": {"candles": bars}})

    return TossPriceSource(
        "id", "secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_interval=0.0,
        sleep=lambda _: None,
    )


def bar(close: str, currency: str = "USD") -> dict:
    return {"closePrice": close, "volume": "1000", "currency": currency}


def test_reads_price_from_candles_not_stocks() -> None:
    """⚠️`/api/v1/stocks` 에는 **가격이 없다**(종목명·ISIN·통화 같은 기본정보뿐).

    이식본이 거기서 close 를 찾느라 늘 빈 결과를 냈다. 가격은 candles 에 있다.
    """
    calls: list = []
    src = source({"AAA": [bar("100"), bar("90")]}, record=calls)
    got = src.quotes(["AAA"])
    assert got["AAA"].price == Decimal("100")
    assert all(path.endswith("/candles") for path, _ in calls)


def test_candles_are_newest_first() -> None:
    """⚠️봉은 최신순이다. [0]=오늘, [1]=전일.

    오름차순으로 착각하면 현재가와 전일종가가 뒤바뀌어 등락 부호까지 반대가 된다.
    """
    src = source({"AAA": [bar("110"), bar("100")]})
    q = src.quotes(["AAA"])["AAA"]
    assert q.price == Decimal("110")
    assert q.previous_close == Decimal("100")
    assert q.change == Decimal("10")


def test_single_candle_has_no_previous_close() -> None:
    """전일 봉이 없으면 등락은 None 이다. 0 으로 채우면 '보합'으로 보인다."""
    src = source({"AAA": [bar("100")]})
    q = src.quotes(["AAA"])["AAA"]
    assert q.previous_close is None
    assert q.change_rate is None


def test_currency_comes_from_the_candle() -> None:
    """미국 종목은 USD 다. KRW 로 굳혀 두면 원화로 오인된다."""
    src = source({"AAA": [bar("100", "USD")], "BBB": [bar("70000", "KRW")]})
    got = src.quotes(["AAA", "BBB"])
    assert got["AAA"].currency == "USD"
    assert got["BBB"].currency == "KRW"


def test_one_failing_symbol_does_not_kill_the_batch() -> None:
    src = source({"AAA": [bar("100")]})
    got = src.quotes(["AAA", "NOPE"])
    assert set(got) == {"AAA"}


def test_empty_candles_are_skipped() -> None:
    src = source({"AAA": []})
    assert src.quotes(["AAA"]) == {}


def test_duplicate_symbols_are_requested_once() -> None:
    calls: list = []
    src = source({"AAA": [bar("100")]}, record=calls)
    src.quotes(["AAA", "AAA"])
    assert [sym for _, sym in calls] == ["AAA"]


def test_us_markets_are_declared() -> None:
    """실측: AAPL → market=NASDAQ, currency=USD. 이식 당시 KRX 만 적혀 있었다."""
    assert "NASDAQ" in TossPriceSource.markets
    assert "KOSPI" in TossPriceSource.markets
