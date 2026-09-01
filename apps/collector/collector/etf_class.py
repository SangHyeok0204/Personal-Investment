"""[국내상장 ETF 자금·수익률] — `국내상장ETF 모니터링.xlsm` 의 `value` 시트 판독 (2026-09-01).

장 마감 뒤 "개인 자금이 어느 분류로 몰렸고 그 분류의 수익률은 어땠나" 를 보는 페이지의
데이터원. 원천은 운용역이 매일 굽는 워크북 한 장뿐이다(S: 의 매크로가 CT/CTD 로 채운다).

★★단위·의미는 시트 수식에서 확정했다(추정 아님):
    E열 거래대금(억)   = CT(code, 16002)/1e8          — 원 → 억
    F열 개인 순매수(억) = CT(code, "6511^10")/1e5      — 천원 → 억  (당일 개인 순매수)
    O~R MMT_1w..6m    = CTD("RATE", code, 시작, 끝, "15001")/100   — 기간 수익률(소수)
    S~V FF_1w..6m     = CTD("SUM",  code, 시작, 끝, "6511^10")/1e5 — **같은 6511^10 의
                         기간 합계**. 즉 FF 는 "펀드 자금유입"이 아니라 **개인 순매수 누적**이다.
  ⚠️이름만 보고 FF 를 설정/환매(자금유입)로 읽으면 페이지 전체가 틀린 말을 하게 된다.
  검증(2026-08-31 기준일): 당일 F열 상·하위가 daily_analysis/20260831.txt 의
  "개인순매수 상위/하위 10개 ETF" 와 종목·금액 모두 일치했다.

★★기간 창은 시트 1·2행(15~22열)에 **명시**돼 있다 — 우리가 날짜를 세지 않는다.
  20260831 기준: 1w=0824~0831, 1m=0731~0831, 3m=0531~0831, 6m=0228~0831.
  네 창은 전부 **끝일이 같고 오늘을 포함**한다(당일 ⊂ 1주 ⊂ 1달 ⊂ 3달 ⊂ 6달).
  그래서 "구간 분해"(1주~1달, 1~3달, 3~6달)는 누적끼리 빼서 만든다 — 겹침을 안 걷어내면
  같은 돈을 네 번 센다.

★★수익률 집계는 **ETF 단위로 먼저 구간 수익률을 만들고**(복리 체인) 그 다음 가중한다.
  누적 평균끼리 나누면 분류가 바뀔 때 종목 구성이 달라져 값이 미끄러진다.
  가중치는 **현재 시총**이다 — 과거 구간에 현재 시총을 쓰는 근사임을 화면에 적어 둔다.
  단순평균도 같이 낸다(daily_analysis txt 의 "중분류 평균" 과 맞춰 보기 위해서다).

★★절대 억원만 보면 순위가 늘 시장형/S&P500 이다(규모가 이긴다). 그래서 강도
  `net/시총`(%)을 같이 낸다 — 주간가격모니터가 "저점 대비 픽" 에서 배운 것과 같은 교훈.

★HISTORICAL 두 갈래:
  1) 구간 분해 — 오늘 스냅샷 하나로 4구간을 만든다. **첫날부터 그려진다.**
  2) 일별 누적 — 이 모듈이 스냅샷을 sqlite 에 적재해 쌓는다(read-through, 기준일 멱등).
     워크북은 **덮어쓰기**라 과거가 없다. 그래서 오늘부터 쌓인다 — 화면이 그 사실을 말한다.
"""
from __future__ import annotations

import io
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

SRC_PATH = os.environ.get(
    "ETF_CLASS_XLSM",
    "/srv/legacy/etf_monitor/국내상장ETF 모니터링.xlsm",
)
DB_PATH = os.environ.get("ETF_CLASS_DB", "/srv/storage/etf_monitor/history.sqlite")
SHEET = "value"
HEADER_ROW = 5      # 5행 = 컬럼명, 6행부터 데이터
ASOF_CELL = (4, 1)  # A4 = 기준일 'YYYYMMDD'

