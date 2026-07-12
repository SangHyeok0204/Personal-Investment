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
    # Presence-only in the api service (it never calls Kiwoom); used to surface
    # credentials_configured to the UI.
    KIWOOM_APP_KEY: str = ""
    KIWOOM_SECRET_KEY: str = ""


settings = Settings()
