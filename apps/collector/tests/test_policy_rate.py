"""policy_rate 회귀 테스트 — 정책금리 카드의 순수 계산부.

CSV 판독(_read_rows)은 겨누지 않는다(마운트 의존) — build_payload 에 합성 행을 넣는다.

  1) 현재 수준·직전 결정 대비 bp
  2) '마지막으로 움직인 회의' 와 그 뒤 동결 횟수 (= "N회 연속 동결"의 근거)
  3) 한 번도 안 움직였으면 전건이 동결
  4) fail-soft: 빈 입력 → 빈 payload
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import policy_rate as pr  # noqa: E402


def test_level_and_bp_change():
    out = pr.build_payload([
        (date(2025, 9, 18), 4.25),
        (date(2025, 10, 30), 4.00),
    ])
    assert out["last"] == 4.00
    assert out["last_date"] == "2025-10-30"
    assert out["asof"] == "2025-10-30"
    assert out["unit"] == "%"
    # 0.25%p 인하 → -25bp (float 오차가 새지 않게 반올림해서 낸다)
    assert out["chg_bp"] == pytest.approx(-25.0)
    assert out["points"][0] == ["2025-09-18", 4.25]


def test_hold_streak_counts_meetings_since_last_move():
    # 12/11 에 3.75 로 내린 뒤 세 번 동결
    out = pr.build_payload([
        (date(2025, 10, 30), 4.00),
        (date(2025, 12, 11), 3.75),
        (date(2026, 1, 29), 3.75),
        (date(2026, 3, 19), 3.75),
        (date(2026, 4, 30), 3.75),
    ])
    assert out["last_change_date"] == "2025-12-11"
    assert out["holds"] == 3
    assert out["chg_bp"] == pytest.approx(0.0)  # 직전 회의 대비는 동결


def test_never_moved_is_all_holds():
    out = pr.build_payload([
        (date(2026, 1, 29), 3.75),
        (date(2026, 3, 19), 3.75),
        (date(2026, 4, 30), 3.75),
    ])
    assert out["last_change_date"] is None
    assert out["holds"] == 2


def test_fail_soft():
    out = pr.build_payload([])
    assert out["points"] == []
    assert out["last"] is None and out["asof"] is None
    assert out["holds"] == 0
    # 한 건뿐이면 직전 대비가 없다
    one = pr.build_payload([(date(2026, 7, 30), 3.75)])
    assert one["chg_bp"] is None
    assert one["last"] == 3.75
