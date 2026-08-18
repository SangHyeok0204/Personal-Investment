"""guru_flows 회귀 테스트.

라이브 DB(S:) 에 의존하지 않는다. 개발 중 실제로 밟았던 함정만 골라
합성 픽스처로 고정한다. 전부 "조용히 틀리는" 부류라 눈으로는 안 잡힌다.

  1) 단위 혼재(천달러/달러)가 wgt 정규화로 상쇄되는가
  2) 최신 분기 제출률이 낮으면 그 분기를 건너뛰는가
  3) 한 분기만 제출한 거장이 '전 종목 신규편입'을 만들지 않는가
  4) 13F-HR/A 정정본이 원본을 덮는가
  5) put_call(옵션) 행이 제외되는가
  6) 주식 클래스(GOOG/GOOGL)가 병합되는가
  7) agreement 가 합의(1.0)와 분열(0.0)을 가르는가
  8) 섹터 매핑률이 분기 간 다르면 unclassified_unreliable 이 서는가
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import guru_flows as gf  # noqa: E402
from collector import guru_queries as gq  # noqa: E402

Q1 = "2025-12-31"
Q2 = "2026-03-31"
Q3 = "2026-06-30"          # 공시 러시 전 = 제출률 낮은 분기
GOOGL = "02079K305"
GOOG = "02079K107"          # _SHARE_CLASS_MERGE 로 GOOGL 에 병합돼야 함


def _mkdb(path: str, filings: list[tuple], holdings: list[tuple],
          refs: list[tuple] = ()) -> None:
    """filings/holdings_13f/cusip_ref 최소 스키마로 픽스처 DB 생성."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE filings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            form_type TEXT, accession_number TEXT, filing_date TEXT,
            period_of_report TEXT, watch_cik TEXT, watch_name TEXT);
        CREATE TABLE holdings_13f (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accession_number TEXT, name_of_issuer TEXT, cusip TEXT,
            value REAL, shares REAL, put_call TEXT);
        CREATE TABLE cusip_ref (cusip TEXT PRIMARY KEY, name TEXT, ticker TEXT);
        """)
    con.executemany(
        "INSERT INTO filings (form_type, accession_number, filing_date, "
        "period_of_report, watch_cik, watch_name) VALUES ('13F',?,?,?,?,?)",
        filings)
    con.executemany(
        "INSERT INTO holdings_13f (accession_number, name_of_issuer, cusip, "
        "value, shares, put_call) VALUES (?,?,?,?,?,?)", holdings)
    con.executemany("INSERT INTO cusip_ref (cusip, name, ticker) VALUES (?,?,?)",
                    refs or [])
    con.commit()
    con.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB 경로를 픽스처로 갈아끼우고, 섹터 맵 캐시를 초기화한다."""
    p = str(tmp_path / "t.db")
    monkeypatch.setattr(gq, "DB_PATH", p, raising=False)
    monkeypatch.setattr(gf, "_SECTOR_MAP", {}, raising=False)
    return p


# ── 1) 단위 혼재 ──────────────────────────────────────────────────────
def test_mixed_currency_units_cancel_out(db):
    """A 는 달러, B 는 천달러로 신고해도 wgt(bp) 는 동일해야 한다.

    13F 는 value 단위가 섞여 있다(관측 68.7% 가 천달러). 절대 value 를 거장
    간에 더하면 천달러 신고자가 1000배로 잡힌다. wgt=value/Σvalue 정규화가
    이를 상쇄하는지 고정한다.
    """
    _mkdb(db,
          [("a1", "2026-05-01", Q2, "0000000001", "A"),
           ("b1", "2026-05-01", Q2, "0000000002", "B")],
          [("a1", "X", "111111111", 7_000_000.0, 1, ""),
           ("a1", "Y", "222222222", 3_000_000.0, 1, ""),
           ("b1", "X", "111111111", 7_000.0, 1, ""),      # 천달러 단위
           ("b1", "Y", "222222222", 3_000.0, 1, "")])
    mat, _ = gf.weight_matrix(["0000000001", "0000000002"], [Q2])
    assert mat[(Q2, "0000000001")] == pytest.approx(mat[(Q2, "0000000002")])
    assert mat[(Q2, "0000000001")]["111111111"] == pytest.approx(7000.0)


