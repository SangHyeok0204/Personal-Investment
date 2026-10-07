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


def test_toss_leads_even_when_us_market_is_closed(monkeypatch) -> None:
    """⚠️미국장이 닫힌 동안 토스의 당일 봉은 한국 **데이마켓** 체결을 포함한다.

    토스 일봉은 미국 세션을 13:00 KST 로 라벨링한다(실측). 한국 데이마켓
    (09:00~16:50 KST)이 열리면 그 시각에 **아직 시작도 안 한** 미국 거래일의
    봉이 얇은 체결가로 먼저 생긴다. 그걸 현재가로 쓰면 하루 등락률이 통째로
    틀린다(DailyPriceAgent 실측: NVDA 371,568주 vs 정규장 9,400만주).
    """
    # ★2026-10-07 사용자 결정: 그래도 데이·프리장 동안 토스를 쓴다 — 값에는 '데이' 표시(thin_session)가 붙는다.
    assert _order(monkeypatch, session_open=False) == ["toss", "yahoo"]


def test_toss_is_omitted_without_keys(monkeypatch) -> None:
    """키가 없으면 아예 끼우지 않는다 — 5초마다 실패하는 토큰 발급은 낭비다."""
    assert _order(monkeypatch, session_open=True, has_toss_keys=False) == ["yahoo"]
    assert _order(monkeypatch, session_open=False, has_toss_keys=False) == ["yahoo"]


# ── 정규장을 거치지 않은 봉 판정 ────────────────────────────────────────────
#
# ⚠️처음엔 한국 데이마켓 시간(09:00~16:50)을 하드코딩했다. **틀렸다** —
#   17:53 KST 에도 봉이 자라고 있었다(SOXL 거래량 614,032 → 1,355,817).
#   게다가 그 창을 박을 때 참고한 측정 시각 자체가 틀렸다: 기계 시계가 8시간
#   40분 어긋나 있어서 17:22 에 한 측정을 09:02 로 적었다(구글 HTTP Date
#   헤더로 확인). 잘못된 시계 위에 시간표를 박으면 이렇게 된다.
#
# ★그래서 시간표를 쓰지 않는다. 토스가 주는 **봉 날짜**로 판단한다:
#     봉 날짜의 미국 정규장이 이미 끝났으면 → 정상 종가
#     아직 안 끝났고 지금 정규장도 아니면   → 정규장을 거치지 않은 봉
#   주말·공휴일은 저절로 처리된다(그런 날엔 새 봉이 생기지 않는다).
#
# ★2026-09-22 실측 세 번 — 거래량이 12배 붙는 동안 괴리의 **부호가 뒤집혔다**:
#     KST 17:22  NVDA +0.05%  SOXL +2.58%  (SOXL 거래량   108,875)
#     KST 17:52  NVDA +0.15%  SOXL +3.50%  (            614,032)
#     KST 17:53  NVDA -0.26%  SOXL -2.12%  (          1,355,817)
#   살아 움직이는 시장이지 잡음이 아니다. 그래서 값을 버리지 않고 표시만 한다.

from datetime import date as _date  # noqa: E402
from decimal import Decimal  # noqa: E402

from app.core.quote_cache import is_thin_session_quote  # noqa: E402
from prices import Quote  # noqa: E402


def _toss(trade_date, volume: str | None = "5119") -> Quote:
    return Quote(
        symbol="NVDA", price=Decimal("227.44"), currency="USD", source="toss",
        volume=Decimal(volume) if volume else None, trade_date=trade_date,
    )


@pytest.mark.parametrize(
    "moment,bar,expected,why",
    [
        # 한국 데이마켓 — 미국 정규장 전. 이 봉은 아직 정규장을 거치지 않았다.
        ("2026-09-22T04:53", _date(2026, 9, 22), True, "한국 데이마켓"),
        # 미국 프리마켓도 마찬가지다.
        ("2026-09-22T08:00", _date(2026, 9, 22), True, "프리마켓"),
        # ⚠️정규장 중에는 토스 봉이 **진행 중인 그 정규장**이다 — 진짜 현재가다.
        #   봉 날짜만 보고 판단하면 이걸 thin 으로 잡는다(실제로 한 번 그랬다).
        ("2026-09-22T11:00", _date(2026, 9, 22), False, "정규장 중"),
        # 마감 후에는 그 봉이 완료된 세션이다(실측 KST 06:02, 7종목 0.00% 차이).
        ("2026-09-22T17:00", _date(2026, 9, 22), False, "마감 후 당일 봉"),
        # 전일 봉은 언제 봐도 완료된 세션이다.
        ("2026-09-22T04:53", _date(2026, 9, 21), False, "전일 봉"),
    ],
)
def test_thin_session_uses_the_bar_date_not_a_hardcoded_schedule(
    moment: str, bar, expected: bool, why: str
) -> None:
    assert is_thin_session_quote(_toss(bar), et(moment)) is expected, why


def test_yahoo_is_never_flagged() -> None:
    """야후는 데이마켓 체결을 담지 않는다 — 전일 정규장 종가를 준다."""
    quote = Quote(
        symbol="NVDA", price=Decimal("227.38"), currency="USD", source="yahoo",
        trade_date=_date(2026, 9, 22),
    )
    assert is_thin_session_quote(quote, et("2026-09-22T04:53")) is False


def test_missing_bar_date_does_not_invent_a_warning() -> None:
    """봉 날짜를 모르면 표시하지 않는다 — 없는 경고를 만들지 않는다."""
    assert is_thin_session_quote(_toss(None), et("2026-09-22T04:53")) is False


def test_us_session_dates_from_gspc_drop_unfinished_bar(monkeypatch) -> None:
    """★2026-10-04: 공휴일 파일 없이 ^GSPC 일봉으로 '끝난 미국 정규장' 날짜를 읽는다.
    진행 중인 오늘 봉은 빼고, 못 받으면 None(호출한 쪽이 live 로 둔다)."""
    from datetime import date
    from decimal import Decimal

    from app.core import quote_cache
    from prices.history import Series

    days = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)]
    spx = Series(symbol="^GSPC", dates=days, closes=[Decimal("1")] * 3,
                 currency="USD", latest=Decimal("1"))
    quote_cache.clear_cache()
    monkeypatch.setattr(quote_cache, "fetch_history", lambda *a, **k: {"^GSPC": spx})
    # 10-05(월) 장중 — 그날 봉은 아직 끝나지 않았다.
    assert quote_cache.us_session_dates(et("2026-10-05T12:00")) == days[:2]
    assert quote_cache.us_session_dates(et("2026-10-05T16:00")) == days

    quote_cache.clear_cache()

    def boom(*a, **k):
        raise RuntimeError("network")

    monkeypatch.setattr(quote_cache, "fetch_history", boom)
    assert quote_cache.us_session_dates() is None
    quote_cache.clear_cache()
