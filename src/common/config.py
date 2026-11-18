"""Application settings loaded from environment variables."""

import os
from pathlib import Path
from typing import Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

# Compute absolute path to project root to ensure .env is discovered
# regardless of current working directory when processes are launched.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = PROJECT_ROOT / ".env"


class AppSettings(BaseSettings):
    """Central configuration class supporting .env file and environment variables."""

    # Controller Settings
    controller_host: str = Field(default="0.0.0.0", alias="CONTROLLER_HOST")
    controller_port: int = Field(default=8000, alias="CONTROLLER_PORT")
    controller_secret_key: str = Field(
        default="niat-default-secret-key-change-in-prod",
        alias="CONTROLLER_SECRET_KEY",
    )

    @field_validator("controller_secret_key", mode="before")
    @classmethod
    def clean_secret_key(cls, v: Any) -> str:
        if isinstance(v, str):
            return v.strip().strip("'\"")
        return str(v) if v is not None else ""

    # Worker Settings
    controller_url: str = Field(
        default="http://localhost:8000", alias="CONTROLLER_URL"
    )
    worker_id: str = Field(default="worker-default", alias="WORKER_ID")
    worker_name: str = Field(default="Default Worker", alias="WORKER_NAME")
    heartbeat_interval_seconds: float = Field(
        default=5.0, alias="HEARTBEAT_INTERVAL_SECONDS"
    )
    heartbeat_timeout_seconds: float = Field(
        default=15.0, alias="HEARTBEAT_TIMEOUT_SECONDS"
    )

    # Security & Policy Settings
    require_explicit_permission: bool = Field(
        default=True, alias="REQUIRE_EXPLICIT_PERMISSION"
    )
    allow_automated_portal_submission: bool = Field(
        default=False, alias="ALLOW_AUTOMATED_PORTAL_SUBMISSION"
    )
    require_student_approval_for_actions: bool = Field(
        default=True, alias="REQUIRE_STUDENT_APPROVAL_FOR_ACTIONS"
    )

    # Supabase (Optional for local testing / milestone 1)
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_key: str = Field(default="", alias="SUPABASE_KEY")

    # AI Provider Settings ("gemini" or "openai")
    ai_provider: str = Field(default="gemini", alias="AI_PROVIDER")

    # Google Gemini Settings
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-flash-lite-latest", alias="GEMINI_MODEL")
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="GEMINI_BASE_URL",
    )

    # OpenAI Settings
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    openai_max_tokens: int = Field(default=4096, alias="OPENAI_MAX_TOKENS")
    openai_timeout_seconds: float = Field(default=60.0, alias="OPENAI_TIMEOUT_SECONDS")
    openai_max_retries: int = Field(default=3, alias="OPENAI_MAX_RETRIES")
    openai_jpeg_quality: int = Field(default=75, ge=10, le=95, alias="OPENAI_JPEG_QUALITY")

    model_config = SettingsConfigDict(
        env_file=(_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Singleton settings instance
settings = AppSettings()
