"""투자 기간·자산 정의는 한 곳에서만 정한다."""
from datetime import date

from app.core.investing import INVESTMENT_START, since


def test_window_never_goes_before_the_start():
    """화면에서 '전체'를 눌러도 투자 기간 밖을 끌어오지 않는다."""
    assert since(3650, today=date(2026, 9, 22)) == INVESTMENT_START


def test_shorter_window_is_respected():
    """30일을 물으면 30일이다 — 시작일로 늘려 주지 않는다."""
    assert since(30, today=date(2026, 9, 22)) == date(2026, 8, 23)


def test_no_days_means_the_whole_period():
    assert since(None) == INVESTMENT_START
