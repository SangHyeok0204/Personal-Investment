"""Access-token acquisition with a process-wide cache.

Token lifecycle per kiwoom-api-reference.md §2 + contract-kiwoom.md §4:
- POST {base}/oauth2/token, body grant_type=client_credentials/appkey/secretkey.
- Response carries expires_dt "YYYYMMDDHHMMSS" in KST (absolute, NOT seconds).
- Cache the token module-level; reuse while >60s remains; re-issuing on every
  call trips the rate limiter, so DON'T. The token is NEVER logged/persisted;
  only issued_at/expires_at leave this module (for token-metadata.json).
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

_lock = threading.Lock()
_cache = {"token": None, "expires_at": None, "issued_at": None}


def reset_token_cache():
    """Clear the cached token (used by tests and on key changes)."""
    with _lock:
        _cache["token"] = None
        _cache["expires_at"] = None
        _cache["issued_at"] = None


def get_token_metadata():
    """Return {'issued_at', 'expires_at'} ISO strings, or None values if unset.

    NEVER returns the token itself — safe to persist to token-metadata.json.
    """
    with _lock:
        issued_at = _cache["issued_at"]
        expires_at = _cache["expires_at"]
    return {
        "issued_at": issued_at.isoformat() if issued_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def _parse_expires_dt(expires_dt, now):
    if not expires_dt:
        return now + _FALLBACK_TTL
    try:
        return datetime.strptime(expires_dt, "%Y%m%d%H%M%S").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return now + _FALLBACK_TTL


def get_access_token(http_client, base_url, app_key, secret_key, now=None):
    """Return a valid access token, issuing a new one only when needed.

    http_client is an httpx.Client-like object (has .post(url, headers, json)
    -> response with .status_code/.json()/.raise_for_status()). Injecting it
    keeps the network boundary mockable in tests.
    """
    now = now or datetime.now(KST)
    with _lock:
        token = _cache["token"]
        expires_at = _cache["expires_at"]
        if (
            token
            and expires_at
            and (expires_at - now).total_seconds() > REFRESH_MARGIN_SECONDS
        ):
            return token

        url = base_url.rstrip("/") + TOKEN_ENDPOINT
        response = http_client.post(
            url,
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={
                "grant_type": "client_credentials",
                "appkey": app_key,
                "secretkey": secret_key,
            },
        )
        response.raise_for_status()
        parsed = TokenResponse(**response.json())

        if parsed.return_code not in (None, 0):
            raise KiwoomAuthError(
                parsed.return_msg or f"token request failed (return_code={parsed.return_code})"
            )
        if not parsed.token:
            raise KiwoomAuthError("token request returned no token")

        _cache["token"] = parsed.token
        _cache["issued_at"] = now
        _cache["expires_at"] = _parse_expires_dt(parsed.expires_dt, now)
        return parsed.token
