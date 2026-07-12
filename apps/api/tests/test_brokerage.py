import uuid


def test_list_connections_seeded(client, seeded):
    response = client.get("/api/v1/brokerage-connections")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(seeded["connection_id"])
    assert item["broker_code"] == "KIWOOM"
    assert item["connection_name"] == "키움 기본 연결"
    assert item["environment"] == "REAL"
    assert item["status"] == "CONFIGURED"
    # Keys are pinned empty by the autouse fixture, so this never depends on
    # whether the developer's environment happens to have them configured.
    assert item["credentials_configured"] is False


def test_credentials_configured_when_keys_present(client, seeded, kiwoom_keys_set):
    response = client.get("/api/v1/brokerage-connections")
    assert response.status_code == 200
    assert response.json()["items"][0]["credentials_configured"] is True


def test_list_connections_empty(client):
    response = client.get("/api/v1/brokerage-connections")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_get_connection(client, seeded):
    connection_id = str(seeded["connection_id"])
    response = client.get(f"/api/v1/brokerage-connections/{connection_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == connection_id
    assert body["broker_code"] == "KIWOOM"
    assert body["credentials_configured"] is False


def test_get_connection_not_found(client):
    response = client.get(f"/api/v1/brokerage-connections/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONNECTION_NOT_FOUND"


def test_get_connection_malformed_uuid(client):
    response = client.get("/api/v1/brokerage-connections/not-a-uuid")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_sync_create_then_reuse(client, seeded):
    connection_id = str(seeded["connection_id"])

    created = client.post(f"/api/v1/brokerage-connections/{connection_id}/sync")
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "PENDING"
    assert body["reused"] is False
    job_id = body["job_id"]

    reused = client.post(f"/api/v1/brokerage-connections/{connection_id}/sync")
    assert reused.status_code == 200
    reused_body = reused.json()
    assert reused_body["reused"] is True
    assert reused_body["job_id"] == job_id


def test_sync_connection_not_found(client):
    response = client.post(f"/api/v1/brokerage-connections/{uuid.uuid4()}/sync")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONNECTION_NOT_FOUND"
