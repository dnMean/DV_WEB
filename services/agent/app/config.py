from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    SERVICE_NAME: str = "agent"
    LOG_LEVEL: str = "INFO"

    INTERNAL_SECRET: str
    GATEWAY_URL: str = "http://gateway:8000"
    AUTH_URL: str = "http://auth:8000"
    TOOL_TIMEOUT_SECONDS: float = 5.0

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_RETRIES: int = 2
    LLM_BACKOFF_SECONDS: float = 1.0

    AGENT_MAX_STEPS: int = 6
    AGENT_MAX_TOKENS: int = 12000
    AGENT_MAX_SAME_CALL: int = 2
    HISTORY_MAX_MESSAGES: int = 20

    GUARD_INPUT_RULES: bool = True
    GUARD_INPUT_LLM: bool = False
    GUARD_TOOL_OUTPUT: bool = True
    GUARD_OUTPUT_PII: bool = True

    # DATABASE_URL overrides the POSTGRES_* parts (used by tests with SQLite).
    DATABASE_URL: str | None = None
    POSTGRES_USER: str = "opspilot"
    POSTGRES_PASSWORD: str = "opspilot"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    DB_NAME: str = "agent_db"

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
