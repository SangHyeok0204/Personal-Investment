"""[국내상장 ETF · 신규상장] 성적표 · 금일 상장 · 상장 임박 (2026-09-02).

[분류별 개인 순매수] 화면 왼쪽 네 박스 중 위 두 개가 쓰는 데이터원. 원천이 넷이고
각자 주인이 달라서, 이 모듈은 **가져다 붙이기만** 한다(계산·판단은 원천 쪽 소관).

  ① 성적표   daily_analysis/YYYYMMDD_신규상장.txt   ← 워크북 매크로가 장 마감 뒤 굽는다
                거래대금·개인순매수만 있고 **수익률은 없다** → 워크북 value 시트에서 이름으로 붙인다.
  ② 금일상장  KRX MDCSTAT04601 (collector 직접 조회)
                ★★상장일 확정치는 **KRX 만** 준다. 총보수(ETF_TOT_FEE)·운용사·기초지수도 여기서 온다.
  ③ 구성종목  펀드공시모니터 cache/holdings/{상장일}.json  ← 그쪽이 07:30 에 KRX+claude 로 굽는다
                ⚠️같은 파일의 fee·company 는 **비어 있다**(실측 09-01). 그래서 ②에서 채운다.
  ④ 실시간   CHECK 호가 envelope 의 newEtfs   ← 거래대금·거래량·등락률
                ⚠️`etf_flows.py` 는 이 배열에서 세 필드만 꺼내 쓴다. 원본에는 change(등락률)·
                price·marketCap 도 들어 있다 — 여기서는 원본을 다시 읽는다.

★★"자정에 DART 로 금일 상장을 판단한다"는 지시대로 할 수 없는 부분이 하나 있다. DART
  예비투자설명서가 주는 건 **예상 상장일 범위**(est_listing_from~to)지 확정일이 아니다
  (실측: 20260813001776 → 2026-09-04~09-11). 그래서 갈랐다:
    · 금일 상장(확정) = KRX LIST_DD == 오늘
    · 상장 임박(예정) = DART processed JSON 의 est_listing 범위가 오늘 이후
  DART 를 확정일로 쓰면 "오늘 상장한다"고 써 놓고 다음 주에 상장하는 일이 생긴다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

DAILY_DIR = os.environ.get(
    "ETF_NEW_DAILY_DIR", "/srv/legacy/etf_monitor/daily_analysis"
)
# 펀드공시모니터가 굽는 두 산출물. 우리는 읽기만 한다.
FUND_FILING_DIR = os.environ.get("ETF_NEW_FUND_FILING_DIR", "/srv/legacy/fund_filing")
HOLDINGS_SUBDIR = "cache/holdings"
PRELISTING_SUBDIR = "input/processed"

# KRX 목록은 1,167행이라 매 요청마다 받을 게 아니다. 하루 한 번이면 충분하다.
KRX_TTL_S = 6 * 3600
UPCOMING_LIMIT = 8
REPORT_LOOKBACK_DAYS = 10   # 성적표 txt 를 며칠까지 거슬러 찾을지


# ── 값 다루기 ────────────────────────────────────────────────────────────────

def _today() -> date:
    return datetime.now(_KST).date()


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


# ── ① 성적표 txt ─────────────────────────────────────────────────────────────

_ITEM_RE = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$")
_AMT_RE = re.compile(r"^\s*거래대금\s*:\s*([-+]?[\d,]+)\s*억\s*$")
_NET_RE = re.compile(r"^\s*개인순매수\s*:\s*([-+]?[\d,]+)\s*억\s*$")


def parse_report(text: str) -> list[dict]:
    """'금일 상장 ETF 성적표' txt → [{rank, name, trade_value, net_buy}] (억원).

    형식이 단순해서 상태 기계 하나면 된다. 번호 줄이 오면 새 종목을 열고, 뒤따르는
    거래대금·개인순매수 줄을 채운다. 값이 없는 종목도 이름만으로 남긴다 —
    조용히 빠지면 "그 종목은 상장 안 했다"로 읽힌다.
    """
    out: list[dict] = []
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-"} or "성적표" in line:
            continue
        m = _AMT_RE.match(line)
        if m and cur is not None:
            cur["trade_value"] = _num(m.group(1))
            continue
        m = _NET_RE.match(line)
        if m and cur is not None:
            cur["net_buy"] = _num(m.group(1))
            continue
        m = _ITEM_RE.match(line)
        if m:
            cur = {
                "rank": int(m.group(1)),
                "name": m.group(2).strip(),
                "trade_value": None,
                "net_buy": None,
            }
            out.append(cur)
    return out


def _decode(blob: bytes) -> str:
    """신규상장 txt 의 인코딩을 정한다.

    ★★같은 폴더의 두 txt 가 인코딩이 다르다(2026-09-02 실측). 일별 분석 txt 는 cp949,
      **신규상장 txt 는 UTF-8** 이다. cp949 로 고정하면 이름이 깨지는 데서 그치지 않고
      `거래대금:` 머리글까지 깨져 정규식이 안 맞아 **금액이 전부 결측**이 된다.
      그래서 UTF-8 을 먼저 엄격하게 시도하고, 실패할 때만 cp949 로 내려간다.
      (errors="replace" 를 처음부터 쓰면 깨진 채로 '성공'해서 이 사실을 못 만난다.)
    """
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            continue
    return blob.decode("cp949", errors="replace")


def _read_report(day: date) -> tuple[str | None, list[dict]]:
    """그날의 신규상장 txt. 없으면 (None, [])."""
    path = os.path.join(DAILY_DIR, f"{day:%Y%m%d}_신규상장.txt")
    if not os.path.isfile(path):
        return None, []
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError:
        return None, []
    return path, parse_report(_decode(blob))


def find_report(upto: date, lookback: int = REPORT_LOOKBACK_DAYS) -> dict:
    """오늘 것이 있으면 오늘 것, 없으면 최근 것을 날짜와 함께.

    ★상장은 주 1회꼴(주로 화요일)이라 대부분의 날은 파일이 없다. 없는 날 빈 화면을
      두는 대신 최근 것을 **날짜를 밝혀서** 보여준다 — 날짜 없이 보여주면 "오늘 상장한
      것"으로 읽혀 틀린 말이 된다.
    """
    path, rows = _read_report(upto)
    if path:
        return {"date": upto.isoformat(), "is_today": True, "rows": rows, "path": path}
    for back in range(1, lookback + 1):
        d = upto - timedelta(days=back)
        path, rows = _read_report(d)
        if path:
            return {"date": d.isoformat(), "is_today": False, "rows": rows, "path": path}
    return {"date": None, "is_today": False, "rows": [], "path": None}


# ── ② KRX 상장 목록 (총보수·운용사·기초지수) ────────────────────────────────

# ★캐시에 **어느 날짜 기준으로 받았는지**를 같이 둔다. TTL 만으로는 부족하다 —
#   자정에 상장한 종목은 전날 받아 둔 목록에 아예 없어서, TTL 이 남아 있는 동안
#   "금일 상장 없음" 이라고 말하게 된다(사용자 지시: 자정마다 판단).
_krx_cache: dict = {"at": 0.0, "day": None, "rows": None, "error": None}


def _krx_rows(force: bool = False) -> tuple[list[dict], str | None]:
    """MDCSTAT04601 전 종목. (rows, error). 실패해도 예외를 올리지 않는다 —
    이 화면의 나머지(성적표·실시간)는 KRX 없이도 나와야 한다."""
    import time

    now = time.time()
    today = _today()
    fresh = (
        _krx_cache["rows"] is not None
        and _krx_cache["day"] == today          # 날짜가 넘어가면 무조건 다시 받는다
        and now - _krx_cache["at"] < KRX_TTL_S
    )
    if not force and fresh:
        return _krx_cache["rows"], _krx_cache["error"]
    try:
        from collector import krx_fetch as kf

        user = os.environ.get("ETF_INAV_MONITOR__KRX_USER") or None
        pw = os.environ.get("ETF_INAV_MONITOR__KRX_PW") or None
        session = kf.make_krx_session(user, pw, verify_ssl=False)
        try:
            df = kf.get_all_listed_etfs(session)
        finally:
            session.close()
        rows = df.to_dict("records")
        _krx_cache.update(at=now, day=today, rows=rows, error=None)
        return rows, None
    except Exception as exc:  # noqa: BLE001 - 자격증명·네트워크 어느 쪽이든 화면은 살린다
        err = f"KRX 목록 조회 실패 — {exc}"
        # 예전 값이 있으면 그걸 계속 쓴다(하루치라 조금 낡아도 총보수는 안 바뀐다).
        if _krx_cache["rows"] is not None:
            # 날짜는 갱신하지 않는다 — 다음 판에서 다시 시도해야 하기 때문이다.
            _krx_cache["error"] = err
            return _krx_cache["rows"], err
        _krx_cache.update(at=now, day=None, rows=[], error=err)
        return [], err


def krx_listed_on(day: date) -> tuple[list[dict], str | None]:
    """그날 상장한 ETF 메타. LIST_DD 는 'YYYY/MM/DD' 형식이다."""
    rows, err = _krx_rows()
    target = f"{day:%Y/%m/%d}"
    out = []
    for r in rows:
        if str(r.get("LIST_DD") or "") != target:
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
    return out, err


def find_listing_day(upto: date, lookback: int = REPORT_LOOKBACK_DAYS) -> tuple[date | None, list[dict], str | None]:
    """오늘 상장이 있으면 오늘, 없으면 가장 최근 상장일."""
    rows, err = krx_listed_on(upto)
    if rows:
        return upto, rows, err
    for back in range(1, lookback + 1):
        d = upto - timedelta(days=back)
        rows, err = krx_listed_on(d)
        if rows:
            return d, rows, err
    return None, [], err


# ── ③ 구성종목 (펀드공시모니터가 구운 캐시) ─────────────────────────────────

def holdings_for(day: date) -> dict[str, list[dict]]:
    """{티커: [{name, weight}]}. 없으면 빈 dict — 구성종목은 있으면 좋은 값이다."""
    path = os.path.join(FUND_FILING_DIR, HOLDINGS_SUBDIR, f"{day:%Y%m%d}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    out: dict[str, list[dict]] = {}
    if not isinstance(data, list):
        return out
    for e in data:
        if not isinstance(e, dict):
            continue
        tk = (e.get("ticker") or "").strip()
        hs = [
            {"name": str(h.get("name") or "").strip(), "weight": _num(h.get("weight"))}
            for h in (e.get("holdings") or [])
            if isinstance(h, dict) and h.get("name")
        ]
        if tk:
            out[tk] = hs
    return out


# ── ④ 상장 임박 (DART 예비투자설명서) ───────────────────────────────────────

def _norm_name(s: str | None) -> str:
    """상장 여부 대조용 정규화. 공백·괄호·구분자를 지우고 대문자로.

    펀드공시모니터 `dart_prelisting._norm` 과 같은 규칙이다 — DART 는 정식 전체명
    ("한국투자ACE…증권상장지수투자신탁(채권혼합)")을, KRX 는 같은 정식명을 ISU_NM 으로
    준다. 표기 차이(괄호·공백)만 걷어내면 맞는다.
    """
    return re.sub(r"[\s()\[\]·\-_,\.]", "", s or "").upper()


def _krx_listed_names() -> set[str]:
    """이미 상장한 ETF 의 정규화 이름 집합. 조회 실패면 빈 집합(필터를 건너뛴다)."""
    rows, _err = _krx_rows()
    out: set[str] = set()
    for r in rows:
        for k in ("ISU_NM", "ISU_ABBRV"):
            n = _norm_name(r.get(k))
            if n:
                out.add(n)
    return out


def upcoming(upto: date, limit: int = UPCOMING_LIMIT) -> list[dict]:
    """**아직 상장 안 한** 건만. 예상 상장 구간이 오늘 이후로 열려 있어야 한다.

    ★DART 가 주는 건 **범위**다. 확정일이 아니므로 화면도 범위로 적어야 한다.
    ★★범위만으로는 부족하다(2026-09-02 사용자 지적). 예상 구간의 끝이 오늘이어도 이미
      상장한 건이 있다 — DART 는 상장 사실을 되돌려 적지 않는다. 그래서 **KRX 상장
      목록과 대조해 이미 상장한 이름을 뺀다**(펀드공시모니터 dart_prelisting 의 필터③과
      같은 방식). KRX 조회가 실패하면 이 필터만 건너뛴다 — 목록 자체는 살린다.
    """
    listed = _krx_listed_names()
    d = os.path.join(FUND_FILING_DIR, PRELISTING_SUBDIR)
    try:
        names = sorted(os.listdir(d), reverse=True)
    except OSError:
        return []
    out: list[dict] = []
    today = upto.isoformat()
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                e = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(e, dict):
            continue
        to = (e.get("est_listing_to") or "").strip()
        if not to or to < today:      # 이미 지난 건은 '임박'이 아니다
            continue
        if listed and _norm_name(e.get("name")) in listed:
            continue                  # 이미 상장했다 — 범위가 아직 안 끝났어도 뺀다
        out.append({
            "rcept_no": e.get("rcept_no") or "",
            "name": (e.get("name") or "").strip(),
            "company": (e.get("corp_name") or "").strip(),
            "est_from": (e.get("est_listing_from") or "").strip(),
            "est_to": to,
            "is_amend": bool(e.get("is_amend")),
            "holdings": [
                {"name": str(h.get("name") or "").strip(), "weight": _num(h.get("weight"))}
                for h in (e.get("holdings") or [])
                if isinstance(h, dict) and h.get("name")
            ],
            "holdings_src": e.get("holdings_src") or "",
        })
    out.sort(key=lambda x: (x["est_from"] or x["est_to"], x["name"]))
    return out[:limit]


# ── ⑤ CHECK 실시간 (호가 envelope 의 newEtfs 원본) ──────────────────────────

# 이보다 오래된 envelope 은 "실시간" 이라 부르지 않는다.
# ★CHECK 는 매초 POST 한다. 5분이면 장중 정상 지연을 훨씬 넘고, 장 마감·CHECK PC 정지
#   같은 상황을 잡아낸다. 낡은 값을 실시간이라 보여주면 그 자체가 틀린 말이다.
REALTIME_STALE_S = 300


def realtime_asof(hoga: dict | None) -> tuple[str | None, bool]:
    """(envelope 시각, 낡았는가). 시각을 못 읽으면 낡은 것으로 본다 — 모르면 믿지 않는다."""
    ts = (hoga or {}).get("source_timestamp")
    if not ts:
        return None, True
    try:
        seen = datetime.fromisoformat(str(ts))
    except ValueError:
        return str(ts), True
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=_KST)
    age = (datetime.now(_KST) - seen).total_seconds()
    return str(ts), age > REALTIME_STALE_S


def realtime(hoga: dict | None) -> dict[str, dict]:
    """{티커: {price, change, trade_value, volume, market_cap, indiv_net}}.

    ⚠️단위가 섞여 있다 — tradeAmt·marketCap 은 **억원**, volume 은 **주**,
      change 는 **%**, price 는 원. `etf_flows.py` 는 웹 포맷터에 맞추려고 억을 원으로
      환산하지만(×1e8), 이 화면은 억을 그대로 쓴다. 두 카드가 같은 필드를 다른 단위로
      쓰므로 옮겨 붙일 때 주의할 것.
    """
    out: dict[str, dict] = {}
    payload = (hoga or {}).get("payload") or {}
    rows = payload.get("newEtfs")
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        tk = str(r.get("code") or "").strip()
        if not tk:
            continue
        out[tk] = {
            "price": _num(r.get("price")),
            "change": _num(r.get("change")),          # %
            "trade_value": _num(r.get("tradeAmt")),   # 억
            "volume": _num(r.get("volume")),          # 주
            "market_cap": _num(r.get("marketCap")),   # 억
            "indiv_net": _num(r.get("indivNet")),     # 억
            "listed": str(r.get("listedDate") or "").strip(),
        }
    return out


def refresh_daily() -> dict:
    """날짜가 넘어갔으면 KRX 목록을 다시 받는다. 배경 루프가 부른다.

    ★"자정마다 금일 신규상장을 판단" 하려면 **자정 이후 첫 조회가 새 목록이어야** 한다.
      요청이 올 때만 받으면(read-through) 아무도 화면을 안 연 아침에는 판단 자체가 없다.
      그렇다고 매번 받을 수도 없다 — 1,167행 조회에 로그인이 붙는다.
    반환: {refreshed, day, count, listed_today, error}
    """
    today = _today()
    stale = _krx_cache["rows"] is None or _krx_cache["day"] != today
    if not stale:
        return {"refreshed": False, "day": today.isoformat(),
                "count": len(_krx_cache["rows"] or []), "listed_today": None, "error": None}
    rows, err = _krx_rows(force=True)
    listed, _ = krx_listed_on(today)
    return {
        "refreshed": True,
        "day": today.isoformat(),
        "count": len(rows),
        "listed_today": [r["name"] for r in listed],
        "error": err,
    }


# ── payload ──────────────────────────────────────────────────────────────────

def build(hoga: dict | None = None, workbook_returns: dict | None = None) -> dict:
    """왼쪽 박스 ①②가 쓰는 한 묶음.

    workbook_returns: {ETF명: 등락률(소수)} — 성적표 txt 에 없는 수익률을 붙이는 데 쓴다.
                      호출부(main)가 etf_class 스냅샷에서 만들어 넘긴다.
    """
    today = _today()
    rt_asof, rt_stale = realtime_asof(hoga)
    out: dict = {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "today": today.isoformat(),
        "note": None,
        # CHECK envelope 이 언제 것인가. 화면은 낡으면 '실시간' 이라 쓰지 않는다.
        "realtime_asof": rt_asof,
        "realtime_stale": rt_stale,
        "report": {"date": None, "is_today": False, "rows": []},
        "listing": {"date": None, "is_today": False, "rows": []},
        "upcoming": [],
    }

    # ① 금일 상장 + ② 구성종목 + ③ 실시간 (성적표가 이 결과를 다시 쓰므로 먼저 만든다)
    day, rows, err = find_listing_day(today)
    if err:
        out["note"] = err
    if day is not None:
        hold = holdings_for(day)
        live = realtime(hoga)
        for r in rows:
            r["holdings"] = hold.get(r["ticker"], [])
            r["realtime"] = live.get(r["ticker"])
        out["listing"] = {
            "date": day.isoformat(),
            "is_today": day == today,
            "rows": rows,
        }

    # ④ 성적표 — 수익률은 워크북에서, 총보수·실시간은 위 KRX/CHECK 결과에서 붙인다.
    #   ★조인은 **이름**으로 한다. txt·KRX 둘 다 같은 정식 약명을 쓴다(2026-09-02 실측:
    #     9/1 3종목 전부 일치, 과거 90종목 중 97.8% 일치·나머지는 상장폐지 종목).
    #   ★조인을 서버에서 하는 이유: 화면이 같은 규칙을 한 벌 더 갖게 두면 두 곳이 갈린다.
    #     못 찾은 종목은 None 으로 둔다 — 0 으로 채우면 "보수 0%" 같은 거짓말이 된다.
    rep = find_report(today)
    rets = workbook_returns or {}
    by_name = {r["name"]: r for r in (out["listing"]["rows"] or [])}
    for r in rep["rows"]:
        r["ret"] = rets.get(r["name"])
        m = by_name.get(r["name"])
        r["ticker"] = (m or {}).get("ticker", "")
        r["fee"] = (m or {}).get("fee")
        r["realtime"] = (m or {}).get("realtime")
    out["report"] = {"date": rep["date"], "is_today": rep["is_today"], "rows": rep["rows"]}

    # ⑤ 상장 임박
    out["upcoming"] = upcoming(today)
    return out
