"""국내 ETF 신규상장 따라잡기 — KRX(상장·구성종목·거래) + OpenDART(상장 예정), 메모리 캐시.

collector `etf_new_listing.py`·`krx_fetch.py` 에서 순수 로직만 옮겼다(계획 personal-dashboard-scope
§5 2.3). 회사 드라이브·CHECK 호가(실시간)는 없다 — 실시간 필드는 뺐다.

[따라잡기] `ai_snapshot_sync` 와 같은 방식 — 60초 쉬고, 30분마다 "오늘(KST) 받은 KRX 목록이
없으면 지금 받는다". 실패하면 1시간 뒤 다시, **마지막 성공 캐시는 그대로 둔다**.
성공/실패는 `source_status`(etf_krx·etf_dart) → /data-operations. 새 표는 없다(전부 다시 받을 수 있다).

★상장일 = `max(LIST_DD <= 오늘)` — 휴장일 달력이 필요 없다(주말·공휴일이면 직전 상장일,
  `is_today=False`). 상장일 당일 장 마감(15:30) 전에 받은 거래 수치는 확정이 아니라서
  16:00(KST) 이후 한 번 더 받는다.

★KRX (개인 무료 계정 `KRX_USER`/`KRX_PW`, TLS 검증 켬 — 회사 프록시 우회용 verify=False 는 없앴다)
  - MDCSTAT04601 전 종목 목록: LIST_DD·총보수(ETF_TOT_FEE, 이미 % 단위)·운용사·기초지수.
  - MDCSTAT05001 구성종목(ISIN·상장일). ⚠️COMPST_RTO 는 '-' 로 오는 일이 많다(2026-09-30 실측,
    주식형도) — 그땐 평가금액(COMPST_AMT) 합계 대비 비중을 계산해 적는다. 금액도 없으면 null.
  - MDCSTAT04301 상장일 거래대금(ACC_TRDVAL, 원)·등락률(FLUC_RT, %).
  - ★개인순매수 **검증됨**(2026-09-30): MDCSTAT04901 + isuCd(ISIN)·strtDd=endDd=상장일 →
    투자자별 행 중 `INVST_TP_NM == "개인"` 의 NETBID_TRDVAL(원). 종목별 값이다(IBK 한미대표
    09-22: 금융투자 −16,384,639 / 개인 +16,384,639 로 서로 맞물림). 못 받으면 null — 0 이 아니다.

★DART (개인 무료 `OPENDART_API_KEY`) — **pblntf_ty=G(펀드공시)** 가 맞다(2026-09-30 실측).
  - G 최근 30일 1,262건 중 207건이 `…증권상장지수투자신탁…`(ETF). C(발행공시)의 '투자설명서'는
    증권사 일괄신고(파생결합증권) 96건뿐이고 ETF 는 0건.
  - ⚠️'예비투자설명서' 라는 **보고서명은 목록에 없다**(G 30일 0건). 신규 ETF 는
    `일괄신고서(집합투자증권-신탁형)(<정식명>)` → `[기재정정]일괄신고서` → `투자설명서` →
    `증권발행실적보고서`(설정·상장 뒤) 순으로 나온다. collector 가 쓰던 20260813001776 도
    `[기재정정]일괄신고서` 였다. 그래서 필터는:
      · report_nm 에 '상장지수' + 종류 ∈ {일괄신고서, 증권신고서, 투자설명서}
      · 창 안에 **원본(비정정) 일괄신고서/증권신고서** 가 있는 펀드만 = 새로 등록된 펀드
        (기존 ETF 의 연례 [기재정정] 은 여기서 빠진다)
      · 운용사가 KRX 운용사 집합에 있다 — KRX COM_ABBRV('케이비자산운용')와 DART corp_name
        ('KB자산운용')이 다르게 적히므로, 집합 = COM_ABBRV(앞부분 일치 포함) ∪ **이미 KRX 에
        상장한 ETF 이름으로 공시한 적이 있는 DART 회사**. 둘 다 KRX 에서 파생된 닫힌 집합이다.
      · KRX 정식명(ISU_NM)과 `_norm_name` 이 같으면 이미 상장 → 뺀다. 증권발행실적보고서·
        철회신고서가 있는 펀드도 뺀다.
  - ⚠️document.xml 은 **표지만** 준다(투자설명서 2.9KB zip, 본문·첨부 없음). 일괄신고서는
    `014 파일이 존재하지 않습니다`. 그래서 예상 상장 범위 정규식은 대부분 **빗나가고 null**
    → 화면은 '미정'. 짐작한 날짜로 채우지 않는다.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import time
import zipfile
from datetime import date, datetime, time as dtime, timedelta, timezone
import httpx

from app.core.ai_snapshot_sync import record_error, record_ok, today_kst
from app.core.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 30 * 60
RETRY_AFTER_SECONDS = 60 * 60
STARTUP_DELAY_SECONDS = 60
UPCOMING_LIMIT = 8
DART_LOOKBACK_DAYS = 90       # list.json 은 회사 지정 없이 3개월까지만 검색된다
STATS_FINAL_AFTER = dtime(16, 0)  # KST — 장 마감 뒤 받은 상장일 수치만 확정으로 본다
EOK = 100_000_000

KRX_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_LOGIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
KRX_LOGIN_JSP_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
KRX_LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
KRX_MAIN_PAGE_URL = "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"
KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd",
}
KRX_TIMEOUT = 60
DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOC_URL = "https://opendart.fss.or.kr/api/document.xml"

# 캐시 — 새 표를 만들지 않는다(원천이 전부 다시 받을 수 있다).
_state: dict = {
    "krx_day": None,        # 목록을 받은 날(KST)
    "krx_rows": None,       # MDCSTAT04601 원본 행
    "listing": None,        # {"date", "is_today", "rows"}
    "report": None,         # {"date", "is_today", "rows"}
    "stats_final": False,
    "krx_error": None,
    "dart_day": None,
    "upcoming": None,
    "dart_error": None,
}
_last_attempt: dict[str, float] = {}
_doc_ranges: dict[str, tuple[str | None, str | None]] = {}


class KeyMissing(RuntimeError):
    """자격증명이 비어 있다 — 호출하지 않는다."""


# ── 값 다루기 (collector etf_new_listing 에서 옮김) ──────────────────────────

def _num(s) -> float | None:
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    if not s:
        return None
    t = str(s).replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _fee_pct(raw) -> float | None:
    """'0.450000' → 0.45. KRX 는 이미 % 단위 문자열로 준다(0.45 = 0.45%)."""
    return _num(raw)


def _eok(raw) -> float | None:
    """원 → 억원. 없으면 None(0 이 아니다)."""
    v = _num(raw)
    return None if v is None else v / EOK


def _norm_name(s: str | None) -> str:
    """상장 여부 대조용 정규화. 공백·괄호·구분자를 지우고 대문자로.

    DART 는 정식 전체명("한국투자ACE…증권상장지수투자신탁(채권혼합)")을, KRX 는 같은 정식명을
    ISU_NM 으로 준다. 표기 차이(괄호·공백)만 걷어내면 맞는다.
    """
    return re.sub(r"[\s()\[\]·\-_,\.]", "", s or "").upper()


def _iso(yyyymmdd_or_slash: str | None) -> str | None:
    t = re.sub(r"\D", "", yyyymmdd_or_slash or "")
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}" if len(t) == 8 else None


# ── KRX 상장일·목록 ──────────────────────────────────────────────────────────

def listing_day(rows: list[dict], today: date) -> date | None:
    """`max(LIST_DD <= today)`. 휴장일 달력 없이 주말·공휴일을 넘는다(F10)."""
    best: date | None = None
    for r in rows:
        iso = _iso(r.get("LIST_DD"))
        if not iso:
            continue
        d = date.fromisoformat(iso)
        if d <= today and (best is None or d > best):
            best = d
    return best


def listed_on(rows: list[dict], day: date) -> list[dict]:
    """그날 상장한 ETF 메타. LIST_DD 는 'YYYY/MM/DD'."""
    out = []
    for r in rows:
        if _iso(r.get("LIST_DD")) != day.isoformat():
            continue
        out.append({
            "name": (r.get("ISU_ABBRV") or r.get("ISU_NM") or "").strip(),
            "ticker": (r.get("ISU_SRT_CD") or "").strip(),
            "isin": (r.get("ISU_CD") or "").strip(),
            "company": (r.get("COM_ABBRV") or "").strip(),
            "fee": _fee_pct(r.get("ETF_TOT_FEE")),
            "benchmark": (r.get("ETF_OBJ_IDX_NM") or "").strip(),
            "asset_class": (r.get("IDX_ASST_CLSS_NM") or "").strip(),
        })
    out.sort(key=lambda x: x["name"])
    return out


def holdings_rows(pdf_output: list[dict]) -> list[dict]:
    """MDCSTAT05001 → [{name, weight}] 비중 큰 순. COMPST_RTO 가 '-' 면 평가금액 비중(%)."""
    amts = [_num(h.get("COMPST_AMT")) for h in pdf_output]
    total = sum(a for a in amts if a is not None)
    out = []
    for h, amt in zip(pdf_output, amts):
        name = str(h.get("COMPST_ISU_NM") or "").strip()
        if not name:
            continue
        w = _num(h.get("COMPST_RTO"))
        if w is None and amt is not None and total > 0:
            w = round(amt / total * 100, 2)
        out.append({"name": name, "weight": w})
    out.sort(key=lambda x: (x["weight"] is None, -(x["weight"] or 0)))
    return out


def individual_net_buy(investor_output: list[dict]) -> float | None:
    """MDCSTAT04901 → 개인 순매수(억원). 행이 없으면 None."""
    for r in investor_output:
        if str(r.get("INVST_TP_NM") or "").strip() == "개인":
            return _eok(r.get("NETBID_TRDVAL"))
    return None


def report_rows(listing_rows: list[dict], stats: dict[str, dict]) -> list[dict]:
    """성적표 — 상장일 거래대금(억)·개인순매수(억)·등락률(소수). 거래대금 큰 순으로 순위."""
    rows = []
    for r in listing_rows:
        s = stats.get(r["ticker"]) or {}
        rows.append({
            "name": r["name"],
            "ticker": r["ticker"],
            "fee": r["fee"],
            "trade_value": s.get("trade_value"),
            "net_buy": s.get("net_buy"),
            "ret": s.get("ret"),
        })
    rows.sort(key=lambda x: (x["trade_value"] is None, -(x["trade_value"] or 0), x["name"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ── DART 상장 예정 ───────────────────────────────────────────────────────────

_KIND_RE = re.compile(r"^(\[[^\]]+\])?\s*(일괄신고서|증권신고서|투자설명서|증권발행실적보고서|철회신고서)")
_D = r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?"
_RANGE_RE = re.compile(
    r"상장\s*(?:예정|예상)\s*(?:일|기간|시기)?\s*[:：]?\s*" + _D
    + r"(?:\s*(?:\(예정\))?\s*(?:~|∼|-|부터)\s*(?:" + _D + r"|(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?))?"
)


def report_kind(report_nm: str) -> tuple[str | None, bool]:
    """('일괄신고서'|…|None, 정정 여부)."""
    m = _KIND_RE.match(report_nm or "")
    if not m:
        return None, False
    return m.group(2), bool(m.group(1))


def fund_name(report_nm: str) -> str | None:
    """'투자설명서(집합투자증권)(<정식명>)' → 정식명. 정식명 안의 괄호는 그대로 둔다."""
    rest = re.sub(r"^\[[^\]]+\]", "", report_nm or "")
    i = rest.find(")(")
    if i < 0:
        return None
    name = rest[i + 2:]
    return name[:-1].strip() if name.endswith(")") else name.strip()


def listing_range(text: str | None) -> tuple[str | None, str | None]:
    """문서 텍스트 → (예상 상장 시작, 끝) ISO. 못 찾으면 (None, None) — 짐작하지 않는다."""
    if not text:
        return None, None
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    m = _RANGE_RE.search(flat)
    if not m:
        return None, None
    g = m.groups()
    try:
        start = date(int(g[0]), int(g[1]), int(g[2]))
        if g[3]:
            end = date(int(g[3]), int(g[4]), int(g[5]))
        elif g[6]:
            end = date(start.year, int(g[6]), int(g[7]))
        else:
            end = start
    except ValueError:
        return None, None
    return start.isoformat(), end.isoformat()


def manager_set(krx_rows: list[dict], filings: list[dict]) -> set[str]:
    """ETF 운용사 닫힌 집합(정규화 이름). KRX COM_ABBRV ∪ KRX 상장 ETF 로 공시한 DART 회사."""
    managers = {_norm_name(r.get("COM_ABBRV")) for r in krx_rows if r.get("COM_ABBRV")}
    listed = _listed_names(krx_rows)
    for f in filings:
        fn = fund_name(f.get("report_nm") or "")
        if fn and _norm_name(fn) in listed:
            managers.add(_norm_name(f.get("corp_name")))
    managers.discard("")
    return managers


def _is_manager(corp: str | None, managers: set[str]) -> bool:
    c = _norm_name(corp)
    if not c:
        return False
    return c in managers or any(c.startswith(m) or m.startswith(c) for m in managers if len(m) >= 4)


def _listed_names(krx_rows: list[dict]) -> set[str]:
    out: set[str] = set()
    for r in krx_rows:
        for k in ("ISU_NM", "ISU_ABBRV"):
            n = _norm_name(r.get(k))
            if n:
                out.add(n)
    return out


def upcoming_candidates(filings: list[dict], krx_rows: list[dict]) -> list[dict]:
    """상장 예정 후보 펀드(범위 붙이기 전). 펀드별 최신 공시 하나 + 문서 볼 투자설명서 접수번호."""
    managers = manager_set(krx_rows, filings)
    listed = _listed_names(krx_rows)
    funds: dict[str, dict] = {}
    for f in filings:
        nm = f.get("report_nm") or ""
        if "상장지수" not in nm:
            continue
        kind, amend = report_kind(nm)
        fn = fund_name(nm)
        if kind is None or not fn:
            continue
        key = _norm_name(fn)
        g = funds.setdefault(key, {"name": fn, "filings": [], "company": f.get("corp_name") or ""})
        g["filings"].append((f.get("rcept_no") or "", f.get("rcept_dt") or "", kind, amend, f.get("corp_name") or ""))

    out = []
    for key, g in funds.items():
        fs = sorted(g["filings"], key=lambda x: x[0], reverse=True)
        kinds = {(k, a) for _, _, k, a, _ in fs}
        if key in listed:
            continue                                   # 이미 상장
        if any(k in ("증권발행실적보고서", "철회신고서") for k, _ in kinds):
            continue                                   # 설정 끝났거나 철회
        if not any(k in ("일괄신고서", "증권신고서") and not a for k, a in kinds):
            continue                                   # 새 펀드가 아니다(기존 ETF 의 정정)
        corp = fs[0][4]
        if not _is_manager(corp, managers):
            continue                                   # ETF 운용사가 아니다
        prospectus = next((r for r, _, k, _, _ in fs if k == "투자설명서"), None)
        out.append({
            "rcept_no": fs[0][0],
            "name": g["name"],
            "company": corp,
            "filed": _iso(fs[0][1]),
            "is_amend": fs[0][3],
            "doc_rcept_no": prospectus,
        })
    return out


def finalize_upcoming(cands: list[dict], ranges: dict[str, tuple[str | None, str | None]],
                      today: date, limit: int = UPCOMING_LIMIT) -> list[dict]:
    out = []
    for c in cands:
        est_from, est_to = ranges.get(c.get("doc_rcept_no") or "", (None, None))
        if est_to and est_to < today.isoformat():
            continue                                   # 예상 구간이 이미 지났다
        out.append({
            "rcept_no": c["rcept_no"],
            "name": c["name"],
            "company": c["company"],
            "filed": c["filed"],
            "est_from": est_from,
            "est_to": est_to,
            "is_amend": c["is_amend"],
        })
    # 범위가 있는 건 이른 순, 없는 건 최근 공시 순.
    out.sort(key=lambda x: (x["est_from"] is None, x["est_from"] or "", "" if x["est_from"] else _neg(x["filed"])))
    return out[:limit]


def _neg(iso: str | None) -> str:
    t = re.sub(r"\D", "", iso or "")
    return "".join(str(9 - int(ch)) for ch in t)


# ── 네트워크 (collector krx_fetch 에서 옮김, verify=True) ────────────────────

def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(transport=transport, verify=True, timeout=KRX_TIMEOUT, follow_redirects=True)


def post_krx_json(client: httpx.Client, payload: dict) -> dict:
    response = client.post(KRX_URL, headers=KRX_HEADERS, data=payload)
    response.raise_for_status()
    return response.json()


def login_krx(client: httpx.Client, user: str, pw: str) -> None:
    client.get(KRX_MAIN_PAGE_URL, headers=KRX_HEADERS)
    client.get(KRX_LOGIN_PAGE_URL, headers=KRX_HEADERS)
    client.get(KRX_LOGIN_JSP_URL, headers={**KRX_HEADERS, "Referer": KRX_LOGIN_PAGE_URL})
    headers = {**KRX_HEADERS, "Referer": KRX_LOGIN_PAGE_URL, "X-Requested-With": "XMLHttpRequest"}
    payload = {"mbrId": user, "pw": pw, "mbrNm": "", "telNo": "", "di": "", "certType": ""}
    response = client.post(KRX_LOGIN_URL, headers=headers, data=payload)
    response.raise_for_status()
    data = response.json()
    error_code = data.get("_error_code", "")
    if error_code == "CD011":                      # 중복 로그인 — skipDup 으로 한 번 더
        payload["skipDup"] = "Y"
        response = client.post(KRX_LOGIN_URL, headers=headers, data=payload)
        response.raise_for_status()
        data = response.json()
        error_code = data.get("_error_code", "")
    if error_code and error_code != "CD001":
        raise RuntimeError(f"KRX login failed: {error_code} {data.get('_error_message', '')}")


def krx_session(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """개인 계정으로 로그인한 세션. ★평문 settings 만 읽는다 — vault·decrypt_env 폴백 없음(A5)."""
    user, pw = settings.KRX_USER, settings.KRX_PW
    if not user or not pw:
        raise KeyMissing("KRX_USER/KRX_PW 미설정")
    client = _client(transport)
    try:
        login_krx(client, user, pw)
    except Exception:
        client.close()
        raise
    return client


def fetch_krx(client: httpx.Client, today: date) -> dict:
    """목록 → 상장일 → 그 종목들의 구성종목·거래·개인순매수."""
    rows = post_krx_json(client, {"bld": "dbms/MDC/STAT/standard/MDCSTAT04601"}).get("output") or []
    if not rows:
        raise RuntimeError("KRX MDCSTAT04601 빈 응답")
    day = listing_day(rows, today)
    listing = {"date": None, "is_today": False, "rows": []}
    report = {"date": None, "is_today": False, "rows": []}
    if day is not None:
        trd = day.strftime("%Y%m%d")
        meta = listed_on(rows, day)
        prices = {
            (p.get("ISU_SRT_CD") or "").strip(): p
            for p in post_krx_json(client, {"bld": "dbms/MDC/STAT/standard/MDCSTAT04301", "trdDd": trd}).get("output") or []
        }
        stats: dict[str, dict] = {}
        for r in meta:
            pdf = post_krx_json(
                client, {"bld": "dbms/MDC/STAT/standard/MDCSTAT05001", "trdDd": trd, "isuCd": r["isin"]}
            ).get("output") or []
            r["holdings"] = holdings_rows(pdf)
            inv = post_krx_json(client, {
                "bld": "dbms/MDC/STAT/standard/MDCSTAT04901", "strtDd": trd, "endDd": trd,
                "isuCd": r["isin"], "inqTpCd": "1", "trdVolVal": "2", "askBid": "3",
            }).get("output") or []
            p = prices.get(r["ticker"]) or {}
            fluc = _num(p.get("FLUC_RT"))
            stats[r["ticker"]] = {
                "trade_value": _eok(p.get("ACC_TRDVAL")),
                "ret": None if fluc is None else fluc / 100,
                "net_buy": individual_net_buy(inv),
            }
        listing = {"date": day.isoformat(), "is_today": day == today, "rows": meta}
        report = {"date": day.isoformat(), "is_today": day == today, "rows": report_rows(meta, stats)}
    return {"rows": rows, "listing": listing, "report": report}


def fetch_dart_filings(client: httpx.Client, key: str, today: date) -> list[dict]:
    bgn = (today - timedelta(days=DART_LOOKBACK_DAYS - 1)).strftime("%Y%m%d")
    out: list[dict] = []
    page = 1
    while True:
        r = client.get(DART_LIST_URL, params={
            "crtfc_key": key, "bgn_de": bgn, "end_de": today.strftime("%Y%m%d"),
            "pblntf_ty": "G", "page_count": 100, "page_no": page,
        })
        r.raise_for_status()
        j = r.json()
        status = j.get("status")
        if status == "013":                            # 조회된 데이터 없음
            return out
        if status != "000":
            raise RuntimeError(f"DART list {status} {j.get('message', '')}")
        out += j.get("list") or []
        if page >= int(j.get("total_page") or 1):
            return out
        page += 1


def fetch_dart_doc_text(client: httpx.Client, key: str, rcept_no: str) -> str | None:
    """document.xml(zip) 본문 텍스트. 없으면(014 등) None."""
    r = client.get(DART_DOC_URL, params={"crtfc_key": key, "rcept_no": rcept_no})
    r.raise_for_status()
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except zipfile.BadZipFile:
        return None
    parts = []
    for n in z.namelist():
        raw = z.read(n)
        for enc in ("utf-8", "cp949"):
            try:
                parts.append(raw.decode(enc))
                break
            except UnicodeDecodeError:
                continue
    return "\n".join(parts)


# ── 루프 본체 ────────────────────────────────────────────────────────────────

def _due(name: str, force: bool) -> bool:
    last = _last_attempt.get(name)
    return force or last is None or time.monotonic() - last >= RETRY_AFTER_SECONDS


def _now_kst(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=9)))


def sync(db, now: datetime | None = None, *, transport: httpx.BaseTransport | None = None,
         force: bool = False) -> dict[str, str]:
    """KRX·DART 를 필요할 때만 받는다. → {"krx": ok|skip|error, "dart": …}."""
    today = today_kst(now)
    kst = _now_kst(now)
    out = {"krx": "skip", "dart": "skip"}

    listing = _state["listing"] or {}
    need_krx = (
        _state["krx_day"] != today
        or (not _state["stats_final"] and listing.get("is_today"))
    )
    if (force or need_krx) and _due("krx", force):
        _last_attempt["krx"] = time.monotonic()
        try:
            # ⚠️로그인으로 이미 열린 httpx.Client 는 `with` 로 다시 열 수 없다 — 직접 닫는다.
            client = krx_session(transport)
            try:
                got = fetch_krx(client, today)
            finally:
                client.close()
            _state.update(
                krx_day=today, krx_rows=got["rows"], listing=got["listing"], report=got["report"],
                stats_final=(not got["listing"]["is_today"]) or kst.time() >= STATS_FINAL_AFTER,
                krx_error=None,
            )
            record_ok(db, "etf_krx", {
                "etfs": len(got["rows"]), "listing_date": got["listing"]["date"],
                "listed": len(got["listing"]["rows"]), "latest_date": today.isoformat(),
            })
            out["krx"] = "ok"
        except Exception as exc:  # noqa: BLE001 — 실패해도 마지막 캐시는 그대로
            db.rollback()
            logger.warning("etf krx sync failed: %s", type(exc).__name__)
            _state["krx_error"] = f"KRX 조회 실패 — {'키 미설정' if isinstance(exc, KeyMissing) else type(exc).__name__}"
            record_error(db, "etf_krx", exc)
            out["krx"] = "error"

    krx_rows = _state["krx_rows"]
    if krx_rows and (force or _state["dart_day"] != today) and _due("dart", force):
        _last_attempt["dart"] = time.monotonic()
        try:
            key = settings.OPENDART_API_KEY
            if not key:
                raise KeyMissing("OPENDART_API_KEY 미설정")
            with _client(transport) as client:
                filings = fetch_dart_filings(client, key, today)
                cands = upcoming_candidates(filings, krx_rows)
                for c in cands:
                    rc = c.get("doc_rcept_no")
                    if rc and rc not in _doc_ranges:
                        _doc_ranges[rc] = listing_range(fetch_dart_doc_text(client, key, rc))
            ups = finalize_upcoming(cands, _doc_ranges, today)
            _state.update(dart_day=today, upcoming=ups, dart_error=None)
            record_ok(db, "etf_dart", {
                "filings": len(filings), "upcoming": len(ups), "latest_date": today.isoformat(),
            })
            out["dart"] = "ok"
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("etf dart sync failed: %s", type(exc).__name__)
            _state["dart_error"] = f"DART 조회 실패 — {'키 미설정' if isinstance(exc, KeyMissing) else type(exc).__name__}"
            record_error(db, "etf_dart", exc)
            out["dart"] = "error"
    return out


def run_once(now: datetime | None = None, *, force: bool = False) -> dict[str, str]:
    with SessionLocal() as db:
        return sync(db, now, force=force)


async def etf_listing_sync_loop() -> None:
    # 기동 직후엔 쉰다 — --reload 재시작·테스트 TestClient 마다 KRX 에 로그인하지 않게.
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = await asyncio.to_thread(run_once)
            if any(v != "skip" for v in result.values()):
                logger.info("etf listing sync: %s", result)
        except Exception:
            logger.exception("etf listing sync check failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ── 응답 ────────────────────────────────────────────────────────────────────

def payload(now: datetime | None = None) -> dict:
    """/api/v1/etf/new-listing 이 내보내는 한 묶음. 캐시가 비어 있으면 note 를 단다(503 아님)."""
    kst = _now_kst(now)
    empty = {"date": None, "is_today": False, "rows": []}
    notes = [n for n in (_state["krx_error"], _state["dart_error"]) if n]
    if _state["krx_day"] is None and not _state["krx_error"]:
        notes.insert(0, "KRX 목록을 아직 받지 않았습니다(기동 후 약 1분 뒤 받습니다)")
    return {
        "generated_at": kst.strftime("%Y-%m-%d %H:%M:%S"),
        "today": kst.date().isoformat(),
        "note": " · ".join(notes) or None,
        "report": _state["report"] or empty,
        "listing": _state["listing"] or empty,
        "upcoming": _state["upcoming"] or [],
    }
