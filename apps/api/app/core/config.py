from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 이 파일 기준으로 저장소 뿌리를 찾는다 — CWD 에 기대면 안 된다.
# pytest 는 apps/api 에서, scripts/*.py 는 저장소 뿌리에서 돌기 때문이다.
_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Defaults mirror .env.example so the app and test collection work even when
    the environment is not fully populated.

    ⚠️`.env` 는 **docker compose 용**이다 — 거기 적힌 호스트는 `postgres`,
      컨테이너 안에서만 풀리는 이름이다. 지금 이 프로젝트는 uvicorn·next·postgres
      를 전부 호스트에서 직접 띄워 쓰므로, 그 파일을 읽으면 오히려 틀린다.
      그래서 호스트용 값은 **`.env.local`** 에 따로 둔다(git 에 올리지 않는다).

    ★왜 절대경로로 읽는가: `scripts/audit_seeds.py` 는 저장소 뿌리에서, pytest 는
      `apps/api` 에서 돈다. 상대경로로 두면 한쪽에서만 읽혀 "왜 여기선 되고
      저기선 안 되지"가 된다 — 실제로 그 함정에 두 번 빠졌다.

    환경변수가 `.env.local` 보다 우선한다(pydantic-settings 기본 순서). 한 번만
    다르게 쓰고 싶으면 `DATABASE_URL=... 명령` 으로 덮어쓰면 된다.
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=_REPO_ROOT / ".env.local",
        env_file_encoding="utf-8",
    )

    DATABASE_URL: str = "postgresql+psycopg://investment_user:change_me@postgres:5432/investment"
    STORAGE_DIR: str = "/app/storage"

    # 리서치 자료 폴더. 비어 있으면 리서치 화면이 **켜는 방법을 안내**한다.
    # ⚠️읽기 전용이다 — 이름·크기·수정시각만 본다. 내용은 열지 않는다.
    RESEARCH_DIR: str = ""

    # SEC 연락처 UA(계획 A3a) — 거장 검색(A7)이 EDGAR 회사 검색을 부를 때 쓴다. worker 와 같은 값.
    SEC_USER_AGENT: str = ""

    # Internal API auth shared with the worker/n8n; guards the /internal router.
    INTERNAL_API_KEY: str = "change_me_internal"

    # Upstream AI usage monitor (Claude/Codex account meters) that /api/v1/ai-token-usage proxies.
    AI_USAGE_MONITOR_BASE_URL: str = ""

    # Upstream ETF iNAV collector (profile service) that /api/v1/inav/snapshot proxies.
    COLLECTOR_URL: str = "http://collector:8100"

    # 종토방 read-replica: push 신선도(staleness) 판정 + keyword 렌더 상한.
    # 임계 = SD_PUSH_INTERVAL_HINT * SD_STALE_FACTOR (단일 파생, D11).
    SD_PUSH_INTERVAL_HINT: int = 60
    SD_STALE_FACTOR: int = 3
    SD_KEYWORD_RENDER_MAX: int = 500

    # AI Key Data — OpenRouter rankings-daily(토큰·tool_calling). 비어 있으면 호출하지 않고 "키 미설정".
    OPENROUTER_API_KEY: str = ""


settings = Settings()
