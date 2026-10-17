from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+pysqlite:///./ai_logs_analyzer.db"
    mcp_database_url: str = "sqlite+pysqlite:///./ai_logs_analyzer_mcp.db"
    log_allowed_roots: str = "/logs"
    auto_log_source_paths: str = "/logs"
    ai_provider: str = "local"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    resource_poll_seconds: int = 15
    agent_poll_seconds: int = Field(default=60, ge=15, le=3600)
    agent_max_steps: int = Field(default=8, ge=1, le=20)
    target_container: str = ""
    api_cors_origins: str = "http://localhost:5173"
    max_log_files: int = 500
    max_log_lines: int = 50_000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_roots(self) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.log_allowed_roots.split(",") if value.strip())

    @property
    def auto_source_paths(self) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.auto_log_source_paths.split(",") if value.strip())

    @property
    def cors_origins(self) -> list[str]:
        return [value.strip() for value in self.api_cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
