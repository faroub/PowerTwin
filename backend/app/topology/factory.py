"""Plant Topology Factory — Dynamic Construction of BESS Plant Models."""

import logging
from typing import Any

import yaml
from plugins.dummy_auxiliary import DummyAuxiliaryPlugin
from plugins.dummy_grid import DummyGridPlugin
from plugins.generic_battery import GenericBatteryPlugin
from plugins.generic_pcs import GenericPCSPlugin
from plugins.registry import PluginRegistry
from pydantic import BaseModel

from backend.app.controllers.ems import EMSConfigModel, EnergyManagementSystem
from backend.app.controllers.equipment_controller import (
    BESSEquipmentController,
    EquipmentControllerConfig,
)
from backend.app.controllers.ppc import PowerPlantController, PPCConfigModel
from backend.app.equipment.models import EquipmentMetadata
from backend.app.models.battery.bms import BMSProtectionLimits, GenericBMSModel
from backend.app.models.battery.system import BatterySystemConfigModel, GenericBatterySystemModel
from backend.app.models.bop.switchgear import GenericSwitchgearModel, SwitchgearConfigModel
from backend.app.models.bop.transformer import GenericTransformerModel, TransformerConfigModel
from backend.app.models.grid.grid_model import GenericGridModel, GridConfigModel
from backend.app.models.grid.network import PlantElectricalNetwork
from backend.app.models.grid.poi_model import POIConfigModel, POIModel
from backend.app.models.meter.meter_model import GenericMeterModel, MeterConfigModel
from backend.app.models.pcs.pcs_model import GenericPCSModel, PCSConfigModel
from backend.app.simulation.config import SimulationConfiguration
from backend.app.simulation.manager import SimulationRunManager
from backend.app.topology.schema import PlantTopologyConfig
from backend.app.topology.validator import TopologyValidator

logger = logging.getLogger(__name__)


class BuiltPlantInstance(BaseModel):
    """Container holding all instantiated components of a built plant topology."""

    model_config = {"arbitrary_types_allowed": True}

    topology_config: PlantTopologyConfig
    plugin_registry: PluginRegistry
    battery_systems: list[GenericBatterySystemModel]
    bms_units: list[GenericBMSModel]
    pcs_units: list[GenericPCSModel]
    transformers: list[GenericTransformerModel]
    switchgear: list[GenericSwitchgearModel]
    meters: list[GenericMeterModel]
    poi: POIModel
    grid: GenericGridModel
    equipment_controller: BESSEquipmentController
    ppc: PowerPlantController
    ems: EnergyManagementSystem
    network: PlantElectricalNetwork
    simulation_engine: SimulationRunManager


