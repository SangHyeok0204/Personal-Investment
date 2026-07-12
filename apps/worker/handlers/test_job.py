import time
from datetime import datetime, timezone


def run(engine, job_id, payload, storage_dir, log_job):
    log_job(engine, job_id, "INFO", "processing", "Processing test job")
    time.sleep(1)
    log_job(engine, job_id, "INFO", "processing", "Test job sleep complete")
    return {
        "echo": payload,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
