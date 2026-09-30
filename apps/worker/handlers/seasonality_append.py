"""SEASONALITY_APPEND — 계절성 시계열의 최근 월말 종가를 Yahoo 에서 받아 붙인다 (계획 C3).

큐: sec_crawl. API 의 캐치업 루프(`app/core/seasonality_sync.py`)가 지난달 값이 비면 넣는다.

- `seasonality_series.yahoo_symbol` 이 있는 시계열만(창업판은 동결 — 없음).
- 원천 전환 달(블룸버그 마지막 달) **12개월 전부터** 받는다. 전환 달 자체의 Yahoo 값이
  다음 달 수익률의 기준이 되고(수익률은 같은 원천 안에서만), 겹치는 12개월로 두 원천의
  월 수익률 차이를 잰다.
- ⚠️`range=max` 를 쓰지 않는다 — 간격을 제멋대로 바꾼다(실측: S&P 42년에 169점).
- ⚠️수정전 `close` 를 쓴다. 블룸버그 PX_LAST 는 가격지수라 배당을 넣은 adjclose 와 다르다.
- ⚠️**진행 중인 달은 넣지 않는다**(월중에 돌아도). 또 Yahoo 는 진행 중인 달을 한 번 더
  돌려주는 경우가 있어(중복 1행) 같은 달은 마지막 값 하나만 남긴다.
- 파이썬 기본 UA 는 429(실측) — 브라우저 UA.
- ⚠️**달은 거래소 현지 시각으로 정한다.** Yahoo 월봉 시각은 현지 월초 00:00 이다 — 코스피 9월
  봉은 `2026-08-31T15:00Z`(= KST 9/1 00:00). UTC 로 달을 정하면 아시아 지수가 **한 달씩 밀려**
  붙는다(실측: 겹침 12개월 월수익률 차이 코스피 평균 19.7%p · 코스닥 14.8%p · 항셍 8.2%p,
  미국 지수는 0 — 시간대가 UTC 보다 늦어서 우연히 맞았다).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import text

from source_health import classify_error, record_error, record_ok

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
OVERLAP_MONTHS = 12


def _month_index(m: str) -> int:
    return int(m[:4]) * 12 + int(m[5:7]) - 1


def _month_from_index(i: int) -> str:
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def _exchange_tz(meta: dict):
    """거래소 시간대. 이름이 있으면 그걸(서머타임 반영), 없으면 고정 시차, 둘 다 없으면 UTC."""
    name = meta.get("exchangeTimezoneName")
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    offset = meta.get("gmtoffset")
    if isinstance(offset, int):
        return timezone(timedelta(seconds=offset))
    return timezone.utc


def completed_months(chart_json: dict, now: datetime) -> dict[str, float]:
    """Yahoo chart 응답 → {'YYYY-MM': 수정전 종가}. 진행 중인 달·빈 값 제외, 같은 달은 마지막 값."""
    result = (chart_json.get("chart") or {}).get("result") or []
    if not result:
        return {}
    r0 = result[0]
    stamps = r0.get("timestamp") or []
    closes = ((r0.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    tz = _exchange_tz(r0.get("meta") or {})
    current = now.astimezone(tz).strftime("%Y-%m")
    out: dict[str, float] = {}
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        month = datetime.fromtimestamp(ts, tz).strftime("%Y-%m")
        if month >= current:
            continue
        out[month] = float(close)
    return out


def run(engine, job_id, payload, storage_dir, log_job):
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        series = conn.execute(
            text(
                "SELECT s.key, s.yahoo_symbol, "
                "(SELECT max(month) FROM monthly_closes c WHERE c.series = s.key "
                " AND c.source = 'bloomberg') AS cutover "
                "FROM seasonality_series s WHERE s.yahoo_symbol IS NOT NULL ORDER BY s.sort"
            )
        ).all()

    stored, failed = {}, {}
    with httpx.Client(headers={"User-Agent": _UA}, timeout=20) as client:
        for key, symbol, cutover in series:
            start = _month_from_index(_month_index(cutover) - OVERLAP_MONTHS) if cutover else "1990-01"
            period1 = int(datetime(int(start[:4]), int(start[5:7]), 1, tzinfo=timezone.utc).timestamp())
            try:
                resp = client.get(
                    _BASE + symbol,
                    params={"period1": period1, "period2": int(now.timestamp()), "interval": "1mo"},
                )
                resp.raise_for_status()
                months = completed_months(resp.json(), now)
            except Exception as exc:  # 한 심볼이 막혀도 나머지는 받는다
                kind = classify_error(exc)
                failed[key] = kind
                record_error(engine, "yahoo", kind, f"{symbol}: {exc}")
                log_job(engine, job_id, "WARN", "fetch", f"{key}({symbol}) 실패: {kind}")
                continue
            with engine.begin() as conn:
                for month, close in months.items():
                    conn.execute(
                        text(
                            "INSERT INTO monthly_closes (series, month, close, source) "
                            "VALUES (:s, :m, :c, 'yahoo') ON CONFLICT (series, month, source) "
                            "DO UPDATE SET close = EXCLUDED.close, loaded_at = now()"
                        ),
                        {"s": key, "m": month, "c": close},
                    )
            stored[key] = max(months) if months else None
            time.sleep(0.3)  # 브라우저 한 명 속도

    if stored:
        record_ok(engine, "yahoo", detail={"series": len(stored), "failed": len(failed)})
    log_job(engine, job_id, "INFO", "done", f"저장 {len(stored)} · 실패 {len(failed)}")
    if not stored and failed:
        raise RuntimeError(f"Yahoo 전부 실패: {sorted(set(failed.values()))}")
    return {"latest": stored, "failed": failed}