class PlantTopologyFactory:
    """Factory dynamically building BESS plant topologies from configuration."""

    def __init__(self, plugin_registry: PluginRegistry | None = None) -> None:
        self.plugin_registry: PluginRegistry = (
            plugin_registry if plugin_registry is not None else PluginRegistry()
        )
        self._ensure_reference_plugins_registered()

    def _ensure_reference_plugins_registered(self) -> None:
        """Register built-in reference equipment plugins."""
        plugins = (
            GenericBatteryPlugin,
            GenericPCSPlugin,
            DummyGridPlugin,
            DummyAuxiliaryPlugin,
        )
        for plugin_cls in plugins:
            try:
                self.plugin_registry.register_plugin_class(plugin_cls)
            except Exception:
                pass

    @classmethod
    def load_config_from_yaml(cls, yaml_filepath: str) -> PlantTopologyConfig:
        """Load and parse YAML topology configuration file."""
        with open(yaml_filepath, encoding="utf-8") as f:
            raw_dict = yaml.safe_load(f)
        return PlantTopologyConfig(**raw_dict)

    def build_plant(
        self,
        config: PlantTopologyConfig | dict[str, Any],
        sim_config: SimulationConfiguration | None = None,
    ) -> BuiltPlantInstance:
        """Build full plant instance and wire simulation engine."""
        if isinstance(config, dict):
            parsed_config = PlantTopologyConfig(**config)
        else:
            parsed_config = config

        # 1. Validate Topology
        validator = TopologyValidator(plugin_registry=self.plugin_registry)
        validator.validate_or_raise(parsed_config)

        logger.info(
            "Topology validation passed for plant '%s' (%s)",
            parsed_config.name,
            parsed_config.plant_id,
        )

        # 2. Instantiate Equipment Models
        battery_systems: list[GenericBatterySystemModel] = []
        bms_units: list[GenericBMSModel] = []

        for c in parsed_config.containers:
            b_cfg = BatterySystemConfigModel(
                capacity_wh=c.capacity_wh,
                nominal_voltage_v=c.nominal_voltage_v,
                initial_soc_pct=c.initial_soc_pct,
            )
            bat = GenericBatterySystemModel(equipment_id=c.container_id, config=b_cfg)
            bat.metadata = EquipmentMetadata(manufacturer=c.vendor, model_name=c.plugin_id)
            battery_systems.append(bat)

            bms_limits = BMSProtectionLimits(
                max_charge_current_a=15000.0,
                max_discharge_current_a=15000.0,
            )
            bms = GenericBMSModel(equipment_id=f"BMS_{c.container_id}", limits=bms_limits)
            bms_units.append(bms)

        pcs_units: list[GenericPCSModel] = []
        for pcs_c in parsed_config.pcs_units:
            p_cfg = PCSConfigModel(
                rated_active_power_w=pcs_c.rated_active_power_w,
                rated_apparent_power_va=pcs_c.rated_apparent_power_va,
                ac_voltage_nominal_v=pcs_c.ac_voltage_v,
                dc_voltage_min_v=pcs_c.dc_voltage_min_v,
                dc_voltage_max_v=pcs_c.dc_voltage_max_v,
            )
            pcs_inst = GenericPCSModel(equipment_id=pcs_c.pcs_id, config=p_cfg)
            pcs_inst.metadata = EquipmentMetadata(
                manufacturer=pcs_c.vendor, model_name=pcs_c.plugin_id
            )
            pcs_units.append(pcs_inst)

        transformers: list[GenericTransformerModel] = []
        for x_c in parsed_config.transformers:
            x_cfg = TransformerConfigModel(
                rating_va=x_c.rating_va,
                primary_voltage_v=x_c.primary_voltage_v,
                secondary_voltage_v=x_c.secondary_voltage_v,
            )
            transformers.append(
                GenericTransformerModel(equipment_id=x_c.transformer_id, config=x_cfg)
            )

        switchgear_list: list[GenericSwitchgearModel] = []
        for s_c in parsed_config.switchgear:
            s_cfg = SwitchgearConfigModel(
                rated_voltage_v=s_c.rated_voltage_v, rated_current_a=s_c.rated_current_a
            )
            switchgear_list.append(
                GenericSwitchgearModel(equipment_id=s_c.switchgear_id, config=s_cfg)
            )

        meters: list[GenericMeterModel] = []
        for m_c in parsed_config.meters:
            m_cfg = MeterConfigModel(nominal_voltage_v=m_c.nominal_voltage_v)
            meters.append(GenericMeterModel(equipment_id=m_c.meter_id, config=m_cfg))

        poi = POIModel(
            equipment_id=parsed_config.poi.poi_id,
            config=POIConfigModel(
                nominal_voltage_v=parsed_config.poi.nominal_voltage_v,
                max_export_power_w=parsed_config.poi.max_export_power_w,
                max_import_power_w=parsed_config.poi.max_import_power_w,
            ),
        )

        grid = GenericGridModel(
            equipment_id=parsed_config.grid.grid_id,
            config=GridConfigModel(
                nominal_frequency_hz=parsed_config.grid.nominal_frequency_hz,
                nominal_voltage_v=parsed_config.grid.nominal_voltage_v,
                short_circuit_mva=parsed_config.grid.short_circuit_mva,
            ),
        )

        # 3. Instantiate Controllers
        eq_ctrl = BESSEquipmentController(
            equipment_id=parsed_config.equipment_controller.controller_id,
            config=EquipmentControllerConfig(
                max_container_temp_c=parsed_config.equipment_controller.max_container_temp_c
            ),
        )

        ppc = PowerPlantController(
            equipment_id=parsed_config.ppc.ppc_id,
            config=PPCConfigModel(
                plant_rated_active_power_w=parsed_config.ppc.plant_rated_active_power_w,
                plant_rated_apparent_power_va=parsed_config.ppc.plant_rated_apparent_power_va,
            ),
        )

        ems = EnergyManagementSystem(
            equipment_id=parsed_config.ems.ems_id,
            config=EMSConfigModel(target_soc_pct=parsed_config.ems.target_soc_pct),
        )

        # 4. Connect Plant Electrical Network
        network = PlantElectricalNetwork(
            battery=battery_systems[0],
            pcs=pcs_units[0],
            transformer=transformers[0],
            switchgear=switchgear_list[0],
            poi=poi,
            meter=meters[0],
            grid=grid,
        )

        # 5. Wire Simulation Engine
        engine_config = (
            sim_config
            if sim_config is not None
            else SimulationConfiguration(tick_step_ns=10_000_000, speed_factor=0.0)
        )
        simulation_engine = SimulationRunManager(config=engine_config)

        # Instantiate plugins for containers and PCS with unique task names
        for c in parsed_config.containers:
            bat_plugin = GenericBatteryPlugin(equipment_id=c.container_id)
            bat_plugin.initialize(
                {
                    "capacity_wh": c.capacity_wh,
                    "nominal_voltage_v": c.nominal_voltage_v,
                    "initial_soc_pct": c.initial_soc_pct,
                }
            )
            bat_plugin.enabled = True
            simulation_engine.register_task(bat_plugin)

        for pcs_c in parsed_config.pcs_units:
            pcs_plugin = GenericPCSPlugin(equipment_id=pcs_c.pcs_id)
            pcs_plugin.initialize(
                {
                    "rated_power_w": pcs_c.rated_active_power_w,
                    "rated_apparent_power_va": pcs_c.rated_apparent_power_va,
                }
            )
            pcs_plugin.enabled = True
            simulation_engine.register_task(pcs_plugin)

        return BuiltPlantInstance(
            topology_config=parsed_config,
            plugin_registry=self.plugin_registry,
            battery_systems=battery_systems,
            bms_units=bms_units,
            pcs_units=pcs_units,
            transformers=transformers,
            switchgear=switchgear_list,
            meters=meters,
            poi=poi,
            grid=grid,
            equipment_controller=eq_ctrl,
            ppc=ppc,
            ems=ems,
            network=network,
            simulation_engine=simulation_engine,
        )
