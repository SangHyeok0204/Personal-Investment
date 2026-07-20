import asyncio

import httpx
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Job
from app.schemas import CheckHogaEnvelope, InternalJobRequest, JobOut

# Hard wall-clock budget for the collector forward, mirroring the inav proxy: a
# stopped collector must fail fast (503) rather than hang the agent's POST.
COLLECTOR_TIMEOUT_S = 2.0


def require_internal_api_key(
    x_internal_api_key: str | None = Header(default=None),
) -> None:
    """Guard every /internal route with the shared internal API key."""
    if x_internal_api_key != settings.INTERNAL_API_KEY:
        raise AppError(401, "UNAUTHORIZED", "Invalid or missing internal API key.")


# Separate router so authentication is layered on all /internal routes.
router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.post("/jobs", response_model=JobOut, status_code=201)
def create_internal_job(body: InternalJobRequest, db: Session = Depends(get_db)) -> Job:
    job = Job(job_type=body.job_type, status="PENDING", payload=body.payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/check/hoga")
async def ingest_check_hoga(body: CheckHogaEnvelope) -> Response:
    """Forward a validated CHECK-agent 호가 envelope to the collector.

    Reuses the /internal API-key guard for auth and the inav proxy's 2s
    wall-clock budget so a stopped collector degrades to a fast 503 (the agent
    backs off) instead of hanging this request.
    """
    url = f"{settings.COLLECTOR_URL}/ingest/hoga"
    try:
        async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT_S) as client:
            upstream = await asyncio.wait_for(
                client.post(url, json=body.model_dump()),
                timeout=COLLECTOR_TIMEOUT_S,
            )
    except (httpx.HTTPError, asyncio.TimeoutError):
        return JSONResponse(status_code=503, content={"detail": "collector unavailable"})

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )
