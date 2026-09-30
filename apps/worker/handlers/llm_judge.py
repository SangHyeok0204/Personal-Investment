"""LLM_JUDGE — 발표가 끝난 종목의 관전포인트 ①~④ 결과를 채운다 (계획 B5).

큐: llm. `LLM_EXHIBIT`(보도자료 구조화)가 끝나면 그 발표에 결과가 빈 관전포인트가 있을 때 이어서 넣는다.
결과 · 시장반응 한 문장 · 판정(verdicts)을 저장한다. 이관(B1) 관전포인트의 원본 결과는 덮지 않는다(빈 칸만).
매출은 **검증된 값**만 프롬프트에 준다(Investing 컨센 / 8-K · Investing 실적) — 이관 컨센은 미검증이라 '미확인'.
"""
from __future__ import annotations

import json

from sqlalchemy import text

from llm.cli import LlmError, run_claude
from llm.judgment import build_prompt, parse_judgment
from sec.client import sec_client, sec_get
from sec.exhibit import html_to_text
from source_health import record_error, record_ok


def _money(v) -> str:
    if v is None:
        return "미확인"
    v = float(v)
    return f"${v / 1e9:.2f}B" if abs(v) >= 1e9 else f"${v / 1e6:.1f}M"


def run(engine, job_id, payload, storage_dir, log_job):
    eid = int((payload or {})["event_id"])
    with engine.begin() as c:
        ev = c.execute(text(
            "SELECT e.id, e.ticker, e.quarter, e.company, e.report_date, e.eps_forecast, e.revenue_forecast, "
            "e.revenue_forecast_source, r.eps_actual, r.revenue_actual, r.verdict, r.filing_url, r.detail "
            "FROM earnings_events e JOIN earnings_results r ON r.event_id = e.id WHERE e.id = :id"), {"id": eid}).one()
        points = c.execute(text(
            "SELECT rank, point, result, source FROM earnings_watchpoints WHERE ticker = :t AND quarter = :q "
            "AND point IS NOT NULL ORDER BY rank"), {"t": ev.ticker, "q": ev.quarter}).all()
    if not points:
        return {"ticker": ev.ticker, "skipped": "관전포인트 없음"}
    if all(p.result for p in points):
        return {"ticker": ev.ticker, "skipped": "결과가 이미 있음"}
    ir = ""
    if ev.filing_url:
        with sec_client(require_ua=True) as sec:
            resp = sec_get(sec, ev.filing_url)
        ir = html_to_text(resp.text) if resp.status_code == 200 else ""
    d = ev.detail or {}
    verified_rev_fc = ev.revenue_forecast if ev.revenue_forecast_source == "investing" else None
    prompt = build_prompt(
        company=ev.company or ev.ticker, ticker=ev.ticker, report_date=str(ev.report_date),
        eps_actual=ev.eps_actual if ev.eps_actual is not None else "미확인",
        eps_forecast=ev.eps_forecast if ev.eps_forecast is not None else "미확인",
        revenue_actual=_money(ev.revenue_actual), revenue_forecast=_money(verified_rev_fc), verdict=ev.verdict,
        points=[p.point for p in points], ir_text=ir, segments=d.get("segments"),
        guidance=d.get("guidance_commentary"))
    try:
        res = run_claude(prompt, storage_dir=storage_dir)
    except LlmError as exc:
        record_error(engine, "claude", exc.kind, str(exc))
        raise
    j = parse_judgment(res.text, len(points))
    if not j["ok"]:
        record_error(engine, "claude", "other", f"결과 판정 형식 오류({ev.ticker}): {res.text[:120]}")
        raise ValueError("LLM 응답이 JSON 이 아님")
    filled = 0
    with engine.begin() as c:
        for p, r in zip(points, j["point_results"]):
            if r and not p.result:                   # 이관 원본 결과는 덮지 않는다 — 빈 칸만
                c.execute(text("UPDATE earnings_watchpoints SET result = :r, updated_at = now() "
                               "WHERE ticker = :t AND quarter = :q AND rank = :k"),
                          {"r": r, "t": ev.ticker, "q": ev.quarter, "k": p.rank})
                filled += 1
        c.execute(text(
            "UPDATE earnings_results SET reaction_note = COALESCE(NULLIF(:n, ''), reaction_note), "
            "detail = COALESCE(detail, '{}'::jsonb) || CAST(:d AS JSONB) WHERE event_id = :id"),
            {"n": j["other_reaction"], "id": eid, "d": json.dumps({
                "judged": True, "judge_model": res.model, "verdicts": j["verdicts"], "judge_detail": j["detail"]})})
    out = {"ticker": ev.ticker, "quarter": ev.quarter, "points": len(points), "filled": filled,
           "verdicts": j["verdicts"], "cost_usd": res.cost_usd}
    record_ok(engine, "claude", detail={"task": "judge", **out, "calls_today": res.calls_today})
    log_job(engine, job_id, "INFO", "done", f"judge: {out}")
    return out
