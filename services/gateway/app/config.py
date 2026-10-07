from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    SERVICE_NAME: str = "gateway"
    LOG_LEVEL: str = "INFO"

    SERVICE_URLS: str = ""
    APPROVAL_URL: str = "http://approval:8000"
    INTERNAL_SECRET: str

    REGISTRY_REFRESH_SECONDS: int = 60
    TOOL_TIMEOUT_SECONDS: float = 5.0
    TOOL_MAX_RESULT_CHARS: int = 4000
    RATE_LIMIT_READ_PER_MIN: int = 10
    RATE_LIMIT_WRITE_PER_MIN: int = 3
    RATE_LIMIT_STAFF_WRITE_PER_MIN: int = 30  # staff process many orders in a row
    AUDIT_LOG_PATH: str = "/data/audit.jsonl"

    @property
    def service_urls(self) -> list[str]:
        return [u.strip().rstrip("/") for u in self.SERVICE_URLS.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
