"""etf_flows 회귀 테스트 — CHECK 호가 envelope 의 newEtfs → 카드 payload 변환.

라이브 수신에 의존하지 않는다 — state.hoga() 리더가 주는 형태를 합성해 넣는다.

  1) 단위 환산: tradeAmt·indivNet(억원)→원(×1e8), volume(주) 그대로, 부호 보존
  2) 정렬 = CHECK 시트 순서(no 오름차순), no 없는 행은 뒤로
  3) 비숫자 값은 None 으로 fail-soft (행 하나 때문에 카드가 죽지 않는다)
  4) envelope 미수신·newEtfs 부재·빈 배열 → 빈 payload (화면 대기 문구 경로)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import etf_flows as ef  # noqa: E402

TS = "2026-08-25T14:50:28.000+09:00"


def _hoga(new_etfs):
    return {
        "payload": {"etfs": [], "newEtfs": new_etfs},
        "source_timestamp": TS,
        "sent_at": TS,
        "seq": 2485800,
    }


def test_unit_conversion_and_fields():
    out = ef.build_etf_flows(_hoga([{
        "no": 1, "code": "0233A0", "name": "ACE 삼성전자SK하이닉스플러스채권혼합50",
        "listedDate": "2026-08-25", "tradeAmt": 61.16, "indivNet": -2.5,
        "vol3tick": 0.038055, "volume": 608705, "price": 10265,
    }]))
    assert out["asof"] == TS
    row = out["rows"][0]
    assert row["code"] == "0233A0"
    assert row["listing_date"] == "2026-08-25"
    assert row["trade_value"] == 61.16 * 1e8
    assert row["indiv_net_buy"] == -2.5 * 1e8   # 부호 보존
    assert row["indiv_net_lp_est"] == 0.038055 * 1e8  # vol3tick = LP추정(억원)
    assert row["trade_volume"] == 608705        # 주 단위 그대로
    assert row["observed_at"] == TS
    # vol3tick 없는 과거 envelope → None (필드 도입 전 재생에도 안 죽는다)
    out2 = ef.build_etf_flows(_hoga([{"no": 1, "code": "A", "tradeAmt": 1}]))
    assert out2["rows"][0]["indiv_net_lp_est"] is None


def test_sheet_order_no_ascending():
    out = ef.build_etf_flows(_hoga([
        {"no": 3, "code": "C", "tradeAmt": 1},
        {"code": "D", "tradeAmt": 9},           # no 없음 → 맨 뒤
        {"no": 1, "code": "A", "tradeAmt": 2},
        {"no": 2, "code": "B", "tradeAmt": 3},
    ]))
    assert [r["code"] for r in out["rows"]] == ["A", "B", "C", "D"]


def test_non_numeric_fail_soft():
    out = ef.build_etf_flows(_hoga([
        {"no": 1, "code": "A", "tradeAmt": "-", "indivNet": None, "volume": "CT"},
    ]))
    row = out["rows"][0]
    assert row["trade_value"] is None
    assert row["indiv_net_buy"] is None
    assert row["trade_volume"] is None


def test_missing_envelope_or_field_empty_payload():
    assert ef.build_etf_flows(None)["rows"] == []
    assert ef.build_etf_flows({"payload": None})["rows"] == []
    assert ef.build_etf_flows({"payload": {"etfs": []}})["rows"] == []
    empty = ef.build_etf_flows(_hoga([]))
    assert empty["rows"] == [] and empty["asof"] is None
