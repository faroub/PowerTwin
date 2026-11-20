"""Automated Unit Tests for WP04A Battery System and BMS Models."""

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
        capacity_wh=100_000.0,  # 100 kWh
        initial_soc_pct=50.0,
        charge_efficiency=0.90,
        discharge_efficiency=0.90,
        aux_power_w=0.0,  # Disable aux for pure energy test
    )
    battery = GenericBatterySystemModel(config=config)

    # Discharging at +36,000 W (+36 kW) for 3600 seconds (1 hour)
    # P_chem = 36,000 / 0.90 = 40,000 W -> 40 kWh drawn from chemistry
    battery.step(power_demand_w=36_000.0, delta_t_s=3600.0)

    assert battery.active_power_w == 36_000.0
    assert battery.current_a > 0.0  # +A discharge current
    # SoC change: 40 kWh / 100 kWh = 40% drop -> 50% - 40% = 10%
    assert pytest.approx(battery.soc_pct, abs=0.01) == 10.0


def test_battery_charge_energy_balance_and_round_trip_efficiency() -> None:
    """Test -P = CHARGING sign convention and round-trip efficiency."""
    config = BatterySystemConfigModel(
        capacity_wh=100_000.0,  # 100 kWh
        initial_soc_pct=10.0,
        charge_efficiency=0.90,
        discharge_efficiency=0.90,
        aux_power_w=0.0,
    )
    battery = GenericBatterySystemModel(config=config)

    # Charge at -44,444.44 W (-44.44 kW) for 3600 seconds (1 hour)
    # P_chem = 44,444.44 * 0.90 = 40,000 W -> 40 kWh added to chemistry
    battery.step(power_demand_w=-44_444.444, delta_t_s=3600.0)

    assert battery.active_power_w < 0.0  # -W charging
    assert battery.current_a < 0.0  # -A charging current
    # SoC change: 40 kWh / 100 kWh = +40% -> 10% + 40% = 50%
    assert pytest.approx(battery.soc_pct, abs=0.01) == 50.0

    # Round trip efficiency check: (36 kW delivered) / (44.44 kW supplied) = 0.81 (0.90 * 0.90)
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

    # Charge towards 95% limit
    battery.step(power_demand_w=-10_000.0, delta_t_s=3600.0)
    assert pytest.approx(battery.soc_pct, abs=0.01) == 95.0  # Clamped at max_soc_pct

    ch_limit, dis_limit = battery.get_available_power_limits()
    assert ch_limit == 0.0  # Cannot charge further
    assert dis_limit > 0.0

    # Discharge down to 5% min limit
    battery.step(power_demand_w=20_000.0, delta_t_s=3600.0)
    assert pytest.approx(battery.soc_pct, abs=0.01) == 5.0  # Clamped at min_soc_pct

    ch_limit2, dis_limit2 = battery.get_available_power_limits()
    assert dis_limit2 == 0.0  # Cannot discharge further
    assert ch_limit2 > 0.0


def test_auxiliary_power_consumption() -> None:
    """Test continuous auxiliary load depletes battery energy."""
    config = BatterySystemConfigModel(
        capacity_wh=10_000.0,
        initial_soc_pct=50.0,
        aux_power_w=1000.0,  # 1 kW aux load
    )
    battery = GenericBatterySystemModel(config=config)

    # 1 hour idle with 1 kW aux load -> 1 kWh consumed
    battery.step(power_demand_w=0.0, delta_t_s=3600.0)

    # SoC change: -1 kWh / 10 kWh = -10% -> 50% - 10% = 40%
    assert pytest.approx(battery.soc_pct, abs=0.01) == 40.0


def test_invalid_time_step_rejection() -> None:
    """Test rejection of non-positive simulation delta_t_s."""
    battery = GenericBatterySystemModel()

    with pytest.raises(InvalidTimeStepError):
        battery.step(power_demand_w=100.0, delta_t_s=0.0)

    with pytest.raises(InvalidTimeStepError):
        battery.step(power_demand_w=100.0, delta_t_s=-1.0)


def test_equipment_faults_and_availability() -> None:
    """Test equipment fault sets is_available = False and zero power output."""
    battery = GenericBatterySystemModel()
    battery.set_fault("CELL_OVERVOLTAGE", "Cell voltage exceeded 3.65V")

    assert battery.operating_state == OperatingState.FAULTED
    assert battery.is_available is False

    ch_limit, dis_limit = battery.get_available_power_limits()
    assert ch_limit == 0.0
    assert dis_limit == 0.0


def test_bms_thermal_derating_and_fault_tripping() -> None:
    """Test BMS thermal protection: 50% derating in warning zone, fault trip at 60C."""
    bms = GenericBMSModel(limits=BMSProtectionLimits())

    # Optimal temp (25 C) -> Full CCL/DCL limits
    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=50.0, temp_c=25.0)
    assert bms.ccl_a == 1000.0
    assert bms.dcl_a == 1000.0
    assert bms.cpl_w == 1_000_000.0

    # Warning temp (50 C) -> 50% derating
    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=50.0, temp_c=50.0)
    assert bms.ccl_a == 500.0
    assert bms.dcl_a == 500.0

    # Over-temp fault (65 C) -> Fault trip, contactors open, 0A limits
    bms.evaluate_protection(voltage_v=1000.0, current_a=0.0, soc_pct=50.0, temp_c=65.0)
    assert bms.operating_state == OperatingState.FAULTED
    assert bms.is_available is False
    assert bms.ccl_a == 0.0
    assert bms.dcl_a == 0.0
    assert len(bms.get_state().alarms) == 1


def test_bms_command_validation() -> None:
    """Test BMS command handling and interlock validation."""
    bms = GenericBMSModel()

    # Valid contactor close command
    res = bms.process_command({"close_contactors": True})
    assert res is True
    assert bms.contactors_closed is True
    assert bms.operating_state == OperatingState.RUNNING

    # Fault state rejects contactor close command
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
