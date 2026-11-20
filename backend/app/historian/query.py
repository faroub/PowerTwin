"""Historian Query Engine for Time-Series, Trend Retrieval, Alarms, and Warranty Metrics."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.historian.models import (
    AlarmsAndEventsModel,
    BatteryWarrantyMetricsModel,
    CommandRecordModel,
    TelemetryDataModel,
)

logger = logging.getLogger(__name__)


class HistorianQueryEngine:
    """Query engine for retrieving historical telemetry, audit logs, and warranty metrics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    async def query_telemetry(
        self,
        equipment_id: str | None = None,
        tag_id: str | None = None,
        simulation_run_id: str | None = None,
        start_time_ns: int | None = None,
        end_time_ns: int | None = None,
        sampling_step_ns: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query time-series telemetry records with optional time range and downsampling."""
        stmt = select(TelemetryDataModel)

        if equipment_id:
            stmt = stmt.where(TelemetryDataModel.equipment_id == equipment_id)
        if tag_id:
            stmt = stmt.where(TelemetryDataModel.tag_id == tag_id)
        if simulation_run_id:
            stmt = stmt.where(TelemetryDataModel.simulation_run_id == simulation_run_id)
        if start_time_ns is not None:
            stmt = stmt.where(TelemetryDataModel.timestamp_ns >= start_time_ns)
        if end_time_ns is not None:
            stmt = stmt.where(TelemetryDataModel.timestamp_ns <= end_time_ns)

        stmt = stmt.order_by(TelemetryDataModel.timestamp_ns.asc()).limit(limit)

        result = await self.session.execute(stmt)
        records = result.scalars().all()

        results: list[dict[str, Any]] = []
        last_sampled_ns = -1

        for r in records:
            if sampling_step_ns is not None and last_sampled_ns >= 0:
                if (r.timestamp_ns - last_sampled_ns) < sampling_step_ns:
                    continue

            last_sampled_ns = r.timestamp_ns
            results.append(
                {
                    "timestamp_ns": r.timestamp_ns,
                    "source_timestamp_ns": r.source_timestamp_ns,
                    "tag_id": r.tag_id,
                    "equipment_id": r.equipment_id,
                    "value": r.val_float,
                    "unit": r.unit,
                    "quality": r.quality,
                    "source_type": r.source_type,
                    "simulation_run_id": r.simulation_run_id,
                }
            )

        return results

    async def query_commands(
        self,
        target_equipment_id: str | None = None,
        simulation_run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query traceable command records."""
        stmt = select(CommandRecordModel)
        if target_equipment_id:
            stmt = stmt.where(CommandRecordModel.target_equipment_id == target_equipment_id)
        if simulation_run_id:
            stmt = stmt.where(CommandRecordModel.simulation_run_id == simulation_run_id)

        stmt = stmt.order_by(CommandRecordModel.timestamp_ns.asc()).limit(limit)
        result = await self.session.execute(stmt)
        records = result.scalars().all()

        return [
            {
                "command_id": r.command_id,
                "timestamp_ns": r.timestamp_ns,
                "requestor": r.requestor,
                "target_equipment_id": r.target_equipment_id,
                "requested_value": r.requested_value,
                "accepted_status": r.accepted_status,
                "rejection_reason": r.rejection_reason,
                "resulting_response": r.resulting_response,
                "simulation_run_id": r.simulation_run_id,
            }
            for r in records
        ]

    async def query_alarms(
        self,
        equipment_id: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query alarms and events log."""
        stmt = select(AlarmsAndEventsModel)
        if equipment_id:
            stmt = stmt.where(AlarmsAndEventsModel.equipment_id == equipment_id)
        if severity:
            stmt = stmt.where(AlarmsAndEventsModel.severity == severity)

        stmt = stmt.order_by(AlarmsAndEventsModel.timestamp_ns.asc()).limit(limit)
        result = await self.session.execute(stmt)
        records = result.scalars().all()

        return [
            {
                "event_id": r.event_id,
                "timestamp_ns": r.timestamp_ns,
                "equipment_id": r.equipment_id,
                "severity": r.severity,
                "code": r.code,
                "description": r.description,
                "acknowledged": r.acknowledged,
                "cleared": r.cleared,
                "simulation_run_id": r.simulation_run_id,
            }
            for r in records
        ]

    async def query_warranty_metrics(self, container_id: str) -> dict[str, Any] | None:
        """Query battery container degradation and warranty metric summary."""
        stmt = (
            select(BatteryWarrantyMetricsModel)
            .where(BatteryWarrantyMetricsModel.container_id == container_id)
            .order_by(BatteryWarrantyMetricsModel.updated_at_ns.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if not record:
            return None

        return {
            "container_id": record.container_id,
            "simulation_run_id": record.simulation_run_id,
            "updated_at_ns": record.updated_at_ns,
            "total_energy_throughput_wh": record.total_energy_throughput_wh,
            "equivalent_full_cycles": record.equivalent_full_cycles,
            "max_temperature_recorded_c": record.max_temperature_recorded_c,
            "time_above_45c_seconds": record.time_above_45c_seconds,
            "current_soh_pct": record.current_soh_pct,
        }
