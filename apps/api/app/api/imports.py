import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Import, Job
from app.schemas import ImportCreateOut

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


@router.post("/csv", response_model=ImportCreateOut, status_code=201)
async def import_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ImportCreateOut:
    original_filename = file.filename or ""
    if not original_filename.lower().endswith(".csv"):
        raise AppError(
            400,
            "INVALID_FILE_TYPE",
            "Only .csv files are accepted.",
            {"filename": original_filename},
        )

    content = await file.read()
    if len(content) == 0:
        raise AppError(400, "EMPTY_FILE", "Uploaded file is empty.", {"filename": original_filename})

    sanitized = _UNSAFE_CHARS.sub("_", original_filename)
    stored_filename = f"{uuid.uuid4().hex}_{sanitized}"
    file_path = f"raw/{stored_filename}"

    raw_dir = Path(settings.STORAGE_DIR) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / stored_filename).write_bytes(content)

    job_id = uuid.uuid4()
    import_id = uuid.uuid4()

    job = Job(
        id=job_id,
        job_type="CSV_IMPORT",
        status="PENDING",
        payload={
            "import_id": str(import_id),
            "stored_filename": stored_filename,
            "file_path": file_path,
            "original_filename": original_filename,
        },
    )
    record = Import(
        id=import_id,
        job_id=job_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        file_path=file_path,
        file_size=len(content),
        status="PENDING",
    )

    db.add(job)
    db.flush()  # insert the job row first so the imports FK is satisfied
    db.add(record)
    db.commit()

    return ImportCreateOut(job_id=job_id, import_id=import_id, original_filename=original_filename)
