"""증권사 연동 API.

이 파일이 지키는 것은 **키가 새지 않는다**는 것 하나다. 화면에서 키를 입력받도록
만든 이상, 키가 응답으로 되돌아오거나 검증 없이 저장되는 일이 없어야 한다.
"""
import os

import pytest

from app.core import credentials_store


@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    """테스트 동안 .env 를 임시 파일로 바꾼다 — 진짜 .env 를 건드리지 않는다.

    ⚠️`monkeypatch.delenv(..., raising=False)` 로는 **되돌아오지 않는다.** 그 함수는
      실제로 지운 키만 복원 목록에 기록하므로, 원래 없던 키는 아무것도 기록하지
      않는다. 그런데 자격증명 저장 API 는 `load_into_environ()` 으로 `os.environ` 에
      KIWOOM_* 를 **진짜로 써 넣는다** — 즉 테스트가 끝나도 그 값이 프로세스에 남는다.

      실제로 이것 때문에 `KIWOOM_MARKETS=US` 가 남아, 뒤따라 도는 worker 테스트가
      국내장을 통째로 건너뛰었다(current_positions 5 → 3, KRW 예수금 행 소실).
      단독 실행에서는 통과하고 전체 실행에서만 깨져서 원인이 보이지 않았다.

      그래서 지우는 것으로 끝내지 않고 **들어왔다 나가는 값까지 직접 되돌린다.**
    """
    path = tmp_path / ".env"
    path.write_text("DATABASE_URL=postgresql://x\nKIWOOM_APP_KEY=\nKIWOOM_SECRET_KEY=\n")
    monkeypatch.setattr(credentials_store, "ENV_PATH", path)

    saved = {name: os.environ.pop(name, None) for name in credentials_store.MANAGED_KEYS}
    try:
        yield path
    finally:
        for name, value in saved.items():
            # 테스트 도중 생긴 값은 버리고, 원래 있던 값만 되돌린다.
            os.environ.pop(name, None)
            if value is not None:
                os.environ[name] = value


def test_status_never_returns_the_keys(client, env_file, monkeypatch):
    env_file.write_text(
        "KIWOOM_APP_KEY=super-secret-app-key-value\n"
        "KIWOOM_SECRET_KEY=super-secret-secret-value\n"
        "KIWOOM_ENVIRONMENT=REAL\nKIWOOM_MARKETS=US\n"
    )
    body = client.get("/api/v1/brokerage/credentials").json()

    assert body["configured"] is True
    text = str(body)
    assert "super-secret-app-key-value" not in text
    assert "super-secret-secret-value" not in text
    # 확인용으로는 꼬리 4자리와 지문만 나간다 — 둘 다 키를 복원하지 못한다.
    assert body["app_key_tail"] == "alue"
    assert len(body["fingerprint"]) == 16


def test_status_reports_not_configured_when_blank(client, env_file):
    body = client.get("/api/v1/brokerage/credentials").json()
    assert body["configured"] is False
    assert body["fingerprint"] is None


def test_rejected_credentials_are_not_saved(client, env_file, monkeypatch):
    """검증에 실패한 키는 저장하지 않는다.

    저장해 버리면 그 뒤 모든 동기화가 조용히 실패하고, 화면에는 "왜 안 되지"만 남는다.
    """
    from app.api import brokerage

    monkeypatch.setattr(
        brokerage, "_probe",
        lambda credentials, markets: (
            {"ok": False, "reason": "bad_credentials", "message": "검증 실패"}, []
        ),
    )
    response = client.post(
        "/api/v1/brokerage/credentials",
        json={
            "app_key": "wrong-key-0123456789",
            "secret_key": "wrong-secret-0123456789",
            "environment": "REAL",
            "markets": ["US"],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["reason"] == "bad_credentials"
    # 파일이 그대로여야 한다.
    assert "wrong-key-0123456789" not in env_file.read_text()


def test_accepted_credentials_are_saved_and_not_echoed(client, env_file, monkeypatch):
    from app.api import brokerage

    monkeypatch.setattr(
        brokerage, "_probe",
        lambda credentials, markets: (
            {"ok": True, "reason": None, "message": "토큰 발급 성공"},
            [
                brokerage.AccountPreview(
                    external_account_id="6210365810",
                    account_number_masked="6210****10",
                    account_name="위탁종합",
                    account_type="위탁종합",
                )
            ],
        ),
    )
    response = client.post(
        "/api/v1/brokerage/credentials",
        json={
            "app_key": "good-key-0123456789",
            "secret_key": "good-secret-0123456789",
            "environment": "REAL",
            "markets": ["US"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["connection_ok"] is True
    assert body["accounts"][0]["account_number_masked"] == "6210****10"
    # 응답에 키가 없어야 한다.
    assert "good-key-0123456789" not in str(body)
    assert "good-secret-0123456789" not in str(body)
    # 파일에는 저장돼야 한다.
    saved = env_file.read_text()
    assert "KIWOOM_APP_KEY=good-key-0123456789" in saved
    assert "KIWOOM_MARKETS=US" in saved


def test_save_preserves_unrelated_env_lines(env_file):
    env_file.write_text("DATABASE_URL=postgresql://keep-me\n# comment\nOTHER=1\n")
    credentials_store.save("k" * 20, "s" * 20, "REAL", ["US"])

    saved = env_file.read_text()
    assert "DATABASE_URL=postgresql://keep-me" in saved
    assert "# comment" in saved
    assert "OTHER=1" in saved
    assert "KIWOOM_APP_KEY=" + "k" * 20 in saved


def test_env_file_is_written_owner_only(env_file):
    import stat

    credentials_store.save("k" * 20, "s" * 20, "REAL", ["US"])
    mode = stat.S_IMODE(env_file.stat().st_mode)
    # 0600 — 같은 머신의 다른 사용자가 읽지 못하게 한다.
    assert mode == 0o600


def test_sync_requires_configuration(client, env_file):
    response = client.post("/api/v1/brokerage/sync")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_CONFIGURED"