# ── 2) 제출률 기반 분기 선택 ──────────────────────────────────────────
def test_low_filing_rate_quarter_is_skipped(db):
    """최신 분기를 1명만 냈으면 그 분기는 비교에서 빠진다.

    공시기한(분기말+45일) 직전 실측에서 23명 중 1명만 제출한 상태였고, 이대로
    쓰면 '참여 거장 1명짜리 합의'가 만들어졌다.
    """
    ciks = [f"{i:010d}" for i in range(1, 5)]
    filings, holdings = [], []
    for i, c in enumerate(ciks):
        for q in (Q1, Q2):
            acc = f"{c}-{q}"
            filings.append((acc, "2026-05-01", q, c, f"G{i}"))
            holdings.append((acc, "X", "111111111", 100.0 + i, 1, ""))
    # Q3 는 1/4 = 25% 만 제출
    filings.append(("solo", "2026-07-31", Q3, ciks[0], "G0"))
    holdings.append(("solo", "X", "111111111", 100.0, 1, ""))
    _mkdb(db, filings, holdings)

    with gq._conn() as c:
        curr, prev, meta = gf.pick_periods(c, ciks)
    assert curr == Q2 and prev == Q1          # Q3 는 건너뛴다
    q3 = next(m for m in meta if m["period"] == Q3)
    assert q3["usable"] is False and q3["filed_pct"] == 25.0


# ── 3) 분기 결측 거장 제외 ────────────────────────────────────────────
def test_partial_filer_excluded_from_participants(db):
    """직전 분기를 안 낸 거장은 참여에서 빠진다.

    빼지 않으면 그 거장의 보유 전 종목이 '신규 편입'으로 잡혀 편입 합의가
    통째로 부풀려진다.
    """
    filings = [("a1", "2026-02-01", Q1, "0000000001", "A"),
               ("a2", "2026-05-01", Q2, "0000000001", "A"),
               ("b2", "2026-05-01", Q2, "0000000002", "B")]   # B 는 Q2 만
    holdings = [("a1", "X", "111111111", 100.0, 1, ""),
                ("a2", "X", "111111111", 100.0, 1, ""),
                ("b2", "Z", "333333333", 100.0, 1, "")]
    _mkdb(db, filings, holdings)
    r = gf.entries_exits(["0000000001", "0000000002"], curr=Q2, prev=Q1)
    assert r["n_participants"] == 1
    assert r["excluded"] == ["0000000002"]
    assert r["entries"] == []                 # B 의 Z 가 신규로 새면 안 된다


# ── 4) 13F-HR/A 정정본 ────────────────────────────────────────────────
def test_amended_filing_supersedes_original(db):
    """같은 (cik, period) 에 2건이면 filing_date 가 늦은 쪽만 쓴다."""
    _mkdb(db,
          [("orig", "2026-05-01", Q2, "0000000001", "A"),
           ("amd", "2026-05-20", Q2, "0000000001", "A")],
          [("orig", "X", "111111111", 100.0, 1, ""),
           ("amd", "X", "111111111", 50.0, 1, ""),
           ("amd", "Y", "222222222", 50.0, 1, "")])
    mat, _ = gf.weight_matrix(["0000000001"], [Q2])
    book = mat[(Q2, "0000000001")]
    assert set(book) == {"111111111", "222222222"}   # 정정본 구성
    assert book["111111111"] == pytest.approx(5000.0)


# ── 5) 옵션 행 제외 ───────────────────────────────────────────────────
def test_put_call_rows_excluded(db):
    """put/call 행은 제외한다. 13F 는 롱 신고라 파생을 섞으면 비중이 왜곡된다.

    ★ 옵션 행은 **다른 CUSIP** 이어야 한다. 같은 CUSIP 에 두면 필터가 있든 없든
      그 종목이 책 전체를 차지해 10000bp 가 나와 테스트가 아무것도 증명하지 못한다
      (변이 테스트로 실제로 걸러낸 결함).
    """
    _mkdb(db, [("a1", "2026-05-01", Q2, "0000000001", "A")],
          [("a1", "X", "111111111", 100.0, 1, ""),
           ("a1", "Y", "222222222", 900.0, 1, "Put")])
    mat, _ = gf.weight_matrix(["0000000001"], [Q2])
    book = mat[(Q2, "0000000001")]
    assert set(book) == {"111111111"}          # 옵션 종목은 아예 없어야 한다
    assert book["111111111"] == pytest.approx(10000.0)


