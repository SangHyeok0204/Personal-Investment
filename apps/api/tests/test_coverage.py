"""계획 S8 — 데이터 보유 현황판 API. 라우터가 아직 `main.py` 에 안 붙어 있어(레인 C·리드가
나중에 통합) 여기서만 얹은 맨 FastAPI 앱으로 검증한다."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.coverage import router
from app.core import valuechain as vc
from app.core.errors import register_exception_handlers
from app.db.session import get_db
from app.models import Account, Asset, Broker, BrokerageConnection, CurrentPosition


@pytest.fixture
def api(db):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c


def _hold(db, ticker: str) -> None:
    broker_id, conn_id, acc_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db.add(Broker(id=broker_id, code="KIWOOM", name="키움증권"))
    db.flush()
    db.add(BrokerageConnection(id=conn_id, broker_id=broker_id, connection_name="주계좌",
                               environment="REAL", status="CONNECTED"))
    db.flush()
    db.add(Account(id=acc_id, broker_id=broker_id, brokerage_connection_id=conn_id,
                   external_account_id="0000", account_number_masked="0000-**",
                   account_name="시험 계좌", base_currency="KRW", is_active=True))
    db.add(Asset(id=asset_id, country="US", market="US", ticker=ticker, name=ticker,
                 asset_type="STOCK", currency="USD"))
    db.flush()
    db.add(CurrentPosition(id=uuid.uuid4(), account_id=acc_id, asset_id=asset_id, quantity=Decimal("3"),
                           as_of=datetime(2026, 9, 27, tzinfo=timezone.utc)))
    db.commit()


def test_unknown_kind_is_422(api):
    assert api.get("/api/v1/research/coverage/bogus").status_code == 422


def test_guru_coverage(api, db):
    db.execute(text(
        "INSERT INTO guru_roster (cik, firm, filer_name, kind, active) VALUES "
        "('0000000001', 'A펀드', 'A', 'guru', true), ('0000000002', 'B펀드', 'B', 'guru', true)"))
    db.execute(text(
        "INSERT INTO sec_filings (form_type, accession_number, period_of_report, watch_cik) VALUES "
        "('13F-HR', 'acc-a-q1', '2026-03-31', '0000000001'), "
        "('13F-HR', 'acc-b-q1', '2026-03-31', '0000000002'), "
        "('13F-HR', 'acc-a-q2', '2026-06-30', '0000000001')"))  # B 는 최신 분기 미제출
    db.execute(text(
        "INSERT INTO holdings_13f (accession_number, cusip, value, shares) VALUES "
        "('acc-a-q2', '000000001', 100, 10), ('acc-a-q2', '000000002', 200, 20)"))
    db.execute(text(
        "INSERT INTO cusip_map (cusip, ticker, confidence) VALUES "
        "('000000001', 'AAA', 'high'), ('000000002', NULL, 'none')"))
    db.execute(text(
        "INSERT INTO source_status (source, kind, last_ok_at) VALUES "
        "('sec_13f', 'source', :t)"), {"t": datetime.now(timezone.utc)})
    db.commit()

    r = api.get("/api/v1/research/coverage/guru")
    assert r.status_code == 200
    d = r.json()
    assert d["kind"] == "guru"
    kpi = {k["label"]: k["value"] for k in d["kpis"]}
    assert kpi["활성/전체 구루"] == "2/2"
    assert kpi["13F 접수"] == "3건"
    assert kpi["최신 분기 제출"] == "1/2"
    assert kpi["holdings 행"] == "2행"
    assert kpi["CUSIP 해석률"] == "50.0%"
    assert d["table"]["columns"] == ["26Q1", "26Q2"]
    rows = {row["key"]: row["cells"] for row in d["table"]["rows"]}
    assert rows["0000000001"] == [True, True]
    assert rows["0000000002"] == [True, False]
    src = {s["source"]: s for s in d["sources"]}
    assert src["sec_13f"]["stale"] is False
    assert src["openfigi"]["last_ok_at"] is None and src["openfigi"]["stale"] is True


def test_earnings_coverage(api, db):
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'NVDA')"), {"i": uuid.uuid4()})
    up = db.execute(text(
        "INSERT INTO earnings_events (ticker, quarter, report_date, source) VALUES "
        "('NVDA', '2026Q2', '2026-05-28', 'nasdaq') RETURNING id")).scalar()
    past = db.execute(text(
        "INSERT INTO earnings_events (ticker, quarter, report_date, source) VALUES "
        "('NVDA', '2026Q1', '2026-02-25', 'nasdaq') RETURNING id")).scalar()
    db.execute(text(
        "INSERT INTO earnings_results (event_id, eps_actual, source) VALUES (:e, 1.1, 'nasdaq')"), {"e": past})
    db.execute(text(
        "INSERT INTO earnings_watchpoints (ticker, quarter, rank, source, result) VALUES "
        "('NVDA', '2026Q1', 1, 'import', '채워짐'), ('NVDA', '2026Q2', 1, 'llm', NULL)"))
    db.execute(text(
        "INSERT INTO earnings_guidance (event_id, metric) VALUES (:e, '매출')"), {"e": past})
    db.commit()

    r = api.get("/api/v1/research/coverage/earnings")
    assert r.status_code == 200
    d = r.json()
    kpi = {k["label"]: k["value"] for k in d["kpis"]}
    assert kpi["추적 종목"] == "1/1"
    assert kpi["이벤트"] == "2건"
    assert kpi["결과 보유율"] == "1/2"
    assert kpi["워치포인트"] == "2건"
    assert "import 1" in next(k["hint"] for k in d["kpis"] if k["label"] == "워치포인트")
    assert "콜 트랜스크립트" not in kpi  # 무료 원천 없음 → 카드 자체를 두지 않는다(0 으로 채우지 않음)
    row = next(row for row in d["table"]["rows"] if row["key"] == "NVDA")
    assert row["cells"] == ["결과", "이벤트"]  # 2026Q1(결과), 2026Q2(이벤트만)


def test_filings_coverage(api, db):
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'NVDA')"), {"i": uuid.uuid4()})
    db.execute(text(
        "INSERT INTO form4_transactions (accession_number, issuer_cik, ticker, transaction_date) VALUES "
        "('f4-1', '0000070858', 'NVDA', '2026-01-15'), "
        "('f4-2', '0000070858', 'NVDA', :future)"), {"future": date.today() + timedelta(days=5)})
    db.execute(text(
        "INSERT INTO sec_filings (form_type, accession_number, issuer_cik, filing_date) VALUES "
        "('4', 'f4-1', '0000070858', '2026-01-15'), "
        "('13G', 'f13g-1', '0000070858', '2026-02-01')"))
    db.commit()

    r = api.get("/api/v1/research/coverage/filings")
    assert r.status_code == 200
    d = r.json()
    kpi = {k["label"]: k["value"] for k in d["kpis"]}
    assert kpi["Form 4"] == "1건"
    assert kpi["13G"] == "1건"
    assert kpi["form4_transactions"] == "2행"
    assert d["anomalies"] == ["미래 날짜 Form4 거래 1건(데이터 오류)"]
    row = next(row for row in d["table"]["rows"] if row["key"] == "NVDA")
    assert row["cells"] == [1, 0, 0, 1]  # Form4, Form4/A, 13D, 13G


def test_stocks_coverage(api, db):
    _hold(db, "NVDA")
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'AMD')"), {"i": uuid.uuid4()})
    db.execute(text(
        "INSERT INTO earnings_events (ticker, quarter, source) VALUES ('NVDA', '2026Q2', 'nasdaq')"))
    db.execute(text(
        "INSERT INTO form4_transactions (accession_number, ticker) VALUES ('f4-x', 'NVDA')"))
    db.commit()

    r = api.get("/api/v1/research/coverage/stocks")
    assert r.status_code == 200
    d = r.json()
    kpi = {k["label"]: k["value"] for k in d["kpis"]}
    assert kpi["커버 종목(보유+관심)"] == "2종목"
    assert kpi["소스별 보유 종목"] == "1/2"
    rows = {row["key"]: row for row in d["table"]["rows"]}
    assert rows["NVDA"]["cells"][0] == 1  # 실적 이벤트
    assert rows["NVDA"]["cells"][2] == 1  # Form4 거래
    # storage/valuechain 실데이터 — 테마(bio) 먼저, 분류(generated/tx-digital) 다음
    assert rows["NVDA"]["cells"][-1] == "바이오 › 파운데이션 모델 / 디지털·컴퓨팅 › 반도체 칩제품"
    assert rows["NVDA"]["link"] == "/research/earnings"  # 실적 이벤트가 있다
    # 13D/G: Form4 거래가 없어 CIK 를 모른다. 밸류체인: 분류 섹터에만 있다
    assert rows["AMD"]["cells"] == [0, 0, 0, 0, None, "디지털·컴퓨팅 › 반도체 칩제품"]
    assert rows["AMD"]["link"] == "/research/filings"  # 실적 이벤트가 없다


VC_TTL = """\
@prefix vc:   <http://ge.local/valuechain#> .
@prefix co:   <http://ge.local/company#> .
@prefix ex:   <http://ge.local/valuechain/example#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Ex a vc:Sector ; vc:code "test" ; rdfs:label "테스트"@ko .

