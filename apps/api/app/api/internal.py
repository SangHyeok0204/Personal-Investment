from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Job
from app.schemas import InternalJobRequest, JobOut


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
