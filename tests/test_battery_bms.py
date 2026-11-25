"""Automated Unit & Property Tests for Battery System and BMS Models."""

import math

import pytest

from backend.app.equipment.models import OperatingState
from backend.app.models.battery.bms import BMSProtectionLimits, GenericBMSModel
from backend.app.models.battery.ecm_interface import (
    ECMStub,
    EquivalentCircuitModelInterface,
)
from backend.app.models.battery.hierarchy import BatteryHierarchyConfig
from backend.app.models.battery.system import (
    BatterySystemConfigModel,
    GenericBatterySystemModel,
)
from backend.app.simulation.exceptions import InvalidTimeStepError


def test_battery_sign_convention_and_discharge_energy_balance() -> None:
    """Test +P = DISCHARGING sign convention and energy balance."""
    config = BatterySystemConfigModel(
        capacity_wh=100_000.0,
        initial_soc_pct=50.0,
        charge_efficiency=0.90,
        discharge_efficiency=0.90,
        aux_power_w=0.0,
    )
    battery = GenericBatterySystemModel(config=config)

    battery.step(power_demand_w=36_000.0, delta_t_s=3600.0)

    assert battery.active_power_w == 36_000.0
    assert battery.current_a > 0.0
    assert pytest.approx(battery.soc_pct, abs=0.01) == 10.0


def test_battery_charge_energy_balance_and_round_trip_efficiency() -> None:
    """Test -P = CHARGING sign convention and round-trip efficiency."""
    config = BatterySystemConfigModel(
        capacity_wh=100_000.0,
        initial_soc_pct=10.0,
        charge_efficiency=0.90,
        discharge_efficiency=0.90,
        aux_power_w=0.0,
    )
    battery = GenericBatterySystemModel(config=config)

    battery.step(power_demand_w=-44_444.444, delta_t_s=3600.0)

    assert battery.active_power_w < 0.0
    assert battery.current_a < 0.0
    assert pytest.approx(battery.soc_pct, abs=0.01) == 50.0
    assert pytest.approx(battery.round_trip_efficiency, abs=0.001) == 0.81


def test_soc_min_max_limits_enforcement() -> None:
    """Test SoC clamping and power limit zeroing at min/max SoC limits."""
    config = BatterySystemConfigModel(
        capacity_wh=10_000.0,
        initial_soc_pct=94.0,
        min_soc_pct=5.0,
        max_soc_pct=95.0,
        aux_power_w=0.0,
    )
    battery = GenericBatterySystemModel(config=config)

    battery.step(power_demand_w=-10_000.0, delta_t_s=3600.0)
    assert pytest.approx(battery.soc_pct, abs=0.01) == 95.0

    ch_limit, dis_limit = battery.get_available_power_limits()
    assert ch_limit == 0.0
    assert dis_limit > 0.0

    battery.step(power_demand_w=20_000.0, delta_t_s=3600.0)
    assert pytest.approx(battery.soc_pct, abs=0.01) == 5.0

    ch_limit2, dis_limit2 = battery.get_available_power_limits()
    assert dis_limit2 == 0.0
    assert ch_limit2 > 0.0


def test_auxiliary_power_consumption_and_unserved_tracking() -> None:
    """Test continuous auxiliary load depletes energy and tracks unserved aux
    energy when at min SoC."""
    config = BatterySystemConfigModel(
        capacity_wh=10_000.0,
        initial_soc_pct=5.0,
        min_soc_pct=5.0,
        aux_power_w=1000.0,
    )
    battery = GenericBatterySystemModel(config=config)

    battery.step(power_demand_w=0.0, delta_t_s=3600.0)

    assert battery.soc_pct == 5.0
    assert battery.unserved_aux_energy_wh == 1000.0


def test_non_finite_input_rejection() -> None:
    """Test battery model rejects non-finite power or time step inputs."""
    battery = GenericBatterySystemModel()

    with pytest.raises(ValueError):
        battery.step(power_demand_w=math.nan, delta_t_s=1.0)

    with pytest.raises((ValueError, InvalidTimeStepError)):
        battery.step(power_demand_w=100.0, delta_t_s=math.nan)


def test_bms_alarm_deduplication_and_persistent_fault_clearing() -> None:
    """Test BMS alarm deduplication and refusal to clear faults while condition persists."""
    bms = GenericBMSModel(limits=BMSProtectionLimits(over_temp_fault_c=60.0))

    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=50.0, temp_c=65.0)
    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=50.0, temp_c=65.0)

    assert len(bms.get_state().alarms) == 1

    cleared = bms.clear_faults(current_temp_c=65.0)
    assert cleared is False
    assert bms.operating_state == OperatingState.FAULTED

    cleared_ok = bms.clear_faults(current_temp_c=25.0)
    assert cleared_ok is True
    assert bms.operating_state == OperatingState.STANDBY


def test_bms_command_validation() -> None:
    """Test BMS command handling and interlock validation."""
    bms = GenericBMSModel()

    res = bms.process_command({"close_contactors": True})
    assert res is True
    assert bms.contactors_closed is True
    assert bms.operating_state == OperatingState.RUNNING

    bms._trigger_fault("TEST_FAULT", "Test fault", 0)
    res_fault = bms.process_command({"close_contactors": True})
    assert res_fault is False
    assert bms.contactors_closed is False


def test_battery_hierarchy_configuration() -> None:
    """Test configurable Plant -> Container -> BMS -> Rack -> Module -> Cell hierarchy."""
    hierarchy = BatteryHierarchyConfig(
        containers_count=2,
        racks_per_container=16,
        modules_per_rack=12,
    )

    assert hierarchy.total_racks == 32
    assert hierarchy.total_modules == 384
    assert hierarchy.total_cells == 6144
    assert pytest.approx(hierarchy.calculate_nominal_dc_voltage_v(), abs=0.1) == 614.4
    assert pytest.approx(hierarchy.calculate_total_energy_wh(), abs=1.0) == 5_505_024.0


def test_ecm_stub_unimplemented_error() -> None:
    """Test ECMStub explicitly raises NotImplementedError."""
    ecm = ECMStub()
    assert isinstance(ecm, EquivalentCircuitModelInterface)
    with pytest.raises(NotImplementedError):
        ecm.calculate_ecm_voltage(current_a=10.0, soc_pct=50.0, temp_c=25.0, delta_t_s=1.0)
