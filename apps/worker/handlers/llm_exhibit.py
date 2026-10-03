"""LLM_EXHIBIT — 실적 보도자료를 `claude -p` 로 구조화해 매출 실적 · 가이던스 · 세그먼트를 채운다 (계획 B4).

큐: llm. `EARNINGS_RESULT` 가 8-K/6-K 를 찾으면 넣는다(payload.event_id).
- 매출 실적: **USD 로 낸 것만**(외국 발행사가 자국 통화로 내면 섞지 않는다). Investing(검증) 값이면 두고 5% 넘게
  다르면 경고, 이관(미검증) 값이면 8-K 값으로 바꾼다. 검증된 컨센과 ±50% 밖이면 추출 오류로 보고 버린다.
- 가이던스: 다음 분기 매출 · EPS 범위 + 코멘트 → `earnings_guidance`. 방향 = 직전 발표의 같은 지표 가이던스 중간값 대비
  (±1% 안 = 유지, 직전 없음 = 신규). ⚠️직전 가이던스는 **이번 분기** 것이라 "다음 분기 가이던스가 순차로 올랐나"를 본다 —
  컨센 대비 상향/하향이 아니다(다음 분기 컨센을 모은다면 그때 바꾼다).
- 세그먼트 · 회사 회계분기 · 통화 → `earnings_results.detail`.
실패는 `claude` 원천에 종류대로(B2). 형식 오류는 'other'.
"""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import text

from llm.cli import LlmError, run_claude
from llm.exhibit import build_prompt, parse, plausible_revenue, scaled, validate
from llm.repair import RepairFailed, run_with_repair, write_escalation
from sec.client import sec_client, sec_get
from sec.exhibit import html_to_text
from source_health import record_error, record_ok


def _direction(new_mid, prior_mid) -> str:
    if prior_mid is None or new_mid is None:
        return "new"
    if prior_mid == 0:
        return "maintain" if new_mid == 0 else ("raise" if new_mid > 0 else "lower")
    ch = (new_mid - prior_mid) / abs(prior_mid)
    return "raise" if ch > Decimal("0.01") else "lower" if ch < Decimal("-0.01") else "maintain"


def _mid(lo, hi):
    vals = [v for v in (lo, hi) if v is not None]
    return sum(vals) / len(vals) if vals else None


def store(engine, ev, data: dict, warnings: list[str], model: str | None) -> dict:
    cur = str(data.get("currency") or "").upper()
    rev = data.get("revenue") or {}
    rev_a = scaled(rev.get("actual"), rev.get("unit")) if cur == "USD" else None
    g = data.get("guidance") or {}
    rows = []
    for metric, key in (("revenue", "next_quarter_revenue"), ("eps", "next_quarter_eps")):
        v = g.get(key) or {}
        lo, hi = (scaled(v.get("low"), v.get("unit")), scaled(v.get("high"), v.get("unit"))) if metric == "revenue" \
            else (scaled(v.get("low"), None), scaled(v.get("high"), None))
        if lo is None and hi is None:
            continue
        rows.append({"metric": metric, "low": lo, "high": hi})
    # 어느 매출을 믿나(실측 NBIS: 원본 이관 매출이 45.83B · 32.44B 로 틀렸고 이관 컨센도 같이 틀려 서로 맞아 보였다):
    #   - 검증된 컨센(Investing)이 있으면 추출값을 그걸로 점검(±50% 밖이면 추출 오류로 보고 버림)
    #   - 매출 실적이 Investing(검증) 것이면 그대로 두고, 이관(미검증) 것이면 8-K 추출값으로 **바꾼다**
    verified_fc = ev.revenue_forecast if ev.revenue_forecast_source == "investing" else None
    if rev_a is not None and not plausible_revenue(rev_a, verified_fc):
        warnings.append(f"추출 매출 {rev_a} 가 검증된 컨센 {verified_fc} 와 50% 넘게 다름 — 추출 오류 의심, 저장 안 함")
        rev_a = None
    verified_actual = (ev.detail or {}).get("revenue_from") == "investing"
    keep = ev.revenue_actual if verified_actual else None
    if ev.revenue_actual is not None and not verified_actual and rev_a is not None \
            and abs(rev_a - ev.revenue_actual) / ev.revenue_actual > Decimal("0.05"):
        warnings.append(f"이관 매출 {ev.revenue_actual} → 8-K {rev_a} 로 바꿈(이관값은 미검증)")
    if ev.revenue_actual is not None and not verified_actual and rev_a is None:
        keep = ev.revenue_actual                         # 8-K 에서 못 읽었으면 이관값이라도 둔다
    with engine.begin() as c:
        if keep is not None and verified_actual and rev_a and abs(rev_a - keep) / keep > Decimal("0.05"):
            warnings.append(f"매출 8-K {rev_a} vs Investing {keep} — 5% 넘게 다름")
        c.execute(text(
            "UPDATE earnings_results SET revenue_actual = COALESCE(:keep, :a), "
            "detail = COALESCE(detail, '{}'::jsonb) || CAST(:d AS JSONB) WHERE event_id = :id"),
            {"a": rev_a, "keep": keep, "id": ev.id, "d": json.dumps({
                "exhibit_parsed": True, "exhibit_model": model, "fiscal_quarter": data.get("fiscal_quarter"),
                "currency": cur or None, "operating_margin": data.get("operating_margin"),
                "segments": data.get("segments") or [], "guidance_commentary": g.get("commentary"),
                "exhibit_warnings": warnings}, default=str)})
        c.execute(text("DELETE FROM earnings_guidance WHERE event_id = :id"), {"id": ev.id})
        for r in rows:
            prior = c.execute(text(
                "SELECT g.low, g.high FROM earnings_guidance g JOIN earnings_events e ON e.id = g.event_id "
                "WHERE e.ticker = :t AND e.report_date < :d AND g.metric = :m ORDER BY e.report_date DESC LIMIT 1"),
                {"t": ev.ticker, "d": ev.report_date, "m": r["metric"]}).one_or_none()
            plo, phi = (prior.low, prior.high) if prior else (None, None)
            c.execute(text(
                "INSERT INTO earnings_guidance (event_id, metric, period, low, high, prior_low, prior_high, direction, "
                "text, source_url) VALUES (:e, :m, 'next_quarter', :lo, :hi, :plo, :phi, :dir, :txt, :url)"),
                {"e": ev.id, "m": r["metric"], "lo": r["low"], "hi": r["high"], "plo": plo, "phi": phi,
                 "dir": _direction(_mid(r["low"], r["high"]), _mid(plo, phi)),
                 "txt": g.get("commentary") if r["metric"] == "revenue" else None, "url": ev.filing_url})
    return {"revenue_actual": str(rev_a) if rev_a else None, "guidance": len(rows),
            "segments": len(data.get("segments") or []), "currency": cur, "warnings": warnings}


