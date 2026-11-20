"""Automated Unit Tests for WP09 Modular Grid Services Framework."""

from backend.app.equipment.interfaces.grid_service import GridServiceStatus
from plugins.grid_services.afrr import AFRRPlugin
from plugins.grid_services.energy_arbitrage import EnergyArbitragePlugin
from plugins.grid_services.fcr import FCRPlugin
from plugins.grid_services.mfrr import MFRRPlugin
from plugins.grid_services.peak_shaving import PeakShavingPlugin
from plugins.grid_services.renewable_smoothing import RenewableSmoothingPlugin
from plugins.grid_services.volt_var import VoltVarSupportPlugin


def test_fcr_frequency_containment_reserve_activation() -> None:
    """Test FCR primary frequency response activation and setpoint calculation."""
    fcr = FCRPlugin(nominal_frequency_hz=50.0, f_deadband_hz=0.02, droop_pct=2.0)

    # Within deadband (50.01 Hz) -> IDLE
    p_req, q_req = fcr.calculate_service_request(
        grid_frequency_hz=50.01, poi_voltage_v=13800.0, current_soc_pct=50.0
    )
    assert p_req == 0.0
    assert q_req == 0.0
    assert fcr.service_status == GridServiceStatus.IDLE

    # Under-frequency drop (49.8 Hz) -> Discharges +P to support grid
    p_req2, _ = fcr.calculate_service_request(
        grid_frequency_hz=49.8, poi_voltage_v=13800.0, current_soc_pct=50.0
    )
    assert p_req2 > 0.0
    assert fcr.service_status == GridServiceStatus.ACTIVE


def test_service_unavailability_on_low_soc() -> None:
    """Test grid service becomes unavailable when SoC falls below minimum threshold."""
    fcr = FCRPlugin(nominal_frequency_hz=50.0)

    # SoC = 5% (below min 15% SoC boundary) -> UNAVAILABLE
    p_req, _ = fcr.calculate_service_request(
        grid_frequency_hz=49.5, poi_voltage_v=13800.0, current_soc_pct=5.0
    )
    assert p_req == 0.0
    assert fcr.service_status == GridServiceStatus.UNAVAILABLE


def test_volt_var_support_activation() -> None:
    """Test Volt-VAR reactive power support activation on voltage drop."""
    vv = VoltVarSupportPlugin(nominal_voltage_v=13800.0)

    # Low voltage (13,000 V vs 13,800 V nominal) -> Supplies reactive power (+Q)
    p_req, q_req = vv.calculate_service_request(
        grid_frequency_hz=50.0, poi_voltage_v=13000.0, current_soc_pct=50.0
    )
    assert p_req == 0.0
    assert q_req > 0.0
    assert vv.service_status == GridServiceStatus.ACTIVE


def test_energy_arbitrage_schedule_dispatch() -> None:
    """Test Energy Arbitrage scheduled time-of-use action."""
    arb = EnergyArbitragePlugin()

    # Scheduled DISCHARGE
    arb.scheduled_action = "DISCHARGE"
    p_req, _ = arb.calculate_service_request(
        grid_frequency_hz=50.0, poi_voltage_v=13800.0, current_soc_pct=50.0
    )
    assert p_req == 10_000_000.0
    assert arb.service_status == GridServiceStatus.ACTIVE

    # Scheduled CHARGE
    arb.scheduled_action = "CHARGE"
    p_req2, _ = arb.calculate_service_request(
        grid_frequency_hz=50.0, poi_voltage_v=13800.0, current_soc_pct=50.0
    )
    assert p_req2 == -10_000_000.0


def test_afrr_and_mfrr_plugins() -> None:
    """Test aFRR AGC secondary control and mFRR manual tertiary control."""
    afrr = AFRRPlugin()
    afrr.set_agc_target(5_000_000.0)
    p_req, _ = afrr.calculate_service_request(50.0, 13800.0, 50.0)
    assert p_req == 5_000_000.0

    mfrr = MFRRPlugin()
    mfrr.manual_dispatch_p_w = 8_000_000.0
    p_req2, _ = mfrr.calculate_service_request(50.0, 13800.0, 50.0)
    assert p_req2 == 8_000_000.0


def test_peak_shaving_and_renewable_smoothing() -> None:
    """Test Peak Shaving and Renewable Ramp Smoothing plugins."""
    ps = PeakShavingPlugin(demand_threshold_w=8_000_000.0)
    # Demand = 10 MW (> 8 MW threshold) -> Discharges 2 MW to shave peak
    p_req, _ = ps.calculate_service_request(50.0, 13800.0, 50.0, active_power_w=10_000_000.0)
    assert p_req == 2_000_000.0

    rs = RenewableSmoothingPlugin()
    # High renewable ramp up -> Charges battery to smooth ramp
    rs.last_power_w = 0.0
    p_req2, _ = rs.calculate_service_request(50.0, 13800.0, 50.0, active_power_w=10_000_000.0)
    assert p_req2 < 0.0


def test_performance_score_calculation() -> None:
    """Test service performance/compliance score calculation."""
    fcr = FCRPlugin()
    # Request 10 MW, actual delivered 9.5 MW -> Score = 0.95
    score = fcr.calculate_performance_score(requested_p_w=10_000_000.0, actual_p_w=9_500_000.0)
    assert score == 0.95
