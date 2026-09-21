"""여러 사람/계좌를 한 프로세스에서 섞이지 않게 다루는가.

이 파일이 지키는 주장은 하나다 — **키움 API 키만 바꾸면 그 사람의 계좌가 조회된다.**
그게 성립하려면 다음이 참이어야 하고, 하나라도 깨지면 "남의 잔고가 내 화면에 뜨는"
형태로 드러난다(게다가 조용히 성공한다).

  1. 토큰 캐시가 자격증명별로 갈린다.
  2. 어댑터는 전역 환경변수를 보지 않는다 — 받은 자격증명만 쓴다.
  3. 시크릿이 repr/로그/메타데이터로 새지 않는다.
  4. 리졸버가 연결 이름별 키를 우선하고, 없으면 공용 키로 떨어진다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from brokers.base import BrokerAdapter
from brokers.credentials import (
    BrokerCredentials,
    EnvCredentialResolver,
    StaticCredentialResolver,
)
from brokers.kiwoom.auth import TokenStore
from brokers.kiwoom.exceptions import KiwoomConfigError
from brokers.registry import get_adapter_class, supported_brokers


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _RecordingHttp:
    """토큰 발급 요청을 기록하는 가짜 클라이언트."""

    def __init__(self):
        self.posts = []

    def post(self, url, headers=None, json=None, **kw):
        self.posts.append({"url": url, "json": json})
        # 앱키별로 다른 토큰을 돌려준다 — 섞이면 테스트가 잡아낸다.
        return _Resp({"token": f"tok-{json['appkey']}", "expires_dt": "20991231235959",
                      "token_type": "bearer", "return_code": 0})


def _creds(app_key, secret="s3cret", label=""):
    return BrokerCredentials(
        broker_code="KIWOOM", app_key=app_key, secret_key=secret, label=label
    )


# ── 1. 토큰 캐시 격리 ────────────────────────────────────────────────────────

def test_token_cache_is_isolated_per_credentials():
    """사람이 둘이면 토큰도 둘이어야 한다. 전역 단일 캐시면 뒤가 앞을 덮어쓴다."""
    store = TokenStore()
    http = _RecordingHttp()
    alice = _creds("alice-key")
    bob = _creds("bob-key")

    assert store.get(http, alice) == "tok-alice-key"
    assert store.get(http, bob) == "tok-bob-key"
    # 다시 불러도 각자 자기 토큰이고, 재발급이 일어나지 않는다.
    assert store.get(http, alice) == "tok-alice-key"
    assert store.get(http, bob) == "tok-bob-key"
    assert len(http.posts) == 2, "자격증명당 한 번씩만 발급되어야 한다"


def test_token_cache_reset_targets_one_credential():
    store = TokenStore()
    http = _RecordingHttp()
    alice, bob = _creds("alice-key"), _creds("bob-key")
    store.get(http, alice)
    store.get(http, bob)

    store.reset(alice.fingerprint)
    store.get(http, alice)  # alice 만 재발급
    store.get(http, bob)    # bob 은 캐시 사용
    assert len(http.posts) == 3


def test_same_key_different_environment_does_not_share_token():
    """실전/모의는 호스트가 다르다 — 같은 앱키라도 토큰을 공유하면 안 된다."""
    store = TokenStore()
    http = _RecordingHttp()
    real = BrokerCredentials(broker_code="KIWOOM", app_key="k", secret_key="s")
    paper = BrokerCredentials(
        broker_code="KIWOOM", app_key="k", secret_key="s", environment="PAPER"
    )
    assert real.base_url != paper.base_url
    assert real.fingerprint != paper.fingerprint
    store.get(http, real)
    store.get(http, paper)
    assert len(http.posts) == 2


# ── 2. 어댑터가 전역 상태를 보지 않는가 ──────────────────────────────────────

def test_adapter_uses_injected_credentials_not_environment(monkeypatch):
    """환경변수에 엉뚱한 키가 있어도 어댑터는 주입받은 자격증명만 쓴다."""
    monkeypatch.setenv("KIWOOM_APP_KEY", "environment-key-should-be-ignored")
    monkeypatch.setenv("KIWOOM_SECRET_KEY", "environment-secret")

    store = TokenStore()
    http = _RecordingHttp()
    adapter_cls = get_adapter_class("KIWOOM")
    adapter = adapter_cls(_creds("injected-key"), http_client=http, token_store=store)

    result = adapter.check_connection()
    assert result["ok"] is True
    assert http.posts[0]["json"]["appkey"] == "injected-key"


def test_registry_exposes_kiwoom_and_rejects_unknown():
    assert "KIWOOM" in supported_brokers()
    assert issubclass(get_adapter_class("kiwoom"), BrokerAdapter)
    with pytest.raises(LookupError):
        get_adapter_class("NOT_A_BROKER")


def test_check_connection_classifies_ip_block():
    """키움은 IP 미등록도 HTTP 200 + return_code=3 으로 내려준다.

    실측 메시지(2026-09-21): '인증에 실패했습니다[8050:IP가 등록되지 않았습니다...]'
    이걸 자격증명 오류로 오해하면 사용자가 멀쩡한 키를 계속 재발급하게 된다.
    """
    class _IpBlockedHttp:
        def post(self, url, headers=None, json=None, **kw):
            return _Resp({
                "return_code": 3,
                "return_msg": "인증에 실패했습니다[8050:IP가 등록되지 않았습니다. "
                              "키움 REST API 홈페이지 > API 사용신청 화면에서 IP를 등록해주세요.]",
            })

    adapter = get_adapter_class("KIWOOM")(
        _creds("k"), http_client=_IpBlockedHttp(), token_store=TokenStore()
    )
    result = adapter.check_connection()
    assert result["ok"] is False
    assert result["reason"] == "ip_not_allowed"
    assert "8050" in result["message"]


# ── 3. 시크릿이 새지 않는가 ─────────────────────────────────────────────────

def test_secrets_never_appear_in_repr_or_metadata():
    c = _creds("super-secret-app-key", secret="super-secret-value", label="주계좌")
    text = repr(c)
    assert "super-secret-app-key" not in text
    assert "super-secret-value" not in text

    redacted = c.redacted()
    assert "super-secret-app-key" not in str(redacted)
    assert "super-secret-value" not in str(redacted)
    assert redacted["credential_fingerprint"] == c.fingerprint


def test_token_metadata_excludes_the_token():
    store = TokenStore()
    c = _creds("k")
    store.get(_RecordingHttp(), c)
    meta = store.metadata(c.fingerprint)
    assert set(meta) == {"issued_at", "expires_at"}
    assert "tok-" not in str(meta)


def test_fingerprint_is_stable_and_does_not_reveal_the_key():
    c1, c2 = _creds("same-key"), _creds("same-key")
    assert c1.fingerprint == c2.fingerprint
    assert c1.fingerprint != _creds("other-key").fingerprint
    assert "same-key" not in c1.fingerprint


# ── 4. 리졸버 ───────────────────────────────────────────────────────────────

def test_resolver_prefers_connection_scoped_keys():
    """한 서버에서 두 사람을 돌릴 때 연결 이름으로 키를 가른다."""
    env = {
        "KIWOOM_APP_KEY": "shared-key",
        "KIWOOM_SECRET_KEY": "shared-secret",
        "KIWOOM__BOB__APP_KEY": "bob-key",
        "KIWOOM__BOB__SECRET_KEY": "bob-secret",
    }
    resolver = EnvCredentialResolver(environ=env)

    bob = resolver.resolve(broker_code="KIWOOM", connection={"connection_name": "bob"})
    assert bob.app_key == "bob-key"

    # 이름별 키가 없는 연결은 공용 키로 떨어진다 — 혼자 쓰는 동안 설정이 그대로다.
    other = resolver.resolve(broker_code="KIWOOM", connection={"connection_name": "주계좌"})
    assert other.app_key == "shared-key"


def test_resolver_reports_missing_keys_clearly():
    resolver = EnvCredentialResolver(environ={})
    with pytest.raises(KiwoomConfigError) as exc:
        resolver.resolve(broker_code="KIWOOM", connection={"connection_name": "main"})
    assert "not configured" in str(exc.value)


def test_static_resolver_returns_what_it_was_given():
    c = _creds("fixed")
    assert StaticCredentialResolver(c).resolve(broker_code="KIWOOM") is c


def test_environment_selects_paper_host():
    env = {
        "KIWOOM_APP_KEY": "k", "KIWOOM_SECRET_KEY": "s",
        "KIWOOM_ENVIRONMENT": "PAPER",
    }
    c = EnvCredentialResolver(environ=env).resolve(broker_code="KIWOOM")
    assert c.base_url == "https://mockapi.kiwoom.com"


# ── 5. 증권사 경계에서의 단위·필드 변환 ──────────────────────────────────────
# 실계좌 연동(2026-09-21) 직후 잡은 두 버그를 고정한다. 둘 다 예외가 안 나고
# **조용히 틀리는** 종류라, 테스트가 없으면 화면을 볼 때까지 모른다.

from decimal import Decimal  # noqa: E402

from brokers.kiwoom.broker import _to_position_row  # noqa: E402


def test_position_name_is_read_from_asset_name_key():
    """어댑터는 'asset_name' 으로 내보낸다. 'name' 으로 읽으면 종목명이 사라진다."""
    row = _to_position_row({
        "ticker": "005930", "asset_name": "삼성전자",
        "quantity": "1", "currency": "KRW",
    })
    assert row.name == "삼성전자"


def test_kiwoom_percent_return_is_converted_to_ratio():
    """키움 prft_rt 는 퍼센트(17.45 = 17.45%). 경계 안쪽은 비율로 통일한다.

    변환하지 않으면 화면에 1745% 로 뜬다 — 예외 없이 100배 틀린다.
    """
    row = _to_position_row({
        "ticker": "005930", "asset_name": "삼성전자",
        "quantity": "1", "currency": "KRW", "unrealized_return": "17.45",
    })
    assert row.unrealized_return == Decimal("0.1745")

    loss = _to_position_row({
        "ticker": "000660", "asset_name": "SK하이닉스",
        "quantity": "4", "currency": "KRW", "unrealized_return": "-14.71",
    })
    assert loss.unrealized_return == Decimal("-0.1471")


def test_missing_return_stays_none_not_zero():
    """수집이 안 된 수익률을 0 으로 바꾸면 '미수집'이 '본전'으로 보인다."""
    row = _to_position_row({"ticker": "005930", "quantity": "1", "currency": "KRW"})
    assert row.unrealized_return is None
