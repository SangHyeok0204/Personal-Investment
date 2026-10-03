"""PLAUD_VIDEO — Plaud 에 올린 유튜브 영상 녹음을 한 문단 이슈 요약으로 (화면 /news/video).

큐: **llm**(`claude -p` 를 부른다 — LLM_EXHIBIT 등과 같은 줄, 같은 하루 상한 `LLM_DAILY_CAP`).
API `sec_sync` 가 매일 07:40 KST 이후 한 번 넣는다(맥이 자고 있었으면 깨어나서). 화면의 "지금 확인"도 같은 작업을 넣는다.

1) Plaud MCP(`plaud/client.py`)로 최근 14일 녹음 목록 → 제목 규칙(`plaud/video.py`)에 맞는 것만.
2) 이미 요약한(done) 녹음은 건너뛴다 — 같은 녹음을 두 번 요약하지 않는다(`plaud_file_id` 유일).
3) 새 것(·전사 대기·실패 3번 미만)은 전사문(+Plaud AI 요약 참고)을 받아 `claude -p` 로 한 문단.
   - 전사문도 Plaud 요약도 없으면 **pending**(LLM 을 부르지 않는다 — 지어낼 재료가 없다). 다음 실행에서 다시.
   - LLM 이 실패하거나 형식이 틀리면 **failed** + 이유. 요약 칸은 비워 둔다.
   - 사용량 초과 · 하루 상한 · 로그아웃이면 남은 녹음은 손대지 않고 멈춘다(다음 실행에서).
원천 상태: `plaud_video`(목록 성공/실패), `claude`(LLM) — /data-operations 에 보인다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from llm.cli import LlmError, run_claude
from llm.repair import RepairFailed, run_with_repair, write_escalation
from llm.video import build_prompt, parse_summary
from plaud.client import PlaudError, PlaudMcp
from plaud.video import parse_title
from source_health import record_error, record_ok

SOURCE = "plaud_video"
LOOKBACK_DAYS = 14
MAX_ATTEMPTS = 3
# 한 번에 요약하는 최대 건수 — 하루 LLM 상한(40)을 다른 작업과 나눠 쓴다. 남은 것은 다음 실행에서.
MAX_PER_RUN = 8
# 이 종류의 LLM 실패는 다음 녹음에서도 똑같이 실패한다 — 더 부르지 않고 멈춘다.
_STOP_KINDS = {"usage_limit", "cap", "logged_out", "missing"}


def _existing(conn, ids: list[str]) -> dict[str, tuple[str, int]]:
    if not ids:
        return {}
    rows = conn.execute(text("SELECT plaud_file_id, status, attempts FROM video_digests "
                             "WHERE plaud_file_id = ANY(:ids)"), {"ids": ids}).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _upsert_meta(conn, rec: dict, t) -> None:
    """녹음 정보만 넣거나 고친다(제목을 고쳤을 수 있다). 요약·상태는 건드리지 않는다."""
    conn.execute(text(
        "INSERT INTO video_digests (plaud_file_id, title, source_tag, video_date, channel, recorded_at, status) "
        "VALUES (:id, :title, :tag, :d, :ch, :at, 'pending') ON CONFLICT (plaud_file_id) DO UPDATE SET "
        "title = EXCLUDED.title, source_tag = EXCLUDED.source_tag, video_date = EXCLUDED.video_date, "
        "channel = EXCLUDED.channel, recorded_at = EXCLUDED.recorded_at, updated_at = now() "
        "WHERE video_digests.status <> 'done'"),
        {"id": rec["id"], "title": rec["name"], "tag": t.source_tag, "d": t.video_date, "ch": t.channel,
         "at": rec["recorded_at"]})


def _set(engine, file_id: str, *, status: str, error: str | None = None, summary: str | None = None,
         model: str | None = None, attempted: bool = False) -> None:
    with engine.begin() as c:
        c.execute(text(
            "UPDATE video_digests SET status = :s, error = :e, summary_ko = COALESCE(:sum, summary_ko), "
            "model = COALESCE(:m, model), attempts = attempts + :a, updated_at = now() WHERE plaud_file_id = :id"),
            {"s": status, "e": error, "sum": summary, "m": model, "a": 1 if attempted else 0, "id": file_id})


def collect(engine, plaud, summarize, *, now: datetime | None = None, log=lambda msg: None,
            storage_dir: str | None = None) -> dict:
    """한 번 훑는다. `plaud` = PlaudMcp(열린 것), `summarize(prompt) -> LlmResult`. 시험은 둘 다 가짜를 넣는다.

    형식이 틀리면 같은 녹음을 한 번 수리 재시도(L1). 그래도 틀리면 failed + (`storage_dir` 가 있으면) 에스컬레이션 패킷.
    """
    now = now or datetime.now(timezone.utc)
    # 서버는 date_from 을 서버 현지 날짜로 거른다 — 하루 앞당겨 받고 아래에서 UTC 시각으로 다시 거른다.
    since = now - timedelta(days=LOOKBACK_DAYS)
    plaud.check_login()
    rows, complete = plaud.list_recent((since - timedelta(days=1)).date().isoformat())
    rows = [r for r in rows if r["recorded_at"] is None or r["recorded_at"] >= since]
    matched = [(r, t) for r in rows if (t := parse_title(r["name"])) is not None]
    out = {"listed": len(rows), "matched": len(matched), "complete": complete, "skipped_done": 0,
           "skipped_failed": 0, "done": 0, "pending": 0, "failed": 0, "deferred": 0}
    with engine.begin() as c:
        seen = _existing(c, [r["id"] for r, _ in matched])
        for r, t in matched:
            _upsert_meta(c, r, t)
    # 오래된 것부터 — 날짜순으로 쌓이게.
    matched.sort(key=lambda rt: (rt[1].video_date, rt[0]["recorded_at"] or now))
    used = 0
    stop: str | None = None
    for r, t in matched:
        status, attempts = seen.get(r["id"], ("new", 0))
        if status == "done":
            out["skipped_done"] += 1
            continue
        if status == "failed" and attempts >= MAX_ATTEMPTS:
            out["skipped_failed"] += 1
            continue
        if stop or used >= MAX_PER_RUN:
            out["deferred"] += 1           # pending 으로 남는다 — 다음 실행에서
            continue
        transcript = plaud.transcript_text(r["id"])
        note = plaud.ai_summary(r["id"])
        if not transcript and not note:
            _set(engine, r["id"], status="pending",
                 error="Plaud 전사 없음 — Plaud 앱에서 전사가 끝나면 다음 확인 때 요약")
            out["pending"] += 1
            continue
        prompt = build_prompt(channel=t.channel, video_date=t.video_date.isoformat(), title=r["name"],
                              transcript=transcript, plaud_summary=note)
        used += 1
        log(f"{r['name']} — 전사 {len(transcript or '')}자 · Plaud 요약 {len(note or '')}자 · 프롬프트 {len(prompt)}자")
        try:
            rep = run_with_repair(prompt, summarize, parse_summary,
                                  lambda s: (s is not None, [] if s else ['{"summary": "…"} JSON 이 없거나 비었음']))
        except LlmError as exc:
            _set(engine, r["id"], status="failed", error=f"LLM {exc.kind}: {str(exc)[:300]}", attempted=True)
            record_error(engine, "claude", exc.kind, str(exc))
            out["failed"] += 1
            if exc.kind in _STOP_KINDS:
                stop = exc.kind
            continue
        except RepairFailed as exc:
            _set(engine, r["id"], status="failed", error=f"형식 오류: 요약 JSON 없음 ({exc.last_text[:120]})",
                 attempted=True)
            if storage_dir:
                write_escalation(storage_dir, "PLAUD_VIDEO", r["id"], exc, task=f"영상 요약 {r['name']}",
                                 decision_needed="수리 재시도까지 형식 실패 — 요약을 손으로 적을지, 비워 둘지",
                                 source={"plaud_file_id": r["id"]})
            out["failed"] += 1
            continue
        summary, res = rep.data, rep.result
        _set(engine, r["id"], status="done", summary=summary, model=res.model, attempted=True)
        out["done"] += 1
    if stop:
        out["stopped"] = stop
    return out


def run(engine, job_id, payload, storage_dir, log_job):
    def log(msg):
        log_job(engine, job_id, "INFO", "plaud", msg)

    try:
        with PlaudMcp() as plaud:
            out = collect(engine, plaud, lambda p: run_claude(p, storage_dir=storage_dir), log=log,
                          storage_dir=storage_dir)
    except PlaudError as exc:
        msg = str(exc)
        if exc.kind == "logged_out":
            msg = f"Plaud 로그아웃 — 터미널에서 `npx -y @plaud-ai/mcp@latest install` 한 번 ({msg[:200]})"
        record_error(engine, SOURCE, exc.kind, msg)
        raise
    record_ok(engine, SOURCE, detail=out)
    if out["done"]:
        record_ok(engine, "claude", detail={"job": "PLAUD_VIDEO", "summaries": out["done"]})
    return out
