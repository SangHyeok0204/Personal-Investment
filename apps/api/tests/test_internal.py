def test_internal_create_job(client):
    response = client.post(
        "/internal/jobs",
        json={"job_type": "TEST_JOB", "payload": {"source": "n8n"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "TEST_JOB"
    assert body["status"] == "PENDING"
    assert body["payload"] == {"source": "n8n"}


def test_internal_create_job_without_payload(client):
    response = client.post("/internal/jobs", json={"job_type": "TEST_JOB"})
    assert response.status_code == 201
    assert response.json()["payload"] is None


def test_internal_create_job_empty_type(client):
    response = client.post("/internal/jobs", json={"job_type": "", "payload": {}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_internal_create_job_missing_type(client):
    response = client.post("/internal/jobs", json={"payload": {}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
