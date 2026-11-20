"""Automated Unit & Multi-Vendor Compatibility Tests for WP11 Equipment Plugins."""

from backend.app.controllers.ems import EnergyManagementSystem
from backend.app.controllers.equipment_controller import BESSEquipmentController
from backend.app.controllers.ppc import PowerPlantController
from backend.app.simulation.manager import SimulationRunManager
from backend.app.topology.factory import PlantTopologyFactory
from backend.app.topology.schema import (
    ContainerConfig,
    GridTopologyConfig,
    MeterTopologyConfig,
    PCSUnitConfig,
    PlantTopologyConfig,
    POITopologyConfig,
    PPCTopologyConfig,
    SwitchgearTopologyConfig,
    TransformerTopologyConfig,
)
from plugins.registry import PluginRegistry
from plugins.vendor.catl_enerone import CATLEnerOneBatteryPlugin
from plugins.vendor.sma_sunnycentral import SMASunnyCentralPCSPlugin
from plugins.vendor.sungrow_sc5000 import SungrowSC5000PCSPlugin
from plugins.vendor.tesla_megapack import TeslaMegapackBatteryPlugin


def test_catl_enerone_battery_plugin_instantiation() -> None:
    """Test CATL EnerOne 3.727 MWh battery container plugin initialization and tick calculation."""
    catl = CATLEnerOneBatteryPlugin("CATL_01")
    catl.initialize({"initial_soc_pct": 60.0})

    manifest = catl.manifest
    assert manifest.plugin_id == "CATL_EnerOne_v1"
    assert "CATL" in manifest.name

    # Step simulation tick
    catl.physical_model.active_power_w = 1_000_000.0  # +1 MW discharge
    engine = SimulationRunManager()
    catl.step_plugin(engine.context, delta_t_s=0.01)

    state = catl.get_state()
    assert state.metadata.manufacturer == "CATL"
    assert "coolant_temp_c" in state.measurements


def test_tesla_megapack_battery_plugin_instantiation() -> None:
    """Test Tesla Megapack 2XL battery container plugin initialization."""
    tesla = TeslaMegapackBatteryPlugin("TESLA_01")
    tesla.initialize({"initial_soc_pct": 50.0})

    manifest = tesla.manifest
    assert manifest.plugin_id == "Tesla_Megapack_v1"
    assert "Tesla" in manifest.name

    state = tesla.get_state()
    assert state.metadata.manufacturer == "Tesla"
    assert state.metadata.model_name == "Megapack 2XL"


def test_sma_sunny_central_pcs_plugin_derating() -> None:
    """Test SMA Sunny Central inverter plugin ambient temperature derating (> 45 C)."""
    sma = SMASunnyCentralPCSPlugin("SMA_01")
    sma.initialize({})
    engine = SimulationRunManager()

    # Normal temp (25 C) -> Full 4.4 MW capacity
    sma.ambient_temp_c = 25.0
    sma.step_plugin(engine.context, delta_t_s=0.01)
    assert sma.physical_model.config.rated_active_power_w == 4_400_000.0

    # High temp (55 C > 45 C) -> Active power derates below 4.4 MW
    sma.ambient_temp_c = 55.0
    sma.step_plugin(engine.context, delta_t_s=0.01)
    assert sma.physical_model.config.rated_active_power_w < 4_400_000.0


def test_sungrow_sc5000_pcs_plugin_instantiation() -> None:
    """Test Sungrow SC5000UD inverter plugin initialization."""
    sungrow = SungrowSC5000PCSPlugin("SUNGROW_01")
    sungrow.initialize({})

    manifest = sungrow.manifest
    assert manifest.plugin_id == "Sungrow_SC5000_v1"

    state = sungrow.get_state()
    assert state.metadata.manufacturer == "Sungrow"


