import uuid

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.models import Job, JobLog
from app.schemas import (
    JobDetailOut,
    JobListOut,
    JobLogOut,
    JobOut,
    JobStatsOut,
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
