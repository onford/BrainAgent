from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    app_name: str = "Brain Agent"
    backend_port: int = 8000
    frontend_origin: str = "http://localhost:5173"

    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "brain_agent"
    mysql_password: str = "brain_agent"
    mysql_database: str = "brain_agent"
    database_url_override: str | None = None
    db_create_tables: bool = True

    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"

    brain_agent_credential_encryption_key: str | None = None
    default_owner_id: str = "local-development-user"
    external_tool_timeout_seconds: float = 10.0
    external_tool_max_retries: int = 2
    log_dir: Path = Path(__file__).resolve().parents[2] / "logs"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5

    @computed_field
    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"mysql+asyncmy://{quote_plus(self.mysql_user)}:{quote_plus(self.mysql_password)}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
