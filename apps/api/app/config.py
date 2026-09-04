"""Application configuration.

Settings come from the environment, optionally seeded by a `.env` file at the
repository root. Everything is validated at startup: a bad value should fail
loudly here rather than surface as a confusing error deep inside a query.

Nothing in this module may be sent to the browser. Secrets live only in
``OPENAI_API_KEY`` and the MongoDB URI, and neither is ever serialized into an
API response, written to a log, or exposed through a ``NEXT_PUBLIC_*``
variable — that namespace belongs to the frontend build and nothing here is
read there.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py -> app -> api -> apps -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Environment-driven settings for the API and the data pipeline."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Source data -------------------------------------------------------
    ais_data_path: Path = Field(
        default=Path("../ais-2025-01-08.csv"),
        description="Path to the raw AIS CSV. Relative paths resolve from the repo root.",
    )
    ais_dataset_name: str = "NOAA/USCG AIS"

    # --- MongoDB -----------------------------------------------------------
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_database: str = "navisight"
    mongodb_test_database: str = "navisight_test"

    # --- Application -------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    web_origin: str = "http://localhost:3000"

    # --- AI copilot (optional) --------------------------------------------
    # Empty provider means the AI feature is disabled. The application must
    # still start and serve every other route (SOUL.md §11: not-configured is
    # a first-class state, not a crash).
    #
    # The literal lists only providers that are actually implemented, so a
    # deployment cannot be configured for something that does not exist.
    llm_provider: Literal["", "openai", "mock"] = ""
    llm_model: str = ""

    #: The OpenAI credential, read only from the backend environment.
    #:
    #: Named for its provider rather than generically, because that is what a
    #: reader looking for "where does the key come from" searches for, and
    #: because a shared LLM_API_KEY invites pointing two providers at one value.
    #:
    #: This is never serialized into a response, never logged, and can never
    #: reach the browser: NEXT_PUBLIC_* is a *frontend* build-time namespace and
    #: this variable is only ever read here. `.env.example` ships it blank.
    openai_api_key: str = ""

    agent_max_tool_calls: int = Field(default=8, ge=1, le=32)
    agent_timeout_seconds: int = Field(default=60, ge=5, le=300)

    @field_validator("ais_data_path")
    @classmethod
    def _resolve_data_path(cls, value: Path) -> Path:
        """Resolve a relative dataset path against the repository root.

        Relative paths are the portable form used in ``.env.example``; an
        absolute path (someone's real local layout) is left untouched.
        """
        if value.is_absolute():
            return value
        return (REPO_ROOT / value).resolve()

    @property
    def cors_origins(self) -> list[str]:
        """Browser origins permitted to call the API."""
        return [origin.strip() for origin in self.web_origin.split(",") if origin.strip()]

    @property
    def ai_enabled(self) -> bool:
        """Whether the copilot has enough configuration to run.

        The ``mock`` provider is deterministic and offline, so it needs no key.
        """
        if self.llm_provider == "":
            return False
        if self.llm_provider == "mock":
            return True
        return bool(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
