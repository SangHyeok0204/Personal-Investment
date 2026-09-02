"""etf_class 회귀 테스트 — 국내상장 ETF 분류별 자금·수익률의 정의부.

워크북 판독(openpyxl)은 겨누지 않는다. 여기서 지키는 건 **정의** 넷이고, 넷 다
이 화면이 틀린 말을 하게 되는 자리다:

  1) 네 창(1주·1개월·3개월·6개월)은 전부 오늘로 끝나 서로 포갠다. 구간 분해는
     누적끼리 빼서 만들어야 하고, Σ구간 == 누적6m 이 성립해야 한다.
  2) 구간 수익률은 **복리 체인**이다. 빼기가 아니다 — Π(1+구간) == 1+누적6m.
  3) 분류 수익률은 종목 단위로 구간을 만든 뒤 가중한다. 결측 종목의 시총은 분모에서
     빠져야 한다(안 그러면 그 분류만 0 쪽으로 끌려 내려간다).
  4) 강도(net/시총 %)는 절대 억원과 순위가 실제로 갈린다.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import etf_class as ec  # noqa: E402


def _etf(**kw):
    base = dict(
        code="000000", name="ETF", listed="2020-01-01", country="한국",
        gubun="시장&전략", big="시장형", mid="코스피", small="코스피200",
        amt=100.0, net=10.0, chg=0.01, price=10000.0, mcap=1000.0,
        mmt_1w=0.02, mmt_1m=0.05, mmt_3m=0.10, mmt_6m=0.20,
        ff_1w=100.0, ff_1m=300.0, ff_3m=900.0, ff_6m=1500.0,
        interest=False,
    )
    base.update(kw)
    return base


# ── 1) 겹치는 창 → 겹치지 않는 구간 ────────────────────────────────────────

def test_interval_net_is_difference_not_the_cumulative_itself():
    """1주 100 · 1개월 300 · 3개월 900 · 6개월 1500 이면 구간은 100/200/600/600."""
    m = ec._etf_metrics(_etf())
    assert m["net_iv"]["1w"] == pytest.approx(100.0)
    assert m["net_iv"]["1m"] == pytest.approx(200.0)
    assert m["net_iv"]["3m"] == pytest.approx(600.0)
    assert m["net_iv"]["6m"] == pytest.approx(600.0)
    # ★항등식 — 이게 깨지면 같은 돈을 두 번 센 것이다.
    assert sum(m["net_iv"].values()) == pytest.approx(m["net_cum"]["6m"])


def test_interval_return_is_a_compound_chain_not_a_subtraction():
    m = ec._etf_metrics(_etf())
    # 1주~1개월 = (1.05/1.02)-1 = +2.94%  (빼기였다면 +3.00%)
    assert m["ret_iv"]["1m"] == pytest.approx(1.05 / 1.02 - 1)
    assert m["ret_iv"]["1m"] != pytest.approx(0.03)
    prod = 1.0
    for k in ("1w", "1m", "3m", "6m"):
        prod *= 1 + m["ret_iv"][k]
    assert prod == pytest.approx(1 + m["ret_cum"]["6m"])


def test_missing_cumulative_does_not_invent_a_value():
    m = ec._etf_metrics(_etf(ff_3m=None, mmt_3m=None))
    assert m["net_iv"]["3m"] is None
    assert m["ret_iv"]["3m"] is None
    # -100% 는 나눌 수 없다 — 체인 대신 결측을 낸다.
    assert ec._chain(0.1, -1.0) is None


# ── 2) 집계 ────────────────────────────────────────────────────────────────

def test_group_return_is_cap_weighted_and_skips_missing_in_the_denominator():
    """수익률이 없는 종목의 시총은 분모에 남으면 안 된다."""
    etfs = [
        _etf(code="A", mcap=1000.0, chg=0.10),
        _etf(code="B", mcap=9000.0, chg=None),   # 결측 — 분모에서 빠져야 한다
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    (row,) = rows
    assert row["ret_cum"]["d"] == pytest.approx(0.10)   # 0.10, 0.01 이 아니다
    assert row["ret_cum_eq"]["d"] == pytest.approx(0.10)
    assert row["mcap"] == pytest.approx(10000.0)        # 시총 합계는 그대로


def test_group_net_is_a_plain_sum_and_ratio_is_scaled_by_group_cap():
    etfs = [
        _etf(code="A", mcap=1000.0, net=30.0),
        _etf(code="B", mcap=3000.0, net=-10.0),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    (row,) = rows
    assert row["net_cum"]["d"] == pytest.approx(20.0)
    assert row["ratio_cum"]["d"] == pytest.approx(20.0 / 4000.0 * 100)


def test_amount_and_intensity_actually_reorder_the_ranking():
    """작은 분류에 몰린 돈이 큰 분류의 절대 금액에 묻히는 자리 — 강도가 그걸 뒤집는다."""
    etfs = [
        _etf(code="BIG", mid="큰분류", mcap=1_000_000.0, net=5000.0),
        _etf(code="SML", mid="작은분류", mcap=1_000.0, net=500.0),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    by_amount = sorted(rows, key=lambda r: -r["net_cum"]["d"])[0]["label"]
    by_ratio = sorted(rows, key=lambda r: -r["ratio_cum"]["d"])[0]["label"]
    assert by_amount == "큰분류"
    assert by_ratio == "작은분류"


def test_group_key_carries_the_ancestor_path_so_same_names_do_not_merge():
    """소분류 이름은 중분류가 다르면 겹칠 수 있다 — 키가 조상 경로를 물고 있어야 한다."""
    etfs = [
        _etf(code="A", big="시장형", mid="코스피", small="반도체"),
        _etf(code="B", big="AI 테크", mid="AI 컴퓨팅", small="반도체"),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "small")
    assert len(rows) == 2
    assert {r["key"] for r in rows} == {
        "시장&전략 / 시장형 / 코스피 / 반도체",
        "시장&전략 / AI 테크 / AI 컴퓨팅 / 반도체",
    }
    # 라벨은 둘 다 '반도체' — 화면은 path 로 구별한다.
    assert {r["label"] for r in rows} == {"반도체"}


def test_blank_classification_becomes_its_own_bucket_not_a_silent_drop():
    etfs = [_etf(code="A", mid=""), _etf(code="B", mid="코스피")]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    assert {r["label"] for r in rows} == {"미분류", "코스피"}
    assert sum(r["n"] for r in rows) == 2


# ── 3) 워크북이 결측 대신 0 을 주는 자리 ────────────────────────────────────

def test_period_return_before_listing_is_missing_not_zero():
    """★워크북 CTD("RATE")는 창 시작에 종목이 없으면 0.0 을 준다 — 결측이 아니다.

    그대로 두면 "이 분류는 3개월간 0% 였다"는 거짓 문장이 되고, 신규 대형 ETF 가 끼면
    분류 평균을 통째로 0 쪽으로 끌어내린다(2026-08-19 '단일종목' 3개월 0.00% 가 그 사례).
    """
    # 창(2026-05-31~) 이후에 상장 → 그 창의 수익률은 없는 것이다
    assert ec._valid_return(0.0, "2026-06-20", "2026-05-31") is None
    # 창 전부터 있었는데 정확히 0.0 → 거래정지·데이터 공백. 실제 시세로는 안 나온다.
    assert ec._valid_return(0.0, "2017-03-21", "2026-05-31") is None
    # 값이 있으면 상장이 늦어도 그대로 쓴다? 아니다 — 창을 못 채운 수익률은 비교 불가.
    assert ec._valid_return(0.05, "2026-06-20", "2026-05-31") is None
    # 정상
    assert ec._valid_return(0.05, "2020-01-01", "2026-05-31") == 0.05
    # 창 날짜를 모르면 판단하지 않는다(값을 버리지 않는다)
    assert ec._valid_return(0.05, "", None) == 0.05


def test_masked_return_is_dropped_from_the_group_average_not_counted_as_zero():
    etfs = [
        _etf(code="OLD", mcap=1000.0, chg=0.10, mmt_3m=0.10, listed="2020-01-01"),
        _etf(code="NEW", mcap=9000.0, chg=0.10, mmt_3m=None, listed="2026-08-01"),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "mid")
    (row,) = rows
    # 9000 짜리가 0 으로 들어왔다면 0.01 이 됐을 자리
    assert row["ret_cum"]["3m"] == pytest.approx(0.10)


# ── 4) 분류 라벨 표기 접기 ──────────────────────────────────────────────────

def test_labels_that_differ_only_in_spelling_are_one_group():
    """`Top10`/`TOP10` 은 한 워크북 안에서도 둘 다 나온다(2026-08-31 실측)."""
    etfs = [
        _etf(code="A", small="Top10", mcap=1000.0, net=10.0),
        _etf(code="B", small="TOP10", mcap=1000.0, net=20.0),
        _etf(code="C", small="탑텐", mcap=1000.0, net=5.0),
    ]
    rows = ec._group(etfs, [ec._etf_metrics(e) for e in etfs], "small")
    assert len(rows) == 2
    top = [r for r in rows if r["n"] == 2][0]
    assert top["net_cum"]["d"] == pytest.approx(30.0)
    # 표시는 접은 결과가 아니라 처음 만난 원래 철자로
    assert top["label"] == "Top10"


def test_each_etf_carries_the_group_key_it_was_actually_put_in():
    """화면은 이 키로 조인한다 — 접힌 쪽도 대표 철자 키를 가리켜야 상세 표가 안 빈다."""
    etfs = [
        _etf(code="A", small="Top10"),
        _etf(code="B", small="TOP10"),
    ]
    metrics = [ec._etf_metrics(e) for e in etfs]
    rows = ec._group(etfs, metrics, "small")
    (row,) = rows
    assert etfs[0]["_gkeys"]["small"] == row["key"]
    assert etfs[1]["_gkeys"]["small"] == row["key"]


# ── 5) 워크북 판독 캐시 ─────────────────────────────────────────────────────

def test_read_cache_is_keyed_by_path_not_just_mtime_and_size(tmp_path, monkeypatch):
    """★`seed_archive` 가 같은 함수로 백업본 여러 장을 훑는다. 캐시 키에 경로가 없으면
    크기·시각이 우연히 겹친 다른 워크북의 스냅샷을 정본으로 내놓을 수 있고, 그러면
    화면 전체가 조용히 다른 날을 말한다."""
    calls = []

    def fake_stat(path):
        calls.append(path)
        class S:  # 두 파일이 mtime·size 가 **같은** 상황을 일부러 만든다
            st_mtime_ns = 1
            st_size = 100
        return S()

    monkeypatch.setattr(ec.os, "stat", fake_stat)
    ec._CACHE["key"] = (os.path.abspath("/a/first.xlsm"), 1, 100)
    ec._CACHE["snap"] = {"asof": "2026-01-01", "etfs": []}

    # 같은 경로 → 캐시 적중
    assert ec._read_snapshot("/a/first.xlsm")["asof"] == "2026-01-01"

    # 다른 경로인데 mtime·size 가 같다 → **적중하면 안 된다**. 실제 판독으로 넘어가
    # 파일이 없어 터지는 것이 정답이다(엉뚱한 스냅샷을 내놓는 것보다 낫다).
    with pytest.raises(Exception):
        ec._read_snapshot("/a/second.xlsm")

    ec._CACHE["key"] = None
    ec._CACHE["snap"] = None


# ── 6) 일평균 환산 분모 ─────────────────────────────────────────────────────

def test_weekday_count_excludes_the_window_start_and_weekends():
    """FF 창의 시작일은 기준선이라 합계에 안 들어간다 — 분모에서도 빼야 한다.

    실측: 1주 창 08/24(월)~08/31(월) 의 daily 리포트는 08/25·26·27·28·31 다섯 장.
    """
    assert ec._weekdays_between("2026-08-24", "2026-08-31") == 5
    # 1개월 창 07/31(금)~08/31(월) → 08/03 ~ 08/31 의 평일
    assert ec._weekdays_between("2026-07-31", "2026-08-31") == 21
    # 주말만 걸친 창
    assert ec._weekdays_between("2026-08-28", "2026-08-31") == 1
    # 날짜가 없거나 뒤집히면 0 (호출부가 max(...,1) 로 막는다)
    assert ec._weekdays_between(None, "2026-08-31") == 0
    assert ec._weekdays_between("2026-08-31", "2026-08-24") == 0
