"""계획 A5 — 거장 13F 분기 변동 분석(순수 함수) + 불러오기(정정·단위 보정)."""
from datetime import date

from sqlalchemy import text

from app.api.guru import load_guru_data
from app.core import guru_flows as gf

Q1, Q2, Q3 = date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30)
GURUS = {c: {"guru": c.upper(), "firm": ""} for c in ("a", "b", "c", "d")}
LABEL = {"X": {"cusip": "X", "name": "X CO", "ticker": "XX"},
         "Y": {"cusip": "Y", "name": "Y CO", "ticker": "YY"},
         "02079K305": {"cusip": "02079K305", "name": "ALPHABET", "ticker": "GOOGL"}}


def _data(mat):
    return gf.GuruData(gurus=dict(GURUS), mat=gf.normalize(mat), label=LABEL)


def test_quorum_skips_thin_latest_quarter():
    # Q3 은 4명 중 1명만 냈다(25% < 50%) → 비교는 Q2 vs Q1
    d = _data({(Q1, "a"): {"X": 1}, (Q1, "b"): {"X": 1}, (Q1, "c"): {"X": 1},
               (Q2, "a"): {"X": 1}, (Q2, "b"): {"X": 1}, (Q2, "c"): {"X": 1}, (Q3, "a"): {"Y": 1}})
    assert gf.usable_periods(d) == [Q2, Q1]
    meta = gf.period_meta(d)
    assert meta[0]["label"] == "26Q3" and meta[0]["usable"] is False and meta[0]["n_filed"] == 1


def test_missing_quarter_not_carried_and_excluded():
    # b 는 Q2 를 안 냈다 → 참여자 아님(전 종목 '방출'로 잡히면 안 된다)
    d = _data({(Q1, "a"): {"X": 1}, (Q1, "b"): {"X": 1, "Y": 1}, (Q2, "a"): {"X": 1, "Y": 1}})
    assert gf.participants(d, Q2, Q1) == ["a"]
    ee = gf.entries_exits(d, Q2, Q1)
    assert [r["key"] for r in ee["entries"]] == ["Y"] and ee["exits"] == []


def test_rebalance_gross_net_agreement():
    d = _data({(Q1, "a"): {"X": 50, "Y": 50}, (Q2, "a"): {"X": 80, "Y": 20},
               (Q1, "b"): {"X": 50, "Y": 50}, (Q2, "b"): {"X": 20, "Y": 80}})
    rows = {r["key"]: r for r in gf.rebalance(d, Q2, Q1)}
    x = rows["X"]
    assert x["movers"] == 2 and x["buyers"] == 1 and x["sellers"] == 1
    assert x["gross_bp"] == 6000.0 and x["net_bp"] == 0.0 and x["agreement"] == 0.0   # 분열 — 합의 아님


def test_value_scale_thousands():
    assert gf.value_scale([(150.0, 1000.0), (90.0, 500.0)]) == 1000.0   # 주당 0.15 → 천 달러 단위
    assert gf.value_scale([(150000.0, 1000.0)]) == 1.0
    assert gf.value_scale([]) == 1.0


