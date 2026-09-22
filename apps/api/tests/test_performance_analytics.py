"""성과지표 계산 검증.

손으로 답을 낼 수 있는 작은 시계열만 쓴다 — 실데이터로 테스트하면 "계산은
돌아간다"만 확인되고 **값이 맞는지**는 확인되지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.performance_analytics import (
    DailyPoint,
    annualized_return,
    base_index,
    cumulative_return,
    daily_returns,
    hit_ratio,
    max_drawdown,
    monthly_returns,
    sharpe,
    volatility,
    window,
)


def pt(day: int, assets: str | None, dep: str = "0", wd: str = "0") -> DailyPoint:
    return DailyPoint(
        base_date=date(2026, 1, 1) + timedelta(days=day - 1),
        assets_krw=None if assets is None else Decimal(assets),
        deposit_krw=Decimal(dep),
        withdrawal_krw=Decimal(wd),
    )


def test_first_day_has_no_return() -> None:
    """첫날은 '이전 잔고'가 없으므로 수익률을 만들지 않는다."""
    rs = daily_returns([pt(1, "100"), pt(2, "110")])
    assert [r.base_date.day for r in rs] == [2]
    assert rs[0].ret == Decimal("0.1")


def test_deposit_is_not_profit() -> None:
    """100 에서 50 을 입금해 150 이 됐으면 수익률은 0% 다.

    이걸 빼먹으면 입금이 그대로 '수익'으로 잡힌다 — 이 프로젝트에서 가장
    틀리기 쉬운 지점이라 따로 못박아 둔다.
    """
    rs = daily_returns([pt(1, "100"), pt(2, "150", dep="50")])
    assert rs[0].ret == Decimal("0")


def test_withdrawal_is_not_loss() -> None:
    rs = daily_returns([pt(1, "100"), pt(2, "60", wd="40")])
    assert rs[0].ret == Decimal("0")


def test_gap_day_does_not_merge_two_days() -> None:
    """값이 빈 날은 건너뛰되, **직전 실측값**을 기준으로 다음 수익률을 낸다."""
    rs = daily_returns([pt(1, "100"), pt(2, None), pt(3, "110")])
    assert len(rs) == 1
    assert rs[0].ret == Decimal("0.1")  # 100 → 110, 빈 날을 0% 로 끼우지 않는다.


def test_zero_balance_day_yields_no_return() -> None:
    """잔고가 0 이던 날 다음은 나눗셈이 불가능하다 — 조용히 0% 로 만들지 않는다."""
    rs = daily_returns([pt(1, "0"), pt(2, "100", dep="100")])
    assert rs == []


def test_cumulative_compounds_not_sums() -> None:
    """+10% 두 번은 +20% 가 아니라 +21% 다."""
    rs = daily_returns([pt(1, "100"), pt(2, "110"), pt(3, "121")])
    cum = cumulative_return(rs)
    assert cum is not None
    assert cum == pytest.approx(Decimal("0.21"), abs=Decimal("1e-9"))


def test_cumulative_on_a_slice_rebases() -> None:
    """구간을 잘라 쓰면 그 구간 **시작 직전**이 기준이 된다."""
    rs = daily_returns([pt(1, "100"), pt(2, "110"), pt(3, "121")])
    tail = rs[1:]  # 3일차 하루만
    cum = cumulative_return(tail)
    assert cum is not None
    assert cum == pytest.approx(Decimal("0.1"), abs=Decimal("1e-9"))


def test_base_index_is_before_the_first_return() -> None:
    """비교의 기준은 첫 수익률 **직전** 지수다.

    ⚠️첫 수익률일의 지수를 기준으로 삼으면 **그날 수익률이 통째로 빠진다.**
      실제로 벤치마크 화면이 그렇게 계산해, 같은 구간·같은 관측일수인데
      성과 분석은 −1.98%, 벤치마크는 −1.21% 를 보였다. 화면 둘이 서로 다른
      말을 하는데 버그로 보이지도 않았다.
    """
    rs = daily_returns([pt(1, "100"), pt(2, "110"), pt(3, "121")])
    assert base_index(rs) == pytest.approx(Decimal("1"), abs=Decimal("1e-9"))
    # 첫 수익률일의 지수로 나누면 +10% 가 빠져 +10% 만 남는다 — 틀린 값이다.
    assert rs[-1].index / rs[0].index == pytest.approx(
        Decimal("1.1"), abs=Decimal("1e-9")
    )
    assert cumulative_return(rs) == pytest.approx(Decimal("0.21"), abs=Decimal("1e-9"))


def test_max_drawdown_measures_from_the_peak() -> None:
    """100 → 120 → 90. 낙폭은 시작 대비 -10% 가 아니라 고점 대비 -25% 다."""
    rs = daily_returns([pt(1, "100"), pt(2, "120"), pt(3, "90")])
    dd = max_drawdown(rs)
    assert dd is not None
    assert dd.value == pytest.approx(Decimal("-0.25"), abs=Decimal("1e-9"))
    assert dd.peak_date == date(2026, 1, 2)
    assert dd.trough_date == date(2026, 1, 3)


def test_max_drawdown_counts_a_fall_from_the_first_day() -> None:
    """첫날부터 내리 빠지면 고점은 '시작점'이다(0 이 아니라)."""
    rs = daily_returns([pt(1, "100"), pt(2, "80")])
    dd = max_drawdown(rs)
    assert dd is not None
    assert dd.value == pytest.approx(Decimal("-0.2"), abs=Decimal("1e-9"))


def test_annualized_return_is_none_under_a_year() -> None:
    """3개월치를 연환산해 부풀리지 않는다."""
    rs = daily_returns([pt(1, "100"), pt(2, "110")])
    assert annualized_return(rs) is None
    assert sharpe(rs) is None


def test_annualized_return_over_a_year() -> None:
    """매일 정확히 +0.1% 씩 252 영업일 → 연 (1.001^252 - 1) ≈ +28.6%."""
    points = [pt(1, "100")]
    value = Decimal("100")
    for i in range(2, 2 + 252):
        value = value * Decimal("1.001")
        points.append(pt(i, str(value)))
    rs = daily_returns(points)
    ann = annualized_return(rs)
    assert ann is not None
    assert float(ann) == pytest.approx(1.001**252 - 1, rel=1e-6)


def test_volatility_of_a_flat_series_is_zero() -> None:
    rs = daily_returns([pt(1, "100"), pt(2, "100"), pt(3, "100")])
    vol = volatility(rs)
    assert vol is not None
    assert float(vol) == pytest.approx(0.0, abs=1e-12)


def test_volatility_needs_two_points() -> None:
    rs = daily_returns([pt(1, "100"), pt(2, "110")])
    assert volatility(rs) is None


def test_monthly_returns_compound_within_the_month() -> None:
    points = [
        DailyPoint(date(2026, 1, 30), Decimal("100"), Decimal("0"), Decimal("0")),
        DailyPoint(date(2026, 1, 31), Decimal("110"), Decimal("0"), Decimal("0")),
        DailyPoint(date(2026, 2, 2), Decimal("121"), Decimal("0"), Decimal("0")),
        DailyPoint(date(2026, 2, 3), Decimal("133.1"), Decimal("0"), Decimal("0")),
    ]
    rs = daily_returns(points)
    months = dict(monthly_returns(rs))
    assert float(months["2026-01"]) == pytest.approx(0.1, abs=1e-9)
    assert float(months["2026-02"]) == pytest.approx(0.21, abs=1e-9)


def test_hit_ratio_excludes_flat_days() -> None:
    rs = daily_returns([pt(1, "100"), pt(2, "110"), pt(3, "110"), pt(4, "100")])
    hr = hit_ratio(rs)
    assert hr is not None
    assert hr == Decimal("1") / Decimal("3")


def test_window_keeps_only_the_tail() -> None:
    points = [pt(i, str(100 + i)) for i in range(1, 31)]
    rs = daily_returns(points)
    recent = window(rs, 7)
    assert len(recent) == 7
    assert recent[-1].base_date == rs[-1].base_date


def test_empty_input_is_safe() -> None:
    assert daily_returns([]) == []
    assert cumulative_return([]) is None
    assert max_drawdown([]) is None
    assert hit_ratio([]) is None
    assert window([], 30) == []


# ── 입출금 날짜 어긋남 보정 ─────────────────────────────────────────────────

from app.core.performance_analytics import reconcile_flows  # noqa: E402


def test_shifts_a_flow_recorded_one_day_late() -> None:
    """실제로 관측된 2025-04-09/10 패턴.

    자산은 971,071 → 2,329,988 로 뛰었는데 입금 1,356,290 은 다음 날 기록돼 있다.
    보정 전이면 하루 +140%, 보정 후에는 +0.27% 가 되어야 한다.
    """
    points = [
        pt(1, "971071", dep="979221"),
        pt(2, "2329988"),
        pt(3, "2345295", dep="1356290"),
        pt(4, "2311518"),
    ]
    before = daily_returns(points)
    assert float(before[0].ret) > 1.0  # 보정 안 하면 +140%

    fixed, shifts = reconcile_flows(points)
    assert len(shifts) == 1
    assert shifts[0].moved_from == date(2026, 1, 3)
    assert shifts[0].moved_to == date(2026, 1, 2)
    assert shifts[0].amount == Decimal("1356290")

    after = daily_returns(fixed)
    assert float(after[0].ret) == pytest.approx(0.0027, abs=5e-4)
    # 당긴 만큼 다음 날에서 빠져야 한다 — 총량은 그대로다.
    assert float(after[1].ret) == pytest.approx(0.00657, abs=5e-4)


def test_leaves_a_real_crash_alone() -> None:
    """입출금이 없는 -40% 는 진짜 폭락이다. 지우면 안 된다."""
    points = [pt(1, "100"), pt(2, "60"), pt(3, "62")]
    fixed, shifts = reconcile_flows(points)
    assert shifts == []
    assert fixed is points
    rs = daily_returns(fixed)
    assert float(rs[0].ret) == pytest.approx(-0.4, abs=1e-9)


def test_leaves_a_mismatched_amount_alone() -> None:
    """다음 날 입금이 있어도 **금액이 안 맞으면** 건드리지 않는다."""
    points = [pt(1, "100"), pt(2, "200"), pt(3, "210", dep="5")]
    _, shifts = reconcile_flows(points)
    assert shifts == []


def test_shift_preserves_total_flow() -> None:
    points = [
        pt(1, "1000000", dep="1000000"),
        pt(2, "3000000"),
        pt(3, "3010000", dep="2000000"),
        pt(4, "3020000"),
    ]
    fixed, shifts = reconcile_flows(points)
    assert len(shifts) == 1
    total_before = sum(p.net_flow for p in points)
    total_after = sum(p.net_flow for p in fixed)
    assert total_before == total_after


def test_ordinary_series_is_untouched() -> None:
    points = [pt(i, str(100 + i)) for i in range(1, 12)]
    fixed, shifts = reconcile_flows(points)
    assert shifts == []
    assert fixed is points
