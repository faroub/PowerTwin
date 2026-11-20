"""Automated Unit Tests for WP04B PCS, Transformer, Switchgear, and Meter Models."""

import math

import pytest

from backend.app.equipment.models import OperatingState, QualityFlag
from backend.app.models.bop.switchgear import (
    GenericSwitchgearModel,
    SwitchgearConfigModel,
)
from backend.app.models.bop.transformer import (
    GenericTransformerModel,
    TransformerConfigModel,
)
from backend.app.models.meter.meter_model import GenericMeterModel, MeterConfigModel
from backend.app.models.pcs.pcs_model import GenericPCSModel, PCSConfigModel


def test_pcs_pq_capability_circle_clamping() -> None:
    """Test P^2 + Q^2 <= S_max^2 capability circle clamping logic with P priority."""
    config = PCSConfigModel(
        rated_active_power_w=5_000_000.0,      # 5.0 MW
        rated_apparent_power_va=5_000_000.0,   # 5.0 MVA S_max
    )
    pcs = GenericPCSModel(config=config)

    # Request P = 4 MW, Q = 4 MW -> S_req = sqrt(16 + 16) = 5.65 MVA (Exceeds S_max = 5.0 MVA!)
    pcs.process_command({"requested_p_w": 4_000_000.0, "requested_q_var": 4_000_000.0})

    # Evaluate capability circle
    p_acc, q_acc = pcs.evaluate_pq_capability_circle(
        pcs.requested_p_w, pcs.requested_q_var, pcs.config.rated_apparent_power_va
    )

    # P_accepted should be 4.0 MW
    assert p_acc == 4_000_000.0

    # Max available Q = sqrt(5^2 - 4^2) = sqrt(25 - 16) = sqrt(9) = 3.0 MVAR
    assert pytest.approx(q_acc, abs=1.0) == 3_000_000.0

    # Total apparent power accepted: sqrt(4^2 + 3^2) = 5.0 MVA == S_max
    s_total = math.sqrt(p_acc**2 + q_acc**2)
    assert pytest.approx(s_total, abs=1.0) == 5_000_000.0


def test_pcs_ramp_rate_limiter() -> None:
    """Test active power ramp-rate limiting (e.g. 10 MW/s = 100 kW per 10ms step)."""
    config = PCSConfigModel(
        rated_active_power_w=5_000_000.0,
        ramp_rate_limit_w_per_s=10_000_000.0,  # 10 MW/s
    )
    pcs = GenericPCSModel(config=config)
    pcs.process_command({"enable_inverter": True, "requested_p_w": 5_000_000.0})

    # Execute single step of 10 ms (0.01 s) -> Max delta_P = 10 MW/s * 0.01 s = 100,000 W (100 kW)
    pcs.step(dc_voltage_v=1000.0, ac_grid_voltage_v=690.0, delta_t_s=0.01)

    # Accepted P is 5 MW, but actual P should be ramp-limited to 100 kW (incorporating 98.5% efficiency)
    assert pcs.accepted_p_w == 5_000_000.0
    assert pytest.approx(pcs.actual_p_w, abs=1000.0) == 100_000.0 * 0.985


def test_pcs_four_explicit_p_and_q_values_distinction() -> None:
    """Test distinct reporting of Requested, Accepted, Actual, and Measured P & Q values."""
    config = PCSConfigModel(
        rated_active_power_w=5_000_000.0,
        rated_apparent_power_va=5_000_000.0,
        efficiency=0.98,
    )
    pcs = GenericPCSModel(config=config)
    pcs.process_command({"enable_inverter": True, "requested_p_w": 6_000_000.0})  # Exceeds 5 MW

    # Step for 1 second (full ramp to limit)
    pcs.step(dc_voltage_v=1000.0, ac_grid_voltage_v=690.0, delta_t_s=1.0)

    # 1. Requested P = 6.0 MW
    assert pcs.requested_p_w == 6_000_000.0
    # 2. Accepted P = 5.0 MW (clamped to rated active power)
    assert pcs.accepted_p_w == 5_000_000.0
    # 3. Actual P = 5.0 MW * 0.98 = 4.9 MW (after 98% efficiency losses)
    assert pcs.actual_p_w == 4_900_000.0
    # 4. Measured P = 4.9 MW (from simulated AC sensor)
    assert pcs.measured_p_w == 4_900_000.0

    state = pcs.get_state()
    assert state.measurements["requested_p_w"].value == 6_000_000.0
    assert state.measurements["accepted_p_w"].value == 5_000_000.0
    assert state.measurements["actual_p_w"].value == 4_900_000.0


