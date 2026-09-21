"""Thin httpx wrapper for Kiwoom TR calls (auth, throttle, retry, paging).

All TRs are POST + JSON body; the TR is selected by the api-id header, not the
URL (reference §3.2). Headers are lowercase/hyphen (reference §3.1/§6.3). Paging
follows cont-yn/next-key, read defensively from BOTH response header and body
because the reference could not confirm which one Kiwoom uses (§3.3 [TV]).
"""
import time

import httpx

from . import auth
from .exceptions import KiwoomApiError, KiwoomRateLimitError

ACNT_PATH = "/api/dostk/acnt"  # 국내 계좌계 공통 경로 (reference §4.1)

_CONTENT_TYPE = "application/json;charset=UTF-8"
_MIN_INTERVAL_SECONDS = 0.25  # >=250ms between TR calls (contract §4)
_BACKOFF_SECONDS = (1, 2, 4)  # retry x3 on 429/return_code=5 (contract §4)
_RATE_LIMIT_RETURN_CODE = 5  # reference §3.4 [TV]
_MAX_PAGES = 50  # safety cap for the paging loop


def _coerce_return_code(value):
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


class KiwoomClient:
    def __init__(self, base_url, app_key, secret_key, http_client=None, sleep=time.sleep):
        self._base_url = base_url.rstrip("/")
        self._app_key = app_key
        self._secret_key = secret_key
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.Client(timeout=30.0)
        self._sleep = sleep
        self._last_call_at = None

    def close(self):
        if self._owns_http:
            self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _token(self):
        return auth.get_access_token(
            self._http, self._base_url, self._app_key, self._secret_key
        )

    def ensure_token(self):
        """Acquire/refresh the token up-front so the request step is explicit."""
        return self._token()

    def _throttle(self):
        if self._last_call_at is not None:
            elapsed = time.monotonic() - self._last_call_at
            if elapsed < _MIN_INTERVAL_SECONDS:
                self._sleep(_MIN_INTERVAL_SECONDS - elapsed)
        self._last_call_at = time.monotonic()

    @staticmethod
    def _extract_paging(response, body):
        headers = response.headers
        cont = (
            headers.get("cont-yn")
            or body.get("cont-yn")
            or body.get("cont_yn")
            or "N"
        )
        next_key = (
            headers.get("next-key")
            or body.get("next-key")
            or body.get("next_key")
            or ""
        )
        return str(cont).strip().upper(), str(next_key).strip()

    def _single_call(self, path, api_id, body, cont_yn, next_key):
        url = self._base_url + path
        headers = {
            "authorization": f"Bearer {self._token()}",
            "api-id": api_id,
            "cont-yn": cont_yn,
            "next-key": next_key,
            "Content-Type": _CONTENT_TYPE,
        }
        attempt = 0
        while True:
            self._throttle()
            response = self._http.post(url, headers=headers, json=body)

            if response.status_code == 429:
                if attempt < len(_BACKOFF_SECONDS):
                    self._sleep(_BACKOFF_SECONDS[attempt])
                    attempt += 1
                    continue
                raise KiwoomRateLimitError(429, "rate limit (HTTP 429) retries exhausted")

            response.raise_for_status()
            data = response.json()
            return_code = _coerce_return_code(data.get("return_code"))

            if return_code == _RATE_LIMIT_RETURN_CODE:
                if attempt < len(_BACKOFF_SECONDS):
                    self._sleep(_BACKOFF_SECONDS[attempt])
                    attempt += 1
                    continue
                raise KiwoomRateLimitError(return_code, data.get("return_msg"))

            if return_code != 0:
                raise KiwoomApiError(return_code, data.get("return_msg"))

            cont, key = self._extract_paging(response, data)
            return data, cont, key

    def request_tr(self, api_id, body, path=ACNT_PATH):
        """Call a TR, following cont-yn/next-key paging. Returns list of pages."""
        pages = []
        cont_yn = "N"
        next_key = ""
        for _ in range(_MAX_PAGES):
            data, cont, key = self._single_call(path, api_id, body, cont_yn, next_key)
            pages.append(data)
            if cont == "Y" and key:
                cont_yn = "Y"
                next_key = key
            else:
                break
        return pages