def test_sector_flows_coverage_gap_flags_unclassified(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text("cusip,sector,ticker\nX,정보기술,XX\n", encoding="utf-8")
    smap = gf.load_sector_map(csv)
    d = _data({(Q1, "a"): {"X": 100}, (Q2, "a"): {"X": 50, "Y": 50}})
    sf = gf.sector_flows(d, Q2, Q1, smap)
    by = {r["sector"]: r["net_bp"] for r in sf["rows"]}
    assert by == {"정보기술": -5000.0, gf.UNCLASSIFIED: 5000.0}
    assert sf["coverage_prev"] == 100.0 and sf["coverage_curr"] == 50.0 and sf["unclassified_unreliable"]
    assert sf["rows"][-1]["sector"] == gf.UNCLASSIFIED                 # 미분류는 숨기지 않고 맨 뒤에


def test_sector_falls_back_to_sic_but_csv_wins(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text("cusip,sector,ticker\n02079K305,커뮤니케이션서비스,GOOGL\n", encoding="utf-8")
    smap = gf.load_sector_map(csv)
    d = gf.GuruData(gurus={}, mat={}, label={
        "02079K305": {"cusip": "02079K305", "ticker": "GOOGL", "name": "", "sector": "정보기술"},   # SIC 7370
        "Y": {"cusip": "Y", "ticker": "YY", "name": "", "sector": "헬스케어"},
        "Z": {"cusip": "Z", "ticker": None, "name": "", "sector": None}})
    assert gf.sector_of(d, "02079K305", smap) == "커뮤니케이션서비스"   # CSV 가 먼저
    assert gf.sector_of(d, "Y", smap) == "헬스케어"                     # CSV 에 없으면 SIC
    assert gf.sector_of(d, "Z", smap) == gf.UNCLASSIFIED


def test_my_holdings_merges_share_class_and_counts_filers():
    d = _data({(Q1, "a"): {"02079K305": 10, "X": 90}, (Q2, "a"): {"02079K305": 30, "X": 70},
               (Q2, "b"): {"X": 100}})
    mine = {r["ticker"]: r for r in gf.my_holdings(d, Q2, Q1, [("GOOG", "Alphabet C"), ("ZZ", None)])}
    g = mine["GOOG"]                                   # 내 GOOG ↔ 거장 GOOGL
    assert g["n_gurus"] == 1 and g["avg_bp"] == 1500.0  # (3000 + 0) / Q2 에 낸 2명
    assert g["delta_bp"] == 2000.0                      # 두 분기 모두 낸 a 만
    assert mine["ZZ"]["n_gurus"] == 0


def test_stock_trend_none_for_unfiled_quarter():
    d = _data({(Q1, "a"): {"X": 100}, (Q2, "b"): {"X": 100}})
    rows = {r["cik"]: r["points"] for r in gf.stock_trend(d, "XX", [Q1, Q2])}
    assert rows == {"a": [10000.0, None], "b": [None, 10000.0]}


def test_loader_merges_new_holdings_with_unit_correction(db):
    """원 공시(천 달러) + NEW HOLDINGS 추가분(달러) → 단위 맞춰 합친 비중. 원본 규칙이면 추가분 1종목만 남는다."""
    db.execute(text(
        "INSERT INTO guru_roster (cik, guru_name, firm, filer_name, kind) VALUES ('0001067983', 'Buffett', 'BRK', 'BRK', 'guru')"))
    db.execute(text(
        "INSERT INTO sec_filings (form_type, accession_number, filing_date, period_of_report, watch_cik, amendment_type) "
        "VALUES ('13F-HR', 'o', '2023-11-14', '2023-09-30', '0001067983', NULL), "
        "('13F-HR/A', 'n', '2024-05-15', '2023-09-30', '0001067983', 'NEW HOLDINGS')"))
    db.execute(text(
        "INSERT INTO holdings_13f (accession_number, seq, cusip, name_of_issuer, value, shares, shr_type, put_call) VALUES "
        "('o', 0, '037833100', 'APPLE', 150000, 1000000, 'SH', NULL), "      # 천 달러 → $150M
        "('o', 1, '037833100', 'APPLE CALL', 999999, 1, 'SH', 'Call'), "      # 옵션 제외
        "('o', 2, '000000000', 'BOND', 999999, 1, 'PRN', NULL), "             # 채권 제외
        "('n', 0, '14040H105', 'CHUBB', 50000000, 250000, 'SH', NULL)"))      # 달러 → $50M
    db.commit()
    d = load_guru_data(db)
    book = d.mat[(date(2023, 9, 30), "0001067983")]
    assert book == {"037833100": 7500.0, "14040H105": 2500.0}
