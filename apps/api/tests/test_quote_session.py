"""시세 소스 순서를 정하는 세션 판정.

⚠️토스의 미국 종목 당일 봉은 한국 데이마켓(KST 09:00~16:50) 체결을 포함한다.
  미국장이 닫힌 동안 그건 거래량이 정규장의 1% 미만인 얇은 체결가라 현재가로
  쓰면 안 된다. 그래서 정규장 여부로 소스 우선순위를 바꾼다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.quote_cache import us_regular_session_open

ET = ZoneInfo("America/New_York")


def et(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=ET).astimezone(timezone.utc)


@pytest.mark.parametrize(
    "moment,expected",
    [
        ("2026-09-21T09:29", False),  # 개장 1분 전
        ("2026-09-21T09:30", True),   # 개장
        ("2026-09-21T12:00", True),
        ("2026-09-21T15:59", True),
        ("2026-09-21T16:00", False),  # 종료
        ("2026-09-19T12:00", False),  # 토요일
        ("2026-09-20T12:00", False),  # 일요일
    ],
)
def test_session_boundaries(moment: str, expected: bool) -> None:
    assert us_regular_session_open(et(moment)) is expected


def test_uses_eastern_time_not_local() -> None:
    """KST 자정은 ET 오전 11시 — 정규장 중이다. 로컬 시간으로 판정하면 틀린다."""
    kst_midnight = datetime(2026, 9, 22, 0, 30, tzinfo=ZoneInfo("Asia/Seoul"))
    assert us_regular_session_open(kst_midnight) is True


# ── 세션에 따라 **소스 순서가 실제로 바뀌는지** ──────────────────────────────
#
# 위의 테스트는 "지금이 정규장인가"만 본다. 그 판정이 실제로 소스 순서를 바꾸는지는
# 별개다 — 판정이 맞아도 순서를 안 바꾸면 아무 소용이 없다.

import app.core.quote_cache as qc  # noqa: E402


def _order(monkeypatch, *, session_open: bool, has_toss_keys: bool = True) -> list[str]:
    monkeypatch.setattr(qc, "us_regular_session_open", lambda *a, **k: session_open)
    monkeypatch.setattr(
        qc.credentials_store,
        "read_env_value",
        lambda name: "dummy" if has_toss_keys else None,
    )
    chain = qc._build_source()
    try:
        return [s.name for s in chain._sources]
    finally:
        chain.close()


def test_toss_leads_during_us_regular_session(monkeypatch) -> None:
    """정규장 중에는 사용자가 원한 소스(토스)가 앞이다.

    실측(2026-09-22 정규장): 두 소스가 소수점까지 같았다. 마감 직후에도 같았다.
    그래서 순서를 정하는 기준은 정확도가 아니라 **언제 믿을 수 있는가** 다.
    """
    assert _order(monkeypatch, session_open=True) == ["toss", "yahoo"]


def test_yahoo_leads_when_us_market_is_closed(monkeypatch) -> None:
    """⚠️미국장이 닫힌 동안 토스의 당일 봉은 한국 **데이마켓** 체결을 포함한다.

    토스 일봉은 미국 세션을 13:00 KST 로 라벨링한다(실측). 한국 데이마켓
    (09:00~16:50 KST)이 열리면 그 시각에 **아직 시작도 안 한** 미국 거래일의
    봉이 얇은 체결가로 먼저 생긴다. 그걸 현재가로 쓰면 하루 등락률이 통째로
    틀린다(DailyPriceAgent 실측: NVDA 371,568주 vs 정규장 9,400만주).
    """
    assert _order(monkeypatch, session_open=False) == ["yahoo", "toss"]


def test_toss_is_omitted_without_keys(monkeypatch) -> None:
    """키가 없으면 아예 끼우지 않는다 — 5초마다 실패하는 토큰 발급은 낭비다."""
    assert _order(monkeypatch, session_open=True, has_toss_keys=False) == ["yahoo"]
    assert _order(monkeypatch, session_open=False, has_toss_keys=False) == ["yahoo"]


# ── 한국 데이마켓 판정 ───────────────────────────────────────────────────────
#
# ★2026-09-22 09:02 KST 실측 — 데이마켓 개장 2분 뒤 처음으로 창 안에서 관측했다.
#   토스 당일 봉이 새로 생기고 그 순간부터 야후와 갈린다:
#       NVDA 5,119주 vs 전일 정규장 81,522,377주 (1/15,930)  야후 대비 +0.05%
#       GLW    311주 vs  4,747,667주                        야후 대비 +1.49%
#       SOXL 108,875주 vs 31,658,379주                      야후 대비 +2.58%
#   같은 순간 야후 값은 토스의 **전일 봉 종가와 소수점까지 일치**했다.

from decimal import Decimal  # noqa: E402

from app.core.quote_cache import is_thin_session_quote, kr_daymarket_open  # noqa: E402
from prices import Quote  # noqa: E402

KST = ZoneInfo("Asia/Seoul")


def kst(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=KST).astimezone(timezone.utc)


@pytest.mark.parametrize(
    "moment,expected",
    [
        ("2026-09-22T08:59", False),  # 개장 1분 전
        ("2026-09-22T09:00", True),   # 개장
        ("2026-09-22T09:02", True),   # 실측한 그 순간
        ("2026-09-22T16:49", True),
        ("2026-09-22T16:50", False),  # 종료
        ("2026-09-22T23:30", False),  # 미국 정규장 시간대
        ("2026-09-19T12:00", False),  # 토요일
        ("2026-09-20T12:00", False),  # 일요일
    ],
)
def test_daymarket_boundaries(moment: str, expected: bool) -> None:
    assert kr_daymarket_open(kst(moment)) is expected


def _toss(price: str, volume: str | None = "5119") -> Quote:
    return Quote(
        symbol="NVDA", price=Decimal(price), currency="USD", source="toss",
        volume=Decimal(volume) if volume else None,
    )


def _yahoo(price: str) -> Quote:
    return Quote(symbol="NVDA", price=Decimal(price), currency="USD", source="yahoo")


def test_toss_quote_during_daymarket_is_flagged_thin() -> None:
    """야후가 죽어 사슬이 토스로 넘어가면 **그 사실이 표시돼야** 한다.

    평소엔 순서가 야후를 먼저 쓰므로 오지 않는 상황이다. 그러나 야후가 죽으면
    화면은 5,119주(정규장의 1/15,930)짜리 가격을 아무 표시 없이 "현재가"로
    띄우게 된다. 값을 버리지는 않는다 — 한국 투자자가 실제로 체결할 수 있는
    가격이다. 다만 정규장 가격인 척하게 두지 않는다.
    """
    assert is_thin_session_quote(_toss("227.44"), kst("2026-09-22T09:02")) is True


def test_yahoo_quote_is_never_flagged_even_during_daymarket() -> None:
    """야후는 데이마켓 체결을 담지 않는다 — 전일 정규장 종가를 준다."""
    assert is_thin_session_quote(_yahoo("227.38"), kst("2026-09-22T09:02")) is False


def test_toss_quote_during_us_regular_session_is_not_thin() -> None:
    """정규장 중의 토스 값은 진짜 현재가다(실측 5종목 야후와 0.00% 차이)."""
    # KST 23:30 = ET 10:30, 미국 정규장 한복판.
    assert is_thin_session_quote(_toss("227.44"), kst("2026-09-22T23:30")) is False


def test_toss_quote_outside_both_sessions_is_not_thin() -> None:
    """미국 마감 뒤·데이마켓 전(KST 06:00)엔 토스 당일 봉이 **완료된 정규장**이다.

    실측(KST 06:02): 7종목 전부 야후와 0.00% 차이였다.
    """
    assert is_thin_session_quote(_toss("227.38"), kst("2026-09-22T06:00")) is False
