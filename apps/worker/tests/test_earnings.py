"""Nasdaq 실적 응답 파싱 규칙 고정."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prices.earnings import _int, _money  # noqa: E402


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1.35", Decimal("1.35")),
        ("$78,960,493,000", Decimal("78960493000")),
        ("1.22", Decimal("1.22")),
        ("($0.42)", Decimal("-0.42")),  # 괄호는 음수 표기다
    ],
)
def test_money_parses_nasdaq_formats(raw: str, expected: Decimal) -> None:
    assert _money(raw) == expected


@pytest.mark.parametrize("raw", ["N/A", "", "  ", "--", None, "abc"])
def test_unreadable_money_is_none_not_zero(raw) -> None:
    """⚠️0 으로 만들면 "EPS 0달러 전망"이라는 틀린 사실이 남는다."""
    assert _money(raw) is None


def test_estimate_count_parses_digits_only() -> None:
    assert _int("8") == 8
    assert _int("1,200") == 1200


@pytest.mark.parametrize("raw", ["N/A", "", None, "-"])
def test_bad_estimate_count_is_none(raw) -> None:
    assert _int(raw) is None


# ── 아직 발표 전인 분기 ──────────────────────────────────────────────────────

import httpx  # noqa: E402

from prices.earnings import fetch_eps_history  # noqa: E402


def eps_client(monkeypatch, rows: list[dict]) -> None:
    """`fetch_eps_history` 가 쓰는 클라이언트를 가짜로 바꾼다.

    ⚠️`monkeypatch` 로 바꾼다. 처음엔 `mod._client = fake` 로 직접 덮었는데,
      그게 **세션 끝까지 남아** 뒤에 오는 test_source_failure 의 '원천 장애'
      테스트가 가짜 200 응답을 받았다. 단독 실행은 통과하고 전체 실행만
      실패해서 원인을 찾기 어려운 종류의 오염이다.
    """
    import prices.earnings as mod

    def fake(timeout: float = 15.0):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"earningsPerShare": rows}})

        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mod, "_client", fake)


def test_upcoming_quarter_has_no_actual(monkeypatch) -> None:
    """⚠️발표 전 분기는 실제 EPS 가 0.0 으로 온다(실측: NVDA Oct 2026).

    그대로 읽으면 "컨센 2.47 vs 실제 0" → 서프라이즈 -2.47 이라는 가짜가 나온다.
    """
    eps_client(
        monkeypatch,
        [
            {"type": "PreviousQuarter", "period": "Jul 2026", "consensus": 2.09, "earnings": 2.22},
            {"type": "UpcomingQuarter", "period": "Oct 2026", "consensus": 2.47, "earnings": 0.0},
        ]
    )
    rows = fetch_eps_history("NVDA")
    past, upcoming = rows[0], rows[1]
    assert past.actual == Decimal("2.22")
    assert past.surprise == Decimal("0.13")
    assert upcoming.actual is None
    assert upcoming.surprise is None


def test_past_quarter_may_legitimately_be_zero(monkeypatch) -> None:
    """값이 아니라 **구분**으로 판정하는 이유 — 과거에 정말 0.00 일 수 있다."""
    eps_client(
        monkeypatch,
        [{"type": "PreviousQuarter", "period": "Jan 2026", "consensus": 0.02, "earnings": 0.0}],
    )
    row = fetch_eps_history("X")[0]
    assert row.actual == Decimal("0")
    assert row.surprise == Decimal("-0.02")
