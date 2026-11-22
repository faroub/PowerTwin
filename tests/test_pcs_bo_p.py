"""Automated Unit Tests for PCS, Transformer, Switchgear, and Meter Models."""

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


def test_pcs_pq_capability_circle_clamping_active_priority() -> None:
    """Test P^2 + Q^2 <= S_max^2 capability circle clamping logic with Active Power Priority."""
    config = PCSConfigModel(
        rated_active_power_w=5_000_000.0,
        rated_apparent_power_va=5_000_000.0,
    )
    pcs = GenericPCSModel(config=config)

    pcs.process_command({"requested_p_w": 4_000_000.0, "requested_q_var": 4_000_000.0})

    p_acc, q_acc = pcs.evaluate_pq_capability_circle(
        pcs.requested_p_w,
        pcs.requested_q_var,
        pcs.config.rated_apparent_power_va,
        "ACTIVE_POWER_PRIORITY",
    )

    assert p_acc == 4_000_000.0
    assert pytest.approx(q_acc, abs=1.0) == 3_000_000.0
    s_total = math.sqrt(p_acc**2 + q_acc**2)
    assert pytest.approx(s_total, abs=1.0) == 5_000_000.0


def test_pcs_pq_capability_circle_reactive_priority() -> None:
    """Test P^2 + Q^2 <= S_max^2 capability circle clamping with Reactive Power Priority."""
    config = PCSConfigModel(
        rated_active_power_w=5_000_000.0,
        rated_apparent_power_va=5_000_000.0,
    )
    pcs = GenericPCSModel(config=config)

    p_acc, q_acc = pcs.evaluate_pq_capability_circle(
        4_000_000.0, 4_000_000.0, 5_000_000.0, priority_mode="REACTIVE_POWER_PRIORITY"
    )

    # Q is prioritized at 4.0 MVAR
    assert q_acc == 4_000_000.0
    # Available P headroom = sqrt(5^2 - 4^2) = 3.0 MW
    assert pytest.approx(p_acc, abs=1.0) == 3_000_000.0


def test_pcs_non_finite_input_rejection() -> None:
    """Test PCS rejects non-finite NaN / Inf inputs."""
    pcs = GenericPCSModel()

    res = pcs.process_command({"requested_p_w": math.nan, "requested_q_var": 0.0})
    assert res is False

    with pytest.raises(ValueError):
        pcs.step(dc_voltage_v=math.nan, ac_grid_voltage_v=690.0, delta_t_s=0.1)


def test_pcs_zero_output_when_faulted() -> None:
    """Test faulted PCS forces accepted and actual P & Q output to 0.0."""
    pcs = GenericPCSModel()
    pcs.requested_p_w = 5_000_000.0
    pcs.step(
        dc_voltage_v=1300.0, ac_grid_voltage_v=690.0, delta_t_s=0.1
    )  # Over-voltage trip

    assert pcs.operating_state == OperatingState.FAULTED
    assert pcs.accepted_p_w == 0.0
    assert pcs.actual_p_w == 0.0


def test_pcs_ramp_rate_limiter() -> None:
    """Test active power ramp-rate limiting (e.g. 10 MW/s = 100 kW per 10ms step)."""
    config = PCSConfigModel(
        rated_active_power_w=5_000_000.0,
        ramp_rate_limit_w_per_s=10_000_000.0,
    )
    pcs = GenericPCSModel(config=config)
    pcs.process_command({"enable_inverter": True, "requested_p_w": 5_000_000.0})

    pcs.step(dc_voltage_v=1000.0, ac_grid_voltage_v=690.0, delta_t_s=0.01)

    assert pcs.accepted_p_w == 5_000_000.0
    assert pytest.approx(pcs.actual_p_w, abs=1000.0) == 100_000.0


def test_pcs_four_explicit_p_and_q_values_distinction() -> None:
    """Test distinct reporting of Requested, Accepted, Actual, and Measured P & Q values."""
    config = PCSConfigModel(
        rated_active_power_w=5_000_000.0,
        rated_apparent_power_va=5_000_000.0,
        efficiency=0.98,
    )
    pcs = GenericPCSModel(config=config)
    pcs.process_command({"enable_inverter": True, "requested_p_w": 6_000_000.0})

    pcs.step(dc_voltage_v=1000.0, ac_grid_voltage_v=690.0, delta_t_s=1.0)

    assert pcs.requested_p_w == 6_000_000.0
    assert pcs.accepted_p_w == 5_000_000.0
    assert pcs.actual_p_w == 5_000_000.0
    assert pcs.measured_p_w == 5_000_000.0


def test_transformer_voltage_ratio_and_losses() -> None:
    """Test Transformer secondary voltage calculation and core/copper losses."""
    config = TransformerConfigModel(
        rating_va=10_000_000.0,
        primary_voltage_v=690.0,
        secondary_voltage_v=13800.0,
        core_loss_pct=0.002,
        copper_loss_pct=0.010,
    )
    xfrm = GenericTransformerModel(config=config)
    assert xfrm.config.turns_ratio == 20.0

    xfrm.step(
        primary_power_w=10_000_000.0,
        primary_power_var=0.0,
        primary_voltage_v=690.0,
        delta_t_s=1.0,
    )

    assert xfrm.secondary_voltage_v == 13800.0
    assert pytest.approx(xfrm.secondary_power_w, abs=100.0) == 9_880_000.0


def test_switchgear_breaker_interlocks_and_overcurrent_trip() -> None:
    """Test Switchgear breaker close interlocks and over-current trip protection."""
    swg = GenericSwitchgearModel(config=SwitchgearConfigModel(rated_current_a=1000.0))

    res = swg.process_command({"close_breaker": True})
    assert res is True
    assert swg.breaker_closed is True
    assert swg.operating_state == OperatingState.RUNNING

    swg.step(current_a=1600.0, timestamp_ns=100, delta_t_s=0.01)
    assert swg.breaker_closed is False
    assert swg.operating_state == OperatingState.FAULTED

    res_rejected = swg.process_command({"close_breaker": True})
    assert res_rejected is False


def test_meter_measurement_consistency_and_energy_registers() -> None:
    """Test Meter 3-phase current, power factor, and energy register accumulation."""
    meter = GenericMeterModel(config=MeterConfigModel(nominal_voltage_v=13800.0))

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
    assert pytest.approx(meter.current_a, abs=0.1) == 418.37
    assert meter.energy_export_wh == 10_000_000.0
    assert meter.energy_import_wh == 0.0