ex:A a vc:Category ; vc:subCategoryOf ex:Ex ; vc:code "A" ; vc:order 1 ; rdfs:label "상류"@ko .

co:US-NVDA a vc:Company ; rdfs:label "NVIDIA"@ko ; vc:ticker "NVDA" ; vc:country "US" ; vc:listed true .
ex:m-US-NVDA a vc:Membership ; vc:company co:US-NVDA ; vc:sector ex:Ex ;
    vc:primaryCategory ex:A ; vc:belongsTo ex:A .
"""


def test_stocks_coverage_valuechain_column(api, db, monkeypatch, tmp_path):
    """밸류체인 열 — storage/valuechain/*.ttl 전체를 로드해 회사 티커로 맞춘다(§7)."""
    (tmp_path / "test.ttl").write_text(VC_TTL, encoding="utf-8")
    monkeypatch.setattr(vc, "VALUECHAIN_DIR", tmp_path)

    _hold(db, "NVDA")
    db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, 'AMD')"), {"i": uuid.uuid4()})
    db.commit()

    r = api.get("/api/v1/research/coverage/stocks")
    assert r.status_code == 200
    d = r.json()
    assert d["table"]["columns"] == ["실적 이벤트", "워치포인트", "Form4 거래", "보유 구루", "13D/G", "밸류체인"]
    rows = {row["key"]: row for row in d["table"]["rows"]}
    assert rows["NVDA"]["cells"][-1] == "테스트 › 상류"
    assert rows["AMD"]["cells"][-1] == "—"


VC_MULTI = """\
@prefix vc:   <http://ge.local/valuechain#> .
@prefix co:   <http://ge.local/company#> .
@prefix ex:   <http://ge.local/valuechain/{code}#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Ex a vc:Sector ; vc:code "{code}" ; vc:kind "{kind}" ; rdfs:label "{code}"@ko .
ex:A a vc:Category ; vc:subCategoryOf ex:Ex ; vc:code "A" ; vc:order 1 ; rdfs:label "상류"@ko .
"""
VC_MEMBER = """
co:US-{t} a vc:Company ; rdfs:label "{t}" ; vc:ticker "{t}" ; vc:country "US" ; vc:listed true .
ex:m-US-{t} a vc:Membership ; vc:company co:US-{t} ; vc:sector ex:Ex ; vc:primaryCategory ex:A ; vc:belongsTo ex:A .
"""


def test_stocks_coverage_valuechain_multi_sector(api, db, monkeypatch, tmp_path):
    """여러 섹터 소속 — 테마 라벨 먼저, 분류(generated/) 라벨 다음, " / " 로 최대 2개."""
    def sector(path, code, kind, tickers):
        path.write_text(VC_MULTI.format(code=code, kind=kind) + "".join(VC_MEMBER.format(t=t) for t in tickers),
                        encoding="utf-8")
    (tmp_path / "generated").mkdir()
    # 파일 이름 순으로는 분류(aa-tx)가 테마보다 먼저 읽혀도 라벨은 테마가 앞선다.
    sector(tmp_path / "generated" / "aa-tx.ttl", "tx-t", "taxonomy", ["NVDA", "AMD", "TEM"])
    sector(tmp_path / "theme1.ttl", "th1", "theme", ["NVDA", "TEM"])
    sector(tmp_path / "theme2.ttl", "th2", "theme", ["TEM"])
    monkeypatch.setattr(vc, "VALUECHAIN_DIR", tmp_path)

    _hold(db, "NVDA")
    for t in ("AMD", "TEM", "MSFT"):
        db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, :t)"), {"i": uuid.uuid4(), "t": t})
    db.commit()

    rows = {row["key"]: row for row in api.get("/api/v1/research/coverage/stocks").json()["table"]["rows"]}
    assert rows["NVDA"]["cells"][-1] == "th1 › 상류 / tx-t › 상류"
    assert rows["AMD"]["cells"][-1] == "tx-t › 상류"                # 분류 전용 → 1개
    assert rows["TEM"]["cells"][-1] == "th1 › 상류 / th2 › 상류"         # 최대 2개(테마 우선)
    assert rows["MSFT"]["cells"][-1] == "—"


def test_stocks_coverage_valuechain_etf_override_only(api, db, monkeypatch, tmp_path):
    """★2026-10-05 '(ETF 지정)' 은 `ETF_L1_OVERRIDES` 에 있는 ETF 에만 붙는다 — 주 소속 분류가 없는
    일반 종목이 ticker_l1_map 에 있어도 지정 ETF 로 둔갑하지 않는다."""
    monkeypatch.setattr(vc, "VALUECHAIN_DIR", tmp_path)           # 분류 없음 → 주 소속 라벨 0개
    monkeypatch.setattr(vc, "ticker_l1_map", lambda: {"SOXL": ("디지털·컴퓨팅", "#4F5AA8"),
                                                      "MSFT": ("디지털·컴퓨팅", "#4F5AA8")})
    for t in ("SOXL", "MSFT"):
        db.execute(text("INSERT INTO watchlist_items (id, ticker) VALUES (:i, :t)"), {"i": uuid.uuid4(), "t": t})
    db.commit()

    rows = {row["key"]: row for row in api.get("/api/v1/research/coverage/stocks").json()["table"]["rows"]}
    assert "SOXL" in vc.ETF_L1_OVERRIDES
    assert rows["SOXL"]["cells"][-1] == "디지털·컴퓨팅 (ETF 지정)"
    assert rows["MSFT"]["cells"][-1] == "—"
