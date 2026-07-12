def test_health_ok(client):
    response = client.get("/system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
