"""EARNINGS_REVENUE — Investing.com 에서 내 종목의 매출 컨센(과 지난 발표의 매출 실적)을 채운다 (계획 B3b).

큐: sec_crawl — 화면 있는 크롬이 떠야 하므로 **GUI 로그인 세션의 LaunchAgent** 여야 한다(`prices/investing.py`).
대상 날짜 = 내 종목의 ① 다가오는 발표일(63일 안) ② 최근 120일 발표 중 검증된 매출 컨센이 없는 날. 한 번에 최대 12일.
- 성공: `revenue_forecast` · status 'ok' · source 'investing'. 지난 날짜면 매출 실적 · 매출 서프라이즈 · 판정 다시.
- **막히면**(Cloudflare · 시간초과): 대상 중 매출 컨센이 없는 다가오는 발표에 status 'failed' → 화면 "수집 실패".
  EPS(Nasdaq)는 그대로 보인다. 원천 상태 `investing`(차단은 'blocked').
- ★날짜마다 받는 즉시 저장한다 — 중간에 죽어도(드라이버 · 시간초과) 받은 날은 남고, 작업은 FAILED
  "(저장된 날짜 N/M)", '수집 실패' 는 못 채운 다가오는 발표에만.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from handlers.earnings_calendar import verdict
from prices.investing import InvestingBlocked, crawl_dates
from source_health import record_error, record_ok
from wallclock import WallClockTimeout, run_in_child

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


def _crawl_streaming(days: list[date], on_progress=None) -> dict:
    """자식 프로세스 쪽 — 하루 끝날 때마다 (날짜, 행들) 을 부모에게 흘려보낸다(spawn 이라 모듈 수준 함수)."""
    return crawl_dates(days, on_day=(lambda d, xs: on_progress((d, xs))) if on_progress else None)


def crawl_isolated(days: list[date], on_day=None) -> dict:
    """(L4) Playwright 크롤을 자식 프로세스에서 — 작업의 남은 벽시계 시간이 지나면 크롬까지 강제 종료.

    ⚠️2026-10-02: 이 크롤이 18시간 굳었다. 동기 Playwright 는 파이프에 막히면 신호로도 못 깨운다.
    ★`on_day(day, rows)` 는 **부모 프로세스**에서 하루씩 돈다(큐로 받아서) — 자식이 죽어도 이미 받은 날은 저장된 뒤.
    """
    return run_in_child(_crawl_streaming, days, on_progress=(lambda v: on_day(*v)) if on_day else None)


def collect(engine, today: date | None = None, crawl=crawl_isolated, only: list[date] | None = None) -> dict:
    """`only` — 수동 실행에서 날짜를 좁힌다(예: 화면 잠금 실측을 짧게).

    ★하루 끝날 때마다 바로 DB 에 쓴다(`on_day` → `_apply`). ⚠️2026-10-04: 크롤 전체가 끝나야 쓰던 때, 드라이버가
      `write EINVAL` 로 죽고 3시간 상한까지 굳어 모은 날짜가 전부 날아갔다. 크롬은 그대로 **한 회차에 한 번**
      (사용자 요구 — Cloudflare 때문에 시도 수를 줄인다): 쪼개 띄우거나 재시도를 더하지 않고, 받은 만큼만 남긴다.
    """
    today = today or date.today()
    with engine.begin() as c:
        rows, days = targets_and_dates(c, today)
    if only:
        days = [d for d in only]
        rows = [r for r in rows if any(abs((d - r.report_date).days) <= 6 for d in days)]
    if not days:
        return {"dates": 0}
    got: dict = {}
    state = {"hit": {}, "filled": set(), "actuals": set()}

    def on_day(day, xs):
        got[day] = xs
        _apply(engine, rows, got, today, state, final=False)

    def settle(kind: str, message: str) -> None:
        # ★2026-10-05 정리 단계가 실패해도(DB 끊김 등) 원래 오류를 가리지 않는다 — 로그 대신 삼킨다.
        for step in (lambda: _apply(engine, rows, got, today, state),
                     lambda: _mark_failed(engine, rows, today, state["filled"]),
                     lambda: record_error(engine, "investing", kind, message)):
            try:
                step()
            except Exception:  # noqa: BLE001
                pass

    try:
        final = crawl(days, on_day=on_day)
    except InvestingBlocked as exc:
        settle("blocked", str(exc))
        raise
    except Exception as exc:
        # 실패여도 받은 날짜는 이미 저장됐다 — 작업은 FAILED 로 두되 몇 날짜를 건졌는지 남긴다
        msg = f"{exc} (저장된 날짜 {len(got)}/{len(days)})"
        settle("timeout" if "timeout" in msg.lower() else "other", msg[-300:])
        # ★2026-10-05 exc.args 를 고쳐 쓰지 않고 새 예외로 감싼다. ⚠️벽시계 시간초과는 타입을 지킨다 —
        #   worker main 이 `WallClockTimeout` 으로 `timeout_wallclock` 을 판정한다(메시지도 그걸로 시작).
        raise (WallClockTimeout(msg) if isinstance(exc, WallClockTimeout) else RuntimeError(msg)) from exc
    for d, xs in (final or {}).items():      # on_day 를 안 부르는 크롤(테스트 · 옛 경로)도 받는다
        got.setdefault(d, xs)
    _apply(engine, rows, got, today, state)
    return {"dates": len(days), "rows_seen": sum(len(v) for v in got.values()), "revenue_forecast": len(state["filled"]),
            "revenue_actual": len(state["actuals"])}


def _apply(engine, rows, got: dict, today: date, state: dict, final: bool = True) -> None:
    """지금까지 받은 날짜(`got`)로 매칭해 UPDATE/UPSERT. 날짜가 늘 때마다 다시 불러도 된다(멱등).

    `state["hit"]` — 발표별로 이미 쓴 행. 같으면 건너뛴다.
    ★2026-10-05 크롤 도중(`final=False`)에는 **발표일 당일** 매칭만 쓴다 — 더 가까운 날이 없으니 확정이다.
      하루라도 떨어진 매칭은 크롤이 끝날 때(성공·실패 모두 `final=True`) 가장 가까운 것으로 한 번 쓴다.
      ⚠️예전엔 먼 날 값을 먼저 쓰고, 더 가까운 날이 '매출 컨센 없음'으로 오면 먼 날 값이 조용히 남았다
      (가장 가까운 매칭과 다른 출처). 이제 가장 가까운 매칭에 컨센이 없으면 그 발표는 손대지 않는다(실행 전 값).
      ⚠️대신 워커 프로세스째 죽으면 당일이 아닌 매칭은 저장되지 않는다(자식·드라이버가 죽는 건 except 경로가 쓴다).
    """
    for r in rows:
        want = (r.ticker, _ALIASES.get(r.ticker))
        # 같은 날 먼저, 없으면 가장 가까운 날(다가오는 발표의 예상일 차이)
        cands = sorted(((abs((d - r.report_date).days), x) for d, xs in got.items() for x in xs
                        if x.ticker.upper() in want and abs((d - r.report_date).days) <= 6), key=lambda t: t[0])
        dist, hit = cands[0] if cands else (None, None)
        if hit is None or state["hit"].get(r.id) == hit or (not final and dist != 0):
            continue
        state["hit"][r.id] = hit
        rev_f, rev_a = money(hit.revenue_forecast), money(hit.revenue)
        with engine.begin() as c:
            if rev_f is not None:
                c.execute(text("UPDATE earnings_events SET revenue_forecast = :f, revenue_forecast_status = 'ok', "
                               "revenue_forecast_source = 'investing', updated_at = now() WHERE id = :id"),
                          {"f": rev_f, "id": r.id})
                state["filled"].add(r.id)
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
                state["actuals"].add(r.id)


def _mark_failed(engine, rows, today: date, filled=()) -> None:
    """다가오는 발표 중 매출 컨센을 못 받은 것만 '수집 실패'(이번 회차에 채운 것 · 이미 값 있는 것은 그대로).

    ⚠️크롤 범위(`INVESTING_AHEAD`) 밖의 먼 발표는 시도조차 안 했다 — '수집 실패'가 아니라 '수집 전'으로 둔다
      (실측 2026-10-04: NVDA·WMT·ADI 등 36~51일 뒤 발표 6건이 실패로 떠 있었다).
    """
    horizon = today + timedelta(days=INVESTING_AHEAD)
    ids = [r.id for r in rows if today <= r.report_date <= horizon and r.id not in filled]
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
