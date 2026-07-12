import uuid
from datetime import datetime, timedelta, timezone

from app.models import Job, JobLog


def test_create_test_job(client):
    response = client.post("/api/v1/jobs/test", json={"payload": {"hello": "world"}})
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "TEST_JOB"
    assert body["status"] == "PENDING"
    assert body["payload"] == {"hello": "world"}
    assert body["result"] is None
    assert body["error_message"] is None
    uuid.UUID(body["id"])  # id is a valid UUID string


def test_create_test_job_without_body(client):
    response = client.post("/api/v1/jobs/test")
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "TEST_JOB"
    assert body["payload"] is None


def test_list_jobs_empty(client):
    response = client.get("/api/v1/jobs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_list_jobs_pagination_and_order(client):
    client.post("/api/v1/jobs/test", json={"payload": {"n": 1}})
    client.post("/api/v1/jobs/test", json={"payload": {"n": 2}})

    response = client.get("/api/v1/jobs?limit=1&offset=0")
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert len(body["items"]) == 1


def test_list_jobs_status_filter(client):
    client.post("/api/v1/jobs/test", json={"payload": {}})
    response = client.get("/api/v1/jobs?status=PENDING")
    assert response.status_code == 200
    assert response.json()["total"] == 1

    empty = client.get("/api/v1/jobs?status=SUCCESS")
    assert empty.json()["total"] == 0


def test_list_jobs_invalid_status(client):
    response = client.get("/api/v1/jobs?status=BOGUS")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_list_jobs_limit_too_large(client):
    response = client.get("/api/v1/jobs?limit=101")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_get_job_detail(client):
    created = client.post("/api/v1/jobs/test", json={"payload": {"x": 1}}).json()
    response = client.get(f"/api/v1/jobs/{created['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["logs"] == []


def test_get_job_detail_with_logs_ordered(client, db):
    job = Job(job_type="TEST_JOB", status="SUCCESS")
    db.add(job)
    db.flush()
    job_id = job.id

    base = datetime.now(timezone.utc)
    first = JobLog(job_id=job_id, level="INFO", step="start", message="first", created_at=base)
    second = JobLog(
        job_id=job_id,
        level="INFO",
        step="end",
        message="second",
        meta={"k": "v"},
        created_at=base + timedelta(seconds=1),
    )
    db.add_all([second, first])  # inserted out of chronological order
    db.commit()

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    logs = response.json()["logs"]
    assert [entry["message"] for entry in logs] == ["first", "second"]
    assert logs[0]["metadata"] is None
    assert logs[1]["metadata"] == {"k": "v"}


def test_get_job_not_found(client):
    response = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_get_job_malformed_uuid(client):
    response = client.get("/api/v1/jobs/not-a-uuid")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_job_stats(client):
    client.post("/api/v1/jobs/test", json={"payload": {}})
    response = client.get("/api/v1/jobs/stats")
    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "pending": 1,
        "running": 0,
        "success": 0,
        "failed": 0,
    }
