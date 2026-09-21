"""증권사 자격증명 — 어느 사람의 계좌인지를 정하는 유일한 지점.

★2026-09-21 설계 요구(사용자): "키움 API 키만 바꾸면 다른 사람 계좌로도 그대로
  돌아가야 한다." 그러려면 자격증명이 **값 객체**여야 한다. 전역 환경변수를 코드
  여기저기서 직접 읽으면, 두 사람의 계좌를 한 프로세스에서 다룰 수 없고 "지금 누구
  것을 조회 중인가"가 호출 스택 어디에도 안 남는다.

구성:
  BrokerCredentials   자격증명 값 객체. 시크릿은 절대 __repr__/로그에 나오지 않는다.
  CredentialResolver  연결(brokerage_connections 행) → 자격증명. 출처를 갈아끼운다.
  EnvCredentialResolver   환경변수에서. 연결 이름별 오버라이드를 지원한다.
  StaticCredentialResolver  테스트·스크립트용.

⚠️시크릿을 DB 에 넣지 않는다. 연결 행은 "어떤 연결이 있는가"만 들고, 실제 키는
  서버 환경(.env / 시크릿 매니저)에 둔다. 대시보드는 DB 만 읽으므로 키가 화면으로
  샐 경로 자체가 없다.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field

from .kiwoom.exceptions import KiwoomConfigError

DEFAULT_BASE_URLS = {
    ("KIWOOM", "REAL"): "https://api.kiwoom.com",
    ("KIWOOM", "PAPER"): "https://mockapi.kiwoom.com",
}


@dataclass(frozen=True)
class BrokerCredentials:
    """한 증권사 연결에 대한 자격증명.

    frozen 인 이유: 자격증명이 도중에 바뀌면 토큰 캐시 키와 실제 키가 어긋나
    "A 의 토큰으로 B 의 계좌를 조회"하는 사고가 난다. 바꾸려면 새 객체를 만든다.
    """

    broker_code: str
    app_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    base_url: str = ""
    environment: str = "REAL"
    # 사람이 알아볼 이름(로그용). 시크릿이 아니다.
    label: str = ""

    def __post_init__(self):
        if not self.app_key or not self.secret_key:
            raise KiwoomConfigError(
                f"{self.broker_code} credentials are not configured "
                f"(label={self.label or '-'}, environment={self.environment})"
            )
        if not self.base_url:
            base = DEFAULT_BASE_URLS.get((self.broker_code, self.environment))
            if not base:
                raise KiwoomConfigError(
                    f"unknown base_url for {self.broker_code}/{self.environment}"
                )
            object.__setattr__(self, "base_url", base)
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))

    @property
    def fingerprint(self) -> str:
        """자격증명을 **되돌릴 수 없게** 식별하는 짧은 지문.

        토큰 캐시 키와 로그에 쓴다. app_key 만 해싱해도 계좌 주인을 가르는 데는
        충분하고, 시크릿은 해시에도 넣지 않는다(해시 유출 시 대조공격 여지를 줄인다).
        """
        raw = f"{self.broker_code}|{self.environment}|{self.base_url}|{self.app_key}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def redacted(self) -> dict:
        """로그·잡 결과에 남겨도 되는 형태. 키 자체는 절대 넣지 않는다."""
        return {
            "broker_code": self.broker_code,
            "environment": self.environment,
            "base_url": self.base_url,
            "label": self.label,
            "credential_fingerprint": self.fingerprint,
        }


class CredentialResolver:
    """연결 → 자격증명. 출처(환경변수·시크릿매니저·파일)를 갈아끼우는 지점."""

    def resolve(self, *, broker_code: str, connection) -> BrokerCredentials:
        raise NotImplementedError


def _env_suffix(name: str) -> str:
    """연결 이름을 환경변수에 쓸 수 있는 형태로. '주 계좌' → 'MAIN' 이 아니라
    'KIWOOM__주_계좌__APP_KEY' 는 쓰기 어려우므로 영숫자만 남기고 대문자화한다."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_").upper()


class EnvCredentialResolver(CredentialResolver):
    """환경변수에서 읽는다.

    조회 순서(먼저 찾은 것을 쓴다):
      1. `{BROKER}__{연결이름}__APP_KEY` / `__SECRET_KEY`  ← 사람별/연결별 분리
      2. `{BROKER}_APP_KEY` / `{BROKER}_SECRET_KEY`        ← 단일 사용자 기본값

    1번이 있는 이유: 한 서버에서 여러 계좌(또는 여러 사람)를 돌릴 때, 연결마다
    다른 키를 주려면 이름으로 갈라야 한다. 없으면 2번으로 조용히 떨어지므로
    혼자 쓰는 동안에는 `.env` 에 KIWOOM_APP_KEY 하나만 있으면 된다.
    """

    def __init__(self, environ=None):
        self._environ = environ if environ is not None else os.environ

    def _get(self, *names: str) -> str:
        for n in names:
            v = (self._environ.get(n) or "").strip()
            if v:
                return v
        return ""

    def resolve(self, *, broker_code: str, connection=None) -> BrokerCredentials:
        broker = broker_code.upper()
        label = (connection or {}).get("connection_name", "") if connection else ""
        suffix = _env_suffix(label)
        scoped = f"{broker}__{suffix}__" if suffix else None

        app_key = self._get(*(([f"{scoped}APP_KEY"] if scoped else []) + [f"{broker}_APP_KEY"]))
        secret_key = self._get(
            *(([f"{scoped}SECRET_KEY"] if scoped else []) + [f"{broker}_SECRET_KEY"])
        )
        environment = (
            self._get(*(([f"{scoped}ENVIRONMENT"] if scoped else []) + [f"{broker}_ENVIRONMENT"]))
            or (connection or {}).get("environment")
            or "REAL"
        ).upper()
        base_url = self._get(
            *(([f"{scoped}API_BASE_URL"] if scoped else []) + [f"{broker}_API_BASE_URL"])
        )

        if not app_key or not secret_key:
            # ⚠️메시지는 영문으로 둔다 — 저장소의 다른 예외 메시지와 같은 관례이고,
            #   기존 테스트가 "not configured" 문구를 계약으로 잡고 있다.
            hint = f"{broker}_APP_KEY/{broker}_SECRET_KEY"
            if scoped:
                hint = f"{scoped}APP_KEY/{scoped}SECRET_KEY (or {hint})"
            raise KiwoomConfigError(f"{hint} is not configured")

        return BrokerCredentials(
            broker_code=broker,
            app_key=app_key,
            secret_key=secret_key,
            base_url=base_url,
            environment=environment,
            label=label,
        )


class StaticCredentialResolver(CredentialResolver):
    """미리 만든 자격증명을 그대로 돌려준다(테스트·일회성 스크립트용)."""

    def __init__(self, credentials: BrokerCredentials):
        self._credentials = credentials

    def resolve(self, *, broker_code: str, connection=None) -> BrokerCredentials:
        return self._credentials
