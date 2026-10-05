import json
import logging
import os
import signal
import sys
import threading
import time

from sqlalchemy import text

from db import get_engine, wait_for_db
from handlers import HANDLERS
from joblog import log_job
from llm.cli import LlmError, daily_cap, stop_reason
from source_health import mark_ok_if_tracked, record_error, record_ok
import wallclock

logger = logging.getLogger("worker")

# ★(0019, 계획 P0) 큐마다 worker 를 따로 띄운다. 기본값 "default" 는 예전과 같은
#   한 줄 — 기존 도커 worker·테스트는 그대로 돈다.
DEFAULT_QUEUES = ("default",)
# 작업 중 심장박동 간격. 이 값의 몇 배 동안 소식이 없으면 죽은 작업으로 본다.
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 5 * 60
# 매번 죽는 작업이 영원히 되살아나지 않게.
MAX_ATTEMPTS = 3

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True


def _get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def claim_job(engine, queues=DEFAULT_QUEUES):
    """Atomically claim one PENDING job from `queues`. Returns its id, or None."""
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT id FROM jobs WHERE status = 'PENDING' AND queue = ANY(:queues) "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
            ),
            {"queues": list(queues)},
        ).first()
        if row is None:
            return None
        job_id = row.id
        conn.execute(
            text(
                "UPDATE jobs SET status='RUNNING', started_at=now(), heartbeat_at=now(), "
                "attempts=attempts+1, updated_at=now() WHERE id=:id"
            ),
            {"id": job_id},
        )
    return job_id


def reap_stale_jobs(engine, queues=DEFAULT_QUEUES, stale_seconds=STALE_SECONDS,
                    max_attempts=MAX_ATTEMPTS):
    """심장박동이 끊긴 RUNNING 작업을 되살린다. 상한을 넘으면 FAILED.

    ⚠️없으면 도중에 죽은 작업(프로세스 종료·맥 재시동)은 **영원히 RUNNING** 이다 —
      `claim_job` 은 PENDING 만 집는다. 반환: (되살린 수, 포기한 수).
    """
    params = {"queues": list(queues), "stale": stale_seconds, "max": max_attempts}
    stale = (
        "status = 'RUNNING' AND queue = ANY(:queues) "
        "AND COALESCE(heartbeat_at, started_at, updated_at) < now() - make_interval(secs => :stale)"
    )
    with engine.begin() as conn:
        failed = conn.execute(
            text(
                f"UPDATE jobs SET status='FAILED', finished_at=now(), updated_at=now(), "
                f"error_message='심장박동이 끊긴 채 ' || attempts || '회 시도 — 포기' "
                f"WHERE {stale} AND attempts >= :max"
            ),
            params,
        ).rowcount
        revived = conn.execute(
            text(
                f"UPDATE jobs SET status='PENDING', started_at=NULL, heartbeat_at=NULL, "
                f"updated_at=now() WHERE {stale} AND attempts < :max"
            ),
            params,
        ).rowcount
    return revived, failed


def _beat(engine, job_id):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET heartbeat_at=now() WHERE id=:id AND status='RUNNING'"),
            {"id": job_id},
        )


class _Heartbeat:
    """작업이 도는 동안 `heartbeat_at` 을 주기적으로 갱신하는 배경 스레드.

    ⚠️(L4) `deadline`(monotonic)을 넘기면 더 뛰지 않는다 — 2026-10-02 에는 핸들러가 18시간 굳어 있는 동안
      심장박동만 살아 있어 리퍼가 손을 못 댔다. 상한을 넘긴 작업은 살아 있는 것으로 보이지 않게 한다.
    """

    def __init__(self, engine, job_id, interval=HEARTBEAT_SECONDS, deadline=None):
        self._engine, self._job_id, self._interval = engine, job_id, interval
        self._deadline = deadline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.wait(self._interval):
            if self._deadline is not None and time.monotonic() > self._deadline:
                return
            try:
                _beat(self._engine, self._job_id)
            except Exception:
                logger.exception("heartbeat failed for job %s", self._job_id)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)


def fetch_job(engine, job_id):
    with engine.begin() as conn:
        row = (
            conn.execute(
                text("SELECT id, job_type, payload FROM jobs WHERE id=:id"),
                {"id": job_id},
            )
            .mappings()
            .first()
        )
    return dict(row)


def finish_job_success(engine, job_id, result):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET status='SUCCESS', result=CAST(:result AS JSONB), "
                "finished_at=now(), updated_at=now() WHERE id=:id"
            ),
            {"id": job_id, "result": json.dumps(result)},
        )


def finish_job_failure(engine, job_id, error_message):
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET status='FAILED', error_message=:error_message, "
                "finished_at=now(), updated_at=now() WHERE id=:id"
            ),
            {"id": job_id, "error_message": error_message},
        )


