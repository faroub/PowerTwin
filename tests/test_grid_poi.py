"""Automated Unit Tests for WP04C Grid, POI, and Plant Electrical Network Models."""

import pytest

from backend.app.models.grid.grid_model import (
    DisturbanceType,
    GenericGridModel,
    GridConfigModel,
    GridDisturbance,
    GridOperatingState,
)
from backend.app.models.grid.network import PlantElectricalNetwork
from backend.app.models.grid.poi_model import FlowDirection, POIConfigModel, POIModel


def test_poi_measurements_respond_to_plant_power() -> None:
    """Test POI measurements and flow direction respond to plant export/import."""
    poi = POIModel()

    # 1. Exporting +10 MW
    poi.step(
        net_p_w=10_000_000.0,
        net_q_var=0.0,
        voltage_v=13800.0,
        frequency_hz=60.0,
        delta_t_s=1.0,
    )
    assert poi.active_power_w == 10_000_000.0
    assert poi.flow_direction == FlowDirection.EXPORTING
    assert poi.current_a > 0.0

    # 2. Importing -10 MW
    poi.step(
        net_p_w=-10_000_000.0,
        net_q_var=0.0,
        voltage_v=13800.0,
        frequency_hz=60.0,
        delta_t_s=1.0,
    )
    assert poi.active_power_w == -10_000_000.0
    assert poi.flow_direction == FlowDirection.IMPORTING

    # 3. Zero power
    poi.step(
        net_p_w=0.0,
        net_q_var=0.0,
        voltage_v=13800.0,
        frequency_hz=60.0,
        delta_t_s=1.0,
    )
    assert poi.flow_direction == FlowDirection.ZERO


def test_grid_disturbances_frequency_step_and_ramp() -> None:
    """Test frequency step and frequency ramp disturbance injection."""
    grid = GenericGridModel()

    # Frequency Step +0.5 Hz at tick 1,000,000,000 ns (1 second)
    grid.apply_disturbance(
        GridDisturbance(
            disturbance_type=DisturbanceType.FREQUENCY_STEP,
            start_time_ns=1_000_000_000,
            magnitude=0.5,
        )
    )

    # Step at t = 0 -> Nominal 60.0 Hz
    _v1, f1 = grid.step(plant_net_p_w=0.0, plant_net_q_var=0.0, delta_t_s=0.1, timestamp_ns=0)
    assert f1 == 60.0

    # Step at t = 1s -> 60.5 Hz
    _v2, f2 = grid.step(
        plant_net_p_w=0.0,
        plant_net_q_var=0.0,
        delta_t_s=0.1,
        timestamp_ns=1_000_000_000,
    )
    assert f2 == 60.5


def test_grid_disconnection_and_reconnection() -> None:
    """Test grid disconnection transitions state to DISCONNECTED and zeroes voltage."""
    grid = GenericGridModel()

    grid.disconnect_grid()
    assert grid.grid_state == GridOperatingState.DISCONNECTED
    assert grid.is_islanding is True

    v, f = grid.step(plant_net_p_w=10_000_000.0, plant_net_q_var=0.0, delta_t_s=1.0)
    assert v == 0.0
    assert f == 0.0

    grid.reconnect_grid()
    assert grid.grid_state == GridOperatingState.GRID_CONNECTED
    assert grid.is_islanding is False


def test_poi_limit_detection_and_alarms() -> None:
    """Test POI limit detection raises appropriate warning alarms."""
    config = POIConfigModel(
        max_export_power_w=50_000_000.0,
        voltage_high_limit_v=14490.0,
    )
    poi = POIModel(config=config)

    # Exceed export limit (+60 MW > +50 MW limit)
    poi.step(
        net_p_w=60_000_000.0,
        net_q_var=0.0,
        voltage_v=15000.0,  # Exceeds 14.49 kV high voltage limit
        frequency_hz=60.0,
        delta_t_s=1.0,
    )

    alarm_codes = [a.code for a in poi.active_alarms]
    assert "POI_EXPORT_LIMIT_EXCEEDED" in alarm_codes
    assert "POI_OVER_VOLTAGE" in alarm_codes


def test_invalid_grid_configurations_rejected() -> None:
    """Test invalid negative grid voltage or frequency raise ValueError."""
    with pytest.raises(ValueError):
        GridConfigModel(nominal_frequency_hz=-60.0)

    with pytest.raises(ValueError):
        GridConfigModel(nominal_voltage_v=0.0)


def test_plant_electrical_network_integration() -> None:
    """Test integrated PlantElectricalNetwork propagation."""
    network = PlantElectricalNetwork()

    # Step network with +2.0 MW discharge demand
    network.step(requested_p_w=2_000_000.0, requested_q_var=0.0, delta_t_s=1.0, timestamp_ns=1000)

    # Verify power flow propagated to POI
    assert network.poi.active_power_w > 0.0
    assert network.poi.flow_direction == FlowDirection.EXPORTING
    assert network.meter.energy_export_wh > 0.0
