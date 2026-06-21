from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM ─────────────────────────────────────────────────────────────────────
    llm_backend: Literal["anthropic", "lm_studio"] = "anthropic"
    llm_model: str = "claude-sonnet-4-5"

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"

    # LM Studio (local, zero-cost, no key needed)
    lm_studio_base_url: str = "http://localhost:1234"
    lm_studio_model: str = "local-model"

    # Service ─────────────────────────────────────────────────────────────────
    service_host: str = "0.0.0.0"
    service_port: int = 8000
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    allowed_origins: str = "*"

    # MCP servers the agent connects to (comma-separated base URLs) ──────────
    mcp_server_urls: str = ""
    mcp_request_timeout_s: float = 15.0

    # Agent loop ──────────────────────────────────────────────────────────────
    max_planner_iterations: int = 6

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def mcp_urls(self) -> list[str]:
        return [u.strip() for u in self.mcp_server_urls.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
