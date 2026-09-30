"""국내 ETF 신규상장 — 순수 로직 + 루프 본체(가짜 KRX/DART 전송) + 라우터. 네트워크 없음.

픽스처 `fixtures/etf/*.json` 은 2026-09-30 개인 계정으로 한 번 받은 실제 응답을 줄인 것이다
(자격증명·쿠키 없음).
"""
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import text

from app.core import etf_listing_sync as m
from app.core.config import settings

FIX = Path(__file__).parent / "fixtures" / "etf"
NOW = datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)   # 12:00 KST


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


KRX_LIST = _load("krx_mdcstat04601.json")
KRX_PRICES = _load("krx_mdcstat04301.json")
KRX_PDF = _load("krx_mdcstat05001.json")
KRX_INV = _load("krx_mdcstat04901.json")
DART_LIST = _load("dart_list.json")
DART_DOC = (FIX / "dart_document_20260918000022.xml").read_bytes()


def _row(ticker: str, list_dd: str, name: str = "X", com: str = "삼성자산운용") -> dict:
    return {"ISU_SRT_CD": ticker, "ISU_CD": f"KR7{ticker}0000", "ISU_ABBRV": name, "ISU_NM": name,
            "LIST_DD": list_dd, "COM_ABBRV": com, "ETF_TOT_FEE": "0.45"}


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(m, "_state", {k: (False if k == "stats_final" else None) for k in m._state})
    monkeypatch.setattr(m, "_last_attempt", {})
    monkeypatch.setattr(m, "_doc_ranges", {})
    monkeypatch.setattr(settings, "KRX_USER", "test-user")
    monkeypatch.setattr(settings, "KRX_PW", "test-pw")
    monkeypatch.setattr(settings, "OPENDART_API_KEY", "test-key")


def _transport(fail: set[str] | None = None, seen: list | None = None) -> httpx.MockTransport:
    """KRX·DART 흉내. fail 에 'krx'·'dart' 를 넣으면 그쪽이 500 을 낸다."""
    fail = fail or set()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append((request.method, url, request.content))
        if "data.krx.co.kr" in url:
            if "krx" in fail:
                return httpx.Response(500)
            if "MDCCOMS001D1" in url:
                return httpx.Response(200, json={"_error_code": "CD001"})
            if "getJsonData" in url:
                bld = parse_qs(request.content.decode())["bld"][0]
                body = {
                    "dbms/MDC/STAT/standard/MDCSTAT04601": KRX_LIST,
                    "dbms/MDC/STAT/standard/MDCSTAT04301": KRX_PRICES,
                    "dbms/MDC/STAT/standard/MDCSTAT05001": KRX_PDF,
                    "dbms/MDC/STAT/standard/MDCSTAT04901": KRX_INV,
                }[bld]
                return httpx.Response(200, json=body)
            return httpx.Response(200, text="<html></html>")
        if "opendart.fss.or.kr" in url:
            if "dart" in fail:
                return httpx.Response(500)
            if "list.json" in url:
                assert request.url.params["pblntf_ty"] == "G"
                return httpx.Response(200, json=DART_LIST)
            if "document.xml" in url:
                return httpx.Response(200, text="<result><status>014</status></result>",
                                      headers={"content-type": "application/xml"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


# ── 8.1 단위 ─────────────────────────────────────────────────────────────────

def test_listing_day_is_max_list_date_not_after_today():
    rows = [_row("A", "2026/09/15"), _row("B", "2026/09/22"), _row("C", "2026/10/06")]
    assert m.listing_day(rows, date(2026, 9, 30)) == date(2026, 9, 22)   # 미래 상장일은 무시
    assert m.listing_day(rows, date(2026, 9, 22)) == date(2026, 9, 22)
    assert m.listing_day(rows, date(2026, 9, 1)) is None


def test_listing_day_weekend_uses_last_list_date():
    rows = [_row("A", "2026/09/29"), _row("B", "2026/10/02"), _row("C", "2026/10/02")]
    saturday = date(2026, 10, 3)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"output": rows} if b"04601" in req.content else {"output": []})
    ))
    got = m.fetch_krx(client, saturday)
    assert got["listing"]["date"] == "2026-10-02"                         # 금요일
    assert got["listing"]["is_today"] is False
    assert {r["ticker"] for r in got["listing"]["rows"]} == {"B", "C"}


