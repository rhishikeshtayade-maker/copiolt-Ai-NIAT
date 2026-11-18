"""Application settings loaded from environment variables."""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class AppSettings(BaseSettings):
    """Central configuration class supporting .env file and environment variables."""

    # Controller Settings
    controller_host: str = Field(default="0.0.0.0", alias="CONTROLLER_HOST")
    controller_port: int = Field(default=8000, alias="CONTROLLER_PORT")
    controller_secret_key: str = Field(
        default="niat-default-secret-key-change-in-prod",
        alias="CONTROLLER_SECRET_KEY",
    )

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

    # OpenAI (Optional for vision/reasoning)
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Singleton settings instance
settings = AppSettings()
