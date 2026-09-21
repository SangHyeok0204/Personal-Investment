"""증권사 API 키의 **서버측** 보관소.

★2026-09-21 사용자 요청: 화면에서 appkey/secretkey 를 입력하면 바로 연동되게.

그래서 키가 브라우저 → 서버로 한 번 흐른다. 대신 반대 방향은 **절대 막는다**:
  · 어떤 응답에도 키를 싣지 않는다(지문과 마지막 4자리만).
  · 디스크에는 `.env` 에 0600 으로 쓴다.
  · 검증에 실패한 키는 저장하지 않는다 — 틀린 키를 넣어 두면 그 뒤 모든 동기화가
    조용히 실패하고, 사용자는 "왜 안 되지"만 남는다.

⚠️이 설계는 **localhost 단독 사용**을 전제한다. 이 API 를 네트워크에 노출할 거라면
  그 전에 인증을 붙여야 한다 — 지금은 키 등록 엔드포인트에 인증이 없다.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

# 저장소 루트의 .env. 컨테이너/로컬 어디서 돌든 같은 파일을 보게 경로를 고정한다.
ENV_PATH = Path(
    os.environ.get("KIWOOM_ENV_FILE")
    or Path(__file__).resolve().parents[4] / ".env"
)

MANAGED_KEYS = (
    "KIWOOM_APP_KEY",
    "KIWOOM_SECRET_KEY",
    "KIWOOM_ENVIRONMENT",
    "KIWOOM_MARKETS",
    "KIWOOM_API_BASE_URL",
)


def _read_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def read_settings() -> dict:
    """현재 설정. **키 자체는 돌려주지 않는다.**"""
    # 파일이 우선이지만, 컨테이너처럼 환경변수만 주입되는 경우도 받는다.
    file_values = _read_env_file()

    def pick(name: str) -> str:
        return (file_values.get(name) or os.environ.get(name) or "").strip()

    app_key = pick("KIWOOM_APP_KEY")
    secret_key = pick("KIWOOM_SECRET_KEY")
    environment = pick("KIWOOM_ENVIRONMENT") or "REAL"
    markets = pick("KIWOOM_MARKETS") or "KR,US"
    return {
        "configured": bool(app_key and secret_key),
        "environment": environment.upper(),
        "markets": [m.strip().upper() for m in markets.split(",") if m.strip()],
        # 지문은 되돌릴 수 없고, 꼬리 4자리는 "내가 넣은 그 키가 맞나"를 눈으로
        # 확인하는 용도다. 둘 다 키를 복원하지 못한다.
        "fingerprint": _fingerprint(app_key) if app_key else None,
        "app_key_tail": app_key[-4:] if len(app_key) >= 4 else None,
    }


def _fingerprint(app_key: str) -> str:
    return hashlib.sha256(app_key.encode()).hexdigest()[:16]


def credentials() -> tuple[str, str, str, list[str]]:
    """실제 키. **서버 내부에서만** 부른다(응답에 싣지 말 것)."""
    file_values = _read_env_file()

    def pick(name: str) -> str:
        return (file_values.get(name) or os.environ.get(name) or "").strip()

    markets = pick("KIWOOM_MARKETS") or "KR,US"
    return (
        pick("KIWOOM_APP_KEY"),
        pick("KIWOOM_SECRET_KEY"),
        (pick("KIWOOM_ENVIRONMENT") or "REAL").upper(),
        [m.strip().upper() for m in markets.split(",") if m.strip()],
    )


def save(app_key: str, secret_key: str, environment: str, markets: list[str]) -> None:
    """`.env` 의 KIWOOM_* 만 갈아끼운다. 다른 줄은 순서까지 그대로 둔다.

    임시파일에 쓰고 원자적으로 바꾼다 — 쓰는 도중 죽어도 .env 가 반쯤 남지 않는다.
    """
    updates = {
        "KIWOOM_APP_KEY": app_key,
        "KIWOOM_SECRET_KEY": secret_key,
        "KIWOOM_ENVIRONMENT": environment.upper(),
        "KIWOOM_MARKETS": ",".join(markets) if markets else "KR,US",
    }

    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        name = match.group(1) if match else None
        if name in updates:
            out.append(f"{name}={updates[name]}")
            seen.add(name)
        else:
            out.append(line)
    for name, value in updates.items():
        if name not in seen:
            out.append(f"{name}={value}")

    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(ENV_PATH.parent), prefix=".env.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(out) + "\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, ENV_PATH)
    except BaseException:
        os.unlink(tmp_path)
        raise

    # 같은 프로세스가 이어서 쓸 수 있게 환경변수도 맞춰 둔다.
    for name, value in updates.items():
        os.environ[name] = value


def load_into_environ() -> bool:
    """`.env` 의 KIWOOM_* 를 현재 프로세스 환경변수로 올린다.

    worker 핸들러와 EnvCredentialResolver 는 `os.environ` 을 본다. API 프로세스는
    `.env` 파일을 읽을 뿐 환경변수로 갖고 있지 않으므로, 핸들러를 부르기 전에
    한 번 올려 줘야 한다. (이미 환경변수가 있으면 **덮지 않는다** — 컨테이너에서
    주입한 값이 파일보다 우선이어야 배포가 예측 가능하다.)

    돌려주는 값: 키가 준비됐는지 여부.
    """
    file_values = _read_env_file()
    for name in MANAGED_KEYS:
        value = file_values.get(name)
        if value and not os.environ.get(name):
            os.environ[name] = value
    return bool(os.environ.get("KIWOOM_APP_KEY") and os.environ.get("KIWOOM_SECRET_KEY"))
