"""price_board 회귀 테스트 — 가격 모니터의 지표 계산부.

xlsx 판독은 겨누지 않는다 — 합성 시계열을 넣는다. 여기 3건은 전부 회의자료 생성기가
겪고 고친 함정이라, 값이 아니라 **정의**를 지키는 게 목적이다.

  1) DtD 는 단순 t-1 이 아니다 — 주말 forward-fill 을 건너뛰고 값이 실제로 달라지는
     직전 관측일을 찾는다
  2) MtD·YtD 는 리포트 날짜가 아니라 그 열 자신의 최신 관측일에 앵커한다
  3) 채권은 bp(변화폭), 그 외는 %(수익률)
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import price_board as pb  # noqa: E402


def _s(pairs) -> dict:
    return {d: v for d, v in pairs}


def test_dtd_uses_last_different_value_not_naive_t_minus_1():
    # 금(8/21) 100 → 토·일 100 으로 ffill → 월(8/24) 103.
    # 핵심은 **기준 값**이 100 이어야 한다는 것(단순 t-1 도 여기선 100 이라 같지만,
    # 값이 안 바뀐 날이 이어지면 그때 갈린다 — 아래 케이스가 그걸 잡는다).
    s = _s([
        (date(2026, 8, 21), 100.0),
        (date(2026, 8, 22), 100.0),
        (date(2026, 8, 23), 100.0),
        (date(2026, 8, 24), 103.0),
    ])
    ref = pb._dtd_ref(s, date(2026, 8, 24))
    assert s[ref] == 100.0
    assert pb.compute_row(s, date(2026, 8, 24), is_yield=False)["dtd"] == pytest.approx(3.0)

    # ★진짜 갈리는 자리: 월요일에 값이 안 움직였고 화요일에 움직인 경우.
    #   naive t-1(월, 103)이 아니라 값이 다른 금요일(100)까지 거슬러야 한다.
    s2 = _s([
        (date(2026, 8, 21), 100.0),
        (date(2026, 8, 22), 100.0),
        (date(2026, 8, 23), 100.0),
        (date(2026, 8, 24), 100.0),
        (date(2026, 8, 25), 106.0),
    ])
    ref2 = pb._dtd_ref(s2, date(2026, 8, 25))
    assert s2[ref2] == 100.0
    assert pb.compute_row(s2, date(2026, 8, 25), is_yield=False)["dtd"] == pytest.approx(6.0)


def test_dtd_gives_up_after_seven_days():
    # 8일 넘게 같은 값이면 기준을 못 찾는다 — 0% 로 우기지 않고 None.
    s = _s([(date(2026, 8, 10) + timedelta(days=i), 50.0) for i in range(15)])
    assert pb._dtd_ref(s, date(2026, 8, 24)) is None
    assert pb.compute_row(s, date(2026, 8, 24), is_yield=False)["dtd"] is None


def test_mtd_ytd_anchor_on_column_asof_not_report_date():
    # 이 열은 7/31 에서 갱신이 멈췄다. 리포트 날짜(8/24)에 앵커하면 분모가 7/31 이 되어
    # MtD 가 0.00% 로 나온다. 열 자신의 최신일(7/31)에 앵커해야 6/30 대비가 나온다.
    s = _s([
        (date(2025, 12, 31), 80.0),
        (date(2026, 6, 30), 100.0),
        (date(2026, 7, 31), 110.0),
    ])
    r = pb.compute_row(s, date(2026, 8, 24), is_yield=False)
    assert r["asof"] == "2026-07-31"
    assert r["mtd"] == pytest.approx(10.0)   # 6/30 100 → 110
    assert r["ytd"] == pytest.approx(37.5)   # 전년말 80 → 110


def test_yield_uses_bp_and_survives_negative():
    # 일본국채처럼 마이너스 구간을 지나도 bp 는 부호가 안 뒤집힌다(%는 뒤집힌다).
    s = _s([
        (date(2025, 12, 31), -0.10),
        (date(2026, 8, 20), 0.05),
        (date(2026, 8, 21), 0.09),
    ])
    r = pb.compute_row(s, date(2026, 8, 21), is_yield=True)
    assert r["dtd"] == pytest.approx(4.0)     # 0.05 → 0.09 = +4bp
    assert r["ytd"] == pytest.approx(19.0)    # -0.10 → 0.09 = +19bp


def test_weekly_downsample_keeps_last_of_week():
    s = _s([(date(2026, 8, d), float(d)) for d in (17, 18, 19, 20, 21, 24)])
    out = pb._weekly(s, date(2026, 1, 1))
    assert out == [["2026-08-21", 21.0], ["2026-08-24", 24.0]]


def test_payload_shape_and_missing_column_is_dropped():
    cols = {
        "SPX Index": _s([(date(2026, 8, 27), 100.0), (date(2026, 8, 28), 101.0)]),
        # MXWD 등 나머지는 시트에 없다고 가정 — 행이 조용히 빠진다
    }
    out = pb.build_payload(cols, "equity")
    assert out["cat"] == "equity" and out["unit"] == "%" and out["is_yield"] is False
    assert [r["key"] for r in out["rows"]] == ["SPX Index"]
    # ★2026-08-28 계층 도입으로 국가가 layer2 로 빠졌다 — 라벨은 지수명만 남는다.
    assert out["rows"][0]["label"] == "S&P500"
    assert (out["rows"][0]["group"], out["rows"][0]["sub_group"]) == ("DM", "미국")
    assert out["asof"] == "2026-08-28"
    assert [c["key"] for c in out["categories"]] == [
        "equity", "bond", "commodity", "fx", "crypto"
    ]
    # 채권 탭은 단위가 bp 로 갈린다
    assert pb.build_payload(cols, "bond")["unit"] == "bp"
    # 모르는 자산군은 기본값(주식)으로 떨어진다
    assert pb.build_payload(cols, "nope")["cat"] == "equity"


def test_tree_nests_layer1_and_layer2():
    # 벤치마크는 layer2 가 없어 지수가 바로 붙고, DM 은 지역 묶음이 한 겹 더 있다.
    cols = {
        t: _s([(date(2026, 8, 28), 100.0), (date(2026, 8, 27), 99.0)])
        for t in ("MXWD Index", "SPX Index", "CCMP Index", "UKX Index", "KOSPI2 Index")
    }
    tree = pb.build_payload(cols, "equity")["tree"]
    names = [n["label"] for n in tree]
    assert names == ["벤치마크", "DM", "EM"]

    bench = tree[0]
    assert [c["type"] for c in bench["children"]] == ["leaf"]
    assert bench["children"][0]["label"] == "MSCI ACWI"

    dm = tree[1]
    assert [c["label"] for c in dm["children"]] == ["미국", "유럽"]
    assert [c["label"] for c in dm["children"][0]["children"]] == ["S&P500", "나스닥종합"]
    # leaf 에는 group/sub_group 을 다시 싣지 않는다(위치가 이미 계층으로 표현됨)
    leaf = dm["children"][0]["children"][0]
    assert "group" not in leaf and "sub_group" not in leaf
    assert leaf["key"] == "SPX Index"


def test_tree_is_flat_when_category_has_no_groups():
    cols = {"DXY Curncy": _s([(date(2026, 8, 28), 99.0)])}
    tree = pb.build_payload(cols, "fx")["tree"]
    assert [n["type"] for n in tree] == ["leaf"]
    assert tree[0]["label"] == "DXY"


def test_rolling_windows_slide_with_t_unlike_calendar_anchors():
    # 8/1 부터 매일 1씩 오르는 시계열. 롤링 1M(30일)은 t 를 따라 미끄러지므로
    # 달력 앵커(MtD)가 월초에 0 으로 리셋되는 것과 달리 항상 30일치를 잰다.
    s = _s([(date(2026, 6, 1) + timedelta(days=i), 100.0 + i) for i in range(120)])
    r = pb.compute_row(s, date(2026, 9, 1), is_yield=False)
    assert r["asof"] == "2026-09-01"           # 6/1+92일
    cur = 192.0
    assert r["r1m"] == pytest.approx((cur / 162.0 - 1) * 100, rel=1e-9)   # 30일 전
    assert r["r3m"] == pytest.approx((cur / 101.0 - 1) * 100, rel=1e-9)   # 91일 전
    # 창이 데이터보다 길면 기준을 못 잡는다 — 0% 로 우기지 않고 None
    assert r["r6m"] is None and r["r1y"] is None
    # 달력 앵커는 그대로 살아 있다(표가 둘 다 쓴다)
    assert r["mtd"] == pytest.approx((cur / 191.0 - 1) * 100, rel=1e-9)   # 8/31 대비


def test_rolling_series_is_historical_not_a_single_point():
    # 각 날짜의 롤링 3M 이 그날 기준으로 다시 계산돼야 한다(0선 교차 = 추세 전환).
    s = _s([(date(2026, 1, 1) + timedelta(days=i), 100.0 + i) for i in range(200)])
    pts = pb.compute_rolling_series(s, 91, is_yield=False)
    # 주간으로 솎이므로 점 수는 줄지만 한 점짜리가 아니다
    assert len(pts) >= 10
    # 앞 91일은 기준이 없어 빠진다 — 첫 점이 시계열 시작보다 늦다
    assert pts[0][0] > "2026-03-01"
    d, v = pts[-1]
    base = 100.0 + (date.fromisoformat(d) - date(2026, 1, 1)).days
    assert v == pytest.approx((base / (base - 91) - 1) * 100, rel=1e-9)


def test_metric_payload_carries_price_and_r3m_and_benchmark():
    cols = {
        "SPX Index": _s([(date(2026, 6, 1) + timedelta(days=i), 100.0 + i) for i in range(120)]),
        "MXWD Index": _s([(date(2026, 6, 1) + timedelta(days=i), 50.0 + i * 0.5) for i in range(120)]),
    }
    out = pb.build_metric_payload(cols, "SPX Index")
    assert [m["key"] for m in out["modes"]] == ["cum", "rs", "r3m"]
    assert len(out["series"]) == 1
    ser = out["series"][0]
    # ★가격 원본과 롤링 3M 을 **둘 다** 싣는다 — 모드 전환에 재요청이 없어야 한다.
    assert ser["price"] and ser["r3m"]
    # 두 배열은 같은 주간 격자 위에 있다(r3m 만 앞이 잘려 짧다)
    assert set(d for d, _ in ser["r3m"]) <= set(d for d, _ in ser["price"])
    # 상대곡선의 분모 — 주식은 MSCI ACWI
    assert out["benchmark"]["key"] == "MXWD Index"
    assert out["benchmark"]["label"] == "MSCI ACWI"


def test_metric_payload_unit_follows_category_and_bond_has_no_benchmark():
    cols = {"GT10 Govt": _s([(date(2026, 8, 27), 4.6), (date(2026, 8, 28), 4.68)])}
    out = pb.build_metric_payload(cols, "GT10 Govt")
    assert out["is_yield"] is True and out["unit"] == "bp"
    assert out["label"] == "10Y" and out["cat"] == "bond"
    # ★금리를 금리로 나눈 상대곡선은 의미가 없다 — 화면이 토글을 비활성으로 둔다.
    assert out["benchmark"] is None
    # 모르는 티커는 note 로 알린다
    miss = pb.build_metric_payload(cols, "NOPE Index")
    assert miss["series"] == [] and miss["note"]


def test_group_payload_shape_matches_single():
    cols = {
        t: _s([(date(2026, 6, 1) + timedelta(days=i), 100.0 + i) for i in range(120)])
        for t in ("SPX Index", "CCMP Index", "MXWD Index")
    }
    out = pb.build_group_metric_payload(cols, "equity", "DM", "미국")
    assert [s["key"] for s in out["series"]] == ["SPX Index", "CCMP Index"]
    assert all(s["price"] and s["r3m"] for s in out["series"])
    assert out["benchmark"]["key"] == "MXWD Index"
    # 분류에 없는 묶음은 note
    assert pb.build_group_metric_payload(cols, "equity", "DM", "없는곳")["note"]


def test_empty_input():
    out = pb.build_payload({}, "equity")
    assert out["rows"] == [] and out["series"] == [] and out["asof"] is None
    assert out["tree"] == []
