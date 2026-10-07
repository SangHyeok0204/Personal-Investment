"""연동/설정 시세 소스 상태 — 키는 내보내지 않고 '있는지'와 우선순위만(2026-10-04 '미등록' 고정 배지 버그)."""
from app.core import credentials_store, quote_cache


def test_price_sources_reflect_keys_and_session(client, monkeypatch):
    quote_cache.clear_cache()
    keys = {"TOSS_CLIENT_ID": "id-xyz", "TOSS_CLIENT_SECRET": "secret-xyz"}
    monkeypatch.setattr(credentials_store, "read_env_value", lambda name: keys.get(name))
    monkeypatch.setattr(quote_cache, "us_regular_session_open", lambda now=None: True)
    body = client.get("/api/v1/brokerage/price-sources").json()
    by = {s["id"]: s for s in body["sources"]}
    assert by["toss"] == {"id": "toss", "configured": True, "rank": 1,       # 정규장: 토스 먼저
                          "state": None, "message": None, "at": None}     # 아직 시세 경로가 안 불림
    assert by["yahoo"]["rank"] == 2
    assert "secret" not in str(body) and "id-xyz" not in str(body)          # 키 값은 나가지 않는다

    monkeypatch.setattr(quote_cache, "us_regular_session_open", lambda now=None: False)
    by = {s["id"]: s for s in client.get("/api/v1/brokerage/price-sources").json()["sources"]}
    assert by["toss"]["rank"] == 1 and by["yahoo"]["rank"] == 2             # ★2026-10-07 장외에도 토스 먼저

    keys.clear()
    by = {s["id"]: s for s in client.get("/api/v1/brokerage/price-sources").json()["sources"]}
    assert by["toss"] == {"id": "toss", "configured": False, "rank": None,
                          "state": None, "message": None, "at": None}
    assert by["yahoo"]["rank"] == 1
