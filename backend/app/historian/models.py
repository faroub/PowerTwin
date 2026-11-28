"""SQLAlchemy ORM Models for PowerTwin PostgreSQL / TimescaleDB Database."""

import datetime
import uuid
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


class TelemetryDataModel(Base):
    """High-frequency time-series telemetry table (TimescaleDB hypertable)."""

    __tablename__ = "telemetry_data"

    timestamp_ns: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    source_timestamp_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tag_id: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    val_float: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quality: Mapped[str] = mapped_column(String(16), nullable=False, default="GOOD")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="SIMULATED")
    simulation_run_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)

    __table_args__ = (
        Index("idx_telemetry_query", "equipment_id", "tag_id", "timestamp_ns"),
        Index("idx_telemetry_run", "simulation_run_id", "timestamp_ns"),
    )


class CommandRecordModel(Base):
    """Traceable audit log for control setpoints and equipment commands."""

    __tablename__ = "command_records"

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    timestamp_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requestor: Mapped[str] = mapped_column(String(64), nullable=False)
    target_equipment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    accepted_status: Mapped[str] = mapped_column(String(32), nullable=False)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False, default="SUCCESS")
    resulting_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    simulation_run_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # The index is declared exactly as migration `001_initial_schema` creates it.
    # The historian query filters on `target_equipment_id` and orders by
    # `timestamp_ns`, so this composite index serves both, and the ORM must
    # not claim individual column indexes that the deployed schema does not
    # have: `alembic check` compares the two and would report the difference.
    __table_args__ = (Index("idx_cmd_target", "target_equipment_id", "timestamp_ns"),)


class AlarmsAndEventsModel(Base):
    """Events, faults, and alarms record table."""

    __tablename__ = "alarms_and_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    timestamp_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    simulation_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged: Mapped[bool | None] = mapped_column(Boolean, default=False)
    cleared: Mapped[bool | None] = mapped_column(Boolean, default=False)


class SimulationRunModel(Base):
    """Simulation run metadata record."""

    __tablename__ = "simulation_runs"

    simulation_run_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    plant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_time_wall: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    end_time_wall: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_ticks_executed: Mapped[int | None] = mapped_column(BigInteger, default=0)
    final_state: Mapped[str | None] = mapped_column(String(32), default="STOPPED")
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PlantConfigurationModel(Base):
    """Plant topology configuration schema storage."""

    __tablename__ = "plant_configurations"

    plant_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    version: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    topology_yaml: Mapped[str] = mapped_column(Text, nullable=False)


class EquipmentInventoryModel(Base):
    """Equipment inventory asset table."""

    __tablename__ = "equipment_inventory"

    equipment_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    equipment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(64), nullable=False)
    is_illustrative: Mapped[bool | None] = mapped_column(Boolean, default=True)


class UserAccountModel(Base):
    """Application user account table for authentication and role management."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    created_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.UTC)
    )
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_login_attempts: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Migration `002_user_accounts` creates this index alongside the unique
    # constraint. The ORM declares it so that `alembic check` sees the same
    # index set as the deployed schema.
    __table_args__ = (Index("idx_users_username", "username"),)


class RevokedTokenModel(Base):
    """Token of a session token the platform has revoked.

    A session token is a stateless JWT that carries the identity of the
    account that holds it, not the identity of the token itself. The table
    therefore records the token's ``jti`` (JWT ID) claim — the value the
    token carries explicitly — and brands it as refused from the moment it
    was revoked until it expired by itself.

    The platform writes a row when a session-ending operation refuses to let
    the same token run again: a logout, a user deactivation or an
    administrative revocation. The ``expires_at`` column is the token's
    ``exp``, so the rows that never expire again can be purged and the table
    does not grow without limit.

    Every other token is answered only by its signature and its expiry: the
    table makes one statement, and the absence of a row is not one of them.
    """

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True, nullable=False)
    sub: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.datetime.now(datetime.UTC)
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="LOGOUT")

    __table_args__ = (Index("idx_revoked_tokens_sub", "sub"),)


class BatteryWarrantyMetricsModel(Base):
    """Battery container operational degradation and warranty metrics."""

    __tablename__ = "battery_warranty_metrics"

    container_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    simulation_run_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    updated_at_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_energy_throughput_wh: Mapped[float | None] = mapped_column(Float, default=0.0)
    equivalent_full_cycles: Mapped[float | None] = mapped_column(Float, default=0.0)
    max_temperature_recorded_c: Mapped[float | None] = mapped_column(Float, default=25.0)
    time_above_45c_seconds: Mapped[float | None] = mapped_column(Float, default=0.0)
    current_soh_pct: Mapped[float | None] = mapped_column(Float, default=100.0)
