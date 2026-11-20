"""Declarative Pydantic Schemas for Configuration-Driven Plant Topology."""

from typing import Any

from pydantic import BaseModel, Field


class ContainerConfig(BaseModel):
    """Battery Container topology specification."""

    container_id: str = Field(description="Unique container ID e.g. 'CONTAINER_01'")
    plugin_id: str = Field(default="generic_battery_v1")
    vendor: str = Field(default="Generic Vendor")
    capacity_wh: float = Field(description="Nominal container energy capacity in Wh")
    nominal_voltage_v: float = Field(default=1000.0, description="Nominal DC voltage in V")
    racks_count: int = Field(default=16, description="Racks per container")
    initial_soc_pct: float = Field(default=50.0)


class PCSUnitConfig(BaseModel):
    """PCS Inverter topology specification."""

    pcs_id: str = Field(description="Unique PCS ID e.g. 'PCS_01'")
    plugin_id: str = Field(default="generic_pcs_v1")
    vendor: str = Field(default="Generic Inverter Vendor")
    rated_active_power_w: float = Field(description="Rated active power (+W = Discharge)")
    rated_apparent_power_va: float = Field(description="Max apparent power S_max")
    ac_voltage_v: float = Field(default=690.0, description="AC nominal terminal voltage")
    dc_voltage_min_v: float = Field(default=800.0)
    dc_voltage_max_v: float = Field(default=1200.0)


class TransformerTopologyConfig(BaseModel):
    """Step-Up Transformer topology specification."""

    transformer_id: str = Field(default="XFRM_01")
    rating_va: float = Field(description="Nominal apparent power rating in VA")
    primary_voltage_v: float = Field(default=690.0)
    secondary_voltage_v: float = Field(default=13800.0)


class SwitchgearTopologyConfig(BaseModel):
    """MV Switchgear topology specification."""

    switchgear_id: str = Field(default="SWG_01")
    rated_voltage_v: float = Field(default=13800.0)
    rated_current_a: float = Field(default=2000.0)


class AuxiliaryTopologyConfig(BaseModel):
    """Auxiliary Systems topology specification."""

    aux_id: str = Field(default="AUX_01")
    plugin_id: str = Field(default="dummy_auxiliary_v1")
    aux_base_power_w: float = Field(default=10000.0)


class MeterTopologyConfig(BaseModel):
    """Power Meter topology specification."""

    meter_id: str = Field(default="METER_01")
    nominal_voltage_v: float = Field(default=13800.0)


class POITopologyConfig(BaseModel):
    """Point of Interconnection (POI) topology specification."""

    poi_id: str = Field(default="POI_METER_01")
    nominal_voltage_v: float = Field(default=13800.0)
    max_export_power_w: float = Field(description="Max export power limit (+W)")
    max_import_power_w: float = Field(description="Max import power limit (-W)")


class GridTopologyConfig(BaseModel):
    """Synthetic Grid Model topology specification."""

    grid_id: str = Field(default="GRID_MODEL_01")
    plugin_id: str = Field(default="dummy_grid_v1")
    nominal_frequency_hz: float = Field(
        default=50.0, description="Grid frequency (50 Hz or 60 Hz)"
    )
    nominal_voltage_v: float = Field(default=13800.0)
    short_circuit_mva: float = Field(default=500.0)


class EquipmentControllerTopologyConfig(BaseModel):
    """Layer A Equipment Controller configuration."""

    controller_id: str = Field(default="EQ_CTRL_01")
    max_container_temp_c: float = Field(default=45.0)


class PPCTopologyConfig(BaseModel):
    """Layer B PPC configuration."""

    ppc_id: str = Field(default="PPC_01")
    plant_rated_active_power_w: float = Field(description="Max plant active power")
    plant_rated_apparent_power_va: float = Field(description="Max plant apparent power")


class EMSTopologyConfig(BaseModel):
    """Layer C EMS configuration."""

    ems_id: str = Field(default="EMS_01")
    mode: str = Field(default="MANUAL_DISPATCH")
    target_soc_pct: float = Field(default=50.0)


class GridServiceTopologyConfig(BaseModel):
    """Grid Service configuration."""

    service_id: str = Field(default="GRID_SVC_01")
    service_type: str = Field(default="FREQUENCY_RESPONSE")


class PlantTopologyConfig(BaseModel):
    """Root BESS Plant Topology declarative configuration schema."""

    plant_id: str = Field(default="POWER_TWIN_PLANT_01")
    name: str = Field(default="PowerTwin Reference BESS Plant")
    rated_power_w: float = Field(description="Plant rated active power (W)")
    rated_energy_wh: float = Field(description="Plant rated energy capacity (Wh)")
    containers: list[ContainerConfig]
    pcs_units: list[PCSUnitConfig]
    transformers: list[TransformerTopologyConfig]
    switchgear: list[SwitchgearTopologyConfig]
    auxiliary_systems: list[AuxiliaryTopologyConfig]
    meters: list[MeterTopologyConfig]
    poi: POITopologyConfig
    grid: GridTopologyConfig
    equipment_controller: EquipmentControllerTopologyConfig = Field(
        default_factory=EquipmentControllerTopologyConfig
    )
    ppc: PPCTopologyConfig
    ems: EMSTopologyConfig = Field(default_factory=EMSTopologyConfig)
    grid_services: list[GridServiceTopologyConfig] = Field(default_factory=list)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)
