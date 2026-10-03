"""LLM_WATCHPOINTS — 종목 하나의 다음 발표 관전포인트를 `claude -p` 로 만든다 (계획 B2 왕복 · B5 생성).

큐: **llm**(SEC·크롤 작업과 줄을 따로 — 한 작업이 8분 걸려도 Form 4 수집이 밀리지 않게).
문맥 = 가장 최근 실적 8-K/6-K 의 Ex.99.1(`sec/exhibit.py`). 대상 분기 = `earnings_events` 의 다음 발표 분기,
없으면 최근 발표 +91일의 분기 라벨.
실패는 종류대로(`claude` 원천): 로그아웃 · 사용량 초과 · 시간초과 · 하루 상한 — 관전포인트 칸은 비워 둔다
(원본처럼 '[타임아웃] …' 글자를 칸에 쓰지 않는다). 사용량 초과는 재시도하지 않는다(작업 실패로 끝).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from llm.cli import LlmError, run_claude
from llm.repair import RepairFailed, run_with_repair, write_escalation
from llm.watchpoints import build_prompt, parse_watchpoints
from sec.client import SecBlocked, sec_client, sec_get
from sec.exhibit import earnings_release
from sec.ownership import cik10
from source_health import record_error, record_ok

TICKERS = "https://www.sec.gov/files/company_tickers.json"


def quarter_label(d: date) -> str:
    """원본 `derive_fiscal_quarter`(발표일 기준 달력 분기 라벨) — `app/core/earnings_import.quarter_of` 와 같다."""
    return f"{d.year - 1}Q4" if d.month <= 3 else f"{d.year}Q{(d.month - 1) // 3}"


def target_quarter(conn, ticker: str, today: date) -> tuple[str, str | None]:
    """(분기 라벨, 회사명). 다음 예정 발표가 있으면 그 분기, 없으면 최근 발표 +91일."""
    nxt = conn.execute(text(
        "SELECT quarter, company FROM earnings_events WHERE ticker = :t AND report_date >= :d "
        "ORDER BY report_date LIMIT 1"), {"t": ticker, "d": today}).one_or_none()
    if nxt:
        return nxt[0], nxt[1]
    last = conn.execute(text(
        "SELECT report_date, company FROM earnings_events WHERE ticker = :t AND report_date IS NOT NULL "
        "ORDER BY report_date DESC LIMIT 1"), {"t": ticker}).one_or_none()
    base = (last[0] + timedelta(days=91)) if last else today
    return quarter_label(base), (last[1] if last else None)


def store_points(conn, ticker: str, quarter: str, points: list[dict], model: str | None) -> int:
    for rank, p in enumerate(points, start=1):
        conn.execute(text(
            "INSERT INTO earnings_watchpoints (ticker, quarter, rank, point, source, model) "
            "VALUES (:t, :q, :r, :p, 'llm', :m) ON CONFLICT (ticker, quarter, rank) DO UPDATE SET "
            "point = EXCLUDED.point, source = 'llm', model = EXCLUDED.model, updated_at = now()"),
            {"t": ticker, "q": quarter, "r": rank, "p": p["text"], "m": model})
    # 이번에 더 적게 나왔으면 남은 옛 LLM 포인트는 지운다(이관분은 건드리지 않는다)
    conn.execute(text("DELETE FROM earnings_watchpoints WHERE ticker = :t AND quarter = :q AND rank > :n "
                      "AND source = 'llm'"), {"t": ticker, "q": quarter, "n": len(points)})
    return len(points)


def run(engine, job_id, payload, storage_dir, log_job):
    ticker = str((payload or {})["ticker"]).upper()
    today = date.today()
    with engine.begin() as c:
        quarter, company = target_quarter(c, ticker, today)
    quarter = (payload or {}).get("quarter") or quarter
    try:
        with sec_client(require_ua=True) as sec:
            tk = sec_get(sec, TICKERS).json()
            hit = next((v for v in tk.values() if str(v["ticker"]).upper() == ticker), None)
            release = earnings_release(sec, cik10(hit["cik_str"])) if hit else None
            company = company or (hit or {}).get("title") or ticker
    except SecBlocked as exc:
        record_error(engine, "sec", "403", str(exc))
        raise
    prompt = build_prompt(company=company, ticker=ticker, context=(release or {}).get("text"))
    log_job(engine, job_id, "INFO", "llm", f"{ticker} {quarter} 문맥 "
            f"{'8-K ' + release['filing_date'] if release else '없음'} · 프롬프트 {len(prompt)}자")
    try:
        rep = run_with_repair(prompt, lambda p: run_claude(p, storage_dir=storage_dir), parse_watchpoints,
                              lambda d: (bool(d["points"]), [] if d["points"] else ["watching_points 목록이 없거나 비었음"]))
    except LlmError as exc:
        record_error(engine, "claude", exc.kind, str(exc))
        raise
    except RepairFailed as exc:
        record_error(engine, "claude", "other", f"형식 오류: 관전포인트 JSON 없음 ({exc.last_text[:120]})")
        write_escalation(storage_dir, "LLM_WATCHPOINTS", f"{ticker}-{quarter}", exc, job_id=job_id,
                         task=f"{ticker} {quarter} 관전포인트 생성",
                         decision_needed="수리 재시도까지 형식 실패 — 관전포인트를 손으로 적을지, 비워 둘지",
                         source={"filing_url": (release or {}).get("url")})
        raise ValueError("LLM 응답에 관전포인트가 없음") from exc
    parsed, res = rep.data, rep.result
    with engine.begin() as c:
        n = store_points(c, ticker, quarter, parsed["points"], res.model)
    detail = {"ticker": ticker, "quarter": quarter, "points": n, "model": res.model,
              "cost_usd": res.cost_usd, "seconds": round(res.duration_ms / 1000, 1),
              "calls_today": res.calls_today, "context": (release or {}).get("url")}
    record_ok(engine, "claude", detail=detail)
    return {**detail, "key_metric": parsed["key_metric"], "detail": parsed["detail"],
            "texts": [p["text"] for p in parsed["points"]]}
