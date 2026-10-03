import time
from datetime import datetime, timezone


def run(engine, job_id, payload, storage_dir, log_job):
    log_job(engine, job_id, "INFO", "processing", "Processing test job")
    # 복구 테스트(하네스 5일차)용 — RUNNING 중에 worker 를 죽일 수 있게 길이를 받는다. 기본 1초.
    time.sleep(float((payload or {}).get("sleep_seconds", 1)))
    log_job(engine, job_id, "INFO", "processing", "Test job sleep complete")
    return {
        "echo": payload,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
