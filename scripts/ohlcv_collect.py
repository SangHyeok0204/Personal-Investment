"""종목별 일봉 OHLCV 를 야후에서 받아 L1(밸류체인 분류)별 CSV 로 모은다.

    .venv/bin/python scripts/ohlcv_collect.py                     # 보유 + 관심종목
    .venv/bin/python scripts/ohlcv_collect.py --universe taxonomy # 밸류체인 분류 전 종목(≈2,400)
    .venv/bin/python scripts/ohlcv_collect.py --tickers MSFT,NVDA # 지정 종목만

★2026-10-15 사용자 요청: 대시보드가 가진 종목 전부의 OHLCV 를 최대한 과거부터, L1 별 CSV 로 관리.
  원천 조사(2026-10): 스투크(Stooq)는 2026년부터 CSV 에 캡차 API 키가 필요하고 일일 한도가 비공개,
  티잉고(Tiingo) 무료는 월 500종목 — 수천 종목에 못 쓴다. 키 없이 상장 이후 전 구간을 주는 건 야후뿐이라
  야후 차트 API 를 **천천히** 부른다.

⚠️`range=max` 는 쓰지 않는다 — 긴 구간이면 야후가 일봉을 **월봉으로 바꿔** 준다(실측 MSFT 164행).
  `period1=0&period2=지금` 으로 부르면 일봉 그대로 온다(MSFT 1986-03-13~ 10,227행).

저장(storage/ohlcv/, git 에 안 올라간다):
  _tickers/{TICKER}.csv  종목별 원본 — 이게 정본이다. 다시 돌리면 여기서 이어 받는다.
  parquet/l1={L1}/data.parquet  L1 별 묶음(ticker,date,open,high,low,close,adj_close,volume; zstd) — 매 실행 끝에 다시 만든다.
  ohlcv.duckdb           조회용 DuckDB — 뷰 ohlcv(+ l1 열) · manifest · events. 데이터 자체는 Parquet 에 있다.
  _events.csv            분할·배당(ticker,date,type,value)
  _manifest.csv          종목별 L1·구간·행 수·상태·받은 시각
  _collect.log           실행 기록

이어 받기: 이미 받은 종목은 최근 10일만 다시 받아 붙인다. ⚠️수정종가(adj_close)는 배당·분할이 생기면
  **과거 전체가 바뀐다** — 겹치는 날의 수정종가가 저장본과 다르면 그 종목은 전 구간을 다시 받는다.

요청 예절: 한 번에 하나씩, 요청 사이 1.5~2.5초. 429·5xx 는 30→60→120→240초 쉬고 다시,
  연속 5번 실패하면 이번 실행을 멈춘다(다음 실행이 이어 받는다). 동시 실행은 잠금 파일로 막는다.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))

OUT = REPO / "storage" / "ohlcv"
TICKERS_DIR = OUT / "_tickers"
UNCLASSIFIED = "미분류"
BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
# ⚠️완전한 크롬 UA("… Chrome/129 Safari/537.36")는 첫 요청부터 429 를 받는다(2026-10-15 실측) — 앱의
#   prices/yahoo.py 와 같은 짧은 UA 를 쓴다.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
FIELDS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
REFETCH_DAYS = 10
BACKOFF = [30, 60, 120, 240]
MAX_CONSECUTIVE_FAILS = 5


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (OUT / "_collect.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── 대상 종목 ────────────────────────────────────────────────────────────────
def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL 없음")


def held_and_watched() -> list[str]:
    from sqlalchemy import create_engine, text

    engine = create_engine(_database_url())
    with engine.connect() as conn:
        held = conn.execute(text(
            "SELECT a.ticker FROM current_positions p JOIN assets a ON a.id = p.asset_id"
        )).scalars().all()
        watched = conn.execute(text("SELECT ticker FROM watchlist_items")).scalars().all()
    return sorted({t.strip().upper() for t in [*held, *watched] if t and t.strip()})


def l1_of() -> dict[str, str]:
    from app.core.valuechain import ticker_l1_map

    return {ticker.upper(): l1 for ticker, (l1, _color) in ticker_l1_map().items()}


# 티커가 바뀐 종목 — 분류(밸류체인)는 옛 티커로 남아 있다. 파일·manifest 는 분류 티커로 두고 야후에서만 새 티커로 받는다.
# ★2026-10-15 실측 404 → 야후 검색으로 새 티커 확인: BK → BNY(BNY Mellon), ASGN → EFOR(Everforth 로 사명 변경).
TICKER_ALIASES: dict[str, str] = {
    "BK": "BNY",
    "ASGN": "EFOR",
    # 야후 첫 거래일이 원래 회사 상장일과 같은 것으로 확인(DMC 1997-10-24, PLGO 2023-06-29).
    "FDP": "DMC",     # Fresh Del Monte Produce → Del Monte Corporation
    "FIHL": "PLGO",   # Fidelis Insurance → Pelagos Insurance Capital
    "PSTG": "P",      # Pure Storage → Everpure(야후 첫 거래 2015-10 = Pure Storage 상장 시기)
}


# 키(파일 이름) → 야후 심볼을 직접 정한 것. WLS 해외 종목(2330.TW 등)은 키가 곧 야후 심볼이라 점을 바꾸면 안 된다
# — scripts/ohlcv_wls.py 가 채운다.
YAHOO_OVERRIDE: dict[str, str] = {}
# 마지막으로 받은 응답의 메타(통화 등) — 야후 심볼별.
LAST_META: dict[str, dict] = {}


def yahoo_symbol(ticker: str) -> str:
    if ticker in YAHOO_OVERRIDE:
        return YAHOO_OVERRIDE[ticker]
    # 야후는 클래스 주식을 BRK-B 처럼 하이픈으로 쓴다.
    return TICKER_ALIASES.get(ticker, ticker).replace(".", "-")


# ── 받기 ─────────────────────────────────────────────────────────────────────
class RateLimited(Exception):
    pass


def fetch(client: httpx.Client, ticker: str, start: int) -> tuple[list[dict], list[dict]] | None:
    """(일봉, 이벤트). 종목이 없으면 None. 막히면 RateLimited."""
    r = client.get(
        f"{BASE}/{yahoo_symbol(ticker)}",
        params={
            "period1": start,
            "period2": int(time.time()),
            "interval": "1d",
            "events": "div|split",
            "includeAdjustedClose": "true",
        },
    )
    if r.status_code in (429, 999) or r.status_code >= 500:
        raise RateLimited(f"{r.status_code}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    result = (r.json().get("chart") or {}).get("result") or []
    if not result:
        return None
    node = result[0]
    LAST_META[yahoo_symbol(ticker)] = node.get("meta") or {}
    tz = ZoneInfo(node.get("meta", {}).get("exchangeTimezoneName") or "America/New_York")
    stamps = node.get("timestamp") or []
    q = (node.get("indicators") or {}).get("quote") or [{}]
    q = q[0]
    adj = ((node.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or [None] * len(stamps)

    def day(ts: int) -> str:
        # ⚠️UTC 로 자르면 장 시작 시각이 전날로 넘어가는 시장이 있다 — 거래소 시간대의 날짜를 쓴다.
        return datetime.fromtimestamp(ts, tz).date().isoformat()

    bars: list[dict] = []
    for i, ts in enumerate(stamps):
        close = q.get("close", [None])[i] if i < len(q.get("close", [])) else None
        if close is None:
            continue  # 휴장·누락 — 0 으로 채우지 않는다.
        bars.append({
            "date": day(ts),
            "open": q["open"][i],
            "high": q["high"][i],
            "low": q["low"][i],
            "close": close,
            "adj_close": adj[i] if i < len(adj) else None,
            "volume": q["volume"][i],
        })
    events: list[dict] = []
    ev = node.get("events") or {}
    for d in (ev.get("dividends") or {}).values():
        events.append({"date": day(d["date"]), "type": "dividend", "value": d.get("amount")})
    for s in (ev.get("splits") or {}).values():
        events.append({"date": day(s["date"]), "type": "split",
                       "value": f"{s.get('numerator')}:{s.get('denominator')}"})
    return bars, events


def fetch_polite(client: httpx.Client, ticker: str, start: int):
    for attempt in range(len(BACKOFF) + 1):
        try:
            return fetch(client, ticker, start)
        except (RateLimited, httpx.TransportError) as exc:
            if attempt == len(BACKOFF):
                raise
            wait = BACKOFF[attempt]
            log(f"  {ticker}: {exc!r} — {wait}초 쉬고 다시")
            time.sleep(wait)


# ── 저장 ─────────────────────────────────────────────────────────────────────
def read_ticker(ticker: str) -> list[dict]:
    path = TICKERS_DIR / f"{ticker}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_ticker(ticker: str, rows: list[dict]) -> None:
    path = TICKERS_DIR / f"{ticker}.csv"
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def _same(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(b)))
    except (TypeError, ValueError):
        return a in (None, "") and b in (None, "")


def collect_one(client: httpx.Client, ticker: str) -> tuple[str, list[dict] | None, list[dict]]:
    """(상태, 저장할 행, 이벤트). 상태: full | incremental | refetched | not_found."""
    old = read_ticker(ticker)
    if old:
        since = date.fromisoformat(old[-1]["date"]) - timedelta(days=REFETCH_DAYS)
        start = int(datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp())
        got = fetch_polite(client, ticker, start)
        if got is None:
            return "not_found", None, []
        bars, events = got
        stored = {r["date"]: r for r in old}
        # ⚠️저장본의 마지막 날은 받던 당시 진행 중이던 봉일 수 있다(값이 계속 바뀐다) — 비교에서 뺀다.
        overlap = [b for b in bars if b["date"] in stored and b["date"] < old[-1]["date"]]
        if overlap and all(_same(stored[b["date"]]["adj_close"], b["adj_close"]) for b in overlap):
            merged = {r["date"]: r for r in old}
            merged.update({b["date"]: b for b in bars})
            return "incremental", [merged[d] for d in sorted(merged)], events
        # 수정종가가 달라졌다(새 배당·분할) — 전 구간을 다시 받는다.
        time.sleep(random.uniform(1.5, 2.5))
        got = fetch_polite(client, ticker, 0)
        if got is None:
            return "not_found", None, []
        return "refetched", got[0], got[1]
    got = fetch_polite(client, ticker, 0)
    if got is None:
        return "not_found", None, []
    return "full", got[0], got[1]


def read_manifest() -> dict[str, dict]:
    path = OUT / "_manifest.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {r["ticker"]: r for r in csv.DictReader(f)}


def write_manifest(rows: dict[str, dict]) -> None:
    cols = ["ticker", "l1", "first_date", "last_date", "rows", "status", "fetched_at", "source", "currency"]
    with (OUT / "_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in sorted(rows):
            w.writerow({c: rows[t].get(c, "") for c in cols})


def write_events(all_events: dict[str, list[dict]]) -> None:
    path = OUT / "_events.csv"
    existing: dict[str, list[dict]] = {}
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing.setdefault(r["ticker"], []).append(r)
    for t, evs in all_events.items():
        if evs:  # 이번에 받은 이벤트가 있으면 그 종목은 받은 것으로 바꾼다(구간이 짧은 이어 받기는 합친다).
            keep = {(e["date"], e["type"]): e for e in existing.get(t, [])}
            keep.update({(e["date"], e["type"]): {"ticker": t, **e} for e in evs})
            existing[t] = list(keep.values())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "date", "type", "value"])
        w.writeheader()
        for t in sorted(existing):
            for e in sorted(existing[t], key=lambda e: (e["date"], e["type"])):
                w.writerow({k: e.get(k, "") for k in ["ticker", "date", "type", "value"]})


PARQUET_DIR = OUT / "parquet"
DUCKDB_PATH = OUT / "ohlcv.duckdb"


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def rebuild_l1_files(manifest: dict[str, dict], also_csv: bool = False) -> dict[str, int]:
    """L1 별 Parquet 을 종목별 원본에서 다시 만든다 — 분류가 바뀌어도 종목이 맞는 파일로 간다.

    ★2026-10-16 사용자 결정: 분석(pandas · DuckDB SQL)용으로 L1 별 CSV 대신 **L1 별 Parquet**(zstd).
      parquet/l1={L1}/data.parquet — 하이브 분할이라 DuckDB 가 `l1` 을 열로 읽는다.
      종목·날짜 순으로 정렬해 써서 종목 하나만 읽을 때 행 그룹을 건너뛴다.
    `also_csv` 면 예전처럼 {L1}.csv 도 같이 쓴다(엑셀로 볼 때). 아니면 남아 있던 L1 CSV 는 지운다.
    """
    import duckdb

    by_l1: dict[str, list[str]] = {}
    for t, m in manifest.items():
        # l1 이 빈 종목은 WLS 로만 들어온 해외 종목 — L1 파일이 아니라 WLS 지역 파일(ohlcv_wls.py)에 간다.
        if m.get("l1") and (TICKERS_DIR / f"{t}.csv").exists():
            by_l1.setdefault(m["l1"], []).append(t)

    for old in OUT.glob("*.csv"):
        if not old.name.startswith("_") and (not also_csv or old.stem not in by_l1):
            old.unlink()
    PARQUET_DIR.mkdir(exist_ok=True)
    for part in PARQUET_DIR.glob("l1=*"):
        if part.name[len("l1="):] not in by_l1:  # 종목이 하나도 안 남은 L1
            for f in part.iterdir():
                f.unlink()
            part.rmdir()

    con = duckdb.connect()
    counts: dict[str, int] = {}
    for l1, tickers in by_l1.items():
        files = "[" + ", ".join(_sql_str(str(TICKERS_DIR / f"{t}.csv")) for t in sorted(tickers)) + "]"
        # ⚠️티커는 파일 이름에서 뽑는다(BRK.B 처럼 점이 든 티커도 있다 — 마지막 .csv 만 뗀다).
        select = f"""
            SELECT regexp_extract(filename, '([^/]+)\\.csv$', 1) AS ticker,
                   date, open, high, low, close, adj_close,
                   CAST(round(volume) AS BIGINT) AS volume
            FROM read_csv({files}, header = true, filename = true, columns = {{
                'date': 'DATE', 'open': 'DOUBLE', 'high': 'DOUBLE', 'low': 'DOUBLE',
                'close': 'DOUBLE', 'adj_close': 'DOUBLE', 'volume': 'DOUBLE'}})
            ORDER BY ticker, date"""
        dest = PARQUET_DIR / f"l1={l1}"
        dest.mkdir(exist_ok=True)
        tmp = dest / "data.parquet.tmp"
        con.execute(f"COPY ({select}) TO {_sql_str(str(tmp))} (FORMAT parquet, COMPRESSION zstd)")
        tmp.replace(dest / "data.parquet")
        if also_csv:
            con.execute(f"COPY (SELECT * FROM read_parquet({_sql_str(str(dest / 'data.parquet'))})) "
                        f"TO {_sql_str(str(OUT / f'{l1}.csv'))} (FORMAT csv, HEADER)")
        counts[l1] = con.execute(
            f"SELECT count(*) FROM read_parquet({_sql_str(str(dest / 'data.parquet'))})"
        ).fetchone()[0]
    con.close()
    _refresh_duckdb_views()
    return counts


def _refresh_duckdb_views() -> None:
    """ohlcv.duckdb — 데이터는 Parquet 에 두고 뷰만 둔다(파일이 작고, Parquet 을 다시 쓰면 바로 반영된다).

        import duckdb; con = duckdb.connect("storage/ohlcv/ohlcv.duckdb", read_only=True)
        con.sql("SELECT l1, count(DISTINCT ticker) FROM ohlcv GROUP BY l1").df()
    ⚠️DuckDB 파일은 쓰기 연결이 하나뿐이다 — 노트북 등에서 쓰기 모드로 열어 두면 여기서 못 고친다
      (뷰는 이미 있으니 경고만 남기고 넘어간다). 조회는 read_only=True 로 열 것.
    """
    import duckdb

    views = {
        "ohlcv": f"SELECT * FROM read_parquet({_sql_str(str(PARQUET_DIR) + '/l1=*/data.parquet')}, hive_partitioning = true)",
        "manifest": f"SELECT * FROM read_csv_auto({_sql_str(str(OUT / '_manifest.csv'))})",
        "events": f"SELECT * FROM read_csv_auto({_sql_str(str(OUT / '_events.csv'))})",
    }
    # WLS(블룸버그 대회 지수) — scripts/ohlcv_wls.py 가 만든 지역별 Parquet 이 있을 때만.
    if any((OUT / "parquet_wls").glob("region=*/data.parquet")):
        views["wls_ohlcv"] = (f"SELECT * FROM read_parquet({_sql_str(str(OUT / 'parquet_wls') + '/region=*/data.parquet')},"
                              " hive_partitioning = true)")
        views["wls_map"] = f"SELECT * FROM read_csv_auto({_sql_str(str(OUT / '_wls_map.csv'))}, all_varchar = true)"
    try:
        con = duckdb.connect(str(DUCKDB_PATH))
    except duckdb.IOException as exc:
        log(f"  ohlcv.duckdb 를 못 열었다(다른 곳에서 쓰기 모드로 열려 있다?) — 뷰 갱신 건너뜀: {exc}")
        return
    try:
        for name, sql in views.items():
            con.execute(f"CREATE OR REPLACE VIEW {name} AS {sql}")
    finally:
        con.close()


# ── 실행 ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["core", "taxonomy"], default="core",
                    help="core=보유+관심(기본), taxonomy=밸류체인 분류 전 종목(+보유+관심)")
    ap.add_argument("--tickers", help="쉼표로 지정한 종목만")
    ap.add_argument("--max", type=int, default=0, help="이번 실행에서 받을 최대 종목 수(0=제한 없음)")
    ap.add_argument("--stale-hours", type=float, default=12.0,
                    help="이 시간 안에 받은 종목은 건너뛴다")
    ap.add_argument("--csv", action="store_true", help="L1 별 CSV 도 같이 쓴다(엑셀용)")
    ap.add_argument("--rebuild-only", action="store_true", help="받지 않고 L1 Parquet·DuckDB 만 다시 만든다")
    args = ap.parse_args()

    TICKERS_DIR.mkdir(parents=True, exist_ok=True)
    lock = (OUT / "_collect.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("다른 수집이 이미 돌고 있다 — 건너뜀")
        return 0

    l1_map = l1_of()
    if args.tickers:
        universe = sorted({t.strip().upper() for t in args.tickers.split(",") if t.strip()})
    elif args.universe == "taxonomy":
        universe = sorted(set(l1_map) | set(held_and_watched()))
    else:
        universe = held_and_watched()

    manifest = read_manifest()
    if args.rebuild_only:
        counts = rebuild_l1_files(manifest, also_csv=args.csv)
        log(f"다시 만듦: L1 Parquet {len(counts)}개 — " + ", ".join(f"{k} {v:,}행" for k, v in sorted(counts.items())))
        return 0
    now = datetime.now(timezone.utc)
    todo = []
    for t in universe:
        m = manifest.get(t)
        if m and m.get("fetched_at") and m.get("status") not in ("error", "not_found"):
            age = now - datetime.fromisoformat(m["fetched_at"])
            if age < timedelta(hours=args.stale_hours):
                manifest[t]["l1"] = l1_map.get(t, UNCLASSIFIED)
                continue
        todo.append(t)
    if args.max:
        todo = todo[: args.max]
    log(f"시작: 대상 {len(universe)}종목, 이번에 받을 것 {len(todo)}종목 ({args.universe})")

    events: dict[str, list[dict]] = {}
    fails = 0
    done = 0
    with httpx.Client(timeout=30.0, headers={"User-Agent": UA}) as client:
        for i, t in enumerate(todo):
            if i:
                time.sleep(random.uniform(1.5, 2.5))
            try:
                status, rows, evs = collect_one(client, t)
                fails = 0
            except Exception as exc:  # noqa: BLE001 — 한 종목 실패로 전체를 죽이지 않는다
                fails += 1
                log(f"  {t}: 실패 {exc!r}")
                manifest[t] = {**manifest.get(t, {}), "ticker": t,
                               "l1": l1_map.get(t, UNCLASSIFIED), "status": "error",
                               "fetched_at": now.isoformat(), "source": "yahoo"}
                if fails >= MAX_CONSECUTIVE_FAILS:
                    log(f"연속 {fails}번 실패 — 이번 실행을 멈춘다(다음 실행이 이어 받는다)")
                    break
                continue
            entry = {"ticker": t, "l1": l1_map.get(t, UNCLASSIFIED), "status": status,
                     "fetched_at": datetime.now(timezone.utc).isoformat(),
                     "source": f"yahoo:{yahoo_symbol(t)}" if t in TICKER_ALIASES else "yahoo"}
            if rows:
                write_ticker(t, rows)
                entry.update(first_date=rows[0]["date"], last_date=rows[-1]["date"], rows=len(rows),
                             currency=LAST_META.get(yahoo_symbol(t), {}).get("currency", ""))
                events[t] = evs
            manifest[t] = {**manifest.get(t, {}), **entry}
            done += 1
            log(f"  [{i + 1}/{len(todo)}] {t} {status} {entry.get('rows', 0)}행 "
                f"{entry.get('first_date', '')}~{entry.get('last_date', '')} → {entry['l1']}")
            if done % 25 == 0:
                write_manifest(manifest)  # 중간 저장 — 끊겨도 이어 받는다

    write_manifest(manifest)
    write_events(events)
    counts = rebuild_l1_files(manifest, also_csv=args.csv)
    log(f"끝: 받은 종목 {done}, L1 Parquet {len(counts)}개 — " +
        ", ".join(f"{k} {v:,}행" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
