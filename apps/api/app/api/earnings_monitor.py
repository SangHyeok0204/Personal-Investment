"""실적 모니터 API (계획 B3a · B6) — `/research/earnings` 화면. 대상 = 내 미국 보유 + 관심종목.

일정 · EPS 컨센은 Nasdaq(B3a), 매출 컨센은 Investing.com 크롤(B3b — 실패하면 `revenue_forecast_status='failed'`
"수집 실패"), 실적 · 8-K · 반응은 B4, 관전포인트는 B2 · B5.
⚠️`quarter` 는 발표일로 정한 달력 분기 라벨(원본 규칙) — 회사 회계분기가 아니다.
⚠️이관(B1) 값 중 컨센은 미검증이다 — Nasdaq 이 당시 컨센으로 바꾼 행만 서프라이즈가 있다.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/research/earnings", tags=["earnings"])

AHEAD_DAYS = 63
RECENT_DAYS = 120
_TIMING = {"BMO": "장전", "AMC": "장후"}


def _targets(db: Session) -> list[str]:
    return sorted(db.execute(text(
        "SELECT upper(a.ticker) FROM current_positions p JOIN assets a ON a.id = p.asset_id "
        "WHERE p.quantity > 0 AND a.country = 'US' UNION SELECT upper(ticker) FROM watchlist_items")).scalars())


def _f(v):
    return float(v) if v is not None else None


def _event(r) -> dict:
    detail = r.result_detail or {}
    eps_verified = r.eps_forecast is not None and (
        detail.get("eps_from") == "nasdaq calendar"
        or (r.source == "nasdaq" and not detail.get("import")))
    revenue_verified = r.revenue_forecast is not None and r.revenue_forecast_source == "investing"
    status = "unverified" if r.revenue_forecast_source == "import" else r.revenue_forecast_status
    return {"id": r.id, "ticker": r.ticker, "quarter": r.quarter, "company": r.company,
            "report_date": r.report_date.isoformat() if r.report_date else None,
            "timing": _TIMING.get(r.timing or "", "미정"), "eps_forecast": _f(r.eps_forecast),
            "n_estimates": r.n_estimates, "revenue_forecast": _f(r.revenue_forecast),
            "revenue_forecast_status": status, "source": r.source,
            "eps_forecast_verified": eps_verified, "revenue_forecast_verified": revenue_verified}


def _result(r) -> dict:
    detail = r.result_detail or {}
    event = _event(r)
    eps_verified = r.eps_actual is not None and detail.get("eps_from") == "nasdaq calendar"
    # A filing or parsed exhibit may retain imported actuals after failed extraction.
    # Only an explicit field source establishes which stored amount was verified.
    revenue_verified = r.revenue_actual is not None and detail.get("revenue_from") == "investing"
    pairs = [(r.eps_surprise_pct, eps_verified and event["eps_forecast_verified"]),
             (r.revenue_surprise_pct, revenue_verified and event["revenue_forecast_verified"])]
    used = [(value, verified) for value, verified in pairs if value is not None]
    expected = ("상회" if any(value >= 3 for value, _ in used) else
                "하회" if any(value <= -3 for value, _ in used) else "부합") if used else None
    verdict_verified = bool(used and all(verified for _, verified in used) and r.verdict == expected)
    return dict(event, eps_actual=_f(r.eps_actual), revenue_actual=_f(r.revenue_actual),
                eps_actual_verified=eps_verified, revenue_actual_verified=revenue_verified,
                eps_surprise_pct=_f(r.eps_surprise_pct), revenue_surprise_pct=_f(r.revenue_surprise_pct),
                verdict=r.verdict, verdict_verified=verdict_verified,
                verified=verdict_verified, reaction_pct=_f(r.reaction_pct), reaction_window=r.reaction_window)


def _week_start(d: date) -> date:
    """'이번 주' 월요일. 주말(토·일)이면 **다가오는** 주 — 일요일에 막 끝난 주를 '이번 주'로 보이지 않게
    (실측: 9/27 일요일에 '이번 주'가 9/21~25 로 나왔다). 그때 '지난주'는 막 끝난 주가 된다."""
    monday = d - timedelta(days=d.weekday())
    return monday + timedelta(days=7) if d.weekday() >= 5 else monday


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    today = date.today()
    targets = _targets(db)
    ev = db.execute(text(
        "SELECT e.*, r.eps_actual, r.revenue_actual, r.eps_surprise_pct, r.revenue_surprise_pct, r.verdict, "
        "r.reaction_pct, r.reaction_window, r.source AS result_source, r.detail AS result_detail "
        "FROM earnings_events e LEFT JOIN earnings_results r ON r.event_id = e.id "
        "WHERE e.ticker = ANY(:t) AND e.report_date BETWEEN :lo AND :hi ORDER BY e.report_date, e.ticker"),
        {"t": targets, "lo": today - timedelta(days=RECENT_DAYS), "hi": today + timedelta(days=AHEAD_DAYS)}).all()
    upcoming = [dict(_event(r), days_left=(r.report_date - today).days, within_4w=(r.report_date - today).days <= 28)
                for r in ev if r.report_date >= today]
    recent = [_result(r) for r in ev if r.report_date < today and r.result_source]
    recent.sort(key=lambda x: x["report_date"], reverse=True)
    # 요일 막대: 이번 주 · 다음 주(월~금), 장전/장후/미정 수 + 종목
    this_monday = _week_start(today)
    days = []
    for w in range(2):
        for i in range(5):
            d = this_monday + timedelta(days=7 * w + i)
            on = [u for u in upcoming if u["report_date"] == d.isoformat()] + \
                 [x for x in recent if x["report_date"] == d.isoformat()]
            days.append({"date": d.isoformat(), "week": w, "tickers": [x["ticker"] for x in on],
                         "bmo": sum(x["timing"] == "장전" for x in on), "amc": sum(x["timing"] == "장후" for x in on),
                         "tbd": sum(x["timing"] == "미정" for x in on)})
    last_monday = this_monday - timedelta(days=7)
    last_week = [x for x in recent if last_monday.isoformat() <= x["report_date"] < this_monday.isoformat()]
    this_week = [d for d in days if d["week"] == 0]
    reacted = [x for x in recent if x["reaction_pct"] is not None]
    return {
        "today": today.isoformat(),
        "targets": targets,
        "no_events": [t for t in targets if not any(e.ticker == t for e in ev)],     # ETF 등
        "this_week_count": sum(len(d["tickers"]) for d in this_week),
        "last_week": {"beat": sum(x["verdict"] == "상회" for x in last_week),
                      "miss": sum(x["verdict"] == "하회" for x in last_week),
                      "inline": sum(x["verdict"] == "부합" for x in last_week), "n": len(last_week)},
        "next": upcoming[0] if upcoming else None,
        "max_reaction": max(reacted, key=lambda x: abs(x["reaction_pct"])) if reacted else None,
        "days": days,
        "upcoming": upcoming,
        "recent": recent,
    }


@router.get("/stock/{ticker}")
def stock(ticker: str, db: Session = Depends(get_db)):
    t = ticker.upper()
    rows = db.execute(text(
        "SELECT e.*, r.eps_actual, r.revenue_actual, r.eps_surprise_pct, r.revenue_surprise_pct, r.verdict, "
        "r.filing_url, r.filing_accession, r.reaction_pct, r.reaction_window, r.reaction_note, r.detail AS result_detail, "
        "r.source AS result_source FROM earnings_events e LEFT JOIN earnings_results r ON r.event_id = e.id "
        "WHERE e.ticker = :t ORDER BY e.report_date DESC NULLS LAST LIMIT 8"), {"t": t}).all()
    if not rows:
        raise AppError(404, "EARNINGS_NOT_FOUND", f"{t} 의 실적 일정이 없습니다")
    points = db.execute(text(
        "SELECT quarter, rank, point, result, source, model FROM earnings_watchpoints WHERE ticker = :t "
        "ORDER BY quarter DESC, rank"), {"t": t}).mappings().all()
    guidance = db.execute(text(
        "SELECT g.event_id, g.metric, g.period, g.low, g.high, g.prior_low, g.prior_high, g.direction, g.text "
        "FROM earnings_guidance g JOIN earnings_events e ON e.id = g.event_id WHERE e.ticker = :t"), {"t": t}).mappings().all()
    by_q: dict[str, list] = {}
    for p in points:
        by_q.setdefault(p["quarter"], []).append(dict(p))
    events = []
    for r in rows:
        events.append(dict(
            _result(r), filing_url=r.filing_url, reaction_note=r.reaction_note,
            # B5 — LLM 결과 판정(서프라이즈 · 중립 · 쇼크 · 미확인). 없으면 None
            overall=((r.result_detail or {}).get("verdicts") or {}).get("overall"),
            watchpoints=by_q.get(r.quarter, []),
            guidance=[{k: (_f(v) if k in ("low", "high", "prior_low", "prior_high") else v) for k, v in g.items()}
                      for g in guidance if g["event_id"] == r.id]))
    return {"ticker": t, "company": next((r.company for r in rows if r.company), t), "events": events}
