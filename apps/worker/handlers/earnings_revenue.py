"""EARNINGS_REVENUE — Investing.com 에서 내 종목의 매출 컨센(과 지난 발표의 매출 실적)을 채운다 (계획 B3b).

큐: sec_crawl — 화면 있는 크롬이 떠야 하므로 **GUI 로그인 세션의 LaunchAgent** 여야 한다(`prices/investing.py`).
대상 날짜 = 내 종목의 ① 다가오는 발표일(63일 안) ② 최근 120일 발표 중 검증된 매출 컨센이 없는 날. 한 번에 최대 12일.
- 성공: `revenue_forecast` · status 'ok' · source 'investing'. 지난 날짜면 매출 실적 · 매출 서프라이즈 · 판정 다시.
- **막히면**(Cloudflare · 시간초과): 대상 중 매출 컨센이 없는 다가오는 발표에 status 'failed' → 화면 "수집 실패".
  EPS(Nasdaq)는 그대로 보인다. 원천 상태 `investing`(차단은 'blocked').
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from handlers.earnings_calendar import verdict
from prices.investing import InvestingBlocked, crawl_dates
from source_health import record_error, record_ok
from wallclock import run_in_child

AHEAD_DAYS = 63
INVESTING_AHEAD = 35    # Investing.com 이 목록을 올리는 거리(실측)
RECENT_DAYS = 120
MAX_DATES = 12        # 다가오는 발표일 수(앞뒤 평일 포함하면 쪽 수는 더 많다)
_ALIASES = {"GOOGL": "GOOG", "GOOG": "GOOGL"}


def money(v: str) -> Decimal | None:
    s = (v or "").strip().replace(",", "").replace("$", "")
    if not s:
        return None
    mult = {"T": Decimal("1e12"), "B": Decimal("1e9"), "M": Decimal("1e6"), "K": Decimal("1e3")}.get(s[-1].upper())
    try:
        return Decimal(s[:-1]) * mult if mult else Decimal(s)
    except Exception:
        return None


def weekday_window(d: date, n: int = 2) -> list[date]:
    """d 와 앞뒤 n 평일."""
    out, back, fwd = [d], d, d
    for _ in range(n):
        back -= timedelta(days=1)
        while back.weekday() >= 5:
            back -= timedelta(days=1)
        fwd += timedelta(days=1)
        while fwd.weekday() >= 5:
            fwd += timedelta(days=1)
        out += [back, fwd]
    return sorted(out)


def targets_and_dates(conn, today: date) -> tuple[list, list[date]]:
    rows = conn.execute(text(
        "SELECT e.id, e.ticker, e.report_date, e.eps_forecast, r.eps_actual, r.eps_surprise_pct "
        "FROM earnings_events e LEFT JOIN earnings_results r ON r.event_id = e.id "
        "WHERE e.ticker IN (SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "  WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items) "
        "AND ((e.report_date BETWEEN :today AND :hi AND (e.revenue_forecast_source IS DISTINCT FROM 'investing' "
        "      OR e.updated_at < now() - interval '20 hours')) "
        "  OR (e.report_date BETWEEN :lo AND :yesterday AND e.revenue_forecast_source IS DISTINCT FROM 'investing')) "
        "ORDER BY e.report_date"),
        {"today": today, "hi": today + timedelta(days=AHEAD_DAYS), "lo": today - timedelta(days=RECENT_DAYS),
         "yesterday": today - timedelta(days=1)}).all()
    # 다가오는 발표일은 Nasdaq **예상일**이라 Investing.com 은 하루 이틀 다른 날에 올려 둔다(실측: GLW · BE 10/27 에 없음)
    # → 앞뒤 2 평일까지 본다. 지난 발표일은 확정이라 그날만.
    # Investing.com 은 약 5주 앞까지만 올린다(실측: 11/04 은 0행) — 그보다 먼 발표는 가까워지면 다음 회차가 채운다
    ahead = sorted({x for r in rows if today <= r.report_date <= today + timedelta(days=INVESTING_AHEAD)
                    for x in weekday_window(r.report_date) if x >= today})
    past = sorted({r.report_date for r in rows if r.report_date < today}, reverse=True)
    return rows, (sorted(ahead) + past)[:MAX_DATES + 10]


def crawl_isolated(days: list[date]) -> dict:
    """(L4) Playwright 크롤을 자식 프로세스에서 — 작업의 남은 벽시계 시간이 지나면 크롬까지 강제 종료.

    ⚠️2026-10-02: 이 크롤이 18시간 굳었다. 동기 Playwright 는 파이프에 막히면 신호로도 못 깨운다.
    """
    return run_in_child(crawl_dates, days)


def collect(engine, today: date | None = None, crawl=crawl_isolated, only: list[date] | None = None) -> dict:
    """`only` — 수동 실행에서 날짜를 좁힌다(예: 화면 잠금 실측을 짧게)."""
    today = today or date.today()
    with engine.begin() as c:
        rows, days = targets_and_dates(c, today)
    if only:
        days = [d for d in only]
        rows = [r for r in rows if any(abs((d - r.report_date).days) <= 6 for d in days)]
    if not days:
        return {"dates": 0}
    try:
        got = crawl(days)
    except InvestingBlocked as exc:
        _mark_failed(engine, rows, today)
        record_error(engine, "investing", "blocked", str(exc))
        raise
    except Exception as exc:
        _mark_failed(engine, rows, today)
        record_error(engine, "investing", "timeout" if "timeout" in str(exc).lower() else "other", str(exc)[:300])
        raise
    filled = actuals = 0
    for r in rows:
        want = (r.ticker, _ALIASES.get(r.ticker))
        # 같은 날 먼저, 없으면 가장 가까운 날(다가오는 발표의 예상일 차이)
        cands = sorted(((abs((d - r.report_date).days), x) for d, xs in got.items() for x in xs
                        if x.ticker.upper() in want and abs((d - r.report_date).days) <= 6), key=lambda t: t[0])
        hit = cands[0][1] if cands else None
        if hit is None:
            continue
        rev_f, rev_a = money(hit.revenue_forecast), money(hit.revenue)
        with engine.begin() as c:
            if rev_f is not None:
                c.execute(text("UPDATE earnings_events SET revenue_forecast = :f, revenue_forecast_status = 'ok', "
                               "revenue_forecast_source = 'investing', updated_at = now() WHERE id = :id"),
                          {"f": rev_f, "id": r.id})
                filled += 1
            if r.report_date < today and rev_a is not None and rev_f:
                rev_s = round((rev_a - rev_f) / abs(rev_f) * 100, 2)
                c.execute(text(
                    "INSERT INTO earnings_results (event_id, revenue_actual, revenue_surprise_pct, verdict, source, detail) "
                    "VALUES (:id, :a, :s, :v, 'investing', '{\"revenue_from\": \"investing\"}') "
                    "ON CONFLICT (event_id) DO UPDATE SET "
                    "revenue_actual = EXCLUDED.revenue_actual, revenue_surprise_pct = EXCLUDED.revenue_surprise_pct, "
                    "verdict = EXCLUDED.verdict, "
                    "detail = COALESCE(earnings_results.detail, '{}'::jsonb) || '{\"revenue_from\": \"investing\"}'"),
                    {"id": r.id, "a": rev_a, "s": rev_s, "v": verdict(r.eps_surprise_pct, rev_s)})
                actuals += 1
    return {"dates": len(days), "rows_seen": sum(len(v) for v in got.values()), "revenue_forecast": filled,
            "revenue_actual": actuals}


def _mark_failed(engine, rows, today: date) -> None:
    ids = [r.id for r in rows if r.report_date >= today]
    if ids:
        with engine.begin() as c:
            c.execute(text("UPDATE earnings_events SET revenue_forecast_status = 'failed' "
                           "WHERE id = ANY(:ids) AND revenue_forecast IS NULL"), {"ids": ids})


def run(engine, job_id, payload, storage_dir, log_job):
    only = [date.fromisoformat(d) for d in (payload or {}).get("dates", [])] or None
    result = collect(engine, only=only)
    record_ok(engine, "investing", detail=result)
    log_job(engine, job_id, "INFO", "done", f"investing: {result}")
    return result
