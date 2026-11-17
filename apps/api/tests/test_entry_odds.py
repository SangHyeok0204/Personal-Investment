import pandas as pd
import pytest

from app.core import entry_odds


def _level(values):
    idx = pd.date_range("2000-01-01", periods=len(values), freq="MS")
    return pd.Series(values, index=idx, dtype=float)


def _row(out, key):
    return next(r for r in out["rows"] if r["key"] == key)


def _cell(row, h):
    return next(c for c in row["cells"] if c["h"] == h)


def test_wilson_lower_is_conservative():
    assert entry_odds.wilson_lower(0, 0) is None
    assert entry_odds.wilson_lower(10, 10) < 1.0          # 10전 10승이어도 하한은 1 이 아니다
    assert entry_odds.wilson_lower(10, 10) < entry_odds.wilson_lower(100, 100)
    assert entry_odds.wilson_lower(5, 10) == pytest.approx(0.2366, abs=1e-3)


def test_always_rising_series_wins_everywhere():
    out = entry_odds.compute(_level([100 * 1.01**i for i in range(200)]))
    row = _row(out, "all")
    for c in row["cells"]:
        assert c["win_rate"] == 1.0
        assert c["worst"] > 0
        assert c["worst_dip"] == 0.0
    assert row["min_months_rate"] == 6
    # 상승만 했으니 낙폭 조건은 한 번도 안 걸린다
    assert all(c["n"] == 0 for c in _row(out, "dd20")["cells"])
    assert out["now"]["drawdown"] == 0.0
    assert out["now"]["active"] == ["all"]


def test_drawdown_condition_uses_running_peak_only():
    # 100 → 70(−30%) → 회복 140. 낙폭 진입월은 70 근처 달들뿐이다.
    vals = [100.0] * 12 + [70.0] * 6 + [140.0] * 40
    out = entry_odds.compute(_level(vals))
    dd30 = _row(out, "dd30")
    c12 = _cell(dd30, 12)
    assert c12["n"] == 6
    assert c12["win_rate"] == 1.0
    assert c12["median"] == pytest.approx(1.0)        # 70 → 140


def test_independent_episodes_skip_overlaps():
    vals = [100 * 1.01**i for i in range(60)]
    c = _cell(_row(entry_odds.compute(_level(vals)), "all"), 12)
    assert c["n"] == 48                    # 60개월 중 12개월 뒤 값이 있는 진입
    assert c["episodes"] == 4              # 0, 12, 24, 36
    assert c["episode_wins"] == 4
    assert c["lower"] == pytest.approx(entry_odds.wilson_lower(4, 4))


def test_min_months_requires_all_longer_horizons():
    # 6개월 승률은 높지만 긴 기간에서 무너지면 '6개월부터 90%'라고 하면 안 된다.
    vals = [100 * 1.02**i for i in range(60)] + [100 * 1.02**60 * 0.98**i for i in range(150)]
    row = _row(entry_odds.compute(_level(vals)), "all")
    assert row["min_months_rate"] is None


def test_month_end_takes_last_trading_day():
    idx = pd.to_datetime(["2020-01-02", "2020-01-31", "2020-02-03", "2020-02-27"])
    out = entry_odds.month_end(pd.Series([1.0, 2.0, 3.0, 4.0], index=idx))
    assert list(out) == [2.0, 4.0]
    assert out.index[0] == pd.Timestamp("2020-01-01")


def test_rare_condition_is_not_judged_on_one_episode():
    # −50% 를 딱 한 번 겪고 회복 — 1회 1승을 '6개월이면 90%'로 내면 안 된다.
    vals = [100.0] * 24 + [45.0] * 3 + [100 * 1.01**i for i in range(150)]
    row = _row(entry_odds.compute(_level(vals)), "dd50")
    assert _cell(row, 6)["episodes"] < entry_odds.MIN_EPISODES
    assert row["min_months_rate"] is None


def test_partial_last_month_is_excluded_from_history():
    vals = [100 * 1.01**i for i in range(30)] + [1.0]   # 마지막(미완성) 달이 폭락처럼 보여도
    out = entry_odds.compute(_level(vals), partial_last=True)
    c = _cell(_row(out, "all"), 6)
    assert c["win_rate"] == 1.0                          # 과거 표에는 들어가지 않는다
    assert out["now"]["drawdown"] < -0.9                 # 지금 상태에는 쓴다
    assert out["now"]["partial"] is True


def test_index_level_splices_by_overlap_ratio_and_drops_before_gap():
    from app.api.strategy import _index_level

    rows = [("2020-01", 100, "bloomberg"), ("2020-02", 110, "bloomberg"),
            ("2020-02", 55, "yahoo"), ("2020-03", 60, "yahoo")]
    level, dropped = _index_level(rows)
    assert list(level.round(6)) == [100, 110, 120]       # 야후 60 × (110/55)
    assert dropped is None
    gap = [("2019-01", 90, "bloomberg"), ("2019-03", 95, "bloomberg"), ("2019-04", 96, "bloomberg")]
    level, dropped = _index_level(gap)
    assert dropped == "2019-02" and list(level) == [95, 96]
