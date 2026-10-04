"""계획 A6 — 내부자 순매수 규칙(비파생 · P/S · 계획매매 제외 · 정정 대체분 제외) + 화면 API."""
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import text

from app.api import insiders as ins

TODAY = date.today()


def _r(**kw):
    base = dict(superseded_by=None, transaction_date=TODAY, is_derivative=False, transaction_code="P",
                is_planned_trade=False, transaction_value=100.0)
    return SimpleNamespace(**{**base, **kw})


def test_exclusion_rules():
    assert ins.exclusion_reason(_r()) is None
    assert ins.exclusion_reason(_r(transaction_code="S")) is None
    assert ins.exclusion_reason(_r(transaction_code="S", is_planned_trade=True)) == "계획매매(10b5-1·ESPP)"
    assert ins.exclusion_reason(_r(transaction_code="A")) == "보상 부여"
    assert ins.exclusion_reason(_r(transaction_code="M")) == "옵션 행사"
    assert ins.exclusion_reason(_r(is_derivative=True)) == "파생(옵션 등)"
    assert ins.exclusion_reason(_r(superseded_by="x")) == "정정으로 대체"
    assert ins.exclusion_reason(_r(transaction_date=TODAY + timedelta(days=400))) == "미래 날짜(데이터 오류)"
    assert ins._signed(_r(transaction_code="S", transaction_value=50)) == -50.0


def test_month_keys_cross_year():
    assert ins._month_keys(date(2026, 2, 10), 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]


def _seed(db):
    aid = uuid.uuid4()
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'NBIS')"), {"i": uuid.uuid4()})
    rows = [
        # (코드, 파생, 계획, 정정, 날짜, 금액, 내부자)
        ("P", False, False, None, TODAY - timedelta(days=5), 1000, "A1"),
        ("P", False, False, None, TODAY - timedelta(days=6), 500, "A2"),       # 두 번째 임원 매수
        ("S", False, True, None, TODAY - timedelta(days=5), 9999, "A3"),       # 계획매도 — 안 센다
        ("S", False, False, None, TODAY - timedelta(days=7), 300, "A3"),
        ("A", False, False, None, TODAY - timedelta(days=5), 7777, "A4"),      # 보상 — 안 센다
        ("P", True, False, None, TODAY - timedelta(days=5), 8888, "A5"),       # 파생 — 안 센다
        ("P", False, False, "amend", TODAY - timedelta(days=5), 6666, "A6"),  # 정정 대체 — 안 센다
        ("P", False, False, None, TODAY + timedelta(days=400), 5555, "A7"),    # 미래 날짜 — 안 센다
    ]
    for i, (code, deriv, plan, sup, d, v, who) in enumerate(rows):
        db.execute(text(
            "INSERT INTO form4_transactions (accession_number, seq, ticker, issuer_cik, insider_cik, insider_name, "
            "transaction_date, transaction_code, transaction_value, is_derivative, is_planned_trade, superseded_by) "
            "VALUES (:a, 0, 'nbis', '0001513845', :who, :who, :d, :c, :v, :der, :pl, :sup)"),
            {"a": f"acc-{i}", "who": who, "d": d, "c": code, "v": v, "der": deriv, "pl": plan, "sup": sup})
    db.execute(text(
        "INSERT INTO sec_filings (form_type, accession_number, filing_date, watch_cik, watch_name, issuer_name, issuer_cik) "
        "VALUES ('13D', 'd1', :d, '0001513845', 'Nebius Group N.V.', 'NEBIUS GROUP N.V.', '0009999999'), "
        "('13D', 'd2', :d, '0001513845', 'Nebius Group N.V.', 'Other Co', '0008888888')"),
        {"d": TODAY - timedelta(days=3)})
    db.commit()
    return aid


def test_overview_counts_only_judgement_trades(client, db):
    _seed(db)
    d = client.get("/api/v1/research/insiders/overview").json()
    assert d["targets"] == ["NBIS"]
    assert d["net_value_window"] == 1000 + 500 - 300
    assert d["buy_count_window"] == 2 and d["sell_count_window"] == 1
    assert d["multi_insider_buys"] == [{"ticker": "NBIS", "n_insiders": 2}]
    assert d["future_dated"] == 1
    assert [x["issuer_name"] for x in d["recent_13d"]] == ["NEBIUS GROUP N.V."]    # 대상이 내 종목인 것만
    months = {m["month"]: m for m in d["monthly"]}
    assert months[(TODAY - timedelta(days=5)).strftime("%Y-%m")]["n_trades"] >= 1   # 거래를 넣은 달 — 월초엔 이번 달이 아니다
    empty = [m for m in d["monthly"] if m["n_trades"] == 0]
    assert empty and all(m["net_value"] is None and m["by_ticker"] == [] for m in empty)  # 거래 없는 달 = 막대 없음


def test_month_lists_excluded_with_reasons(client, db):
    _seed(db)
    mk = (TODAY - timedelta(days=5)).strftime("%Y-%m")
    d = client.get(f"/api/v1/research/insiders/month?month={mk}").json()
    reasons = {t["insider"]: t["excluded_reason"] for t in d["trades"]}
    assert reasons.get("A3") in (None, "계획매매(10b5-1·ESPP)")
    assert reasons.get("A4") == "보상 부여" and reasons.get("A5") == "파생(옵션 등)" and reasons.get("A6") == "정정으로 대체"
    assert all(t["ticker"] == "NBIS" for t in d["trades"])
