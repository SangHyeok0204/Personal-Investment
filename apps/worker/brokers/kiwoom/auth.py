"""접근토큰 발급 — 자격증명별로 분리된 캐시.

Token lifecycle per kiwoom-api-reference.md §2 + contract-kiwoom.md §4:
- POST {base}/oauth2/token, body grant_type=client_credentials/appkey/secretkey.
- Response carries expires_dt "YYYYMMDDHHMMSS" in KST (absolute, NOT seconds).
- 토큰은 재사용한다. 호출마다 재발급하면 유량제한에 걸린다.
- 토큰 자체는 절대 로그·디스크로 나가지 않는다. issued_at/expires_at 만 나간다.

★2026-09-21 재설계: 캐시가 **프로세스 전역 단일 슬롯**이었다. 계좌(사람)가 둘이면
  뒤에 발급한 토큰이 앞의 것을 덮어써서, A 의 토큰으로 B 의 계좌를 조회하는 사고가
  난다 — 게다가 조용히 성공한다(키움은 토큰 소유자의 계좌를 돌려주므로 "남의 잔고가
  내 화면에 뜨는" 형태로 드러난다). 캐시를 자격증명 지문으로 가른다.
"""
import threading
from datetime import datetime, timedelta, timezone

from .exceptions import KiwoomAuthError
from .schemas.auth import TokenResponse

KST = timezone(timedelta(hours=9))
TOKEN_ENDPOINT = "/oauth2/token"
REFRESH_MARGIN_SECONDS = 60
# Fallback TTL when expires_dt is absent/unparseable. Community convention is
# ~24h; we stay conservative. TO-VERIFY(공식 TTL 미확인, reference §2.2).
_FALLBACK_TTL = timedelta(hours=23)


def _parse_expires_dt(expires_dt, now):
    if not expires_dt:
        return now + _FALLBACK_TTL
    try:
        return datetime.strptime(expires_dt, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return now + _FALLBACK_TTL


class TokenStore:
    """자격증명 지문 → 토큰. 인스턴스 하나가 여러 사람의 토큰을 섞이지 않게 들고 있다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}  # fingerprint -> {token, issued_at, expires_at}

    def reset(self, fingerprint=None):
        """캐시를 비운다. 지문을 주면 그 자격증명만, 없으면 전부."""
        with self._lock:
            if fingerprint is None:
                self._entries.clear()
            else:
                self._entries.pop(fingerprint, None)

    def metadata(self, fingerprint):
        """{'issued_at','expires_at'} ISO 문자열. **토큰 자체는 돌려주지 않는다** —
        token-metadata.json 에 그대로 써도 안전하다."""
        with self._lock:
            entry = self._entries.get(fingerprint)
        if not entry:
            return {"issued_at": None, "expires_at": None}
        return {
            "issued_at": entry["issued_at"].isoformat() if entry["issued_at"] else None,
            "expires_at": entry["expires_at"].isoformat() if entry["expires_at"] else None,
        }

    def get(self, http_client, credentials, now=None):
        """유효한 토큰을 돌려준다. 필요할 때만 새로 발급한다.

        http_client 는 httpx.Client 유사 객체(.post(url, headers, json)). 주입해 두면
        네트워크 경계를 테스트에서 그대로 막을 수 있다.
        """
        now = now or datetime.now(KST)
        key = credentials.fingerprint

        with self._lock:
            entry = self._entries.get(key)
            if (
                entry
                and entry["token"]
                and (entry["expires_at"] - now).total_seconds() > REFRESH_MARGIN_SECONDS
            ):
                return entry["token"]

            response = http_client.post(
                credentials.base_url + TOKEN_ENDPOINT,
                headers={"Content-Type": "application/json;charset=UTF-8"},
                json={
                    "grant_type": "client_credentials",
                    "appkey": credentials.app_key,
                    "secretkey": credentials.secret_key,
                },
            )
            response.raise_for_status()
            parsed = TokenResponse(**response.json())

            if parsed.return_code not in (None, 0):
                raise KiwoomAuthError(
                    parsed.return_msg
                    or f"token request failed (return_code={parsed.return_code})"
                )
            if not parsed.token:
                raise KiwoomAuthError("token request returned no token")

            self._entries[key] = {
                "token": parsed.token,
                "issued_at": now,
                "expires_at": _parse_expires_dt(parsed.expires_dt, now),
            }
            return parsed.token


# 프로세스 기본 저장소. 워커는 이걸 쓰고, 테스트는 자기 인스턴스를 만들어 격리한다.
default_store = TokenStore()


# ── 하위 호환 (기존 호출부·테스트가 쓰던 모듈 함수) ───────────────────────────
# 새 코드는 TokenStore 를 직접 쓴다. 이 함수들은 자격증명 객체 없이 호출하던
# 자리를 위해 남겨 두고, 내부적으로는 같은 지문 기반 캐시를 탄다.

def reset_token_cache(fingerprint=None):
    default_store.reset(fingerprint)


def get_token_metadata(fingerprint=None):
    if fingerprint is None:
        # 지문을 모르면 **하나뿐일 때만** 의미가 있다. 여럿이면 빈 값을 준다 —
        # 아무거나 골라 주면 "누구 토큰인지 모르는 메타데이터"가 남는다.
        with default_store._lock:  # noqa: SLF001 - 같은 모듈 내 협력 객체
            keys = list(default_store._entries)
        if len(keys) != 1:
            return {"issued_at": None, "expires_at": None}
        fingerprint = keys[0]
    return default_store.metadata(fingerprint)


def get_access_token(http_client, base_url, app_key, secret_key, now=None):
    """구 시그니처. 내부에서 자격증명 객체를 만들어 지문 캐시를 탄다."""
    from ..credentials import BrokerCredentials

    credentials = BrokerCredentials(
        broker_code="KIWOOM",
        app_key=app_key,
        secret_key=secret_key,
        base_url=base_url,
    )
    return default_store.get(http_client, credentials, now=now)
