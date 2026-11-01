"""Environment-based application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+psycopg://nifty:change-me@localhost:5432/nifty_backtester"
    redis_url: str = "redis://localhost:6379/0"
    data_root: Path = Path("./data")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Provider credentials. Backend only: never serialised into an API response.
    dhan_access_token: SecretStr | None = None

    @field_validator("dhan_access_token", mode="before")
    @classmethod
    def blank_credential_is_unset(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
