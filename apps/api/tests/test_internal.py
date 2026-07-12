from app.core.config import settings

AUTH_HEADER = {"X-Internal-API-Key": settings.INTERNAL_API_KEY}


def test_internal_create_job(client):
    response = client.post(
        "/internal/jobs",
        json={"job_type": "TEST_JOB", "payload": {"source": "n8n"}},
        headers=AUTH_HEADER,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "TEST_JOB"
    assert body["status"] == "PENDING"
    assert body["payload"] == {"source": "n8n"}


def test_internal_create_job_without_payload(client):
    response = client.post(
        "/internal/jobs", json={"job_type": "TEST_JOB"}, headers=AUTH_HEADER
    )
    assert response.status_code == 201
    assert response.json()["payload"] is None


def test_internal_create_job_empty_type(client):
    response = client.post(
        "/internal/jobs", json={"job_type": "", "payload": {}}, headers=AUTH_HEADER
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_internal_create_job_missing_type(client):
    response = client.post("/internal/jobs", json={"payload": {}}, headers=AUTH_HEADER)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_internal_missing_api_key(client):
    response = client.post("/internal/jobs", json={"job_type": "TEST_JOB"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_internal_wrong_api_key(client):
    response = client.post(
        "/internal/jobs",
        json={"job_type": "TEST_JOB"},
        headers={"X-Internal-API-Key": "not-the-key"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