def test_listing_day_holiday_without_calendar():
    # 2026-09-24~26 추석 휴장. 달력 없이 LIST_DD 만으로 직전 상장일(09-22)을 잡는다.
    rows = [_row("A", "2026/09/22"), _row("B", "2026/09/15")]
    assert m.listing_day(rows, date(2026, 9, 25)) == date(2026, 9, 22)
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert "holiday" not in src and "exchange_calendars" not in src
    assert "exchange_calendars" not in sys.modules


def test_upcoming_drops_already_listed_names():
    assert m._norm_name("KB RISE 삼성SK그룹증권상장지수투자신탁(주식)") == m._norm_name(
        "KBRISE삼성SK그룹증권상장지수투자신탁(주식)")
    krx = [{**_row("0240J0", "2026/09/22", "RISE 삼성SK그룹", "케이비자산운용"),
            "ISU_NM": "KB RISE 삼성SK그룹증권상장지수투자신탁(주식)"}]
    filings = [
        {"rcept_no": "1", "rcept_dt": "20260831", "corp_name": "KB자산운용",
         "report_nm": "일괄신고서(집합투자증권-신탁형)(KBRISE삼성SK그룹증권상장지수투자신탁(주식))"},
        {"rcept_no": "2", "rcept_dt": "20260901", "corp_name": "KB자산운용",
         "report_nm": "일괄신고서(집합투자증권-신탁형)(KBRISE새ETF증권상장지수투자신탁(주식))"},
    ]
    names = [c["name"] for c in m.upcoming_candidates(filings, krx)]
    assert names == ["KBRISE새ETF증권상장지수투자신탁(주식)"]                  # 상장한 건 빠진다


def test_upcoming_filter_uses_krx_manager_set():
    krx = KRX_LIST["output"]
    kb_listed = {"rcept_no": "8", "rcept_dt": "20260831", "corp_name": "KB자산운용",
                 "report_nm": "[기재정정]투자설명서(집합투자증권)(KBRISE삼성SK그룹증권상장지수투자신탁(주식))"}
    managers = m.manager_set(krx, DART_LIST["list"] + [kb_listed])
    # KRX 는 '케이비자산운용', DART 는 'KB자산운용' — 상장 ETF 공시로 이어 붙는다.
    assert m._norm_name("KB자산운용") in managers and "케이비자산운용" in managers
    stranger = {"rcept_no": "9", "rcept_dt": "20260920", "corp_name": "베어링자산운용",
                "report_nm": "일괄신고서(집합투자증권-신탁형)(베어링새증권상장지수투자신탁(주식))"}
    cands = m.upcoming_candidates(DART_LIST["list"] + [stranger], krx)
    assert all(c["company"] != "베어링자산운용" for c in cands)
    # 기존 ETF 의 [기재정정]·비ETF 공시·발행실적보고서는 후보가 아니다.
    assert all("상장지수" in c["name"] for c in cands)
    assert {c["name"] for c in cands} >= {"삼성KODEX미국AI에이전트액티브증권상장지수투자신탁[주식]"}
    for c in cands:
        assert m._norm_name(c["name"]) not in m._listed_names(krx)


