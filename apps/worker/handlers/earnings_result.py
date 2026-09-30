"""EARNINGS_RESULT — 발표가 끝난 내 종목의 8-K/6-K · 발표 후 반응 (계획 B4).

큐: sec_crawl. API `sec_sync` 가 **발표 구간이 끝난 뒤 15분마다** 넣는다(찾거나 기한이 지날 때까지):
  장후(AMC) 발표일 17:40 ET · 장전(BMO) 발표일 08:40 ET · 시각 모름은 다음 날 09:00 ET. (계획 데이터·파이프라인 표)
대상 = 최근 30일 발표(토스가 30일 전 1분봉까지 준다 — 맥이 잤어도 캐치업).

1) **보도자료**: `sec/exhibit.earnings_release`(발표일 창 −1 ~ +7일 · 8-K Item 2.02 → 6-K 외국 발행사 — NBIS 등).
   찾으면 `earnings_results.filing_*` 을 채우고, 아직 안 읽었으면 LLM 구조화 작업(`LLM_EXHIBIT`, llm 큐)을 예약한다.
   발표일 +3일이 지나도 못 찾으면 `detail.filing_missing=true`(그만 찾는다 — 6-K 만 내는 곳이 창 밖일 수 있다).
2) **반응**: 토스 1분봉(`prices/reaction.py`) — 장전/장후를 모르면 내지 않는다. ⚠️토스 토큰은 API 시세 캐시와 같은 키 →
   **미국 정규장이 닫혀 있을 때만** 부른다(열려 있으면 다음 회차로 미룬다).
원천 상태 `earnings_result`.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from prices.reaction import earnings_reaction, us_regular_session_open
from prices.toss import TossPriceSource
from sec.client import SecBlocked, sec_client, sec_get
from sec.exhibit import earnings_release
from sec.ownership import cik10
from source_health import record_error, record_ok

LOOKBACK_DAYS = 30
FILING_GIVE_UP_DAYS = 3
TICKERS = "https://www.sec.gov/files/company_tickers.json"
_ENV = Path(__file__).resolve().parents[3] / ".env"      # API credentials_store 와 같은 파일(토스 키)


def env_value(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in _ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.partition("=")[2].strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None


def candidates(conn, today: date, lookback: int = LOOKBACK_DAYS) -> list:
    return conn.execute(text(
        "SELECT e.id, e.ticker, e.report_date, e.timing, r.filing_url, r.reaction_pct, r.detail "
        "FROM earnings_events e LEFT JOIN earnings_results r ON r.event_id = e.id "
        "WHERE e.ticker IN (SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "  WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items) "
        "AND e.report_date BETWEEN :lo AND :today "
        "AND ((r.filing_url IS NULL AND COALESCE(r.detail->>'filing_missing', 'false') <> 'true') "
        "  OR (r.reaction_pct IS NULL AND e.timing IN ('AMC', 'BMO') "
        "      AND COALESCE(r.detail->>'reaction_missing', 'false') <> 'true')) ORDER BY e.report_date"),
        {"lo": today - timedelta(days=lookback), "today": today}).all()


def _merge(conn, event_id: int, fields: dict, detail: dict) -> None:
    cols = ", ".join(fields)
    vals = ", ".join(f":{k}" for k in fields)
    sets = ", ".join(f"{k} = COALESCE(EXCLUDED.{k}, earnings_results.{k})" for k in fields)
    conn.execute(text(
        f"INSERT INTO earnings_results (event_id, {cols}, source, detail) VALUES (:id, {vals}, 'sec', CAST(:d AS JSONB)) "
        f"ON CONFLICT (event_id) DO UPDATE SET {sets}, "
        "detail = COALESCE(earnings_results.detail, '{}'::jsonb) || EXCLUDED.detail"),
        {**fields, "id": event_id, "d": json.dumps(detail)})


def collect(engine, now: datetime | None = None, sec=None, toss=None, lookback: int = LOOKBACK_DAYS) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    with engine.begin() as c:
        rows = candidates(c, today, lookback)
    stats = {"candidates": len(rows), "filings": 0, "filing_missing": 0, "reactions": 0, "reaction_deferred": 0,
             "exhibit_jobs": 0}
    if not rows:
        return stats
    ciks: dict[str, str] = {}
    market_open = us_regular_session_open(now)
    for r in rows:
        if r.filing_url is None and sec is not None:
            if not ciks:
                ciks = {str(v["ticker"]).upper(): cik10(v["cik_str"]) for v in sec_get(sec, TICKERS).json().values()}
            cik = ciks.get(r.ticker) or ciks.get({"GOOGL": "GOOG"}.get(r.ticker, ""))
            rel = earnings_release(sec, cik, asof=r.report_date) if cik else None
            with engine.begin() as c:
                if rel:
                    _merge(c, r.id, {"filing_accession": rel["accession"], "filing_url": rel["url"]},
                           {"filing_form": rel["form"], "filing_date": rel["filing_date"]})
                    stats["filings"] += 1
                    queued = c.execute(text(
                        "INSERT INTO jobs (id, job_type, status, queue, payload) SELECT gen_random_uuid(), "
                        "'LLM_EXHIBIT', 'PENDING', 'llm', CAST(:p AS JSONB) WHERE NOT EXISTS (SELECT 1 FROM jobs "
                        "WHERE job_type = 'LLM_EXHIBIT' AND payload->>'event_id' = :e "
                        "AND payload->>'accession' = :a)"),     # 같은 공시는 한 번만 — 공시가 바뀌면 다시 읽는다
                        {"p": json.dumps({"event_id": r.id, "accession": rel["accession"]}), "e": str(r.id),
                         "a": rel["accession"]}).rowcount
                    stats["exhibit_jobs"] += queued
                elif (today - r.report_date).days > FILING_GIVE_UP_DAYS:
                    _merge(c, r.id, {"filing_url": None}, {"filing_missing": True})
                    stats["filing_missing"] += 1
        if r.reaction_pct is None and r.timing in ("AMC", "BMO") and toss is not None:
            if market_open:
                stats["reaction_deferred"] += 1            # 토큰 충돌 방지 — 장 닫힌 뒤에
                continue
            react = earnings_reaction(toss, r.ticker, r.report_date, r.timing, now)
            with engine.begin() as c:
                if react:
                    _merge(c, r.id, {"reaction_pct": react["pct"], "reaction_window": react["window"]},
                           {"reaction_base": react["base_price"], "reaction_end": react["end_price"]})
                    stats["reactions"] += 1
                elif (today - r.report_date).days > 2:
                    _merge(c, r.id, {"reaction_pct": None}, {"reaction_missing": True})
    return stats


def run(engine, job_id, payload, storage_dir, log_job):
    cid, secret = env_value("TOSS_CLIENT_ID"), env_value("TOSS_CLIENT_SECRET")
    toss = TossPriceSource(cid, secret) if cid and secret else None
    try:
        with sec_client(require_ua=True) as sec:
            # 수동 실행에서만 기간을 넓힌다(과거 발표 캐치업 검증) — 토스 1분봉은 약 30일 전까지라 그 너머 반응은 비기 쉽다
            result = collect(engine, sec=sec, toss=toss,
                             lookback=int((payload or {}).get("lookback_days", LOOKBACK_DAYS)))
    except SecBlocked as exc:
        record_error(engine, "sec", "403", str(exc))
        raise
    except Exception as exc:
        record_error(engine, "earnings_result", "other", str(exc)[:300])
        raise
    finally:
        if toss is not None:
            toss.close()
    result["toss"] = toss is not None
    record_ok(engine, "earnings_result", detail=result)
    log_job(engine, job_id, "INFO", "done", f"earnings_result: {result}")
    return result
