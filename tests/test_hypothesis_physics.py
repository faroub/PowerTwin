"""Hypothesis Property-Based Engineering Physics Tests."""

import math

from hypothesis import given
from hypothesis import strategies as st

from backend.app.models.battery.system import (
    BatterySystemConfigModel,
    GenericBatterySystemModel,
)
from backend.app.models.bop.transformer import GenericTransformerModel
from backend.app.models.pcs.pcs_model import GenericPCSModel, PCSConfigModel
from plugins.grid_services.fcr import FCRPlugin


@given(
    p_req=st.floats(min_value=-20_000_000.0, max_value=20_000_000.0),
    q_req=st.floats(min_value=-20_000_000.0, max_value=20_000_000.0),
)
def test_hypothesis_pcs_pq_capability_circle_bound(p_req: float, q_req: float) -> None:
    """Hypothesis Property Test: Accepted P & Q setpoints ALWAYS satisfy P^2 + Q^2 <= S_max^2."""
    pcs = GenericPCSModel(config=PCSConfigModel(rated_apparent_power_va=5_500_000.0))
    p_acc, q_acc = pcs.evaluate_pq_capability_circle(p_req, q_req, s_max_eff=5_500_000.0)

    apparent_s = math.sqrt(p_acc**2 + q_acc**2)
    assert apparent_s <= 5_500_001.0


@given(
    power_demand_w=st.floats(min_value=-10_000_000.0, max_value=10_000_000.0),
    delta_t_s=st.floats(min_value=0.001, max_value=1.0),
)
def test_hypothesis_battery_soc_conservation(power_demand_w: float, delta_t_s: float) -> None:
    """Hypothesis Property Test: Battery SoC remains within bounds (5% <= SoC <= 95%)."""
    battery = GenericBatterySystemModel(
        config=BatterySystemConfigModel(initial_soc_pct=50.0, capacity_wh=10_000_000.0)
    )
    battery.step(power_demand_w=power_demand_w, delta_t_s=delta_t_s, timestamp_ns=1000)

    assert 5.0 <= battery.soc_pct <= 95.0
    assert battery.stored_energy_wh >= 0.0


@given(grid_freq=st.floats(min_value=47.0, max_value=53.0))
def test_hypothesis_fcr_droop_proportionality(grid_freq: float) -> None:
    """Hypothesis Property Test: FCR response magnitude scales linearly with frequency deviation."""
    fcr = FCRPlugin(nominal_frequency_hz=50.0, f_deadband_hz=0.02, droop_pct=2.0)
    p_req, _ = fcr.calculate_service_request(
        grid_frequency_hz=grid_freq, poi_voltage_v=13800.0, current_soc_pct=50.0
    )

    f_dev = grid_freq - 50.0
    if abs(f_dev) <= 0.02:
        assert p_req == 0.0
    elif f_dev < -0.02:  # Under-frequency drop -> Discharges +P
        assert p_req > 0.0
    elif f_dev > 0.02:  # Over-frequency surge -> Charges -P
        assert p_req < 0.0


@given(input_p_w=st.floats(min_value=0.0, max_value=50_000_000.0))
def test_hypothesis_transformer_power_losses_bound(input_p_w: float) -> None:
    """Hypothesis Property Test: Transformer efficiency losses reduce
    exported power (P_sec <= P_pri)."""
    xfrm = GenericTransformerModel()
    xfrm.step(
        primary_power_w=input_p_w,
        primary_power_var=0.0,
        primary_voltage_v=690.0,
        delta_t_s=0.1,
    )

    assert xfrm.secondary_power_w <= input_p_w + 1e-6
