"""EARNINGS_CALENDAR — Nasdaq 실적 캘린더(향후 9주) + 지난 발표의 EPS 실적/컨센/서프라이즈 → DB (계획 B3a).

큐: sec_crawl(수집 작업 줄). API `earnings_sync` 가 매일 07:10 KST 이후 한 번 넣는다(맥이 자고 있었으면 깨어나서).
대상 = 내 미국 보유 + 관심종목(`prices/earnings.py` 의 Nasdaq 수집기 재사용 — 키 없이 · 브라우저 UA).

1) 앞으로 63일(9주 — 아래 AHEAD_DAYS 주석): 날짜별 캘린더 → 내 종목만 `earnings_events` 에 upsert(source='nasdaq'). EPS 컨센 · 추정 수 · 장전/장후.
   발표일이 옮겨 가도 (종목, 분기 라벨)로 같은 행을 고친다.
2) 지난 발표(최근 400일): 그 **발표일의 캘린더**를 다시 부르면 `eps`(실적) · `epsForecast`(당시 컨센) ·
   `surprise`(%)가 온다(실측 NVDA 2026-08-26: $2.22 vs $2.09, +6.22). → `earnings_results` 를 Nasdaq 값으로 채우고
   이관(B1)의 미검증 컨센을 **당시 컨센으로 바꾼다**.
   판정은 원본 `consensus_from_values` 규칙 — EPS · 매출 서프라이즈 중 하나라도 ≥ +3% 면 상회, 아니면 ≤ −3% 면 하회,
   그 밖 부합(매출 컨센은 B3b 가 채우면 같이 본다).
⚠️지난 발표일 캘린더의 `time` 은 'time-not-supplied' 로 온다 — 장전/장후는 기존 값을 지우지 않는다.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from prices.earnings import fetch_calendar
from source_health import record_error, record_ok

# 계획은 "향후 4주"였지만 실측(2026-09-27): 내 종목 11개의 다음 발표가 전부 10/27 ~ 11/18 — 4주 창이면 한 달 동안 빈 화면.
# Nasdaq 은 약 두 달 앞(예상일 포함)까지 준다 → 한 분기 간격만큼(9주) 본다. 화면은 4주 안/밖을 나눠 보인다.
AHEAD_DAYS = 63
LOOKBACK_DAYS = 400
THRESHOLD = Decimal("3")          # %, 원본 consensus_from_values(threshold=0.03)
_TIMING = {"장전": "BMO", "장후": "AMC"}
_ALIASES = {"GOOGL": "GOOG", "GOOG": "GOOGL"}


def quarter_label(d: date) -> str:
    return f"{d.year - 1}Q4" if d.month <= 3 else f"{d.year}Q{(d.month - 1) // 3}"


def verdict(eps_surprise: Decimal | None, rev_surprise: Decimal | None) -> str | None:
    s = [x for x in (eps_surprise, rev_surprise) if x is not None]
    if not s:
        return None
    if any(x >= THRESHOLD for x in s):
        return "상회"
    if any(x <= -THRESHOLD for x in s):
        return "하회"
    return "부합"


def _targets(conn) -> set[str]:
    return set(conn.execute(text(
        "SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items")).scalars())


def _match(targets: set[str], symbol: str) -> str | None:
    s = symbol.upper()
    if s in targets:
        return s
    alias = _ALIASES.get(s)
    return alias if alias in targets else None


_UPSERT_EVENT = text(
    "INSERT INTO earnings_events (ticker, quarter, company, report_date, timing, eps_forecast, n_estimates, "
    "market_cap, source, updated_at) VALUES (:ticker, :quarter, :company, :report_date, :timing, :eps_forecast, "
    ":n_estimates, :market_cap, 'nasdaq', now()) ON CONFLICT (ticker, quarter) DO UPDATE SET "
    "company = COALESCE(EXCLUDED.company, earnings_events.company), report_date = EXCLUDED.report_date, "
    "timing = COALESCE(EXCLUDED.timing, earnings_events.timing), "
    "eps_forecast = COALESCE(EXCLUDED.eps_forecast, earnings_events.eps_forecast), "
    "n_estimates = COALESCE(EXCLUDED.n_estimates, earnings_events.n_estimates), "
    "market_cap = COALESCE(EXCLUDED.market_cap, earnings_events.market_cap), source = 'nasdaq', updated_at = now()"
)


def collect(engine, today: date | None = None, fetch=fetch_calendar) -> dict:
    today = today or date.today()
    with engine.begin() as c:
        targets = _targets(c)
    # 1) 앞으로 AHEAD_DAYS 일
    upcoming = 0
    for ev in fetch(today, AHEAD_DAYS):
        tk = _match(targets, ev.ticker)
        if not tk:
            continue
        with engine.begin() as c:
            c.execute(_UPSERT_EVENT, {"ticker": tk, "quarter": quarter_label(ev.report_date), "company": ev.company,
                                      "report_date": ev.report_date, "timing": _TIMING.get(ev.timing),
                                      "eps_forecast": ev.eps_forecast, "n_estimates": ev.estimate_count,
                                      "market_cap": ev.market_cap})
        upcoming += 1

    # 2) 지난 발표 — Nasdaq 값이 아직 없는 것만
    with engine.begin() as c:
        past = c.execute(text(
            "SELECT e.id, e.ticker, e.report_date, e.revenue_forecast, e.revenue_forecast_source, r.revenue_actual "
            "FROM earnings_events e "
            "LEFT JOIN earnings_results r ON r.event_id = e.id WHERE e.ticker = ANY(:t) "
            "AND e.report_date BETWEEN :lo AND :today AND (r.event_id IS NULL OR r.eps_surprise_pct IS NULL)"),
            {"t": list(targets), "lo": today - timedelta(days=LOOKBACK_DAYS), "today": today}).all()
    by_date: dict[date, list] = {}
    for row in past:
        by_date.setdefault(row.report_date, []).append(row)
    filled, missing = 0, []
    for d, rows in sorted(by_date.items()):
        cal = {ev.ticker.upper(): ev for ev in fetch(d, 1)}
        for row in rows:
            ev = cal.get(row.ticker) or cal.get(_ALIASES.get(row.ticker, ""))
            if ev is None or ev.eps_actual is None:
                missing.append(f"{row.ticker} {d}")
                continue
            # ⚠️매출 서프라이즈는 **검증된 매출 컨센**(Investing.com, B3b)일 때만 판정에 넣는다 — 이관(B1) 컨센은
            #   분기마다 갱신되지 않았다(실측: GLW 2026Q1 EPS 정확히 부합인데 이관 매출 컨센 탓에 '하회'가 됐다).
            rev_s = None
            if (row.revenue_actual is not None and row.revenue_forecast
                    and row.revenue_forecast_source not in (None, "import")):
                rev_s = round((row.revenue_actual - row.revenue_forecast) / abs(row.revenue_forecast) * 100, 2)
            # Nasdaq 이 surprise 칸을 비워 보내기도 한다(실측 GLW 0.70 vs 0.70) — 두 값이 있으면 직접 낸다
            eps_s = ev.eps_surprise_pct
            if eps_s is None and ev.eps_forecast not in (None, 0):
                eps_s = round((ev.eps_actual - ev.eps_forecast) / abs(ev.eps_forecast) * 100, 2)
            with engine.begin() as c:
                c.execute(text("UPDATE earnings_events SET eps_forecast = :f, n_estimates = COALESCE(:n, n_estimates), "
                               "updated_at = now() WHERE id = :id"),
                          {"f": ev.eps_forecast, "n": ev.estimate_count, "id": row.id})
                c.execute(text(
                    "INSERT INTO earnings_results (event_id, eps_actual, eps_surprise_pct, verdict, source, detail) "
                    "VALUES (:id, :a, :s, :v, 'nasdaq', CAST(:d AS JSONB)) ON CONFLICT (event_id) DO UPDATE SET "
                    "eps_actual = EXCLUDED.eps_actual, eps_surprise_pct = EXCLUDED.eps_surprise_pct, "
                    "verdict = EXCLUDED.verdict, source = 'nasdaq', "
                    "detail = COALESCE(earnings_results.detail, '{}'::jsonb) || EXCLUDED.detail"),
                    {"id": row.id, "a": ev.eps_actual, "s": eps_s, "v": verdict(eps_s, rev_s),
                     "d": '{"eps_from": "nasdaq calendar", "forecast_unverified": false}'})
            filled += 1
    return {"targets": len(targets), "upcoming": upcoming, "past_checked": len(past), "past_filled": filled,
            "past_missing": missing[:20]}


def run(engine, job_id, payload, storage_dir, log_job):
    try:
        result = collect(engine)
    except Exception as exc:
        record_error(engine, "nasdaq", "other", str(exc))
        raise
    record_ok(engine, "nasdaq", detail=result)
    log_job(engine, job_id, "INFO", "done", f"nasdaq: {result}")
    return result