def test_dart_listing_range_regex_hit_and_miss():
    hit = "<P>상장예정일 : 2026년 09월 04일 ~ 2026년 09월 11일</P>"
    assert m.listing_range(hit) == ("2026-09-04", "2026-09-11")
    assert m.listing_range("상장 예정일: 2026.10.06") == ("2026-10-06", "2026-10-06")
    assert m.listing_range("상장예정일 2026년 9월 4일 ~ 9월 11일") == ("2026-09-04", "2026-09-11")
    # 실제 표지(document.xml 은 표지만 준다)에는 없다 → None, 짐작하지 않는다.
    assert m.listing_range(DART_DOC.decode("utf-8")) == (None, None)
    assert m.listing_range(None) == (None, None)
    up = m.finalize_upcoming(
        [{"rcept_no": "1", "name": "A", "company": "c", "filed": "2026-09-01", "is_amend": False,
          "doc_rcept_no": "1"},
         {"rcept_no": "2", "name": "B", "company": "c", "filed": "2026-09-02", "is_amend": False,
          "doc_rcept_no": "2"}],
        {"1": ("2026-09-04", "2026-09-11")}, date(2026, 9, 30))
    assert [u["name"] for u in up] == ["B"]                       # 지난 범위는 빠지고, 미상은 null 로 남는다
    assert up[0]["est_from"] is None and up[0]["est_to"] is None


def test_num_dash_is_none_and_missing_fee_stays_none():
    assert m._num("-") is None and m._num("") is None and m._num(None) is None
    assert m._num("1,234") == 1234.0
    assert m._fee_pct(None) is None
    meta = m.listed_on([{**_row("A", "2026/09/22"), "ETF_TOT_FEE": ""}], date(2026, 9, 22))
    assert meta[0]["fee"] is None
    rows = m.report_rows(meta, {})
    assert rows[0]["trade_value"] is None and rows[0]["net_buy"] is None and rows[0]["ret"] is None
    assert m.individual_net_buy([]) is None
    assert m.holdings_rows([{"COMPST_ISU_NM": "현금", "COMPST_RTO": "-", "COMPST_AMT": "-"}]) == [
        {"name": "현금", "weight": None}]


def test_payload_shape_matches_contract_without_realtime():
    with httpx.Client(transport=_transport()) as client:
        m.login_krx(client, "u", "p")
        got = m.fetch_krx(client, date(2026, 9, 30))
    m._state.update(krx_day=date(2026, 9, 30), krx_rows=got["rows"], listing=got["listing"],
                    report=got["report"], upcoming=[])
    p = m.payload(NOW)
    assert set(p) == {"generated_at", "today", "note", "report", "listing", "upcoming"}
    assert not any("realtime" in k for k in p)
    assert p["listing"]["date"] == "2026-09-22" and p["listing"]["is_today"] is False
    lr = p["listing"]["rows"][0]
    assert set(lr) == {"name", "ticker", "isin", "company", "fee", "benchmark", "asset_class", "holdings"}
    assert lr["holdings"] and set(lr["holdings"][0]) == {"name", "weight"}
    rr = {r["ticker"]: r for r in p["report"]["rows"]}
    ibk = rr["0238C0"]
    assert set(ibk) == {"rank", "name", "ticker", "fee", "trade_value", "net_buy", "ret"}
    assert ibk["trade_value"] == pytest.approx(94_551_649 / 1e8)
    assert ibk["ret"] == pytest.approx(-0.001)
    assert ibk["net_buy"] == pytest.approx(16_384_639 / 1e8)             # 개인 순매수(억)
    assert [r["rank"] for r in p["report"]["rows"]] == list(range(1, len(rr) + 1))


def test_krx_session_reads_plain_settings_only(monkeypatch):
    called = []
    monkeypatch.setattr(m, "decrypt_env", lambda k: called.append(k) or "vault", raising=False)
    monkeypatch.setenv("ETF_INAV_MONITOR__KRX_USER", "vault-user")
    monkeypatch.setenv("ETF_INAV_MONITOR__KRX_PW", "vault-pw")
    seen: list = []
    m.krx_session(_transport(seen=seen)).close()
    login = [c for meth, u, c in seen if "MDCCOMS001D1" in u][0]
    assert parse_qs(login.decode())["mbrId"] == ["test-user"]
    monkeypatch.setattr(settings, "KRX_USER", "")
    with pytest.raises(m.KeyMissing):
        m.krx_session(_transport())
    assert called == []


