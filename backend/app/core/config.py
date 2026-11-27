"""Application configuration management using Pydantic BaseSettings."""

import logging
import os
import secrets
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.app.core.secrets import REDACTED_PLACEHOLDER
from backend.app.simulation.config import SimulationConfiguration

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """System configuration settings loaded from environment or defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._validate_password_config()

    def _validate_password_config(self) -> None:
        """Warn (never block) when a database password is weaker than the guidance."""
        password = self.POSTGRES_PASSWORD
        if password and len(password) < 20:
            logger.warning(
                "POSTGRES_PASSWORD should be at least 20 characters; this strongly "
                "reduces the cost of offline brute-force attacks."
            )

    # General Project Information
    PROJECT_NAME: str = "PowerTwin BESS Simulator"
    ENVIRONMENT: Literal["development", "production", "testing"] = "development"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"

    @staticmethod
    def _generate_jwt_secret() -> str:
        """Generate a cryptographically secure JWT signing key.

        Production deployments inherit no default; `validate_safety_invariants`
        treat a missing key as a fatal failure so that an unprotected secret can
        never accidentally sign production tokens.
        """
        env_value = os.getenv("JWT_SECRET_KEY", "").strip()
        if env_value:
            return env_value
        if os.getenv("ENVIRONMENT", "development") == "production":
            return ""
        return secrets.token_hex(32)

    @staticmethod
    def _secret_from_env(name: str) -> str:
        """Read a secret from the environment, treating a blank value as unset.

        This is the fallback used when the settings source supplies no value
        at all. The authoritative guard against a blank secret is the
        `_reject_blank_*` field validator, which also covers a value that the
        settings source resolves to an empty string.
        """
        value = os.getenv(name, "")
        return value if value.strip() else ""

    @field_validator("JWT_SECRET_KEY", mode="after")
    @classmethod
    def _reject_blank_jwt_secret(cls, value: str) -> str:
        """Replace a blank JWT signing key outside production.

        A key that is exported but empty must never sign session tokens. In
        production the blank value is preserved so that
        `validate_safety_invariants` fails the start-up closed; in every other
        environment a random per-process key is generated instead.
        """
        if value.strip():
            return value
        if os.getenv("ENVIRONMENT", "development") == "production":
            return ""
        return secrets.token_hex(32)

    # Authentication & Security
    #
    # No default secret is embedded: in development/testing a new cryptographically
    # secure key is generated on startup, while production deployments require an
    # explicit and strong key (checked at startup in `validate_safety_invariants`).
    JWT_SECRET_KEY: str = Field(
        default_factory=lambda: Settings._generate_jwt_secret(),
        description="Secret key for JWT signing. Must be set to a strong secret in production.",
    )
    JWT_SECRET_MIN_BYTES: int = 32
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str = "powertwin"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    LOGIN_RATE_LIMIT: int = Field(
        default=5,
        description="Maximum authentication attempts over the lockout window.",
    )
    LOGIN_LOCKOUT_SECONDS: int = Field(
        default=60, description="Duration of a single authentication lockout window."
    )

    # Authentication client identity
    #
    # The rate limiter measures one identity per login attempt: the client
    # identity of the request combined with the username it attempts. The
    # client identity is the request peer address by default, and is only
    # ever rewritten by `X-Forwarded-For` or `X-Real-IP` when the peer is
    # declared in `TRUSTED_PROXIES`.
    TRUSTED_PROXIES: list[str] = Field(
        default=[],
        description=(
            "Peer addresses declared as trusted to rewrite X-Forwarded-For or "
            "X-Real-IP headers, as plain addresses or CIDR blocks. Empty by "
            "default: the request peer address is trusted then."
        ),
    )

    # Server Configuration
    # The default is the loopback interface so that a deployment that does not
    # explicitly opt into a trusted external network never binds a writable
    # control interface to all available interfaces.
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # Protocol Gateway & CIL Settings (Safety Invariants)
    PROTOCOL_GATEWAY_ENABLED: bool = Field(
        default=False,
        description=(
            "Starts the loopback Modbus TCP CIL gateway. Disabled by default: no "
            "socket is opened until an operator explicitly enables it."
        ),
    )
    ALLOW_EXTERNAL_MODBUS_WRITES: bool = Field(
        default=False, description="Disabled by default; requires explicit CIL configuration"
    )
    PROTOCOL_GATEWAY_HOST: str = Field(
        default="127.0.0.1", description="Bound strictly to loopback by default"
    )
    PROTOCOL_GATEWAY_PORT: int = Field(default=5020, description="Modbus TCP Server port")

    # Database Settings
    # Default values are environment overrides; POSTGRES_PASSWORD itself defaults to a
    # per-process random string so no codified credential leaks through the source.
    POSTGRES_SERVER: str = Field(default_factory=lambda: os.getenv("POSTGRES_SERVER", "localhost"))
    POSTGRES_PORT: int = Field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    POSTGRES_USER: str = Field(default_factory=lambda: os.getenv("POSTGRES_USER", "powertwin"))
    POSTGRES_PASSWORD: str = Field(
        default_factory=lambda: (
            Settings._secret_from_env("POSTGRES_PASSWORD") or secrets.token_hex(32)
        ),
        description="Override: MUST be set to a strong secret in production.",
    )
    POSTGRES_DB: str = Field(default_factory=lambda: os.getenv("POSTGRES_DB", "powertwin_db"))

    @field_validator("POSTGRES_PASSWORD", mode="after")
    @classmethod
    def _reject_blank_database_password(cls, value: str) -> str:
        """Replace a blank database password with a random per-process secret.

        A password that is exported but empty (for example by a Compose file
        that expands an undefined `${POSTGRES_PASSWORD}` to an empty string)
        must never be used to authenticate against the historian. An empty
        credential is replaced by a random value so the connection fails
        closed instead of succeeding with no password at all.
        """
        if value.strip():
            return value
        return secrets.token_hex(32)

    @property
    def DATABASE_URL(self) -> str:
        """Construct PostgreSQL async connection URL."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def REDACTED_DATABASE_URL(self) -> str:
        """Return the connection URL with its password replaced by a placeholder.

        Use this property for any log line, error message or API response that
        mentions the database URL; the real URL must never leave the process.
        """
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{REDACTED_PLACEHOLDER}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Simulation Defaults
    SIMULATION_TICK_RATE_HZ: int = Field(
        default=100, description="Simulation tick rate in Hz (default: 100 Hz)"
    )
    SIMULATION_SPEED_FACTOR: float = Field(
        default=1.0,
        description="Wall-clock pacing multiplier. 1.0 = real-time, 0.0 = max speed",
    )
    SIMULATION_RANDOM_SEED: int = Field(
        default=42, description="Seed for deterministic pseudo-random number generator"
    )
    TOPOLOGY_CONFIG_PATH: str | None = Field(
        default=None,
        description="Path to the plant topology YAML loaded at application start-up",
    )

    # Historian Recording
    #
    # The historian is the platform's time-series store. AGENTS.md §1 asks for
    # a historian, so the recorder is on by default; it is a switch because a
    # deployment that must not write anything to a database can turn it off.
    # Turning it off does not weaken any guardrail: the recorder only ever
    # reads the plant and writes history, and it never influences the
    # simulation.
    HISTORIAN_ENABLED: bool = Field(
        default=True,
        description="Record the running plant's telemetry, alarms and commands into the historian",
    )
    HISTORIAN_SAMPLE_INTERVAL_TICKS: int = Field(
        default=10,
        ge=1,
        description=(
            "Record one telemetry sample every N simulation ticks. At the default tick rate "
            "of 100 Hz this samples at 10 Hz"
        ),
    )
    HISTORIAN_FLUSH_INTERVAL_S: float = Field(
        default=5.0,
        gt=0.0,
        description="Seconds between flushes of the historian's in-memory buffer to the database",
    )

    # Warranty Analysis
    #
    # The warranty analysis reads the running plant and writes its findings
    # into the historian's buffer. It never influences the simulation: the
    # degradation is reported, not applied back. It is a switch because a
    # deployment that must not analyse anything can turn it off, and because
    # the degradation model behind it is illustrative — its constants have
    # not been validated against any manufacturer document (`AGENTS.md`
    # §2.13, §2.14).
    WARRANTY_ENABLED: bool = Field(
        default=True,
        description=(
            "Analyse the running plant's battery warranty state and record the "
            "findings in the historian"
        ),
    )
    WARRANTY_SAMPLE_INTERVAL_TICKS: int = Field(
        default=10,
        ge=1,
        description=(
            "Publish one warranty snapshot every N simulation ticks. The operating "
            "history behind the snapshot is accumulated on every tick regardless, "
            "so the time above 45 degC is not undercounted"
        ),
    )
    WARRANTY_THRESHOLD_SOH_PCT: float = Field(
        default=70.0,
        gt=0.0,
        le=100.0,
        description=(
            "The state of health at or below which a container is reported as having "
            "reached the end of its warranty band. ILLUSTRATIVE: the default is a "
            "representative value, not a manufacturer's published figure"
        ),
    )
    WARRANTY_PROJECTION_HORIZON_YEARS: float = Field(
        default=10.0,
        gt=0.0,
        description=(
            "The horizon the projected state of health is made over. ILLUSTRATIVE: "
            "the default is a representative value, not a manufacturer's published "
            "figure"
        ),
    )

    # Logging
    LOG_LEVEL: str = "INFO"
    JSON_LOGS: bool = False

    # Operator-Action Journal
    #
    # The journal is the platform's dedicated, append-only and tamper-evident
    # audit trail. It is always on: AGENTS.md §2.10 requires every command,
    # setpoint change, configuration change, fault and operator action to be
    # recorded, so there is deliberately no switch that turns it off.
    OPERATOR_JOURNAL_PATH: str = Field(
        default="var/operator_actions.jsonl",
        description="Path of the append-only operator-action journal (JSON Lines)",
    )
    OPERATOR_JOURNAL_FSYNC: bool = Field(
        default=True,
        description=(
            "Force every journal entry to the storage device before the write returns. "
            "Turning it off keeps the entry in the operating system's page cache, "
            "which survives a process crash but not a machine crash"
        ),
    )

    def create_simulation_configuration(self) -> "SimulationConfiguration":
        """Build the simulation engine configuration from these settings."""
        from backend.app.simulation.config import SimulationConfiguration

        tick_step_ns = int(1_000_000_000 / max(1, self.SIMULATION_TICK_RATE_HZ))
        return SimulationConfiguration(
            tick_step_ns=tick_step_ns,
            speed_factor=self.SIMULATION_SPEED_FACTOR,
            random_seed=self.SIMULATION_RANDOM_SEED,
        )


settings = Settings()