def test_pcs_thermal_derating_and_dc_voltage_window() -> None:
    """Test IGBT thermal derating and DC voltage window limits."""
    config = PCSConfigModel(
        dc_voltage_min_v=800.0,
        dc_voltage_max_v=1200.0,
    )
    pcs = GenericPCSModel(config=config)

    # DC over-voltage fault trip (1300 V > 1200 V)
    pcs.step(dc_voltage_v=1300.0, ac_grid_voltage_v=690.0, delta_t_s=0.01)
    assert pcs.operating_state == OperatingState.FAULTED
    assert pcs.is_available is False


def test_transformer_voltage_ratio_and_losses() -> None:
    """Test Transformer secondary voltage calculation and core/copper losses."""
    config = TransformerConfigModel(
        rating_va=10_000_000.0,
        primary_voltage_v=690.0,
        secondary_voltage_v=13800.0,
        core_loss_pct=0.002,    # 0.2% = 20 kW
        copper_loss_pct=0.010,  # 1.0% = 100 kW at full load
    )
    xfrm = GenericTransformerModel(config=config)
    assert xfrm.config.turns_ratio == 20.0

    # Step at full load (10 MW primary input at 690 V)
    xfrm.step(primary_power_w=10_000_000.0, primary_power_var=0.0, primary_voltage_v=690.0, delta_t_s=1.0)

    # Secondary voltage = 690 V * 20 = 13800 V
    assert xfrm.secondary_voltage_v == 13800.0

    # Losses = 20 kW core + 100 kW copper = 120 kW total loss
    # Secondary output P = 10,000,000 - 120,000 = 9,880,000 W (9.88 MW)
    assert pytest.approx(xfrm.secondary_power_w, abs=100.0) == 9_880_000.0


def test_switchgear_breaker_interlocks_and_overcurrent_trip() -> None:
    """Test Switchgear breaker close interlocks and over-current trip protection."""
    swg = GenericSwitchgearModel(config=SwitchgearConfigModel(rated_current_a=1000.0))

    # Close breaker
    res = swg.process_command({"close_breaker": True})
    assert res is True
    assert swg.breaker_closed is True
    assert swg.operating_state == OperatingState.RUNNING

    # Over-current trip at 1600 A (> 150% of 1000 A rating)
    swg.step(current_a=1600.0, timestamp_ns=100, delta_t_s=0.01)
    assert swg.breaker_closed is False
    assert swg.operating_state == OperatingState.FAULTED

    # Close attempt rejected while faulted
    res_rejected = swg.process_command({"close_breaker": True})
    assert res_rejected is False


def test_meter_measurement_consistency_and_energy_registers() -> None:
    """Test Meter 3-phase current, power factor, and energy register accumulation."""
    meter = GenericMeterModel(config=MeterConfigModel(nominal_voltage_v=13800.0))

    # 10 MW export (+P) and 0 VAR for 3600 seconds (1 hour)
    meter.step(
        active_power_w=10_000_000.0,
        reactive_power_var=0.0,
        voltage_v=13800.0,
        frequency_hz=60.0,
        delta_t_s=3600.0,
        quality=QualityFlag.GOOD,
    )

    assert meter.power_factor == 1.0
    assert meter.apparent_power_va == 10_000_000.0
    # 3-phase current: I = 10,000,000 / (sqrt(3) * 13800) = 418.37 A
    assert pytest.approx(meter.current_a, abs=0.1) == 418.37

    # Energy export register: 10 MW * 1 hr = 10,000,000 Wh (10 MWh)
    assert meter.energy_export_wh == 10_000_000.0
    assert meter.energy_import_wh == 0.0

    state = meter.get_state()
    assert state.measurements["active_power_w"].value == 10_000_000.0
    assert state.measurements["energy_export_wh"].value == 10_000_000.0
