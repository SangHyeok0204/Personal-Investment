from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from urllib3.exceptions import InsecureRequestWarning


PROD_REST_BASE = "https://openapi.koreainvestment.com:9443"
PROD_WS_URL = "ws://ops.koreainvestment.com:21000"
VPS_REST_BASE = "https://openapivts.koreainvestment.com:29443"
VPS_WS_URL = "ws://ops.koreainvestment.com:31000"

BASE_DIR = Path(__file__).resolve().parent.parent
NEW_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE_DIR = NEW_ROOT / "data" / "ETF_iNAV모니터" / "cache"
VAULT_ENV = NEW_ROOT / "data" / "_비밀값(중요)" / ".env"


def _vault_get(key: str) -> str:
    # 비밀값을 중앙 vault(평문, ETF_INAV_MONITOR__ 네임스페이스)에서 읽는다.
    # 이전 Fernet 암호문 스킴은 2026-06-25 중앙 vault 통합으로 폐기됨.
    return os.environ.get(f"ETF_INAV_MONITOR__{key}", "") or os.environ.get(key, "")


@dataclass
class KisCredentials:
    app_key: str
    app_secret: str
    rest_base: str = PROD_REST_BASE
    ws_url: str = PROD_WS_URL

    @classmethod
    def from_env(cls, paper: bool = False) -> "KisCredentials":
        load_dotenv(VAULT_ENV)
        app_key = _vault_get("KIS_APP_KEY")
        app_secret = _vault_get("KIS_APP_SECRET")
        if not app_key or not app_secret:
            raise RuntimeError(
                "ETF_INAV_MONITOR__KIS_APP_KEY/__KIS_APP_SECRET이 중앙 vault"
                f"({VAULT_ENV})에 없습니다."
            )
        if paper:
            return cls(app_key, app_secret, VPS_REST_BASE, VPS_WS_URL)
        return cls(app_key, app_secret, PROD_REST_BASE, PROD_WS_URL)


class KisAuth:
    def __init__(
        self,
        credentials: KisCredentials,
        cache_dir: Path | None = None,
        timeout: int = 10,
        verify_ssl: bool = False,
    ):
        self.credentials = credentials
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        if not verify_ssl:
            urllib3.disable_warnings(InsecureRequestWarning)

    def _token_cache_path(self) -> Path:
        return self.cache_dir / f"token_{datetime.now().strftime('%Y%m%d')}.json"

    def access_token(self, refresh: bool = False) -> str:
        cache_path = self._token_cache_path()
        if not refresh and cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data.get("expires_at", 0) > time.time() + 60:
                    return data["access_token"]
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        url = f"{self.credentials.rest_base}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.credentials.app_key,
            "appsecret": self.credentials.app_secret,
        }
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers={"content-type": "application/json"},
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        cache_path.write_text(
            json.dumps(
                {
                    "access_token": token,
                    "expires_at": time.time() + expires_in - 300,
                }
            ),
            encoding="utf-8",
        )
        return token

    def approval_key(self) -> str:
        url = f"{self.credentials.rest_base}/oauth2/Approval"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.credentials.app_key,
            "secretkey": self.credentials.app_secret,
        }
        response = requests.post(
            url,
            data=json.dumps(payload),
            headers={"content-type": "application/json"},
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        return response.json()["approval_key"]

    def rest_headers(self, tr_id: str) -> dict:
        return {
            "content-type": "application/json; charset=UTF-8",
            "authorization": f"Bearer {self.access_token()}",
            "appkey": self.credentials.app_key,
            "appsecret": self.credentials.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }
