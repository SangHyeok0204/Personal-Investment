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


# ── ★2026-10-04 분기 총 투자금액 × 밸류체인 L1 ────────────────────────────────

TMAP = {"XX": ("디지털·컴퓨팅", "#4F5AA8"), "BRK-A": ("금융", "#2E5B88")}
PALETTE = [("금융", "#2E5B88"), ("디지털·컴퓨팅", "#4F5AA8")]


def test_quarter_l1_totals_and_shares_sum_to_one():
    label = {**LABEL, "B": {"cusip": "B", "name": "BERKSHIRE", "ticker": "BRK.A"},   # 클래스 표기 BRK.A ↔ BRK-A
             "Z": {"cusip": "Z", "name": "NO TICKER", "ticker": None}}             # 티커 없음 → 미분류
    usd = {(Q1, "a"): {"X": 600.0, "Y": 400.0}, (Q1, "b"): {"B": 1000.0},
           (Q2, "a"): {"X": 300.0, "Z": 100.0}}
    d = gf.GuruData(gurus=dict(GURUS), mat=gf.normalize(usd), label=label, usd=usd)
    q1, q2 = gf.quarter_l1(d, [Q1, Q2], TMAP, PALETTE)
    assert q1["total_usd"] == 2000.0 and q1["n_filed"] == 2                  # 거장들 보유 금액 합
    assert q2["total_usd"] == 400.0 and q2["n_filed"] == 1                   # 안 낸 b 는 이월하지 않는다
    by1 = {s["l1"]: s for s in q1["segments"]}
    assert [s["l1"] for s in q1["segments"]] == ["금융", "디지털·컴퓨팅", gf.UNCLASSIFIED]   # 범례 순, 미분류 끝
    assert by1["금융"]["usd"] == 1000.0 and by1["금융"]["share"] == 0.5
    assert by1[gf.UNCLASSIFIED]["usd"] == 400.0 and q1["unclassified_share_pct"] == 20.0   # YY 는 L1 없음
    for q in (q1, q2):
        assert abs(sum(s["share"] for s in q["segments"]) - 1.0) < 1e-12        # 미분류 포함 합 = 1
    assert {s["l1"]: s["share_pct"] for s in q2["segments"]} == {"디지털·컴퓨팅": 75.0, gf.UNCLASSIFIED: 25.0}


def test_quarter_l1_share_pct_is_bp_over_100():
    # 서버 % 변환: 몫(분수) × 100 = %, 소수 2자리. 1/3 → 33.33%(= 3333bp / 100)
    usd = {(Q1, "a"): {"X": 1.0, "Y": 2.0}}
    d = gf.GuruData(gurus=dict(GURUS), mat=gf.normalize(usd), label=LABEL, usd=usd)
    (q,) = gf.quarter_l1(d, [Q1], TMAP, PALETTE)
    seg = {s["l1"]: s for s in q["segments"]}["디지털·컴퓨팅"]
    assert seg["share_pct"] == 33.33 and round(d.mat[(Q1, "a")]["X"]) / 100 == seg["share_pct"]


def test_quarterly_l1_endpoint_matches_loader_totals(client, db, monkeypatch):
    from app.api import guru as guru_api
    from app.core import valuechain as vc
    monkeypatch.setattr(vc, "ticker_l1_map", lambda: {"AAPL": ("디지털·컴퓨팅", "#4F5AA8")})
    monkeypatch.setattr(vc, "l1_palette", lambda: [("디지털·컴퓨팅", "#4F5AA8")])
    guru_api._cache.clear()
    db.execute(text("INSERT INTO guru_roster (cik, guru_name, firm, filer_name, kind) "
                    "VALUES ('0000000001', 'A', 'A', 'A', 'guru'), ('0000000002', 'B', 'B', 'B', 'guru')"))
    db.execute(text(
        "INSERT INTO sec_filings (form_type, accession_number, filing_date, period_of_report, watch_cik) VALUES "
        "('13F-HR', 'a1', '2026-05-15', '2026-03-31', '0000000001'), ('13F-HR', 'b1', '2026-05-15', '2026-03-31', '0000000002'), "
        "('13F-HR', 'a2', '2026-08-14', '2026-06-30', '0000000001'), ('13F-HR', 'b2', '2026-08-14', '2026-06-30', '0000000002')"))
    db.execute(text("INSERT INTO cusip_map (cusip, ticker) VALUES ('037833100', 'AAPL')"))
    db.execute(text(
        "INSERT INTO holdings_13f (accession_number, seq, cusip, name_of_issuer, value, shares, shr_type, put_call) VALUES "
        "('a1', 0, '037833100', 'APPLE', 300000000, 1000000, 'SH', NULL), "
        "('b1', 0, '99999X999', 'UNMAPPED', 100000000, 1000000, 'SH', NULL), "
        "('a2', 0, '037833100', 'APPLE', 150000, 1000000, 'SH', NULL), "                 # 천 달러 → $150M
        "('b2', 0, '99999X999', 'UNMAPPED', 50000000, 1000000, 'SH', NULL)"))
    db.commit()
    body = client.get("/api/v1/research/guru/quarterly-l1").json()
    assert [q["label"] for q in body["quarters"]] == ["26Q1", "26Q2"]               # 오래된 것부터
    q1, q2 = body["quarters"]
    assert q1["total_usd"] == 400_000_000.0 and q2["total_usd"] == 200_000_000.0
    assert q1["has_prev"] is False and q2["has_prev"] is True
    assert q2["unclassified_share_pct"] == 25.0                                      # CUSIP 미해석 → 미분류
    assert abs(sum(s["share"] for s in q2["segments"]) - 1.0) < 1e-12
    data = load_guru_data(db)                                                        # 거장별 보유표와 맞는다
    assert q2["total_usd"] == sum(sum(b.values()) for (p, _), b in data.usd.items() if p == date(2026, 6, 30))
