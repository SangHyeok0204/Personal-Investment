from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Job
from app.schemas import InternalJobRequest, JobOut

# Separate router so authentication can be layered on /internal later.
router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/jobs", response_model=JobOut, status_code=201)
def create_internal_job(body: InternalJobRequest, db: Session = Depends(get_db)) -> Job:
    job = Job(job_type=body.job_type, status="PENDING", payload=body.payload)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
