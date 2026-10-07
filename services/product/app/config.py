from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    SERVICE_NAME: str = "product"
    LOG_LEVEL: str = "INFO"

    # DATABASE_URL overrides the POSTGRES_* parts (used by tests with SQLite).
    DATABASE_URL: str | None = None
    POSTGRES_USER: str = "opspilot"
    POSTGRES_PASSWORD: str = "opspilot"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    DB_NAME: str = "product_db"

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg://{quote_plus(self.POSTGRES_USER)}:{quote_plus(self.POSTGRES_PASSWORD)}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.DB_NAME}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