# 시트 열 인덱스(0-base)와 기대 헤더. 열이 밀리면 조용히 틀린 값을 낸다 — 그래서 대조한다.
COLS = {
    "code": (1, "종목코드"),
    "name": (2, "ETF명"),
    "listed": (3, "상장일"),
    "amt": (4, "거래대금(억)"),
    "net": (5, "개인 순매수(억)"),
    "chg": (6, "등락률"),
    "price": (7, "현재가(원)"),
    "mcap": (8, "시총(억)"),
    "country": (9, "투자 국가"),
    "gubun": (10, "구분"),
    "big": (11, "대분류"),
    "mid": (12, "중분류"),
    "small": (13, "소분류"),
    "mmt_1w": (14, "MMT_1w"),
    "mmt_1m": (15, "MMT_1m"),
    "mmt_3m": (16, "MMT_3m"),
    "mmt_6m": (17, "MMT_6m"),
    "ff_1w": (18, "FF_1w"),
    "ff_1m": (19, "FF_1m"),
    "ff_3m": (20, "FF_3m"),
    "ff_6m": (21, "FF_6m"),
    "interest": (22, "관심ETF여부"),
}
_HORIZONS = ("1w", "1m", "3m", "6m")

# 화면이 고르는 기간. 누적(창 그대로) 다섯 + 구간(누적 차이) 넷.
PERIODS = [
    {"key": "d",  "label": "당일",  "span": None},
    {"key": "1w", "label": "1주",   "span": "1w"},
    {"key": "1m", "label": "1개월", "span": "1m"},
    {"key": "3m", "label": "3개월", "span": "3m"},
    {"key": "6m", "label": "6개월", "span": "6m"},
]
INTERVALS = [
    {"key": "1w", "label": "최근 1주",  "outer": "1w", "inner": None},
    {"key": "1m", "label": "1주~1개월", "outer": "1m", "inner": "1w"},
    {"key": "3m", "label": "1~3개월",   "outer": "3m", "inner": "1m"},
    {"key": "6m", "label": "3~6개월",   "outer": "6m", "inner": "3m"},
]

# 분류 축. path 는 트리 조상 열 — 표를 접었다 폈다 하는 데 쓴다.
AXES = [
    {"key": "gubun",   "label": "구분",     "col": "gubun",   "path": []},
    {"key": "big",     "label": "대분류",   "col": "big",     "path": ["gubun"]},
    {"key": "mid",     "label": "중분류",   "col": "mid",     "path": ["gubun", "big"]},
    {"key": "small",   "label": "소분류",   "col": "small",   "path": ["gubun", "big", "mid"]},
    {"key": "country", "label": "투자국가", "col": "country", "path": []},
]
_AXIS_BY_KEY = {a["key"]: a for a in AXES}
DEFAULT_AXIS = "mid"

_PERIOD_KEYS = [p["key"] for p in PERIODS]
_IV_KEYS = [s["key"] for s in INTERVALS]


# ── 값 다루기 ────────────────────────────────────────────────────────────────

