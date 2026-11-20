"""Application configuration management using Pydantic BaseSettings."""

import os
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """System configuration settings loaded from environment or defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General Project Information
    PROJECT_NAME: str = "PowerTwin BESS Simulator"
    ENVIRONMENT: Literal["development", "production", "testing"] = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Protocol Gateway & CIL Settings (Safety Invariants)
    ALLOW_EXTERNAL_MODBUS_WRITES: bool = Field(
        default=False, description="Disabled by default; requires explicit CIL configuration"
    )
    PROTOCOL_GATEWAY_HOST: str = Field(
        default="127.0.0.1", description="Bound strictly to loopback by default"
    )
    PROTOCOL_GATEWAY_PORT: int = Field(default=5020, description="Modbus TCP Server port")

    # Database Settings
    POSTGRES_SERVER: str = Field(default_factory=lambda: os.getenv("POSTGRES_SERVER", "localhost"))
    POSTGRES_PORT: int = Field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    POSTGRES_USER: str = Field(default_factory=lambda: os.getenv("POSTGRES_USER", "powertwin"))
    POSTGRES_PASSWORD: str = Field(
        default_factory=lambda: os.getenv("POSTGRES_PASSWORD", "powertwin_secret")
    )
    POSTGRES_DB: str = Field(default_factory=lambda: os.getenv("POSTGRES_DB", "powertwin_db"))

    @property
    def DATABASE_URL(self) -> str:
        """Construct PostgreSQL async connection URL."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Logging
    LOG_LEVEL: str = "INFO"
    JSON_LOGS: bool = False


settings = Settings()
