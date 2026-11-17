import pandas as pd
import pytest

from app.core import basket_lab as bl


def _idx(n, start="2025-06-02"):
    return pd.bdate_range(start, periods=n)


def test_indicators():
    px = pd.DataFrame({"A": [100.0, 110, 121, 133.1]}, index=_idx(4))
    ret = bl.member_indicator(px, "ret", 1)
    assert ret["A"].iloc[1] == pytest.approx(0.10)
    ma = bl.member_indicator(pd.DataFrame({"A": [1.0, 2, 3, 4, 5, 6]}, index=_idx(6)), "ma5", 1)
    assert ma["A"].iloc[5] == pytest.approx(4 / 3 - 1)          # MA5: 3 → 4


def test_bands_use_only_the_past():
    s = pd.Series(range(200), index=_idx(200), dtype=float)
    lo, hi = bl.bands(s)
    # 오늘 값이 경계 계산에 들어가지 않는다 — 계속 오르는 시계열은 늘 '상위 10% 이상'
    assert s.iloc[150] > hi.iloc[150]
    assert pd.isna(lo.iloc[30])                                  # 60개 모이기 전엔 경계 없음


def test_signal_direction_first_cross_and_cooldown():
    idx = pd.bdate_range("2026-01-21", periods=40)
    spread = pd.Series(0.0, index=idx)
    spread.iloc[[5, 6, 7]] = 1.0          # 상위로 3일 연속 — 신호는 첫날 하루
    spread.iloc[20] = -1.0                # 하위로
    lo = pd.Series(-0.5, index=idx)
    hi = pd.Series(0.5, index=idx)
    lev = {"A": pd.Series(1.0, index=idx), "B": pd.Series([1.0] * 6 + [1.06] * 34, index=idx)}
    sigs = bl.spread_signals(spread, lo, hi, "A", "B", lev, hold=5, start=idx[0])
    assert [s.side for s in sigs] == ["hi", "lo"]
    assert sigs[0].bought == "B" and sigs[1].bought == "A"       # A 비쌈 → B 매수, A 쌈 → A 매수
    assert sigs[0].entry == idx[6]                               # 다음 영업일 종가 진입
    assert sigs[0].hit is False                                  # 진입가가 이미 1.06 — 그 뒤로 안 오름


def test_dip_masks_fire_on_first_day_only():
    px = pd.Series([10, 9, 8, 7, 6, 5, 6, 5, 4, 3], index=_idx(10), dtype=float)
    m = bl.dip_masks(px)
    assert list(m["down3"][m["down3"]].index) == [px.index[3], px.index[9]]
    assert m["down5"].sum() == 1 and bool(m["down5"].iloc[5])


def test_gap_does_not_create_a_false_fresh_signal():
    idx = pd.bdate_range("2026-01-21", periods=20)
    spread = pd.Series(0.0, index=idx)
    spread.iloc[3:12] = 1.0
    spread.iloc[6] = float("nan")          # 꼬리 안에서 하루 빈칸
    lo = pd.Series(-0.5, index=idx)
    hi = pd.Series(0.5, index=idx)
    lev = {"A": pd.Series(1.0, index=idx), "B": pd.Series(1.0, index=idx)}
    sigs = bl.spread_signals(spread, lo, hi, "A", "B", lev, hold=1, start=idx[0])
    assert [s.date for s in sigs] == [idx[3]]  # 빈칸 다음 날(idx[7])을 새 신호로 세지 않는다


def test_dip_stop_loss_exits_at_first_close_below_threshold():
    idx = _idx(12, "2026-01-21")
    px = pd.Series([10, 9, 8, 7, 7.0, 6.3, 6.0, 7.5, 8, 8, 8, 8], index=idx, dtype=float)
    mask = pd.Series(False, index=idx)
    mask.iloc[3] = True                       # 진입 = idx[4] 종가 7.0
    ev = bl._dip_events(px, mask, hold=5, start=idx[0])
    assert ev[0]["ret"] == pytest.approx(8 / 7 - 1)          # 손절 없으면 +14%
    assert ev[0]["ret_stop"] == pytest.approx(6.3 / 7 - 1)   # −10% 로 닫힌 첫날 판다
