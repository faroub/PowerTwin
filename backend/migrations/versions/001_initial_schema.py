"""Initial database schema migration for PowerTwin.

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Telemetry Data Table
    op.create_table(
        "telemetry_data",
        sa.Column("timestamp_ns", sa.BigInteger(), nullable=False),
        sa.Column("source_timestamp_ns", sa.BigInteger(), nullable=False),
        sa.Column("tag_id", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=64), nullable=False),
        sa.Column("val_float", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("simulation_run_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("timestamp_ns", "tag_id", "equipment_id", "simulation_run_id"),
    )
    op.create_index(
        "idx_telemetry_query", "telemetry_data", ["equipment_id", "tag_id", "timestamp_ns"]
    )
    op.create_index("idx_telemetry_run", "telemetry_data", ["simulation_run_id", "timestamp_ns"])

    # Convert telemetry_data to TimescaleDB hypertable if TimescaleDB extension is available
    hypertable_sql = (
        "SELECT create_hypertable('telemetry_data', 'timestamp_ns', "
        "chunk_time_interval => 86400000000000, if_not_exists => TRUE);"
    )
    op.execute(hypertable_sql)

    # 2. Command Records Table
    op.create_table(
        "command_records",
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp_ns", sa.BigInteger(), nullable=False),
        sa.Column("requestor", sa.String(length=64), nullable=False),
        sa.Column("target_equipment_id", sa.String(length=64), nullable=False),
        sa.Column("requested_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted_status", sa.String(length=32), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=False),
        sa.Column("resulting_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("simulation_run_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("command_id"),
    )
    op.create_index("idx_cmd_target", "command_records", ["target_equipment_id", "timestamp_ns"])

    # 3. Alarms and Events Table
    op.create_table(
        "alarms_and_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp_ns", sa.BigInteger(), nullable=False),
        sa.Column("simulation_run_id", sa.String(length=64), nullable=False),
        sa.Column("equipment_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=True),
        sa.Column("cleared", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )

    # 4. Simulation Runs Table
    op.create_table(
        "simulation_runs",
        sa.Column("simulation_run_id", sa.String(length=64), nullable=False),
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_name", sa.String(length=128), nullable=False),
        sa.Column("start_time_wall", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_time_wall", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_ticks_executed", sa.BigInteger(), nullable=True),
        sa.Column("final_state", sa.String(length=32), nullable=True),
        sa.Column(
            "configuration_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.PrimaryKeyConstraint("simulation_run_id"),
    )

    # 5. Plant Configurations Table
    op.create_table(
        "plant_configurations",
        sa.Column("plant_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("topology_yaml", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("plant_id", "version"),
    )

    # 6. Equipment Inventory Table
    op.create_table(
        "equipment_inventory",
        sa.Column("equipment_id", sa.String(length=64), nullable=False),
        sa.Column("equipment_type", sa.String(length=32), nullable=False),
        sa.Column("manufacturer", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("serial_number", sa.String(length=64), nullable=False),
        sa.Column("is_illustrative", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("equipment_id"),
    )

    # 7. Battery Warranty Metrics Table
    op.create_table(
        "battery_warranty_metrics",
        sa.Column("container_id", sa.String(length=64), nullable=False),
        sa.Column("simulation_run_id", sa.String(length=64), nullable=False),
        sa.Column("updated_at_ns", sa.BigInteger(), nullable=False),
        sa.Column("total_energy_throughput_wh", sa.Float(), nullable=True),
        sa.Column("equivalent_full_cycles", sa.Float(), nullable=True),
        sa.Column("max_temperature_recorded_c", sa.Float(), nullable=True),
        sa.Column("time_above_45c_seconds", sa.Float(), nullable=True),
        sa.Column("current_soh_pct", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("container_id", "simulation_run_id"),
    )


def downgrade() -> None:
    op.drop_table("battery_warranty_metrics")
    op.drop_table("equipment_inventory")
    op.drop_table("plant_configurations")
    op.drop_table("simulation_runs")
    op.drop_table("alarms_and_events")
    op.drop_table("command_records")
    op.drop_table("telemetry_data")
