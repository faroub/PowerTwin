"""Read-only Plant Topology Endpoint.

The HMI needs to show an operator the plant that is actually running: its
identity, its ratings and the equipment it contains. Before this endpoint
existed, the only configuration the platform published was the platform's own
settings, and a screen that wanted the plant's topology had nothing to read.
The removed ``ConfigurationView`` filled that gap by printing a development
template as though it were a live plant's configuration, which is why it was
removed rather than repaired.

This endpoint closes the gap honestly:

* it reads the **running** plant from the application-scoped runtime, the same
  source the Plant Overview reads, so a load-balanced request always sees the
  plant that owns the engine;
* it reports the configuration the plant was **built from**, not a template;
* it labels every illustrative parameter as illustrative, as
  ``AGENTS.md`` §2.14 requires;
* it is read-only. It cannot change a plant, and there is no route here that
  writes one.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.app.core.rbac import Permission, require_permission
from backend.app.core.safety import SafetyGuardrailsReport, get_safety_report
from backend.app.simulation.runtime import get_simulation_runtime
from backend.app.topology.schema import PlantTopologyConfig

router = APIRouter(tags=["Plant Topology"])


class TopologyEquipment(BaseModel):
    """One piece of equipment of the running plant.

    Every field that the topology does not declare is ``null``. A value the
    configuration does not carry is reported as absent rather than filled in
    with a placeholder, because a placeholder on a configuration screen reads
    as a configured value.
    """

    equipment_id: str = Field(description="Unique equipment identifier")
    equipment_type: str = Field(description="Equipment category, e.g. BATTERY_SYSTEM")
    manufacturer: str | None = Field(
        default=None,
        description="The vendor the topology declares, or null when it declares none",
    )
    plugin_id: str | None = Field(
        default=None, description="The plugin that implements this equipment"
    )
    illustrative: bool = Field(
        description="True when the parameters of this item are illustrative"
    )
    capacity_wh: float | None = Field(default=None, description="Nominal energy capacity in Wh")
    rated_power_w: float | None = Field(default=None, description="Rated active power in W")
    rated_apparent_power_va: float | None = Field(
        default=None, description="Rated apparent power in VA"
    )
    nominal_voltage_v: float | None = Field(default=None, description="Nominal voltage in V")
    specifications: dict[str, float] = Field(
        default_factory=dict,
        description="The remaining type-specific ratings, in SI units",
    )


class TopologyResponse(BaseModel):
    """The topology of the running plant."""

    plant_configured: bool = Field(
        description="False when no plant is attached to the running platform"
    )
    plant_id: str | None = Field(default=None, description="The plant identifier")
    plant_name: str | None = Field(default=None, description="The plant name")
    illustrative: bool | None = Field(
        default=None,
        description="True when the plant contains illustrative parameters",
    )
    rated_power_w: float | None = Field(default=None, description="Plant rated active power in W")
    rated_energy_wh: float | None = Field(default=None, description="Plant rated energy in Wh")
    source_path: str | None = Field(
        default=None, description="The topology configuration the plant was built from"
    )
    equipment: list[TopologyEquipment] = Field(
        default_factory=list, description="Every item of the plant's equipment inventory"
    )
    counts: dict[str, int] = Field(
        default_factory=dict, description="How many items of each equipment type the plant has"
    )
    message: str | None = Field(
        default=None, description="Why the plant is not configured, when it is not"
    )
    safety: SafetyGuardrailsReport = Field(
        default_factory=get_safety_report,
        description="The platform safety report",
    )


def _equipment_from_config(config: PlantTopologyConfig) -> list[TopologyEquipment]:
    """Build the equipment inventory of a plant from its topology configuration.

    The inventory is read from the configuration the plant was built from, so
    it names the identifiers, the vendors and the ratings that are actually in
    force. A vendor the configuration does not declare is reported as absent:
    the models fall back on a placeholder manufacturer, and a placeholder on a
    configuration screen reads as a configured vendor.
    """
    items: list[TopologyEquipment] = []

    for container in config.containers:
        items.append(
            TopologyEquipment(
                equipment_id=container.container_id,
                equipment_type="BATTERY_SYSTEM",
                manufacturer=container.vendor,
                plugin_id=container.plugin_id,
                illustrative=container.illustrative,
                capacity_wh=container.capacity_wh,
                nominal_voltage_v=container.nominal_voltage_v,
                specifications={
                    "racks_count": float(container.racks_count),
                    "initial_soc_pct": container.initial_soc_pct,
                },
            )
        )

    for pcs in config.pcs_units:
        items.append(
            TopologyEquipment(
                equipment_id=pcs.pcs_id,
                equipment_type="PCS",
                manufacturer=pcs.vendor,
                plugin_id=pcs.plugin_id,
                illustrative=pcs.illustrative,
                rated_power_w=pcs.rated_active_power_w,
                rated_apparent_power_va=pcs.rated_apparent_power_va,
                nominal_voltage_v=pcs.ac_voltage_v,
                specifications={
                    "dc_voltage_min_v": pcs.dc_voltage_min_v,
                    "dc_voltage_max_v": pcs.dc_voltage_max_v,
                },
            )
        )

    for transformer in config.transformers:
        items.append(
            TopologyEquipment(
                equipment_id=transformer.transformer_id,
                equipment_type="TRANSFORMER",
                illustrative=transformer.illustrative,
                rated_apparent_power_va=transformer.rating_va,
                nominal_voltage_v=transformer.secondary_voltage_v,
                specifications={
                    "primary_voltage_v": transformer.primary_voltage_v,
                    "secondary_voltage_v": transformer.secondary_voltage_v,
                },
            )
        )

    for switchgear in config.switchgear:
        items.append(
            TopologyEquipment(
                equipment_id=switchgear.switchgear_id,
                equipment_type="SWITCHGEAR",
                illustrative=switchgear.illustrative,
                nominal_voltage_v=switchgear.rated_voltage_v,
                specifications={"rated_current_a": switchgear.rated_current_a},
            )
        )

    for auxiliary in config.auxiliary_systems:
        items.append(
            TopologyEquipment(
                equipment_id=auxiliary.aux_id,
                equipment_type="AUXILIARY_SYSTEM",
                plugin_id=auxiliary.plugin_id,
                illustrative=auxiliary.illustrative,
                rated_power_w=auxiliary.aux_base_power_w,
            )
        )

    for meter in config.meters:
        items.append(
            TopologyEquipment(
                equipment_id=meter.meter_id,
                equipment_type="METER",
                illustrative=meter.illustrative,
                nominal_voltage_v=meter.nominal_voltage_v,
            )
        )

    items.append(
        TopologyEquipment(
            equipment_id=config.poi.poi_id,
            equipment_type="POI",
            illustrative=config.poi.illustrative,
            nominal_voltage_v=config.poi.nominal_voltage_v,
            specifications={
                "max_export_power_w": config.poi.max_export_power_w,
                "max_import_power_w": config.poi.max_import_power_w,
            },
        )
    )

    items.append(
        TopologyEquipment(
            equipment_id=config.grid.grid_id,
            equipment_type="GRID_MODEL",
            plugin_id=config.grid.plugin_id,
            illustrative=config.grid.illustrative,
            nominal_voltage_v=config.grid.nominal_voltage_v,
            specifications={
                "nominal_frequency_hz": config.grid.nominal_frequency_hz,
                "short_circuit_mva": config.grid.short_circuit_mva,
            },
        )
    )

    return items


@router.get("/topology")
async def get_plant_topology(
    request: Request,
    _user: Any = Depends(require_permission(Permission.READ_CONFIG)),
) -> TopologyResponse:
    """Return the topology of the running plant.

    The plant is read from the application-scoped runtime, so the answer
    always describes the plant that owns the engine. When no plant is
    attached, the endpoint says so instead of answering with the inventory of
    some other plant.
    """
    runtime = get_simulation_runtime(request=request)
    plant = runtime.active_plant

    if plant is None:
        return TopologyResponse(
            plant_configured=False,
            message=(
                "No plant is attached to the running platform. The topology is built at "
                "start-up from TOPOLOGY_CONFIG_PATH."
            ),
            safety=get_safety_report(),
        )

    config = plant.topology_config
    equipment = _equipment_from_config(config)
    counts: dict[str, int] = {}
    for item in equipment:
        counts[item.equipment_type] = counts.get(item.equipment_type, 0) + 1

    return TopologyResponse(
        plant_configured=True,
        plant_id=config.plant_id,
        plant_name=config.name,
        illustrative=config.illustrative,
        rated_power_w=config.rated_power_w,
        rated_energy_wh=config.rated_energy_wh,
        source_path=plant.topology_source_path,
        equipment=equipment,
        counts=counts,
        safety=get_safety_report(),
    )
