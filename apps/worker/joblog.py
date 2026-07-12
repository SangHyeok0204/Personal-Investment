import json
import uuid

from sqlalchemy import text


def log_job(engine, job_id, level, step, message, metadata=None):
    """Insert one row into job_logs."""
    metadata_json = json.dumps(metadata) if metadata is not None else None
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO job_logs (id, job_id, level, step, message, metadata, created_at) "
                "VALUES (:id, :job_id, :level, :step, :message, CAST(:metadata AS JSONB), now())"
            ),
            {
                "id": uuid.uuid4(),
                "job_id": job_id,
                "level": level,
                "step": step,
                "message": message,
                "metadata": metadata_json,
            },
        )
