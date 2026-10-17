"""블룸버그 대회 WLS 지수 구성종목(약 1만 개)의 일봉 OHLCV 를 야후에서 받아 지역별 Parquet 으로 모은다.

    .venv/bin/python scripts/ohlcv_wls.py                 # 전 종목(이어 받기)
    .venv/bin/python scripts/ohlcv_wls.py --max 50        # 시험 삼아 50개만
    .venv/bin/python scripts/ohlcv_wls.py --rebuild-only  # 받지 않고 지역 Parquet 만 다시

★2026-10-17 사용자 요청: `Ongoings/블룸버그 대회/wls 종목.xlsx` 의 종목도 OHLCV 를. 파일은 엑셀의 **지역 시트 6개**
  (미국·중화권·한국·일본·유럽·기타 아시아·태평양·미주·중동·아프리카) 로 나눈다. 받기·이어 받기·저장은
  scripts/ohlcv_collect.py 를 그대로 쓴다 — 종목별 원본도 같은 storage/ohlcv/_tickers/ 에 둔다.

블룸버그 티커 → 야후 심볼:
  1) 대회 대시보드(~/Developer/gtc_research)의 market.db 가 이미 매핑해 둔 것(core·satellite 5,765개)
  2) 없으면 거래소 코드 → 야후 접미사 규칙(EXCHANGE_SUFFIX). 중국 본토는 종목코드 앞자리로 상하이/선전/베이징.
  3) 그래도 없으면 야후 검색(코드로 검색 → 그 거래소 접미사인 결과). ⚠️블룸버그 약칭과 야후 심볼이 다른 시장이 있다
     (인도 HDFCB → HDFCBANK.NS, 싱가포르 DBS → D05.SI, 말레이시아 MAY → 1155.KL — 2026-10-17 실측).
  ⚠️어떤 경로든 **가격으로 검증**한다 — 엑셀의 가격(현지 통화)과 야후 종가(엑셀 날짜 이전 마지막 날)의 비가
    0.67~1.5 면 ok, 100배 차이(펜스·아고롯 같은 보조 단위)면 ok_unit, 아니면 다음 후보. 끝까지 안 맞으면
    price_mismatch 로 남기되 데이터는 둔다(분할 직후 등 엑셀 쪽이 다를 수도 있다) — map_status 로 거른다.

저장(storage/ohlcv/):
  parquet_wls/region={지역}/data.parquet  bbg, ticker, yahoo, name_ko, currency, map_status, date, open…volume
  _wls_map.csv                            블룸버그 티커별 매핑·검증 결과
  ohlcv.duckdb                            뷰 wls_ohlcv(+ region) · wls_map 추가
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import random
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ohlcv_collect as oc  # noqa: E402

EXCEL = Path.home() / "Library/CloudStorage/OneDrive-개인/Ongoings/블룸버그 대회/wls 종목.xlsx"
GTC_DB = Path.home() / ".local/share/gtc_research/market.db"
MAP_PATH = oc.OUT / "_wls_map.csv"
PARQUET_WLS = oc.OUT / "parquet_wls"
REGIONS = ["미국", "중화권", "한국·일본", "유럽", "기타 아시아·태평양", "미주·중동·아프리카"]
US_EXCH = {"UN", "UW", "UQ", "UR", "UA", "UF", "UP", "UV"}

# 블룸버그 거래소 코드 → 야후 접미사(앞의 것부터 시도). 대회 대시보드가 매핑해 둔 시장(JT·TT·KP…)은
# 그 매핑을 먼저 쓰지만, 같은 규칙을 여기에도 둔다(매핑이 없는 종목용).
EXCHANGE_SUFFIX: dict[str, list[str]] = {
    "JT": [".T"], "TT": [".TW", ".TWO"], "KP": [".KS"], "KQ": [".KQ"],
    "LN": [".L"], "SS": [".ST"], "SF": [".ST"], "BS": [".SA"], "GY": [".DE"], "FP": [".PA"],
    "SE": [".SW"], "IM": [".MI"], "NO": [".OL"], "PW": [".WA"], "SQ": [".MC"], "NA": [".AS"],
    "DC": [".CO"], "FH": [".HE"], "GA": [".AT"], "BB": [".BR"], "AV": [".VI"], "PL": [".LS"],
    "ID": [".IR"],
    "IS": [".NS", ".BO"], "IB": [".BO", ".NS"], "CT": [".TO", ".V"], "AT": [".AX"],
    "AB": [".SR"], "MK": [".KL"], "TI": [".IS"], "TB": [".BK"], "IT": [".TA"], "IJ": [".JK"],
    "SJ": [".JO"], "SP": [".SI"], "KK": [".KW"], "PM": [".PS"], "MF": [".MX"],
    "DH": [".AD"], "DB": [".AE"], "CC": [".SN"], "EC": [".CA"], "QD": [".QA"], "NZ": [".NZ"],
    "HB": [".BD"], "CK": [".PR"], "CX": [".CL"], "PE": [".LM"],
}
PRICE_OK = (0.67, 1.5)
PRICE_UNIT = (67.0, 150.0)  # 100배(보조 단위) 차이
MAP_COLS = ["bbg", "code", "exch", "region", "name_ko", "wls_weight", "wls_price", "key", "yahoo",
            "method", "price_ratio", "status", "checked_at"]
GOOD = ("ok", "ok_unit")


# ── 대상: 엑셀 지역 시트 ─────────────────────────────────────────────────────
def load_excel(path: Path) -> list[dict]:
    import pandas as pd

    rows: list[dict] = []
    for region in REGIONS:
        raw = pd.read_excel(path, sheet_name=region, header=None)
        head = next(i for i, v in enumerate(raw.iloc[:, 0]) if str(v).strip() == "티커")
        body = raw.iloc[head + 1:, :6]
        body.columns = ["ticker", "name", "weight", "shares", "price", "country"]
        for r in body.itertuples(index=False):
            if not isinstance(r.ticker, str) or " " not in r.ticker.strip():
                continue
            bbg = r.ticker.replace(" Equity", "").strip()
            code, exch = bbg.rsplit(" ", 1)
            rows.append({"bbg": bbg, "code": code, "exch": exch, "region": region,
                         "name_ko": str(r.name), "wls_weight": r.weight, "wls_price": r.price})
    return rows


def load_gtc_map() -> dict[str, str]:
    if not GTC_DB.exists():
        return {}
    con = sqlite3.connect(f"file:{GTC_DB}?mode=ro", uri=True)
    try:
        return {bbg: y for bbg, y in con.execute(
            "SELECT bbg, yahoo FROM wls_universe WHERE yahoo IS NOT NULL AND yahoo <> ''")}
    finally:
        con.close()


def candidates(row: dict, gtc: dict[str, str]) -> list[tuple[str, str]]:
    """(야후 심볼, 경로) 후보."""
    out: list[tuple[str, str]] = []
    if row["bbg"] in gtc:
        out.append((gtc[row["bbg"]], "gtc"))
    code, exch = row["code"].replace("/", "-"), row["exch"]
    if exch in US_EXCH:
        out.append((code, "rule"))
    elif exch in ("C", "C1", "C2"):
        # 엑셀은 C1(상하이)·C2(선전)로 나뉜다. 그 밖(C)은 종목코드 앞자리로 정한다.
        c = code.zfill(6)
        suffix = {"C1": ".SS", "C2": ".SZ"}.get(exch) or (".SS" if c[0] in "69" else ".BJ" if c[0] in "48" else ".SZ")
        out.append((c + suffix, "rule"))
    elif exch == "HK":
        out.append((code.lstrip("0").zfill(4) + ".HK", "rule"))
    else:
        out += [(code + s, "rule") for s in EXCHANGE_SUFFIX.get(exch, [])]
    seen: set[str] = set()
    return [c for c in out if not (c[0] in seen or seen.add(c[0]))]


def allowed(sym: str, exch: str) -> bool:
    if exch in US_EXCH:
        return "." not in sym
    if exch in ("C", "C1", "C2"):
        return sym.endswith((".SS", ".SZ", ".BJ"))
    if exch == "HK":
        return sym.endswith(".HK")
    return sym.endswith(tuple(EXCHANGE_SUFFIX.get(exch, ["\0"])))


def key_of(yahoo: str) -> str:
    # 미국 종목은 L1 쪽과 같은 키(BRK.B)로 — 같은 종목을 두 번 받지 않는다. 해외는 야후 심볼 그대로(2330.TW).
    return yahoo.replace("-", ".") if "." not in yahoo else yahoo


def search(client: httpx.Client, code: str, exch: str) -> list[str]:
    for wait in (0, *oc.BACKOFF):
        if wait:
            oc.log(f"  검색 {code}: 막힘 — {wait}초 쉬고 다시")
            time.sleep(wait)
        r = client.get("https://query1.finance.yahoo.com/v1/finance/search",
                       params={"q": code, "quotesCount": 10, "newsCount": 0})
        if r.status_code in (429, 999) or r.status_code >= 500:
            continue
        if r.status_code != 200:
            return []
        quotes = r.json().get("quotes") or []
        return [q["symbol"] for q in quotes if q.get("symbol") and allowed(q["symbol"], exch)][:3]
    raise oc.RateLimited("search")


def price_check(rows: list[dict], wls_price, as_of: date) -> tuple[str, float | None]:
    try:
        target = float(wls_price)
    except (TypeError, ValueError):
        return "no_price", None
    close = None
    for r in rows:
        if r["date"] > as_of.isoformat():
            break
        close = r["close"]
    if close in (None, "") or not target:
        return "price_mismatch", None
    ratio = float(close) / target
    if PRICE_OK[0] <= ratio <= PRICE_OK[1]:
        return "ok", ratio
    if PRICE_UNIT[0] <= ratio <= PRICE_UNIT[1] or PRICE_UNIT[0] <= 1 / ratio <= PRICE_UNIT[1]:
        return "ok_unit", ratio
    return "price_mismatch", ratio


# ── 저장 ─────────────────────────────────────────────────────────────────────
def read_map() -> dict[str, dict]:
    if not MAP_PATH.exists():
        return {}
    with MAP_PATH.open(encoding="utf-8") as f:
        return {r["bbg"]: r for r in csv.DictReader(f)}


def write_map(m: dict[str, dict]) -> None:
    tmp = MAP_PATH.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MAP_COLS)
        w.writeheader()
        for bbg in sorted(m):
            w.writerow({c: m[bbg].get(c, "") for c in MAP_COLS})
    tmp.replace(MAP_PATH)


def rebuild_wls(wls_map: dict[str, dict], manifest: dict[str, dict]) -> dict[str, int]:
    """지역별 Parquet — 매핑된(검증 결과 무관, map_status 로 표시) 종목만."""
    import duckdb

    picked = [r for r in wls_map.values()
              if r.get("key") and (oc.TICKERS_DIR / f"{r['key']}.csv").exists()]
    PARQUET_WLS.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute("CREATE TABLE m (bbg VARCHAR, ticker VARCHAR, yahoo VARCHAR, name_ko VARCHAR, "
                "region VARCHAR, currency VARCHAR, map_status VARCHAR)")
    con.executemany("INSERT INTO m VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (r["bbg"], r["key"], r["yahoo"], r["name_ko"], r["region"],
         manifest.get(r["key"], {}).get("currency", ""), r["status"]) for r in picked])
    counts: dict[str, int] = {}
    for region in REGIONS:
        keys = sorted({r["key"] for r in picked if r["region"] == region})
        dest = PARQUET_WLS / f"region={region}"
        if not keys:
            continue
        dest.mkdir(exist_ok=True)
        files = "[" + ", ".join(oc._sql_str(str(oc.TICKERS_DIR / f"{k}.csv")) for k in keys) + "]"
        tmp = dest / "data.parquet.tmp"
        con.execute(f"""
            COPY (
              SELECT m.bbg, p.ticker, m.yahoo, m.name_ko, m.currency, m.map_status,
                     p.date, p.open, p.high, p.low, p.close, p.adj_close, p.volume
              FROM (SELECT regexp_extract(filename, '([^/]+)\\.csv$', 1) AS ticker,
                           date, open, high, low, close, adj_close,
                           CAST(round(volume) AS BIGINT) AS volume
                    FROM read_csv({files}, header = true, filename = true, columns = {{
                        'date': 'DATE', 'open': 'DOUBLE', 'high': 'DOUBLE', 'low': 'DOUBLE',
                        'close': 'DOUBLE', 'adj_close': 'DOUBLE', 'volume': 'DOUBLE'}})) p
              JOIN m ON m.ticker = p.ticker AND m.region = {oc._sql_str(region)}
              ORDER BY p.ticker, p.date
            ) TO {oc._sql_str(str(tmp))} (FORMAT parquet, COMPRESSION zstd)""")
        tmp.replace(dest / "data.parquet")
        counts[region] = con.execute(
            f"SELECT count(*) FROM read_parquet({oc._sql_str(str(dest / 'data.parquet'))})").fetchone()[0]
    con.close()
    oc._refresh_duckdb_views()
    return counts


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", type=Path, default=EXCEL)
    ap.add_argument("--price-date", default="2026-10-09",
                    help="엑셀 가격의 기준일 — 이 날 이전 마지막 종가와 비교한다")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--stale-hours", type=float, default=12.0)
    ap.add_argument("--retry-failed", action="store_true", help="못 찾은·가격 불일치 종목도 다시 시도")
    ap.add_argument("--rebuild-only", action="store_true")
    ap.add_argument("--bbg", help="쉼표로 지정한 블룸버그 티커만(예: 'HDFCB IS,700 HK')")
    args = ap.parse_args()

    oc.TICKERS_DIR.mkdir(parents=True, exist_ok=True)
    lock = (oc.OUT / "_collect.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("다른 수집이 이미 돌고 있다 — 건너뜀")
        return 0

    manifest = oc.read_manifest()
    wls_map = read_map()
    if args.rebuild_only:
        counts = rebuild_wls(wls_map, manifest)
        oc.log("WLS 다시 만듦: " + ", ".join(f"{k} {v:,}행" for k, v in counts.items()))
        return 0

    rows = load_excel(args.excel)
    gtc = load_gtc_map()
    l1_map = oc.l1_of()
    as_of = date.fromisoformat(args.price_date)
    now = datetime.now(timezone.utc)

    todo = []
    for r in rows:
        prev = wls_map.get(r["bbg"])
        if prev:
            fresh = manifest.get(prev.get("key", ""), {}).get("fetched_at")
            age = now - datetime.fromisoformat(prev["checked_at"]) if prev.get("checked_at") else None
            if prev["status"] in GOOD and fresh and now - datetime.fromisoformat(fresh) < timedelta(hours=args.stale_hours):
                continue
            if prev["status"] not in GOOD and not args.retry_failed and age and age < timedelta(days=7):
                continue
        todo.append(r)
    if args.bbg:
        want = {b.strip() for b in args.bbg.split(",")}
        todo = [r for r in rows if r["bbg"] in want]
    if args.max:
        todo = todo[: args.max]
    oc.log(f"WLS 시작: 엑셀 {len(rows)}종목(대회 매핑 {len(gtc)}), 이번에 받을 것 {len(todo)}종목")

    events: dict[str, list[dict]] = {}
    fails = done = 0
    first = True
    with httpx.Client(timeout=30.0, headers={"User-Agent": oc.UA}) as client:
        for i, r in enumerate(todo):
            tried: list[str] = []
            best = None  # (status, ratio, key, yahoo, method, fetch_status, rows, evs)
            queue = candidates(r, gtc)
            searched = False
            try:
                while True:
                    if not queue:
                        if searched or (best and best[0] in GOOD):
                            break
                        searched = True
                        if not first:
                            time.sleep(random.uniform(1.5, 2.5))
                        first = False
                        queue = [(s, "search") for s in search(client, r["code"], r["exch"]) if s not in tried]
                        continue
                    yahoo, method = queue.pop(0)
                    tried.append(yahoo)
                    key = key_of(yahoo)
                    oc.YAHOO_OVERRIDE[key] = yahoo
                    m = manifest.get(key, {})
                    if (m.get("fetched_at") and m.get("status") not in ("error", "not_found")
                            and now - datetime.fromisoformat(m["fetched_at"]) < timedelta(hours=args.stale_hours)):
                        fetch_status, data, evs = "cached", oc.read_ticker(key), []  # L1 쪽에서 이미 받은 미국 종목
                    else:
                        if not first:
                            time.sleep(random.uniform(1.5, 2.5))
                        first = False
                        fetch_status, data, evs = oc.collect_one(client, key)
                    if not data:
                        continue
                    status, ratio = price_check(data, r["wls_price"], as_of)
                    if best is None or (status in GOOD and best[0] not in GOOD):
                        best = (status, ratio, key, yahoo, method, fetch_status, data, evs)
                    if status in GOOD:
                        break
                fails = 0
            except Exception as exc:  # noqa: BLE001
                fails += 1
                oc.log(f"  {r['bbg']}: 실패 {exc!r}")
                if fails >= oc.MAX_CONSECUTIVE_FAILS:
                    oc.log(f"연속 {fails}번 실패 — 이번 실행을 멈춘다(다음 실행이 이어 받는다)")
                    break
                continue

            entry = {**r, "checked_at": datetime.now(timezone.utc).isoformat()}
            if best is None:
                entry.update(key="", yahoo="", method="", price_ratio="", status="not_found")
                oc.log(f"  [{i + 1}/{len(todo)}] {r['bbg']} 못 찾음 (시도: {', '.join(tried) or '없음'})")
            else:
                status, ratio, key, yahoo, method, fetch_status, data, evs = best
                entry.update(key=key, yahoo=yahoo, method=method, status=status,
                             price_ratio=f"{ratio:.4f}" if ratio else "")
                if fetch_status != "cached":
                    oc.write_ticker(key, data)
                    events[key] = evs
                    manifest[key] = {**manifest.get(key, {}), "ticker": key,
                                     "l1": manifest.get(key, {}).get("l1") or l1_map.get(key, ""),
                                     "status": fetch_status, "first_date": data[0]["date"],
                                     "last_date": data[-1]["date"], "rows": len(data),
                                     "fetched_at": datetime.now(timezone.utc).isoformat(),
                                     "source": f"yahoo:{yahoo}",
                                     "currency": oc.LAST_META.get(yahoo, {}).get("currency", "")}
                oc.log(f"  [{i + 1}/{len(todo)}] {r['bbg']} → {yahoo} ({method}) {status} "
                       f"{ratio and round(ratio, 3)} {len(data)}행 {data[0]['date']}~ [{r['region']}]")
            wls_map[r["bbg"]] = entry
            done += 1
            if done % 25 == 0:
                write_map(wls_map)
                oc.write_manifest(manifest)

    write_map(wls_map)
    oc.write_manifest(manifest)
    oc.write_events(events)
    counts = rebuild_wls(wls_map, manifest)
    st: dict[str, int] = {}
    for v in wls_map.values():
        st[v["status"]] = st.get(v["status"], 0) + 1
    oc.log(f"WLS 끝: 이번 {done}종목, 매핑 상태 {st} — " + ", ".join(f"{k} {v:,}행" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