def test_multi_vendor_plant_topology_without_modifying_core_engine() -> None:
    """Demonstrate that a second/third vendor implementation can be added and dispatched in a single plant

    topology without modifying the generic simulation engine, PPC (Layer B), or EMS (Layer C).
    """
    # 1. Register vendor plugins with PluginRegistry
    registry = PluginRegistry()
    registry.register_plugin_class(CATLEnerOneBatteryPlugin)
    registry.register_plugin_class(TeslaMegapackBatteryPlugin)
    registry.register_plugin_class(SMASunnyCentralPCSPlugin)
    registry.register_plugin_class(SungrowSC5000PCSPlugin)

    # 2. Construct Multi-Vendor Topology (CATL + Tesla Containers, SMA + Sungrow PCS Inverters)
    multi_vendor_config = PlantTopologyConfig(
        plant_id="MULTI_VENDOR_PLANT_01",
        name="Multi-Vendor Demonstration BESS Plant",
        rated_power_w=15_000_000.0,
        rated_energy_wh=60_000_000.0,
        containers=[
            ContainerConfig(
                container_id="CATL_CONT_01",
                plugin_id="CATL_EnerOne_v1",
                vendor="CATL",
                capacity_wh=30_000_000.0,
            ),
            ContainerConfig(
                container_id="TESLA_CONT_01",
                plugin_id="Tesla_Megapack_v1",
                vendor="Tesla",
                capacity_wh=30_000_000.0,
            ),
        ],
        pcs_units=[
            PCSUnitConfig(
                pcs_id="SMA_PCS_01",
                plugin_id="SMA_SunnyCentral_v1",
                vendor="SMA",
                rated_active_power_w=7_500_000.0,
                rated_apparent_power_va=8_000_000.0,
            ),
            PCSUnitConfig(
                pcs_id="SUNGROW_PCS_01",
                plugin_id="Sungrow_SC5000_v1",
                vendor="Sungrow",
                rated_active_power_w=7_500_000.0,
                rated_apparent_power_va=8_000_000.0,
            ),
        ],
        transformers=[TransformerTopologyConfig(rating_va=16_000_000.0)],
        switchgear=[SwitchgearTopologyConfig()],
        auxiliary_systems=[],
        meters=[MeterTopologyConfig()],
        poi=POITopologyConfig(max_export_power_w=15_000_000.0, max_import_power_w=15_000_000.0),
        grid=GridTopologyConfig(),
        ppc=PPCTopologyConfig(plant_rated_active_power_w=15_000_000.0, plant_rated_apparent_power_va=16_000_000.0),
    )

    # 3. Build plant using PlantTopologyFactory without touching PPC or EMS!
    factory = PlantTopologyFactory(plugin_registry=registry)
    plant = factory.build_plant(multi_vendor_config)

    assert len(plant.battery_systems) == 2
    assert len(plant.pcs_units) == 2
    assert plant.battery_systems[0].get_state().metadata.manufacturer == "CATL"
    assert plant.battery_systems[1].get_state().metadata.manufacturer == "Tesla"
    assert plant.pcs_units[0].get_state().metadata.manufacturer == "SMA"
    assert plant.pcs_units[1].get_state().metadata.manufacturer == "Sungrow"

    # 4. Dispatch setpoint via unmodified EMS and PPC after Layer A Startup Sequence
    eq_ctrl = BESSEquipmentController()
    eq_ctrl.execute_startup_sequence(
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        switchgear=plant.switchgear[0],
        container_temp_c=25.0,
        current_time_ns=0,
    )

    ppc = PowerPlantController()
    ems = EnergyManagementSystem()

    acc_p, _ = ems.dispatch_step(
        requested_p_w=10_000_000.0,  # +10 MW discharge setpoint
        requested_q_var=0.0,
        ppc=ppc,
        battery=plant.battery_systems[0],
        bms_list=plant.bms_units,
        pcs_list=plant.pcs_units,
        equipment_controller=eq_ctrl,
    )

    # 5 MW allocated to SMA PCS, 5 MW allocated to Sungrow PCS
    assert acc_p == 10_000_000.0
    assert plant.pcs_units[0].requested_p_w == 5_000_000.0
    assert plant.pcs_units[1].requested_p_w == 5_000_000.0
