"""포트폴리오 성격.

여기서 지키려는 것: **비중만 보면 안 보이는 것을 보이게 하되, 없는 것을
지어내지 않는다.**
"""
from decimal import Decimal as D

import pytest

from app.core.portfolio_character import Holding, build, multiplier_from_name

LEV = {"SOXL": ("3", "종목명"), "TSL": ("1.25", "종목명"), "TSLL": ("2", "디렉시온")}


def test_multiplier_reads_decimal_and_integer_from_the_name():
    assert multiplier_from_name("미국 반도체 3배 디렉시온 ETF") == D("3")
    assert multiplier_from_name("테슬라 1.25배 레버리지 그래닛셰어즈 ETF") == D("1.25")


def test_no_multiplier_in_the_name_is_not_one_times():
    """⚠️'배'가 없다고 1배라고 단정하지 않는다 — 안 적었을 뿐일 수 있다."""
    assert multiplier_from_name("금 SPDR ETF") is None
    assert multiplier_from_name(None) is None


def test_effective_exposure_counts_the_multiplier():
    """비중 20% 인 3배 상품은 하루 움직임으로 60% 를 들고 있는 것과 같다."""
    c = build(
        [Holding("SOXL", "미국 반도체 3배 디렉시온 ETF", D("0.2")),
         Holding("NVDA", "엔비디아", D("0.3"))],
        LEV,
    )
    assert c.leveraged_weight == D("0.2")
    # 0.2×3 + 0.3×1 = 0.9
    assert c.effective_exposure == D("0.9")
    assert c.leverage[0].effective_weight == D("0.6")


def test_name_wins_when_the_seed_disagrees_and_we_say_so():
    """⚠️TSL 을 시드에 2배로 잘못 적어 둔 적이 있다(이름은 1.25배).

    조용히 한쪽을 고르면 화면과 시드 중 어느 쪽이 맞는지 알 수 없게 된다 —
    증권사가 준 이름을 믿되 **어긋났다는 사실을 내보낸다.**
    """
    c = build(
        [Holding("TSL", "테슬라 1.25배 레버리지 그래닛셰어즈 ETF", D("0.1"))],
        {"TSL": ("2", "잘못된 시드")},
    )
    line = c.leverage[0]
    assert line.multiplier == D("1.25")
    assert line.disputed is True
    assert "시드는 2배" in line.source


def test_agreeing_sources_are_not_flagged():
    c = build([Holding("SOXL", "미국 반도체 3배 디렉시온 ETF", D("0.2"))], LEV)
    assert c.leverage[0].disputed is False


def test_cash_is_excluded_from_concentration():
    """⚠️현금을 종목처럼 세면 집중도가 낮아 보인다 — 분산된 게 아니다."""
    c = build(
        [Holding("SOXL", None, D("0.5")), Holding("__CASH__", "예수금", D("0.5"))],
        LEV, cash_ticker="__CASH__",
    )
    assert c.cash_weight == D("0.5")
    assert c.top1_ticker == "SOXL"
    # 주식만 놓고 보면 한 종목뿐이다.
    assert c.herfindahl == D("0.25")


def test_effective_count_is_none_when_there_is_nothing():
    """나눌 수 없으면 0 이 아니라 None 이다."""
    c = build([], LEV)
    assert c.effective_count is None
    assert c.top1_ticker is None


def test_effective_count_reads_as_how_many_names_you_really_hold():
    """네 종목 균등이면 유효 종목 수는 4 다."""
    c = build([Holding(t, None, D("0.25")) for t in "ABCD"], {})
    assert c.herfindahl == D("0.25")
    assert c.effective_count == D("4.0")
