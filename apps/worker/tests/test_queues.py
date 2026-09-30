"""P0: 큐 분리 · 죽은 작업 되살리기 · 심장박동 · 원천 상태 기록."""
import json
import time
import uuid

import httpx
from sqlalchemy import text

import main
from source_health import classify_error, record_error, record_ok


def _insert(db, job_type="TEST_JOB", queue="default", status="PENDING",
            heartbeat_age_s=None, attempts=0):
    job_id = uuid.uuid4()
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (id, job_type, status, payload, queue, attempts) "
                "VALUES (:id, :t, :s, CAST(:p AS JSONB), :q, :a)"
            ),
            {"id": job_id, "t": job_type, "s": status, "p": json.dumps({"q": queue}),
             "q": queue, "a": attempts},
        )
        if status == "RUNNING":
            conn.execute(
                text(
                    "UPDATE jobs SET started_at = now(), "
                    "heartbeat_at = now() - make_interval(secs => :age) WHERE id = :id"
                ),
                {"id": job_id, "age": float(heartbeat_age_s or 0)},
            )
    return job_id


def _job(db, job_id):
    with db.begin() as conn:
        return conn.execute(
            text("SELECT status, attempts, heartbeat_at, error_message FROM jobs WHERE id=:id"),
            {"id": job_id},
        ).mappings().first()


def test_claim_only_from_own_queue(db):
    sec = _insert(db, queue="sec_crawl")
    llm = _insert(db, queue="llm")

    assert main.claim_job(db, ("llm",)) == llm
    assert main.claim_job(db, ("llm",)) is None  # sec_crawl 작업은 llm worker 가 안 집는다
    assert main.claim_job(db, ("sec_crawl",)) == sec


def test_default_queue_unchanged_for_existing_callers(db, tmp_path):
    job_id = _insert(db)  # queue 기본값 'default'
    assert main.run_one_cycle(db, str(tmp_path)) is True
    assert _job(db, job_id)["status"] == "SUCCESS"


def test_claim_counts_attempts_and_sets_heartbeat(db):
    job_id = _insert(db, queue="llm")
    main.claim_job(db, ("llm",))
    row = _job(db, job_id)
    assert row["attempts"] == 1
    assert row["heartbeat_at"] is not None


def test_reap_revives_stale_running_job(db):
    stale = _insert(db, queue="llm", status="RUNNING", heartbeat_age_s=600, attempts=1)
    fresh = _insert(db, queue="llm", status="RUNNING", heartbeat_age_s=5, attempts=1)
    other = _insert(db, queue="sec_crawl", status="RUNNING", heartbeat_age_s=600, attempts=1)

    revived, failed = main.reap_stale_jobs(db, ("llm",), stale_seconds=300)

    assert (revived, failed) == (1, 0)
    assert _job(db, stale)["status"] == "PENDING"
    assert _job(db, fresh)["status"] == "RUNNING"      # 살아 있는 작업은 건드리지 않는다
    assert _job(db, other)["status"] == "RUNNING"      # 다른 큐는 그 큐의 worker 몫


def test_reap_gives_up_after_max_attempts(db):
    job_id = _insert(db, queue="llm", status="RUNNING", heartbeat_age_s=600, attempts=3)
    revived, failed = main.reap_stale_jobs(db, ("llm",), stale_seconds=300, max_attempts=3)
    assert (revived, failed) == (0, 1)
    row = _job(db, job_id)
    assert row["status"] == "FAILED"
    assert "3회" in row["error_message"]


def test_heartbeat_thread_updates_while_running(db):
    job_id = _insert(db, queue="llm", status="RUNNING", heartbeat_age_s=600, attempts=1)
    before = _job(db, job_id)["heartbeat_at"]
    with main._Heartbeat(db, job_id, interval=0.2):
        time.sleep(0.6)
    assert _job(db, job_id)["heartbeat_at"] > before


def test_classify_error_kinds():
    req = httpx.Request("GET", "https://example.com")
    forbidden = httpx.HTTPStatusError("x", request=req, response=httpx.Response(403, request=req))
    limited = httpx.HTTPStatusError("x", request=req, response=httpx.Response(429, request=req))
    assert classify_error(forbidden) == "403"
    assert classify_error(limited) == "429"
    # ⚠️Nasdaq 은 막을 때 응답 없이 붙잡는다 — 시간초과를 차단 신호로 따로 센다.
    assert classify_error(httpx.ReadTimeout("slow")) == "timeout"
    assert classify_error(ValueError("x")) == "other"
    assert classify_error(status_code=403) == "403"


def test_record_ok_and_error_upsert(db):
    record_error(db, "nasdaq", "timeout", "read timed out")
    record_ok(db, "nasdaq", detail={"rows": 284})
    with db.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM source_status WHERE source='nasdaq'")
        ).mappings().first()
    assert row["kind"] == "source"
    assert row["last_error_kind"] == "timeout"   # 성공이 와도 마지막 실패 기록은 남긴다
    assert row["last_ok_at"] >= row["last_error_at"]
    assert row["detail"] == {"rows": 284}