def run(engine, job_id, payload, storage_dir, log_job):
    eid = int((payload or {})["event_id"])
    with engine.begin() as c:
        ev = c.execute(text(
            "SELECT e.id, e.ticker, e.report_date, e.eps_forecast, e.revenue_forecast, e.revenue_forecast_source, "
            "r.filing_url, r.revenue_actual, r.detail "
            "FROM earnings_events e JOIN earnings_results r ON r.event_id = e.id WHERE e.id = :id"), {"id": eid}).one()
    with sec_client(require_ua=True) as sec:
        resp = sec_get(sec, ev.filing_url)
    body = html_to_text(resp.text) if resp.status_code == 200 else ""
    if len(body) < 200:
        raise ValueError(f"보도자료 글이 너무 짧음({len(body)}자): {ev.filing_url}")
    prompt = build_prompt(ev.ticker, body, ev.eps_forecast, ev.revenue_forecast)
    try:
        rep = run_with_repair(prompt, lambda p: run_claude(p, storage_dir=storage_dir), parse, validate)
    except LlmError as exc:
        record_error(engine, "claude", exc.kind, str(exc))
        raise
    except RepairFailed as exc:
        record_error(engine, "claude", "other", f"보도자료 구조화 실패({ev.ticker}): {exc}")
        write_escalation(storage_dir, "LLM_EXHIBIT", eid, exc, job_id=job_id,
                         task=f"{ev.ticker} {ev.report_date} 실적 보도자료 구조화",
                         decision_needed="수리 재시도까지 검증 실패 — 매출·가이던스를 손으로 넣을지, 비워 둘지",
                         source={"filing_url": ev.filing_url})
        raise
    data, warns, res = rep.data, rep.warns, rep.result
    out = store(engine, ev, data, warns, res.model)
    # B5 — 결과가 빈 관전포인트가 있으면 결과 판정을 이어서 예약(같은 발표는 한 번)
    with engine.begin() as c:
        out["judge_job"] = c.execute(text(
            "INSERT INTO jobs (id, job_type, status, queue, payload) SELECT gen_random_uuid(), 'LLM_JUDGE', 'PENDING', "
            "'llm', CAST(:p AS JSONB) WHERE EXISTS (SELECT 1 FROM earnings_watchpoints w JOIN earnings_events e "
            "ON e.ticker = w.ticker AND e.quarter = w.quarter WHERE e.id = :id AND w.point IS NOT NULL "
            "AND w.result IS NULL) AND NOT EXISTS (SELECT 1 FROM jobs WHERE job_type = 'LLM_JUDGE' "
            "AND payload->>'event_id' = :e AND status IN ('PENDING', 'RUNNING', 'SUCCESS'))"),
            {"p": json.dumps({"event_id": ev.id}), "id": ev.id, "e": str(ev.id)}).rowcount
    record_ok(engine, "claude", detail={"task": "exhibit", "ticker": ev.ticker, "cost_usd": res.cost_usd,
                                        "calls_today": res.calls_today})
    log_job(engine, job_id, "INFO", "done", f"{ev.ticker} exhibit: {out}")
    return {"ticker": ev.ticker, "event_id": eid, **out, "cost_usd": res.cost_usd}
