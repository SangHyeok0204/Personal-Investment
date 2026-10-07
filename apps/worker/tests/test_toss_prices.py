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


# ── 토큰 단계 실패는 종목별로 삼키지 않는다(2026-10-05) ─────────────────────────
#
# ★2026-10-05 23:40 KST 실측: 맥의 공인 IP 가 바뀌어 토큰 발급이 403(IP 미허용).
#   종목별 `except Exception: continue` 가 그걸 삼켜 16종목이면 토큰을 16번 두드리고
#   빈 dict 를 돌려줬다 — 호출부는 조용히 야후로 넘어갔다.

import pytest  # noqa: E402

from prices import CompositePriceSource, PriceSource, Quote  # noqa: E402
from prices.toss import TossAuthError, TossIpNotAllowed  # noqa: E402


def _blocked_source(token_calls: list, status: int = 403, body: str = '{"error":"access_denied","error_description":"IP address not allowed"}'):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            token_calls.append(1)
            return httpx.Response(status, text=body)
        return httpx.Response(200, json={"result": {"candles": [bar("1")]}})

    return TossPriceSource(
        "id", "secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        min_interval=0.0, sleep=lambda _: None,
    )


def test_ip_block_raises_once_for_the_whole_call() -> None:
    token_calls: list = []
    src = _blocked_source(token_calls)
    with pytest.raises(TossIpNotAllowed):
        src.quotes([f"S{i}" for i in range(16)])
    assert len(token_calls) == 1  # 16종목이어도 토큰 시도는 한 번


def test_other_token_failure_also_fails_fast() -> None:
    token_calls: list = []
    src = _blocked_source(token_calls, status=400, body='{"error":"invalid_client"}')
    with pytest.raises(TossAuthError):
        src.quotes(["AAA", "BBB", "CCC"])
    assert len(token_calls) == 1


def test_symbol_level_error_is_still_tolerated() -> None:
    """한 티커의 404 는 그 종목만 빠진다 — 나머지는 산다."""
    src = source({"AAA": [bar("100")]})  # BBB 는 404
    got = src.quotes(["BBB", "AAA"])
    assert set(got) == {"AAA"}


class _Raising(PriceSource):
    name = "toss"

    def quotes(self, symbols):
        raise TossIpNotAllowed("blocked")


class _Fixed(PriceSource):
    name = "yahoo"

    def quotes(self, symbols):
        return {s: Quote(symbol=s, price=Decimal("1"), source="yahoo") for s in symbols}


def test_composite_remembers_why_a_source_failed() -> None:
    chain = CompositePriceSource([_Raising(), _Fixed()])
    got = chain.quotes(["AAA"])
    assert got["AAA"].source == "yahoo"                       # 폴백은 그대로
    assert isinstance(chain.last_errors["toss"], TossIpNotAllowed)  # 이유는 남는다
    assert chain.attempted == ["toss", "yahoo"]
    assert "yahoo" not in chain.last_errors


def test_many_symbols_are_fetched_concurrently_with_one_token() -> None:
    """★2026-10-07 관심종목 51개 첫 조회 15.7초 → 동시 요청. 모든 종목이 빠짐없이, 토큰은 한 번만."""
    tokens = []
    syms = [f"S{i}" for i in range(30)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            tokens.append(1)
            return httpx.Response(200, json=TOKEN)
        sym = request.url.params.get("symbol")
        return httpx.Response(200, json={"result": {"candles": [bar("10"), bar("9")]}}) if sym != "S7" \
            else httpx.Response(404, json={})

    src = TossPriceSource("id", "secret", http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                          min_interval=0.0, sleep=lambda _: None)
    got = src.quotes(syms)
    assert set(got) == set(syms) - {"S7"} and len(tokens) == 1
