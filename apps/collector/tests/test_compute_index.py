"""compute_index 회귀 테스트 — 컴퓨팅 지수 모니터링의 순수 계산부.

xlsx 판독(_read_blocks)은 겨누지 않는다(openpyxl·마운트 의존) — build_payload 에
합성 블록을 넣는다.

  1) 패널은 INDICES 순서(H100·B200·A100), 기초 파일에 없는 지수는 빠진다
  2) stats: 시작·최근·최저·최고·전일대비·구간 변화
  3) fail-soft: 빈 입력이면 빈 series, 한 점짜리는 전일대비 None
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import compute_index as ci  # noqa: E402

H = "SDH100RT Index"
B = "SDB200RT Index"
A = "SDA100RT Index"


def _pts(start: date, vals):
    return [(start + timedelta(days=i), float(v)) for i, v in enumerate(vals)]


def test_panel_order_follows_indices():
    # 산출 시작일이 서로 달라도 패널은 INDICES 순서 그대로다.
    blocks = {
        A: _pts(date(2026, 8, 1), [1.0, 1.1, 1.2, 1.3, 1.4]),
        H: _pts(date(2026, 8, 3), [2.0, 2.5, 2.0]),
        B: _pts(date(2026, 8, 1), [5.0, 5.0, 5.0, 5.0, 6.0]),
    }
    out = ci.build_payload(blocks)
    assert [s["key"] for s in out["series"]] == ["h100", "b200", "a100"]
    assert [s["label"] for s in out["series"]] == ["H100", "B200", "A100"]
    assert out["asof"] == "2026-08-05"          # 계열 중 가장 최근
    assert out["unit"] == "$/GPU-hr"
    # 셋 다 단가라 kind·단위가 같다(배수 패널은 2026-08-27 제거됨)
    assert {s["kind"] for s in out["series"]} == {"price"}
    assert {s["unit"] for s in out["series"]} == {"$/GPU-hr"}


def test_missing_index_is_dropped_not_faked():
    # 기초 파일에 A100 블록이 아직 없는 상태 — 패널이 2개로 줄 뿐 빈 계열을 만들지 않는다.
    out = ci.build_payload({
        H: _pts(date(2026, 8, 3), [2.0, 2.1]),
        B: _pts(date(2026, 8, 3), [5.0, 5.1]),
    })
    assert [s["key"] for s in out["series"]] == ["h100", "b200"]


def test_stats_fields():
    blocks = {H: _pts(date(2026, 8, 20), [2.0, 1.6, 2.4, 2.2])}
    s = ci.build_payload(blocks)["series"][0]
    t = s["stats"]
    assert t["n"] == 4
    assert (t["start"], t["start_date"]) == (2.0, "2026-08-20")
    assert (t["last"], t["last_date"]) == (2.2, "2026-08-23")
    assert (t["min"], t["min_date"]) == (1.6, "2026-08-21")
    assert (t["max"], t["max_date"]) == (2.4, "2026-08-22")
    assert t["chg_1d_pct"] == pytest.approx((2.2 / 2.4 - 1) * 100)  # 전일(2.4) 대비
    assert t["chg_pct"] == pytest.approx(10.0)                      # 구간 2.0→2.2
    # 차트가 그대로 그릴 수 있게 날짜 오름차순 [날짜, 값] 쌍
    assert s["points"][0] == ["2026-08-20", 2.0]
    assert s["points"][-1] == ["2026-08-23", 2.2]


def test_fail_soft():
    assert ci.build_payload({})["series"] == []
    assert ci.build_payload({})["asof"] is None
    # 모르는 티커는 무시한다 — INDICES 에 있는 것만 패널이 된다
    unknown = ci.build_payload({"SDH200RT Index": _pts(date(2026, 8, 20), [3.0, 3.1])})
    assert unknown["series"] == []


def test_single_point_series_has_no_1d():
    s = ci.build_payload({H: _pts(date(2026, 8, 24), [2.65])})["series"][0]
    assert s["stats"]["chg_1d_pct"] is None
    assert s["stats"]["chg_pct"] == pytest.approx(0.0)