def _num(v) -> float | None:
    """엑셀 셀 → float. '#VALUE!' 같은 오류 문자열·bool 은 결측으로 본다."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _txt(v) -> str:
    return str(v).strip() if v not in (None, "") else ""


def _asof_date(raw) -> str | None:
    """'YYYYMMDD'(또는 날짜형) → 'YYYY-MM-DD'."""
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    s = re.sub(r"\D", "", str(raw or ""))
    if len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat()
    except ValueError:
        return None


def _chain(outer: float | None, inner: float | None) -> float | None:
    """누적 수익률 둘 → 안쪽을 걷어낸 구간 수익률. (1+outer)/(1+inner)-1."""
    if outer is None:
        return None
    if inner is None:
        return outer
    if inner <= -1:
        return None      # -100% 는 나눌 수 없다. 값을 지어내지 않는다.
    return (1.0 + outer) / (1.0 + inner) - 1.0


def _diff(outer: float | None, inner: float | None) -> float | None:
    """누적 순매수 둘 → 구간 순매수. 합계라 그냥 뺀다."""
    if outer is None:
        return None
    return outer - (inner or 0.0)


# 묶음 크기 때문에 자릿수를 자른다 — 861종목 × 지표 18개면 `-0.20309999999999997` 같은
# 부동소수 꼬리가 payload 의 3할이다. 억은 소수 3자리(=1천원), 수익률은 6자리(=0.0001%)로
# 자른다. 화면 표기는 소수 1~2자리라 눈에 보이는 값은 하나도 안 바뀐다.
def _r(v: float | None, nd: int) -> float | None:
    return None if v is None else round(v, nd)


def _rd(d: dict, nd: int) -> dict:
    return {k: _r(v, nd) for k, v in d.items()}


# ── 워크북 판독 (mtime+size 캐시) ────────────────────────────────────────────

_CACHE: dict = {"sig": None, "snap": None}


def _read_snapshot(path: str = SRC_PATH) -> dict:
    """워크북 한 장 → {asof, windows, etfs[], source_modified}.

    헤더(5행)를 COLS 의 기대 문자열과 대조한다. 어긋나면 그 열만 비우는 게 아니라
    **전체를 거부**한다 — 열이 한 칸 밀린 채 계산하면 화면이 조용히 거짓말을 한다.
    """
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    if _CACHE["sig"] == sig and _CACHE["snap"] is not None:
        return _CACHE["snap"]

    with open(path, "rb") as f:
        blob = f.read()

    import openpyxl

    wb = openpyxl.load_workbook(
        io.BytesIO(blob), data_only=True, read_only=True, keep_links=False
    )
    try:
        ws = wb[SHEET]
        head = [row for row in ws.iter_rows(min_row=1, max_row=HEADER_ROW, values_only=True)]

        asof = _asof_date(head[ASOF_CELL[0] - 1][ASOF_CELL[1] - 1])
        hdr = head[HEADER_ROW - 1]
        for key, (idx, want) in COLS.items():
            got = _txt(hdr[idx] if idx < len(hdr) else None)
            if got != want:
                raise ValueError(f"열 배치가 다릅니다: {idx + 1}번째 열이 {got!r} (기대 {want!r})")

        # 1·2행 15~22열 = MMT 4창(15~18) + FF 4창(19~22)의 시작일/끝일.
        # 지금 워크북은 두 벌이 같은 날짜라 한 벌만 화면에 쓴다. 그래도 대조는 한다 —
        # 언젠가 갈라지면 "수익률 창"으로 "자금 창"을 설명하는 말이 되기 때문이다.
        def _win(base: int) -> dict:
            return {
                h: {
                    "start": _asof_date(head[0][base + i]) if len(head[0]) > base + i else None,
                    "end": _asof_date(head[1][base + i]) if len(head[1]) > base + i else None,
                }
                for i, h in enumerate(_HORIZONS)
            }

        windows = _win(14)
        ff_windows = _win(18)
        window_mismatch = [h for h in _HORIZONS if windows[h] != ff_windows[h]]

        etfs = []
        for r in ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True):
            code = _txt(r[COLS["code"][0]]) if len(r) > COLS["code"][0] else ""
            name = _txt(r[COLS["name"][0]]) if len(r) > COLS["name"][0] else ""
            if not code or not name:
                continue
            rec = {"code": code, "name": name}
            for key, (idx, _w) in COLS.items():
                if key in ("code", "name"):
                    continue
                v = r[idx] if idx < len(r) else None
                if key in ("listed", "country", "gubun", "big", "mid", "small"):
                    rec[key] = _txt(v)
                elif key == "interest":
                    rec[key] = bool(_num(v))
                else:
                    rec[key] = _num(v)
            etfs.append(rec)
    finally:
        wb.close()

    snap = {
        "asof": asof,
        "windows": windows,
        "ff_windows": ff_windows,
        "window_mismatch": window_mismatch,
        "etfs": etfs,
        "source_modified": datetime.fromtimestamp(st.st_mtime, _KST).strftime("%Y-%m-%d %H:%M"),
    }
    _CACHE["sig"] = sig
    _CACHE["snap"] = snap
    return snap


# ── ETF 한 줄 → 화면이 쓰는 지표 ─────────────────────────────────────────────

def _etf_metrics(e: dict) -> dict:
    """누적·구간을 ETF 단위에서 확정한다.

    ★수익률 구간은 여기서만 만든다. 분류 평균끼리 체인하면(집계 후 체인) 분류의 종목
      구성이 창마다 달라 값이 미끄러진다 — 종목 단위 체인이 유일하게 옳다.
    """
    net_cum = {"d": e["net"], "1w": e["ff_1w"], "1m": e["ff_1m"],
               "3m": e["ff_3m"], "6m": e["ff_6m"]}
    ret_cum = {"d": e["chg"], "1w": e["mmt_1w"], "1m": e["mmt_1m"],
               "3m": e["mmt_3m"], "6m": e["mmt_6m"]}
    net_iv, ret_iv = {}, {}
    for spec in INTERVALS:
        o, i = spec["outer"], spec["inner"]
        net_iv[spec["key"]] = _diff(net_cum[o], net_cum[i] if i else None)
        ret_iv[spec["key"]] = _chain(ret_cum[o], ret_cum[i] if i else None)
    return {"net_cum": net_cum, "ret_cum": ret_cum, "net_iv": net_iv, "ret_iv": ret_iv}


def _blank_bucket(label: str, path: list[str]) -> dict:
    return {
        "key": label, "label": label, "path": path, "n": 0,
        "mcap": 0.0, "amt": 0.0,
        "net_cum": dict.fromkeys(_PERIOD_KEYS, 0.0),
        "net_iv": dict.fromkeys(_IV_KEYS, 0.0),
        # 수익률은 (Σ w·r, Σ w) 를 따로 모은다 — 결측 종목의 시총이 분모에 남으면
        # 그 분류만 0 쪽으로 끌려 내려간다.
        "_rw": dict.fromkeys(_PERIOD_KEYS, 0.0),
        "_rwd": dict.fromkeys(_PERIOD_KEYS, 0.0),
        "_rs": dict.fromkeys(_PERIOD_KEYS, 0.0),
        "_rn": dict.fromkeys(_PERIOD_KEYS, 0),
        "_iw": dict.fromkeys(_IV_KEYS, 0.0),
        "_iwd": dict.fromkeys(_IV_KEYS, 0.0),
        "_is": dict.fromkeys(_IV_KEYS, 0.0),
        "_in": dict.fromkeys(_IV_KEYS, 0),
    }


def _accumulate(b: dict, e: dict, m: dict) -> None:
    b["n"] += 1
    mcap = e["mcap"] or 0.0
    b["mcap"] += mcap
    b["amt"] += e["amt"] or 0.0
    for k in _PERIOD_KEYS:
        v = m["net_cum"][k]
        if v is not None:
            b["net_cum"][k] += v
        r = m["ret_cum"][k]
        if r is not None:
            b["_rw"][k] += r * mcap
            b["_rwd"][k] += mcap
            b["_rs"][k] += r
            b["_rn"][k] += 1
    for k in _IV_KEYS:
        v = m["net_iv"][k]
        if v is not None:
            b["net_iv"][k] += v
        r = m["ret_iv"][k]
        if r is not None:
            b["_iw"][k] += r * mcap
            b["_iwd"][k] += mcap
            b["_is"][k] += r
            b["_in"][k] += 1


def _finalize(b: dict) -> dict:
    """가중/단순 평균을 확정하고 내부 누산기를 걷어낸다."""
    out = {k: v for k, v in b.items() if not k.startswith("_")}
    out["ret_cum"] = {k: (b["_rw"][k] / b["_rwd"][k] if b["_rwd"][k] else None)
                      for k in _PERIOD_KEYS}
    out["ret_cum_eq"] = {k: (b["_rs"][k] / b["_rn"][k] if b["_rn"][k] else None)
                         for k in _PERIOD_KEYS}
    out["ret_iv"] = {k: (b["_iw"][k] / b["_iwd"][k] if b["_iwd"][k] else None)
                     for k in _IV_KEYS}
    out["ret_iv_eq"] = {k: (b["_is"][k] / b["_in"][k] if b["_in"][k] else None)
                        for k in _IV_KEYS}
    # 강도 — 절대 억원은 규모가 이긴다. 시총 대비 몇 %가 들어왔나로 같이 본다.
    mc = b["mcap"] or 0.0
    out["ratio_cum"] = {k: (b["net_cum"][k] / mc * 100.0 if mc else None)
                        for k in _PERIOD_KEYS}
    out["ratio_iv"] = {k: (b["net_iv"][k] / mc * 100.0 if mc else None)
                       for k in _IV_KEYS}
    out["mcap"] = _r(out["mcap"], 1)
    out["amt"] = _r(out["amt"], 1)
    for k in ("net_cum", "net_iv"):
        out[k] = _rd(out[k], 3)
    for k in ("ret_cum", "ret_cum_eq", "ret_iv", "ret_iv_eq", "ratio_cum", "ratio_iv"):
        out[k] = _rd(out[k], 6)
    return out


def _group(etfs: list[dict], metrics: list[dict], axis_key: str) -> list[dict]:
    """한 축으로 묶는다. 라벨이 빈 종목은 '미분류' 로 모은다(조용히 버리지 않는다)."""
    axis = _AXIS_BY_KEY[axis_key]
    col, path_cols = axis["col"], axis["path"]
    buckets: dict[tuple, dict] = {}
    for e, m in zip(etfs, metrics):
        label = e.get(col) or "미분류"
        path = [e.get(c) or "미분류" for c in path_cols]
        k = (*path, label)
        b = buckets.get(k)
        if b is None:
            b = buckets[k] = _blank_bucket(label, path)
            b["key"] = " / ".join(k)
        _accumulate(b, e, m)
    rows = [_finalize(b) for b in buckets.values()]
    rows.sort(key=lambda r: -(r["net_cum"]["3m"] or 0.0))
    return rows


# ── payload ──────────────────────────────────────────────────────────────────

def build_snapshot() -> dict:
    """오늘의 분류별 자금·수익률 한 장. 전 축·전 기간을 한 번에 실어 보낸다.

    ★화면이 축·기간을 바꿀 때 재요청하지 않는다 — 축 5개·기간 9개를 다 담아도 묶음이
      크지 않고(수백 KB), 집계식이 서버 한 곳에만 있어 두 곳으로 갈라지지 않는다.
    """
    out: dict = {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "asof": None,
        "source_modified": None,
        "note": None,
        "axes": [{"key": a["key"], "label": a["label"]} for a in AXES],
        "periods": [dict(p) for p in PERIODS],
        "intervals": [dict(s) for s in INTERVALS],
        "windows": {},
        "groups": {},
        "etfs": [],
        "totals": None,
        "history_days": 0,
    }
    try:
        snap = _read_snapshot()
    except FileNotFoundError:
        out["note"] = f"원천 워크북이 없습니다 — {SRC_PATH}"
        return out
    except Exception as exc:  # 열 배치 어긋남·손상 등
        out["note"] = f"워크북을 읽지 못했습니다 — {exc}"
        return out

    etfs = snap["etfs"]
    metrics = [_etf_metrics(e) for e in etfs]
    out["asof"] = snap["asof"]
    out["source_modified"] = snap["source_modified"]
    out["windows"] = snap["windows"]
    for p in out["periods"]:
        w = snap["windows"].get(p["span"]) if p["span"] else None
        p["start"] = (w or {}).get("start") or snap["asof"]
        p["end"] = (w or {}).get("end") or snap["asof"]
    for s in out["intervals"]:
        inner = snap["windows"].get(s["inner"]) if s["inner"] else None
        outer = snap["windows"].get(s["outer"]) or {}
        s["start"] = outer.get("start")
        s["end"] = (inner or {}).get("start") or outer.get("end")

    if snap.get("window_mismatch"):
        out["note"] = (
            "수익률(MMT)과 순매수(FF)의 기간 창이 다릅니다 — "
            + ", ".join(snap["window_mismatch"])
            + ". 화면의 기간 표기는 수익률 창 기준입니다."
        )

    for a in AXES:
        out["groups"][a["key"]] = _group(etfs, metrics, a["key"])

    out["etfs"] = [
        {
            "code": e["code"], "name": e["name"],
            "country": e["country"], "gubun": e["gubun"],
            "big": e["big"], "mid": e["mid"], "small": e["small"],
            "mcap": _r(e["mcap"], 1), "amt": _r(e["amt"], 1), "price": e["price"],
            "interest": e["interest"],
            "net_cum": _rd(m["net_cum"], 3), "net_iv": _rd(m["net_iv"], 3),
            "ret_cum": _rd(m["ret_cum"], 6), "ret_iv": _rd(m["ret_iv"], 6),
        }
        for e, m in zip(etfs, metrics)
    ]

    total = _blank_bucket("전체", [])
    for e, m in zip(etfs, metrics):
        _accumulate(total, e, m)
    out["totals"] = _finalize(total)

    # 적재는 판독 뒤 조용히 한 번. 실패해도 화면은 그대로 나간다.
    try:
        out["history_days"] = ingest(snap)
    except Exception:
        out["history_days"] = 0
    return out


# ── 일별 누적 (read-through 적재) ────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS snapshot (
  asof     TEXT NOT NULL,
  code     TEXT NOT NULL,
  name     TEXT,
  country  TEXT, gubun TEXT, big TEXT, mid TEXT, small TEXT,
  amt REAL, net REAL, chg REAL, price REAL, mcap REAL,
  mmt_1w REAL, mmt_1m REAL, mmt_3m REAL, mmt_6m REAL,
  ff_1w REAL, ff_1m REAL, ff_3m REAL, ff_6m REAL,
  PRIMARY KEY (asof, code)
);
CREATE INDEX IF NOT EXISTS ix_snapshot_asof ON snapshot(asof);
"""