def test_macro_universe_includes_new_fred_rows():
    seed = Path(__file__).resolve().parents[3] / "database" / "seeds" / "macro_universe.py"
    spec = importlib.util.spec_from_file_location("_mu_test", seed)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = {r[0]: r for r in mod.MACRO_UNIVERSE}
    for sid in ("DFEDTARU", "EXPINF1YR", "DCOILWTICO", "ADPMNUSNERSA"):
        assert sid in rows
        assert rows[sid][2] in mod.CATEGORY_ORDER
    assert rows["ADPMNUSNERSA"][3] == "mom_diff"


# ── 8.2 통합 (테스트 DB · HTTP 는 픽스처) ─────────────────────────────────────

def _status(db, source):
    return db.execute(text(
        "SELECT last_ok_at, last_error_kind FROM source_status WHERE source = :s"), {"s": source}).one_or_none()


def test_sync_writes_source_status_and_keeps_payload_on_500(db):
    out = m.sync(db, NOW, transport=_transport())
    assert out == {"krx": "ok", "dart": "ok"}
    assert _status(db, "etf_krx").last_ok_at is not None
    assert _status(db, "etf_dart").last_ok_at is not None
    before = m.payload(NOW)
    assert before["listing"]["rows"] and before["note"] is None
    assert any(u["name"].startswith("삼성KODEX미국AI에이전트") for u in before["upcoming"])

    out = m.sync(db, NOW, transport=_transport(fail={"krx", "dart"}), force=True)
    assert out == {"krx": "error", "dart": "error"}
    assert _status(db, "etf_krx").last_error_kind == "other"
    assert _status(db, "etf_dart").last_error_kind == "other"
    after = m.payload(NOW)
    assert after["listing"] == before["listing"] and after["upcoming"] == before["upcoming"]
    assert "KRX 조회 실패" in after["note"]

    # 성공한 날에는 다시 받지 않는다(30분 체크가 KRX 를 두드리지 않게).
    m._state.update(krx_error=None, dart_error=None)
    assert m.sync(db, NOW, transport=_transport(fail={"krx", "dart"})) == {"krx": "skip", "dart": "skip"}


def test_sync_without_keys_records_error_not_zero(db, monkeypatch):
    monkeypatch.setattr(settings, "KRX_USER", "")
    assert m.sync(db, NOW, transport=_transport())["krx"] == "error"
    assert _status(db, "etf_krx").last_error_kind == "other"
    p = m.payload(NOW)
    assert p["listing"]["rows"] == [] and "키 미설정" in p["note"]


def test_new_listing_endpoint_cold_cache_is_200_with_note(client):
    r = client.get("/api/v1/etf/new-listing")
    assert r.status_code == 200
    body = r.json()
    assert body["note"] and body["listing"]["rows"] == [] and body["upcoming"] == []
    assert set(body) == {"generated_at", "today", "note", "report", "listing", "upcoming"}


def test_new_listing_endpoint_warm_cache_shape(client, db):
    m.sync(db, NOW, transport=_transport())
    body = client.get("/api/v1/etf/new-listing").json()
    assert body["listing"]["date"] == "2026-09-22" and len(body["listing"]["rows"]) >= 1
    assert body["report"]["rows"][0]["rank"] == 1


@pytest.mark.parametrize("path", [
    "/api/v1/inav/snapshot", "/api/v1/etf-class", "/api/v1/macro/panels",
    "/api/v1/stock-monitor/policy-rate", "/api/v1/ai-key-data/epoch-chips",
    "/api/v1/lan/servers", "/api/v1/ai-token-usage", "/internal/check/hoga",
])
def test_removed_paths_are_404(client, path):
    assert client.get(path).status_code == 404
