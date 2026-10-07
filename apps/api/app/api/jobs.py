import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.models import Job, JobLog, SourceStatus
from app.schemas import (
    JobDetailOut,
    JobListOut,
    JobLogOut,
    JobOut,
    JobStatsOut,
    SourceStatusListOut,
    SourceStatusOut,
    TestJobRequest,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

ALLOWED_STATUSES = {"PENDING", "RUNNING", "SUCCESS", "FAILED"}


@router.post("/test", response_model=JobOut, status_code=201)
def create_test_job(
    body: TestJobRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> Job:
    job = Job(job_type="TEST_JOB", status="PENDING", payload=body.payload if body else None)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=JobListOut)
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    if status is not None and status not in ALLOWED_STATUSES:
        raise AppError(
            400,
            "VALIDATION_ERROR",
            "Invalid status filter.",
            {"allowed": sorted(ALLOWED_STATUSES)},
        )

    count_stmt = select(func.count()).select_from(Job)
    list_stmt = select(Job)
    if status is not None:
        count_stmt = count_stmt.where(Job.status == status)
        list_stmt = list_stmt.where(Job.status == status)

    total = db.execute(count_stmt).scalar_one()
    rows = db.execute(
        list_stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()

    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/stats", response_model=JobStatsOut)
def job_stats(db: Session = Depends(get_db)) -> JobStatsOut:
    rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    counts = {status: count for status, count in rows}
    return JobStatsOut(
        total=sum(counts.values()),
        pending=counts.get("PENDING", 0),
        running=counts.get("RUNNING", 0),
        success=counts.get("SUCCESS", 0),
        failed=counts.get("FAILED", 0),
    )


# worker 는 30초마다 생존 신호를 남긴다. 그 네 배 동안 소식이 없으면 멈춘 것으로 본다.
WORKER_ALIVE_WINDOW = timedelta(minutes=2)


def _state(row: SourceStatus, now: datetime, busy_queues: frozenset[str] = frozenset()) -> str:
    if row.kind == "worker":
        if row.last_ok_at and now - row.last_ok_at <= WORKER_ALIVE_WINDOW:
            return "alive"
        # ★2026-10-07: worker 의 생존 신호는 작업과 작업 **사이**에만 찍힌다. 3시간짜리 크롤을 도는 동안
        #   '멈춤'으로 보였다(EARNINGS_REVENUE 07:51~). 그 큐의 RUNNING 작업 심장박동이 살아 있으면 작동 중이다.
        queues = set((row.detail or {}).get("queues") or [])
        return "alive" if queues & busy_queues else "down"
    if row.last_error_at and (not row.last_ok_at or row.last_error_at > row.last_ok_at):
        return row.last_error_kind or "other"
    return "ok" if row.last_ok_at else "unknown"


# ⚠️`/{job_id}` 보다 **먼저** 선언한다. 뒤에 두면 "sources" 가 job_id 로 잡혀 422 가 난다.
@router.get("/sources", response_model=SourceStatusListOut)
def list_sources(db: Session = Depends(get_db)) -> SourceStatusListOut:
    """수집기(worker)와 외부 원천의 상태 — /data-operations 가 쓴다."""
    now = datetime.now(timezone.utc)
    rows = db.execute(select(SourceStatus).order_by(SourceStatus.kind.desc(), SourceStatus.source)).scalars()
    busy = frozenset(q for (q,) in db.execute(
        select(Job.queue).where(Job.status == "RUNNING", Job.heartbeat_at >= now - WORKER_ALIVE_WINDOW)
    ).all() if q)
    return SourceStatusListOut(
        items=[
            SourceStatusOut(
                source=r.source,
                kind=r.kind,
                state=_state(r, now, busy),
                last_ok_at=r.last_ok_at,
                last_error_at=r.last_error_at,
                last_error_kind=r.last_error_kind,
                last_error_message=r.last_error_message,
                detail=r.detail,
            )
            for r in rows
        ]
    )


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobDetailOut:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise AppError(400, "VALIDATION_ERROR", "Malformed job id.", {"job_id": job_id})

    job = db.get(Job, parsed_id)
    if job is None:
        raise AppError(404, "JOB_NOT_FOUND", "Job not found.", {"job_id": job_id})

    logs = db.execute(
        select(JobLog).where(JobLog.job_id == parsed_id).order_by(JobLog.created_at.asc())
    ).scalars().all()

    job_out = JobOut.model_validate(job)
    return JobDetailOut(**job_out.model_dump(), logs=[JobLogOut.model_validate(row) for row in logs])