# ── 6) 주식 클래스 병합 ───────────────────────────────────────────────
def test_share_classes_merged(db):
    """GOOG 와 GOOGL 은 한 종목으로 합친다."""
    assert gq._SHARE_CLASS_MERGE.get(GOOG) == GOOGL      # 전제 확인
    _mkdb(db, [("a1", "2026-05-01", Q2, "0000000001", "A")],
          [("a1", "ALPHABET A", GOOGL, 60.0, 1, ""),
           ("a1", "ALPHABET C", GOOG, 40.0, 1, "")])
    mat, _ = gf.weight_matrix(["0000000001"], [Q2])
    book = mat[(Q2, "0000000001")]
    assert set(book) == {GOOGL}
    assert book[GOOGL] == pytest.approx(10000.0)


# ── 7) agreement: 합의 vs 분열 ────────────────────────────────────────
def _two_by_two(db, deltas):
    """거장 4명이 X 를 각자 deltas 만큼 조정한 픽스처. deltas 는 bp 부호만 의미."""
    ciks = [f"{i:010d}" for i in range(1, 5)]
    filings, holdings = [], []
    for i, c in enumerate(ciks):
        for q, xv in ((Q1, 500.0), (Q2, 500.0 + deltas[i])):
            acc = f"{c}-{q}"
            filings.append((acc, "2026-05-01", q, c, f"G{i}"))
            holdings.append((acc, "X", "111111111", xv, 1, ""))
            holdings.append((acc, "F", "999999999", 1000.0 - xv, 1, ""))  # 채움
    _mkdb(db, filings, holdings)
    return ciks


def test_agreement_unanimous_is_one(db):
    """전원 같은 방향이면 agreement = 1.0."""
    ciks = _two_by_two(db, [50.0, 60.0, 70.0, 80.0])
    r = gf.rebalance_intensity(ciks, curr=Q2, prev=Q1, baseline_quarters=0)
    x = next(row for row in r["rows"] if row["cusip"] == "111111111")
    assert x["movers"] == 4 and x["buyers"] == 4 and x["sellers"] == 0
    assert x["agreement"] == pytest.approx(1.0)


def test_agreement_split_is_zero(db):
    """정확히 반반 갈리면 agreement = 0.0 — movers 만 보면 합의로 오독한다."""
    ciks = _two_by_two(db, [50.0, 50.0, -50.0, -50.0])
    r = gf.rebalance_intensity(ciks, curr=Q2, prev=Q1, baseline_quarters=0)
    x = next(row for row in r["rows"] if row["cusip"] == "111111111")
    assert x["movers"] == 4 and x["buyers"] == 2 and x["sellers"] == 2
    assert x["agreement"] == pytest.approx(0.0)
    assert x["gross_bp"] > 0                  # 총량은 남는다


# ── 8) 섹터 커버리지 격차 경보 ────────────────────────────────────────
def test_coverage_gap_flags_unclassified(db, monkeypatch):
    """분기 간 매핑률이 다르면 미분류 순변화는 아티팩트다.

    실측에서 커버리지 82.3%→88.7%(6.4%p) 격차가 미분류 -643bp/거장 이라는
    가짜 이동을 만들었다. 격차가 있으면 반드시 플래그가 서야 한다.
    """
    filings, holdings = [], []
    for q, cu in ((Q1, "AAAAAAAAA"), (Q2, "BBBBBBBBB")):
        acc = f"a-{q}"
        filings.append((acc, "2026-05-01", q, "0000000001", "A"))
        holdings.append((acc, "N", cu, 100.0, 1, ""))
    _mkdb(db, filings, holdings)
    # B 만 매핑 → prev 커버리지 0%, curr 100%
    monkeypatch.setattr(gf, "_SECTOR_MAP", {"BBBBBBBBB": "정보기술"}, raising=False)
    r = gf.sector_flows(["0000000001"], curr=Q2, prev=Q1)
    assert r["coverage_prev"] == 0.0 and r["coverage_curr"] == 100.0
    assert r["coverage_gap"] == 100.0
    assert r["unclassified_unreliable"] is True
