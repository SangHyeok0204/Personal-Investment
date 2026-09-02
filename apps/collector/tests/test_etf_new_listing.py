"""etf_new_listing 회귀 테스트 — 신규상장 세 갈래의 판독부.

여기서 지키는 건 실제로 틀렸던 자리들이다:
  1) 신규상장 txt 는 **UTF-8** 이다(같은 폴더의 일별 분석 txt 는 cp949). cp949 로 고정하면
     이름이 깨지는 데 그치지 않고 `거래대금:` 머리글까지 깨져 금액이 전부 결측이 된다.
  2) DART 는 상장일을 **범위**로만 준다 — 지난 건은 '임박'에서 빠져야 한다.
  3) CHECK newEtfs 의 단위가 섞여 있다(억/주/%/원). etf_flows 와 달리 억을 그대로 쓴다.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import etf_new_listing as nl  # noqa: E402


SAMPLE = """----------------------------------------
금일 상장 ETF 성적표
----------------------------------------
1. 마이티 신약포커스바이오액티브
거래대금: 18억
개인순매수: 0억

2. RISE 글로벌AI낸드메모리반도체
거래대금: 30억
개인순매수: 9억

3. KIWOOM 삼성SK그룹TOP4+
거래대금: 1,513억
개인순매수: -34억
"""


# ── 1) 성적표 판독 ──────────────────────────────────────────────────────────

def test_report_parses_names_and_amounts():
    rows = nl.parse_report(SAMPLE)
    assert [r["name"] for r in rows] == [
        "마이티 신약포커스바이오액티브",
        "RISE 글로벌AI낸드메모리반도체",
        "KIWOOM 삼성SK그룹TOP4+",
    ]
    assert rows[0]["trade_value"] == pytest.approx(18)
    assert rows[1]["net_buy"] == pytest.approx(9)
    # 천 단위 구분자와 음수도 읽어야 한다
    assert rows[2]["trade_value"] == pytest.approx(1513)
    assert rows[2]["net_buy"] == pytest.approx(-34)


def test_report_is_utf8_not_cp949():
    """★실측 결함: cp949 로 고정하면 이름이 깨지고 `거래대금:` 도 안 맞아 금액이 전부 None."""
    blob = SAMPLE.encode("utf-8")
    rows = nl.parse_report(nl._decode(blob))
    assert rows[0]["name"] == "마이티 신약포커스바이오액티브"
    assert rows[0]["trade_value"] == pytest.approx(18)
    # cp949 로 억지로 읽으면 이렇게 깨진다 — 그래서 감지가 필요하다
    broken = nl.parse_report(blob.decode("cp949", errors="replace"))
    assert broken and broken[0]["trade_value"] is None


def test_report_falls_back_to_cp949_when_not_utf8():
    rows = nl.parse_report(nl._decode(SAMPLE.encode("cp949")))
    assert rows[0]["name"] == "마이티 신약포커스바이오액티브"
    assert rows[0]["trade_value"] == pytest.approx(18)


def test_item_without_amounts_is_kept_not_dropped():
    """값이 없다고 종목을 버리면 '그 종목은 상장 안 했다'로 읽힌다."""
    rows = nl.parse_report("1. 이름만 있는 ETF\n")
    assert len(rows) == 1
    assert rows[0]["trade_value"] is None and rows[0]["net_buy"] is None


# ── 2) 상장 임박 — DART 는 범위만 준다 ──────────────────────────────────────

def test_upcoming_drops_windows_that_already_passed(tmp_path, monkeypatch):
    d = tmp_path / "input" / "processed"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({
        "rcept_no": "1", "name": "지난 건", "corp_name": "A",
        "est_listing_from": "2026-08-01", "est_listing_to": "2026-08-08",
        "holdings": [],
    }), encoding="utf-8")
    (d / "b.json").write_text(json.dumps({
        "rcept_no": "2", "name": "임박 건", "corp_name": "B",
        "est_listing_from": "2026-09-04", "est_listing_to": "2026-09-11",
        "holdings": [{"name": "삼성전자", "weight": 21.5}],
    }), encoding="utf-8")
    monkeypatch.setattr(nl, "FUND_FILING_DIR", str(tmp_path))

    import datetime as _dt
    got = nl.upcoming(_dt.date(2026, 9, 2))
    assert [g["name"] for g in got] == ["임박 건"]
    assert got[0]["holdings"][0]["weight"] == pytest.approx(21.5)
    assert got[0]["est_from"] == "2026-09-04" and got[0]["est_to"] == "2026-09-11"


def test_upcoming_survives_a_missing_or_broken_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(nl, "FUND_FILING_DIR", str(tmp_path / "없음"))
    import datetime as _dt
    assert nl.upcoming(_dt.date(2026, 9, 2)) == []


# ── 3) CHECK 실시간 ─────────────────────────────────────────────────────────

def test_realtime_keeps_eok_units_and_reads_change():
    """★`etf_flows` 는 억을 원으로(×1e8) 바꾸지만 여기는 억을 그대로 쓴다.
    그리고 `change`(등락률)는 etf_flows 가 아예 안 꺼내는 필드다."""
    hoga = {"payload": {"newEtfs": [{
        "code": "0234N0", "name": "KIWOOM 삼성SK그룹TOP4+", "listedDate": "2026-09-01",
        "tradeAmt": 5.26, "volume": 53664, "change": -2.32, "price": 9320,
        "marketCap": 198.1, "indivNet": 0,
    }]}}
    got = nl.realtime(hoga)
    assert set(got) == {"0234N0"}
    r = got["0234N0"]
    assert r["trade_value"] == pytest.approx(5.26)   # 억 그대로
    assert r["change"] == pytest.approx(-2.32)       # %
    assert r["volume"] == pytest.approx(53664)       # 주
    assert r["market_cap"] == pytest.approx(198.1)


def test_realtime_is_empty_when_envelope_missing():
    assert nl.realtime(None) == {}
    assert nl.realtime({"payload": {}}) == {}


# ── 4) 총보수 형식 ──────────────────────────────────────────────────────────

def test_fee_is_a_number_in_percent_not_a_string():
    """KRX 는 '0.450000' 처럼 준다. 화면이 자릿수를 정할 수 있게 숫자로 넘긴다."""
    assert nl._fee_pct("0.450000") == pytest.approx(0.45)
    assert nl._fee_pct("0.785000") == pytest.approx(0.785)
    assert nl._fee_pct("-") is None
    assert nl._fee_pct("") is None


# ── 5) 자정 판단 — 날짜가 넘어가면 KRX 목록을 다시 받아야 한다 ──────────────

def test_krx_cache_is_invalidated_when_the_day_rolls_over(monkeypatch):
    """★TTL 만으로는 부족하다. 자정에 상장한 종목은 **전날 받아 둔 목록에 아예 없어서**,
    TTL 이 남아 있는 동안 '금일 상장 없음' 이라고 말하게 된다."""
    import datetime as _dt

    calls = []

    def fake_fetch(force=False):
        calls.append(force)
        nl._krx_cache.update(at=9e9, day=nl._today(), rows=[{"LIST_DD": "x"}], error=None)
        return nl._krx_cache["rows"], None

    # 어제 받아 둔 캐시가 TTL 안에 있는 상태
    nl._krx_cache.update(at=9e9, day=_dt.date(2026, 9, 1), rows=[{"LIST_DD": "old"}], error=None)
    monkeypatch.setattr(nl, "_today", lambda: _dt.date(2026, 9, 2))
    monkeypatch.setattr(nl, "_krx_rows", fake_fetch)
    monkeypatch.setattr(nl, "krx_listed_on", lambda d: ([{"name": "새 ETF"}], None))

    got = nl.refresh_daily()
    assert got["refreshed"] is True          # 날짜가 바뀌었으니 다시 받는다
    assert got["listed_today"] == ["새 ETF"]
    assert calls == [True]

    # 같은 날 두 번째 호출은 받지 않는다(1,167행 조회에 로그인이 붙는다)
    got2 = nl.refresh_daily()
    assert got2["refreshed"] is False
    assert calls == [True]

    nl._krx_cache.update(at=0.0, day=None, rows=None, error=None)


# ── 6) 화요일(실제 상장일) 경로 ─────────────────────────────────────────────
# 상장은 주 1회꼴이라 이 분기는 **화요일에만 화면에 나온다**. 눈으로 볼 수 없는 구간이라
# 여기서 고정한다 — 못 보는 코드가 조용히 틀리는 자리다.

def _write_report(dirpath, day: str, body: str, enc: str = "utf-8"):
    import pathlib
    p = pathlib.Path(dirpath) / f"{day}_신규상장.txt"
    p.write_bytes(body.encode(enc))
    return p


def test_today_report_wins_over_older_ones(tmp_path, monkeypatch):
    """오늘 파일이 있으면 그것만 쓰고 is_today=True 여야 한다."""
    import datetime as _dt
    monkeypatch.setattr(nl, "DAILY_DIR", str(tmp_path))
    _write_report(tmp_path, "20260825", "1. 지난 화요일 ETF\n거래대금: 5억\n개인순매수: 1억\n")
    _write_report(tmp_path, "20260901", SAMPLE)

    got = nl.find_report(_dt.date(2026, 9, 1))
    assert got["is_today"] is True
    assert got["date"] == "2026-09-01"
    assert len(got["rows"]) == 3


def test_falls_back_to_the_most_recent_report_with_its_own_date(tmp_path, monkeypatch):
    """오늘 파일이 없으면 최근 것을 **그 날짜와 함께** 준다.

    ★날짜를 안 돌려주면 화면이 "오늘 상장한 것"으로 쓰게 된다 — 틀린 말이 된다.
    """
    import datetime as _dt
    monkeypatch.setattr(nl, "DAILY_DIR", str(tmp_path))
    _write_report(tmp_path, "20260901", SAMPLE)

    got = nl.find_report(_dt.date(2026, 9, 3))
    assert got["is_today"] is False
    assert got["date"] == "2026-09-01"        # 오늘이 아니라 실제 파일 날짜
    assert len(got["rows"]) == 3


def test_no_report_at_all_is_an_empty_result_not_an_error(tmp_path, monkeypatch):
    """화면이 '금일 신규 상장된 ETF가 없습니다' 를 띄우는 근거."""
    import datetime as _dt
    monkeypatch.setattr(nl, "DAILY_DIR", str(tmp_path))
    got = nl.find_report(_dt.date(2026, 9, 3))
    assert got == {"date": None, "is_today": False, "rows": [], "path": None}


def test_lookback_does_not_reach_past_its_window(tmp_path, monkeypatch):
    """너무 오래된 성적표를 '최근' 이라고 내밀지 않는다."""
    import datetime as _dt
    monkeypatch.setattr(nl, "DAILY_DIR", str(tmp_path))
    _write_report(tmp_path, "20260901", SAMPLE)
    assert nl.find_report(_dt.date(2026, 9, 20), lookback=5)["date"] is None
    assert nl.find_report(_dt.date(2026, 9, 3), lookback=5)["date"] == "2026-09-01"


def test_build_joins_workbook_returns_onto_report_rows(tmp_path, monkeypatch):
    """★성적표 txt 에는 수익률이 없다 — 워크북 등락률을 **이름으로** 붙인다.
    이름이 안 맞는 종목은 None 이어야 한다(0% 로 채우면 '보합' 이라는 거짓말이 된다)."""
    import datetime as _dt
    monkeypatch.setattr(nl, "DAILY_DIR", str(tmp_path))
    monkeypatch.setattr(nl, "FUND_FILING_DIR", str(tmp_path / "없음"))
    monkeypatch.setattr(nl, "_today", lambda: _dt.date(2026, 9, 1))
    monkeypatch.setattr(nl, "find_listing_day", lambda *a, **k: (None, [], None))
    _write_report(tmp_path, "20260901", SAMPLE)

    got = nl.build(None, {"마이티 신약포커스바이오액티브": -0.0229})
    rows = {r["name"]: r["ret"] for r in got["report"]["rows"]}
    assert rows["마이티 신약포커스바이오액티브"] == pytest.approx(-0.0229)
    assert rows["RISE 글로벌AI낸드메모리반도체"] is None   # 0.0 이 아니라 결측


# ── 7) 실시간 신선도 ────────────────────────────────────────────────────────
# ★낡은 envelope 의 마지막 값을 "실시간" 이라 부르면 그 자체가 틀린 말이다.
#   장 마감 뒤·CHECK PC 정지 뒤에 값은 그대로 남아 있어서 화면만 봐서는 구분이 안 된다.

def test_realtime_is_stale_when_the_envelope_is_old(monkeypatch):
    import datetime as _dt

    now = _dt.datetime(2026, 9, 2, 10, 0, 0, tzinfo=nl._KST)

    class _FakeDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(nl, "datetime", _FakeDT)

    # 1분 전 → 실시간
    ts, stale = nl.realtime_asof({"source_timestamp": "2026-09-02T09:59:00+09:00"})
    assert stale is False and ts.startswith("2026-09-02")
    # 30분 전 → 낡음
    _, stale = nl.realtime_asof({"source_timestamp": "2026-09-02T09:30:00+09:00"})
    assert stale is True
    # 시각이 없거나 못 읽으면 낡은 것으로 본다 — 모르면 믿지 않는다
    assert nl.realtime_asof(None) == (None, True)
    assert nl.realtime_asof({}) == (None, True)
    assert nl.realtime_asof({"source_timestamp": "이상한 값"})[1] is True


# ── 8) 성적표에 KRX·CHECK 값 잇기 ──────────────────────────────────────────

def test_report_rows_get_fee_and_realtime_joined_by_name(tmp_path, monkeypatch):
    """★조인은 서버에서 한 번만 한다. 화면이 같은 규칙을 또 가지면 두 곳이 갈린다.
    못 찾은 종목은 None 이어야 한다 — 0 으로 채우면 '보수 0%' 라는 거짓말이 된다."""
    import datetime as _dt
    monkeypatch.setattr(nl, "DAILY_DIR", str(tmp_path))
    monkeypatch.setattr(nl, "FUND_FILING_DIR", str(tmp_path / "없음"))
    monkeypatch.setattr(nl, "_today", lambda: _dt.date(2026, 9, 1))
    _write_report(tmp_path, "20260901", SAMPLE)

    krx = [{"name": "마이티 신약포커스바이오액티브", "ticker": "0229F0", "isin": "",
            "company": "디비자산운용", "fee": 0.785, "benchmark": "", "asset_class": ""}]
    monkeypatch.setattr(nl, "find_listing_day",
                        lambda *a, **k: (_dt.date(2026, 9, 1), krx, None))
    monkeypatch.setattr(nl, "holdings_for", lambda d: {})

    hoga = {"payload": {"newEtfs": [{"code": "0229F0", "tradeAmt": 5.24,
                                     "volume": 6416, "change": 0.53}]}}
    got = nl.build(hoga, {})
    rows = {r["name"]: r for r in got["report"]["rows"]}

    hit = rows["마이티 신약포커스바이오액티브"]
    assert hit["ticker"] == "0229F0"
    assert hit["fee"] == pytest.approx(0.785)
    assert hit["realtime"]["change"] == pytest.approx(0.53)
    assert hit["realtime"]["volume"] == pytest.approx(6416)
    # txt 값은 그대로 남아 있어야 한다(상장일 성적)
    assert hit["trade_value"] == pytest.approx(18)

    miss = rows["RISE 글로벌AI낸드메모리반도체"]
    assert miss["fee"] is None and miss["realtime"] is None and miss["ticker"] == ""


# ── 9) 상장 예정에서 '이미 상장한 건' 빼기 ──────────────────────────────────

def test_upcoming_drops_names_already_on_the_krx_list(tmp_path, monkeypatch):
    """★예상 구간이 안 끝났어도 이미 상장했으면 '임박'이 아니다. DART 는 상장 사실을
    되돌려 적지 않으므로 KRX 목록과 대조해야 한다(2026-09-02 사용자 지적)."""
    import datetime as _dt
    d = tmp_path / "input" / "processed"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({
        "rcept_no": "1", "name": "한화PLUSS&P500증권상장지수투자신탁(주식)(H)",
        "corp_name": "한화", "est_listing_from": "2026-08-26",
        "est_listing_to": "2026-09-02", "holdings": [],
    }), encoding="utf-8")
    (d / "b.json").write_text(json.dumps({
        "rcept_no": "2", "name": "아직안한투자신탁(주식)", "corp_name": "B",
        "est_listing_from": "2026-09-10", "est_listing_to": "2026-09-17",
        "holdings": [],
    }), encoding="utf-8")
    monkeypatch.setattr(nl, "FUND_FILING_DIR", str(tmp_path))

    # KRX 에 첫 건이 이미 올라 있다(표기가 조금 달라도 정규화하면 같다)
    monkeypatch.setattr(nl, "_krx_rows", lambda force=False: (
        [{"ISU_NM": "한화 PLUS S&P500 증권상장지수투자신탁 (주식)(H)",
          "ISU_ABBRV": "PLUS S&P500(H)"}], None))

    got = nl.upcoming(_dt.date(2026, 9, 2))
    assert [g["name"] for g in got] == ["아직안한투자신탁(주식)"]


def test_upcoming_keeps_everything_when_krx_lookup_fails(tmp_path, monkeypatch):
    """KRX 가 안 되면 필터만 건너뛴다 — 목록 자체를 비우면 '예정 없음' 이라는 거짓말이 된다."""
    import datetime as _dt
    d = tmp_path / "input" / "processed"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({
        "rcept_no": "1", "name": "어떤투자신탁", "corp_name": "A",
        "est_listing_from": "2026-09-10", "est_listing_to": "2026-09-17",
        "holdings": [],
    }), encoding="utf-8")
    monkeypatch.setattr(nl, "FUND_FILING_DIR", str(tmp_path))
    monkeypatch.setattr(nl, "_krx_rows", lambda force=False: ([], "조회 실패"))
    assert [g["name"] for g in nl.upcoming(_dt.date(2026, 9, 2))] == ["어떤투자신탁"]
