from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Defaults mirror .env.example so the app and test collection work even when
    the environment is not fully populated.
    """

    model_config = SettingsConfigDict(extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://investment_user:change_me@postgres:5432/investment"
    STORAGE_DIR: str = "/app/storage"


settings = Settings()
