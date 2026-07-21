from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Defaults mirror .env.example so the app and test collection work even when
    the environment is not fully populated.
    """

    model_config = SettingsConfigDict(extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://investment_user:change_me@postgres:5432/investment"
    STORAGE_DIR: str = "/app/storage"

    # Internal API auth shared with the worker/n8n; guards the /internal router.
    INTERNAL_API_KEY: str = "change_me_internal"

    # Upstream AI usage monitor (Claude/Codex account meters) that /api/v1/ai-token-usage proxies.
    AI_USAGE_MONITOR_BASE_URL: str = "http://192.168.199.120:8002"

    # Upstream ETF iNAV collector (profile service) that /api/v1/inav/snapshot proxies.
    COLLECTOR_URL: str = "http://collector:8100"

    # 종토방 read-replica: push 신선도(staleness) 판정 + keyword 렌더 상한.
    # 임계 = SD_PUSH_INTERVAL_HINT * SD_STALE_FACTOR (단일 파생, D11).
    SD_PUSH_INTERVAL_HINT: int = 60
    SD_STALE_FACTOR: int = 3
    SD_KEYWORD_RENDER_MAX: int = 500


settings = Settings()