_INSERT = (
    "INSERT OR REPLACE INTO snapshot (asof,code,name,country,gubun,big,mid,small,"
    "amt,net,chg,price,mcap,mmt_1w,mmt_1m,mmt_3m,mmt_6m,ff_1w,ff_1m,ff_3m,ff_6m) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.executescript(_DDL)
    return con


def _rows_of(snap: dict) -> list[tuple]:
    asof = snap["asof"]
    return [
        (asof, e["code"], e["name"], e["country"], e["gubun"], e["big"], e["mid"],
         e["small"], e["amt"], e["net"], e["chg"], e["price"], e["mcap"],
         e["mmt_1w"], e["mmt_1m"], e["mmt_3m"], e["mmt_6m"],
         e["ff_1w"], e["ff_1m"], e["ff_3m"], e["ff_6m"])
        for e in snap["etfs"]
    ]


def ingest(snap: dict | None = None) -> int:
    """스냅샷을 적재하고 보유 일수를 돌려준다. 같은 기준일은 다시 넣지 않는다.

    워크북은 매일 **덮어쓰기**라 이 적재가 유일한 과거 보관이다. 스케줄러를 두지 않고
    판독 때마다 확인하는 read-through 로 만든 이유: 화면이 열려 있는 한 스스로 낫는다
    (기동 순서·잡 실패에 기대지 않는다).
    """
    if snap is None:
        snap = _read_snapshot()
    asof = snap.get("asof")
    if not asof:
        return 0
    con = _connect()
    try:
        if con.execute("SELECT 1 FROM snapshot WHERE asof=? LIMIT 1", (asof,)).fetchone() is None:
            con.executemany(_INSERT, _rows_of(snap))
            con.commit()
        (days,) = con.execute("SELECT COUNT(DISTINCT asof) FROM snapshot").fetchone()
        return int(days or 0)
    finally:
        con.close()


def build_history(axis: str = DEFAULT_AXIS, days: int = 180) -> dict:
    """일별 시계열 — 분류별 당일 개인순매수와 그 누적, 시총가중 등락률.

    ★워크북에 과거가 없으므로 이 계열은 적재를 시작한 날부터 자란다. 며칠 안 되는 구간을
      선처럼 이어 그리면 없는 추세를 만들어 보이므로 화면이 점 개수를 밝힌다.
    """
    axis_key = axis if axis in _AXIS_BY_KEY else DEFAULT_AXIS
    col = _AXIS_BY_KEY[axis_key]["col"]
    out = {
        "generated_at": datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
        "axis": axis_key,
        "dates": [],
        "series": [],
        "note": None,
    }
    try:
        con = _connect()
    except OSError as exc:
        out["note"] = f"이력 저장소를 열지 못했습니다 — {exc}"
        return out
    try:
        rows = con.execute(
            f"SELECT asof, COALESCE(NULLIF({col},''),'미분류') AS g, "
            "SUM(COALESCE(net,0)) AS net, "
            "SUM(COALESCE(chg,0)*COALESCE(mcap,0)) AS rw, "
            "SUM(CASE WHEN chg IS NULL THEN 0 ELSE COALESCE(mcap,0) END) AS rwd "
            "FROM snapshot WHERE asof >= ? GROUP BY asof, g ORDER BY asof",
            ((date.today() - timedelta(days=days)).isoformat(),),
        ).fetchall()
    finally:
        con.close()

    if not rows:
        out["note"] = "아직 쌓인 스냅샷이 없습니다."
        return out

    dates = sorted({r[0] for r in rows})
    idx = {d: i for i, d in enumerate(dates)}
    per: dict[str, dict] = {}
    for asof, g, net, rw, rwd in rows:
        s = per.setdefault(g, {"net": [None] * len(dates), "ret": [None] * len(dates)})
        i = idx[asof]
        s["net"][i] = net
        s["ret"][i] = (rw / rwd) if rwd else None

    series = []
    for g, s in per.items():
        run, cum = 0.0, []
        for v in s["net"]:
            run += v or 0.0
            cum.append(round(run, 3))
        series.append({
            "key": g, "label": g,
            "net": [None if v is None else round(v, 3) for v in s["net"]],
            "cum": cum,
            "ret": [None if v is None else round(v, 6) for v in s["ret"]],
            "total": round(run, 3),
        })
    series.sort(key=lambda x: -x["total"])
    out["dates"] = dates
    out["series"] = series
    return out
