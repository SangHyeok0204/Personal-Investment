"""외부 원천이 죽었을 때 **예외 대신 빈 결과**를 돌려주는지.

★이 대시보드는 외부 API 6곳(야후·토스·FRED·Nasdaq·Epoch·npm)에 의존한다.
  야후가 이미 v7·v10 을 막은 걸 보면 끊기는 건 시간문제다. 한 곳이 죽었을 때
  **화면 전체가 500 으로 죽으면 안 된다** — 그 부분만 비고 나머지는 살아야 한다.

⚠️여기서 검증하는 건 "빈 결과"이지 "0"이 아니다. 0 을 돌려주면 화면이
  "값이 0"이라고 말하게 된다 — 원천이 죽은 것과 값이 0 인 것은 다르다.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices import ai_data, earnings, fred, history, yahoo  # noqa: E402


def dead_transport() -> httpx.MockTransport:
    """모든 요청이 연결 실패하는 전송 계층."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("원천이 죽었다", request=request)

    return httpx.MockTransport(handler)


def error_transport(status: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="nope")

    return httpx.MockTransport(handler)


@pytest.mark.parametrize("transport", [dead_transport(), error_transport(500), error_transport(403)])
def test_yahoo_quotes_degrade_to_empty(transport) -> None:
    src = yahoo.YahooPriceSource(http_client=httpx.Client(transport=transport))
    assert src.quotes(["NVDA", "MSFT"]) == {}


def test_history_degrades_to_empty(monkeypatch) -> None:
    monkeypatch.setattr(history, "BASE", "http://127.0.0.1:9")
    assert history.fetch_series(["^GSPC"], range_="1y") == {}


def test_fred_degrades_to_empty(monkeypatch) -> None:
    monkeypatch.setattr(fred, "BASE", "http://127.0.0.1:9")
    assert fred.fetch_series(["CPIAUCSL"]) == {}


def test_earnings_calendar_degrades_to_empty(monkeypatch) -> None:
    """⚠️빈 목록이어야 한다. 호출부는 이걸 보고 "원천 장애"라고 판단한다 —
    정상이면 60일 구간에 언제나 수천 건이 있다(실측 4,201건)."""
    monkeypatch.setattr(earnings, "BASE", "http://127.0.0.1:9")
    assert earnings.fetch_calendar(date(2026, 9, 22), 14) == []
    assert earnings.fetch_eps_history("NVDA") == []


def test_ai_sources_degrade_independently(monkeypatch) -> None:
    """가속기와 SDK 는 **서로 다른 원천**이다. 한쪽만 죽을 수 있다."""
    monkeypatch.setattr(ai_data, "EPOCH_HARDWARE", "http://127.0.0.1:9")
    assert ai_data.fetch_accelerators() == []

    monkeypatch.setattr(ai_data, "NPM_BASE", "http://127.0.0.1:9")
    assert ai_data.fetch_downloads([("openai", "OpenAI")]) == []


def test_one_dead_symbol_does_not_kill_the_batch() -> None:
    """한 종목이 실패해도 나머지는 살아야 한다 — 대시보드가 통째로 비면 안 된다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "BAD" in str(request.url):
            raise httpx.ConnectError("죽음", request=request)
        return httpx.Response(
            200,
            json={"chart": {"result": [{"meta": {"regularMarketPrice": 10, "currency": "USD"}}]}},
        )

    src = yahoo.YahooPriceSource(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    got = src.quotes(["GOOD", "BAD"])
    assert set(got) == {"GOOD"}
