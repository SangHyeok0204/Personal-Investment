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
