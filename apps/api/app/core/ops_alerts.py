"""서버측 트립와이어 (하네스 O1) — 웹 탭이 닫혀 있어도 API 가 5분마다 이상을 잡아 `ops_alert_state` 에 적는다.

★왜: 2026-10-02 EARNINGS_REVENUE 가 18시간 RUNNING 으로 멈춰 sec_crawl 큐를 막았는데 아무도 몰랐다.
  종(상단 바)은 화면이 열려 있어야 묻는다 — 판정은 서버가 해야 한다.

조건 (key → kind):
  · `JOB_STUCK:<job id>`        — RUNNING 이 작업별 벽시계 상한(worker `wallclock.LIMITS`, 그 밖은 60분)을 넘었다.
  · `SOURCE_ERROR:<source>`     — `last_error_at > coalesce(last_ok_at, epoch)` 이고 마지막 성공(없으면 마지막 실패)
                                   뒤로 6시간이 지났다. ⚠️실패는 last_error_at 을 계속 밀어 올리므로 '실패가 시작된 때'는
                                   기록이 없다 — 마지막 성공을 그 대신으로 쓴다.
  · `LLM_CAP_80PCT`             — 오늘(KST) 카운터 `storage/llm/calls-YYYY-MM-DD.json` 의 n ≥ 0.8 × `LLM_DAILY_CAP`.
                                   상한 값은 `.env.local` 에서 worker 와 같이 읽는다(config.py 참조).
  · `LLM_ESCALATION:<파일명>`   — worker `llm/repair.write_escalation` 이 남긴 패킷(`storage/llm/escalations/*.json`).
                                   파일이 지워지면 풀린다.

상태(0027): **전이만** 적는다. 처음 잡히면 넣고(열림), 계속이면 last_seen 만, 조건이 사라지면 resolved_at.
  열린 key 는 다시 알리지 않는다. 풀린 뒤 또 잡히면 같은 행을 새로 연다(first_seen·acked_at 초기화).
  종에는 열려 있고 확인(acked_at) 안 한 것만 나온다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_, select

from app.core.ai_snapshot_sync import today_kst
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Job, OpsAlertState, SourceStatus

logger = logging.getLogger(__name__)

STARTUP_DELAY_SECONDS = 60
STUCK_DEFAULT_SECONDS = 60 * 60
# worker `wallclock.LIMITS` 와 같게 둔다(API 는 worker 모듈을 들여오지 않는다).
STUCK_LIMITS = {"EARNINGS_REVENUE": 20 * 60, "SEC_13F_BACKFILL": 60 * 60}
SOURCE_ERROR_AFTER = timedelta(hours=6)
CAP_RATIO = 0.8
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _llm_dir() -> Path:
    return Path(settings.STORAGE_DIR) / "llm"


def _calls_today() -> int:
    path = _llm_dir() / f"calls-{today_kst():%Y-%m-%d}.json"
    try:
        return int(json.loads(path.read_text()).get("n", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def detect(db, now: datetime) -> dict[str, tuple[str, dict]]:
    """지금 걸린 조건 전부 — key → (kind, detail)."""
    found: dict[str, tuple[str, dict]] = {}

    for job in db.execute(select(Job).where(Job.status == "RUNNING")).scalars():
        started = job.started_at or job.updated_at
        limit = STUCK_LIMITS.get(job.job_type, STUCK_DEFAULT_SECONDS)
        if started and (now - started).total_seconds() > limit:
            found[f"JOB_STUCK:{job.id}"] = ("JOB_STUCK", {
                "job_id": str(job.id), "job_type": job.job_type, "queue": job.queue,
                "started_at": started.isoformat(), "limit_minutes": limit // 60,
            })

    for src in db.execute(select(SourceStatus)).scalars():
        if src.last_error_at is None or src.last_error_at <= (src.last_ok_at or _EPOCH):
            continue
        since = src.last_ok_at or src.last_error_at
        if now - since > SOURCE_ERROR_AFTER:
            found[f"SOURCE_ERROR:{src.source}"] = ("SOURCE_ERROR", {
                "source": src.source, "error_kind": src.last_error_kind,
                "last_error_at": src.last_error_at.isoformat(),
                "last_ok_at": src.last_ok_at.isoformat() if src.last_ok_at else None,
                "message": (src.last_error_message or "")[:200],
            })

    cap = settings.LLM_DAILY_CAP
    n = _calls_today()
    if cap > 0 and n >= CAP_RATIO * cap:
        found["LLM_CAP_80PCT"] = ("LLM_CAP_80PCT", {"calls_today": n, "cap": cap})

    esc = _llm_dir() / "escalations"
    if esc.is_dir():
        for path in sorted(esc.glob("*.json")):
            found[f"LLM_ESCALATION:{path.name}"] = ("LLM_ESCALATION", {"file": path.name})

    return found


def tick(db, now: datetime | None = None) -> dict[str, list[str]]:
    """한 번 판정해 전이를 적는다. 반환: 새로 열린 key·풀린 key."""
    now = now or datetime.now(timezone.utc)
    found = detect(db, now)
    rows = {
        r.key: r
        for r in db.execute(
            select(OpsAlertState).where(
                or_(OpsAlertState.resolved_at.is_(None), OpsAlertState.key.in_(list(found)))
            )
        ).scalars()
    }
    opened: list[str] = []
    resolved: list[str] = []
    for key, (kind, detail) in found.items():
        row = rows.get(key)
        if row is None:
            db.add(OpsAlertState(key=key, kind=kind, first_seen=now, last_seen=now, detail=detail))
            opened.append(key)
        elif row.resolved_at is not None:
            row.first_seen = row.last_seen = now
            row.resolved_at = row.acked_at = None
            row.detail = detail
            opened.append(key)
        else:
            row.last_seen = now
            row.detail = detail
    for key, row in rows.items():
        if key not in found and row.resolved_at is None:
            row.resolved_at = now
            resolved.append(key)
    db.commit()
    return {"opened": opened, "resolved": resolved}


def message(row: OpsAlertState) -> str:
    d = row.detail or {}
    if row.kind == "JOB_STUCK":
        return f"{d.get('job_type')} 작업이 {d.get('limit_minutes')}분 넘게 RUNNING 입니다."
    if row.kind == "SOURCE_ERROR":
        return f"원천 {d.get('source')} 이(가) 6시간 넘게 실패 중입니다({d.get('error_kind')})."
    if row.kind == "LLM_CAP_80PCT":
        return f"오늘 LLM 호출 {d.get('calls_today')}/{d.get('cap')} — 하루 상한의 80%를 넘었습니다."
    if row.kind == "LLM_ESCALATION":
        return f"LLM 이 사람 판단을 요청했습니다: {d.get('file')}"
    return row.kind


def open_unacked(db) -> list[OpsAlertState]:
    return list(
        db.execute(
            select(OpsAlertState)
            .where(OpsAlertState.resolved_at.is_(None), OpsAlertState.acked_at.is_(None))
            .order_by(OpsAlertState.first_seen)
        ).scalars()
    )


def run_once() -> dict[str, list[str]]:
    with SessionLocal() as db:
        return tick(db)


async def ops_alert_loop() -> None:
    # 기동 직후엔 쉰다 — --reload 재시작·테스트 TestClient 마다 돌지 않게.
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = await asyncio.to_thread(run_once)
            if result["opened"] or result["resolved"]:
                logger.warning("ops alerts: %s", result)
        except Exception:
            logger.exception("ops alert check failed")
        await asyncio.sleep(settings.OPS_ALERT_INTERVAL_SECONDS)
