"""야후 시세 소스 파싱 규칙 고정. 네트워크를 타지 않는다(가짜 클라이언트).

실측에서 걸렸던 함정들을 여기 박아 둔다 — 지우면 조용히 되살아나는 것들이다.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.yahoo import YahooPriceSource  # noqa: E402


def fake_client(payloads: dict[str, dict], status: int = 200) -> httpx.Client:
    """심볼별 응답을 흉내 내는 클라이언트. 없는 심볼은 404 를 돌려준다."""

    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.path.rsplit("/", 1)[-1]
        if symbol not in payloads:
            return httpx.Response(404, json={})
        return httpx.Response(status, json=payloads[symbol])

    return httpx.Client(transport=httpx.MockTransport(handler))


def meta(**kw) -> dict:
    base = {
        "symbol": "AAA",
        "regularMarketPrice": 100.0,
        "currency": "USD",
        "chartPreviousClose": 80.0,
        "regularMarketTime": 1790004182,
    }
    base.update(kw)
    return {"chart": {"result": [{"meta": base}]}}


def test_reads_price_and_previous_close() -> None:
    src = YahooPriceSource(http_client=fake_client({"AAA": meta()}))
    q = src.quotes(["AAA"])["AAA"]
    assert q.price == Decimal("100.0")
    assert q.previous_close == Decimal("80.0")
    assert q.currency == "USD"
    assert q.source == "yahoo"
    assert q.as_of is not None


def test_uses_chart_previous_close_not_previous_close() -> None:
    """⚠️v8 meta 의 `previousClose` 는 None 으로 온다(실측).

    그걸 읽으면 전일종가가 영영 비고, 당일 등락이 통째로 "—" 가 된다.
    정본은 `chartPreviousClose` 다.
    """
    src = YahooPriceSource(
        http_client=fake_client({"AAA": meta(previousClose=None, chartPreviousClose=90.0)})
    )
    q = src.quotes(["AAA"])["AAA"]
    assert q.previous_close == Decimal("90.0")
    assert q.change == Decimal("10.0")
    assert q.change_rate == Decimal("10.0") / Decimal("90.0")


def test_missing_previous_close_does_not_become_zero() -> None:
    """전일종가를 못 받으면 등락은 None 이다. 0 으로 채우면 '보합'처럼 보인다."""
    src = YahooPriceSource(
        http_client=fake_client({"AAA": meta(chartPreviousClose=None)})
    )
    q = src.quotes(["AAA"])["AAA"]
    assert q.previous_close is None
    assert q.change is None
    assert q.change_rate is None


def test_one_bad_symbol_does_not_kill_the_batch() -> None:
    """한 종목이 실패해도 나머지는 살아야 한다 — 대시보드가 통째로 비면 안 된다."""
    src = YahooPriceSource(http_client=fake_client({"AAA": meta(symbol="AAA")}))
    got = src.quotes(["AAA", "NOPE"])
    assert set(got) == {"AAA"}


def test_price_missing_means_symbol_is_dropped() -> None:
    src = YahooPriceSource(
        http_client=fake_client({"AAA": meta(regularMarketPrice=None)})
    )
    assert src.quotes(["AAA"]) == {}


def test_duplicate_symbols_are_requested_once() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json=meta())

    src = YahooPriceSource(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    src.quotes(["AAA", "AAA", "AAA"])
    assert calls == ["AAA"]


def test_empty_input_makes_no_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("빈 입력인데 요청이 나갔다")

    src = YahooPriceSource(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert src.quotes([]) == {}


def test_non_200_is_skipped_not_raised() -> None:
    src = YahooPriceSource(http_client=fake_client({"AAA": meta()}, status=500))
    assert src.quotes(["AAA"]) == {}