def requeue_stopped(engine, job_id):
    """★(B1) 비상 정지로 멈춘 작업을 PENDING 으로 되돌린다 — `claim_job` 의 `attempts+1` 을 되돌려 시도로 세지 않는다."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE jobs SET status='PENDING', attempts=GREATEST(attempts-1, 0), started_at=NULL, "
                "heartbeat_at=NULL, updated_at=now() WHERE id=:id"
            ),
            {"id": job_id},
        )


def process_job(engine, job, storage_dir):
    job_id = job["id"]
    job_type = job["job_type"]
    payload = job["payload"] or {}

    log_job(engine, job_id, "INFO", "claimed", f"Job claimed (type={job_type})")

    handler = HANDLERS.get(job_type)
    if handler is None:
        error_message = f"Unknown job type: {job_type}"
        finish_job_failure(engine, job_id, error_message)
        log_job(engine, job_id, "ERROR", "failed", error_message)
        return

    # ★(L4) 벽시계 상한 — 핸들러는 스레드에서 돌고, 여기는 상한 + 여유만 기다린다. 넘으면 그 스레드는 버린다
    #   (죽일 수 없다 — 막힐 수 있는 Playwright 는 핸들러 안에서 `wallclock.run_in_child` 로 프로세스째 죽인다).
    limit = wallclock.limit_for(job_type)
    deadline = time.monotonic() + limit
    box = {}

    def _target():
        wallclock.set_deadline(deadline)
        try:
            box["result"] = handler(engine, job_id, payload, storage_dir, log_job)
        except BaseException as exc:     # noqa: BLE001 — 아래에서 FAILED 로 적는다
            box["exc"] = exc

    worker = threading.Thread(target=_target, daemon=True, name=f"job-{job_id}")
    with _Heartbeat(engine, job_id, deadline=deadline + wallclock.GRACE_SECONDS):
        worker.start()
        worker.join(limit + wallclock.GRACE_SECONDS)
    exc = box.get("exc")
    if worker.is_alive() or isinstance(exc, wallclock.WallClockTimeout):
        error_message = str(exc) if exc else f"timeout_wallclock: {job_type} {int(limit)}초 상한 초과 — 포기"
        finish_job_failure(engine, job_id, error_message)
        log_job(engine, job_id, "ERROR", "failed", error_message)
        record_error(engine, f"job:{job_type}", "timeout_wallclock", error_message)
        return
    if exc is not None:
        if not isinstance(exc, Exception):
            raise exc
        if isinstance(exc, LlmError) and exc.kind == "stopped":
            # ★(B1) STOP 파일 / LLM_DAILY_CAP=0 — 실패가 아니다. 작업은 남기고(PENDING) 시도 횟수도 되돌린다.
            requeue_stopped(engine, job_id)
            log_job(engine, job_id, "WARN", "stopped", f"비상 정지 — PENDING 으로 되돌림: {exc}")
            record_error(engine, "claude", "stopped", str(exc))
            return
        error_message = str(exc) or exc.__class__.__name__
        finish_job_failure(engine, job_id, error_message)
        log_job(engine, job_id, "ERROR", "failed", error_message)
        return
    result = box.get("result")

    finish_job_success(engine, job_id, result)
    log_job(engine, job_id, "INFO", "done", "Job completed successfully")
    mark_ok_if_tracked(engine, f"job:{job_type}")      # 지난 상한 초과 경고를 성공으로 닫는다


def run_one_cycle(engine, storage_dir, queues=DEFAULT_QUEUES):
    """Claim and process a single job. Returns True if a job was processed."""
    if "llm" in queues and stop_reason(storage_dir):
        # ★(B1) 비상 정지 중에는 llm 큐 작업을 집지 않는다 — 집었다 되돌리기를 2초마다 되풀이하지 않게.
        queues = tuple(q for q in queues if q != "llm")
        if not queues:
            return False
    job_id = claim_job(engine, queues)
    if job_id is None:
        return False
    job = fetch_job(engine, job_id)
    process_job(engine, job, storage_dir)
    return True


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    database_url = _get_required_env("DATABASE_URL")
    storage_dir = _get_required_env("STORAGE_DIR")
    poll_interval = float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "2"))
    queues = tuple(
        q.strip() for q in os.environ.get("WORKER_QUEUES", "default").split(",") if q.strip()
    )
    worker_name = os.environ.get("WORKER_NAME") or "+".join(queues)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    engine = get_engine(database_url)
    wait_for_db(engine)

    # ★(M2) 실제로 먹은 설정을 한 줄로 — env 가 worker 까지 닿았는지 로그로 확인한다.
    stop_file = "present" if os.path.exists(os.path.join(storage_dir, "llm", "STOP")) else "absent"
    logger.info("Worker %s started on queues %s, polling every %ss llm_daily_cap=%s stop_file=%s",
                worker_name, queues, poll_interval, daily_cap(), stop_file)

    last_housekeeping = 0.0
    while not _shutdown:
        # 생존 신호 + 죽은 작업 되살리기 — 폴링마다 할 일은 아니라 30초에 한 번.
        if time.monotonic() - last_housekeeping >= HEARTBEAT_SECONDS:
            last_housekeeping = time.monotonic()
            try:
                revived, failed = reap_stale_jobs(engine, queues)
                if revived or failed:
                    logger.warning("reaped stale jobs: revived=%s failed=%s", revived, failed)
                record_ok(engine, f"worker:{worker_name}", kind="worker",
                          detail={"queues": list(queues), "pid": os.getpid()})
                # ★(계획 A3a) SEC 를 부르는 큐인데 연락처 UA 가 없으면 화면에 '설정 필요'.
                if "sec_crawl" in queues and not (os.environ.get("SEC_USER_AGENT") or "").strip():
                    record_error(engine, "sec", "config", "SEC_USER_AGENT 미설정 — .env.local 에 연락처 UA 필요")
                # ★(B1) 비상 정지 중이면 화면(/data-operations)의 claude 줄에 'stopped'.
                reason = stop_reason(storage_dir) if "llm" in queues else None
                if reason:
                    record_error(engine, "claude", "stopped", reason)
            except Exception:
                logger.exception("housekeeping failed")
        try:
            processed = run_one_cycle(engine, storage_dir, queues)
        except Exception:
            logger.exception("Unexpected error during poll cycle")
            processed = False
        if not processed and not _shutdown:
            time.sleep(poll_interval)

    logger.info("Worker shutting down gracefully")
    sys.exit(0)


if __name__ == "__main__":
    main()
