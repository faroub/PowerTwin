"""Declarative Pydantic Schemas for Configuration-Driven Plant Topology."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IllustrativeConfigModel(BaseModel):
    """Base for configuration models that declare whether their values are illustrative.

    `AGENTS.md` §2.14 requires illustrative parameters to be clearly labelled.
    The marker is part of the schema so the label travels with the data and can
    be asserted by a test, rather than living only in prose.

    The default is `True`. A parameter set is treated as illustrative unless it
    is explicitly declared to have been validated against authoritative
    documentation or test data: under-labelling is the dangerous direction, so
    the default errs towards labelling.

    The runtime counterpart of this field is
    `backend.app.equipment.models.EquipmentMetadata.is_illustrative`, which the
    plant factory populates from the configuration.
    """

    illustrative: bool = Field(
        default=True,
        description=(
            "True when these parameters are illustrative: representative values "
            "chosen for demonstration and not validated against authoritative "
            "documentation or test data. Set to False only for a parameter set "
            "that was validated against a datasheet or a test campaign."
        ),
    )


class BatteryParameterOverride(IllustrativeConfigModel):
    """Calibrated parameters for one container's battery physical model.

    A digital-twin calibration fits the parameters that the battery model
    exposes but the topology does not: the open-circuit-voltage curve, the
    series internal resistance, the thermal mass, the cooling rate and the
    auxiliary load. The values are applied to the authoritative physical
    model by the plant factory, so a calibrated container runs with them
    whichever plugin it uses.

    Every field is optional: an absent field means "keep the configured
    value". A field that is present and null is not the same thing, and is
    refused by the schema.

    The model forbids unknown keys. The rest of the topology schema follows
    Pydantic's default of ignoring them, which is how a misspelled key
    disappears without a word; this model is new, so there is no
    back-compatibility to protect, and a calibration that silently drops a
    parameter would be worse than one that refuses to load.
    """

    model_config = ConfigDict(extra="forbid")

    ocv_intercept: float | None = Field(
        default=None,
        description="Open-circuit voltage at zero SoC, as a fraction of the nominal voltage.",
    )
    ocv_slope: float | None = Field(
        default=None,
        description=(
            "Open-circuit voltage rise across the whole SoC range, as a fraction "
            "of the nominal voltage."
        ),
    )
    internal_resistance_ohm: float | None = Field(
        default=None, description="Series internal resistance in ohms."
    )
    cooling_coefficient_per_s: float | None = Field(
        default=None, description="Lumped cooling rate toward the ambient reference, per second."
    )
    thermal_mass_j_per_c: float | None = Field(
        default=None, description="Lumped container thermal mass in J/degC."
    )
    aux_power_w: float | None = Field(
        default=None, description="Continuous auxiliary container load in Watts."
    )
    calibration_source: str | None = Field(
        default=None,
        description=(
            "What the fitted values came from: a dataset path, a test campaign "
            "identifier, or a description of the data the fit is based on."
        ),
    )
    calibration_report_sha256: str | None = Field(
        default=None,
        description="The SHA-256 of the calibration report the values were taken from.",
    )


class ContainerConfig(IllustrativeConfigModel):
    """Battery Container topology specification."""

    container_id: str = Field(description="Unique container ID e.g. 'CONTAINER_01'")
    plugin_id: str = Field(default="generic_battery_v1")
    vendor: str = Field(default="Generic Vendor")
    capacity_wh: float = Field(description="Nominal container energy capacity in Wh")
    nominal_voltage_v: float = Field(default=1000.0, description="Nominal DC voltage in V")
    racks_count: int = Field(default=16, description="Racks per container")
    initial_soc_pct: float = Field(default=50.0)
    battery_parameters: BatteryParameterOverride | None = Field(
        default=None,
        description=(
            "Calibrated parameters for this container's battery physical model. "
            "Absent means the container runs on the model's configured defaults."
        ),
    )

    @model_validator(mode="after")
    def validate_parameter_label(self) -> "ContainerConfig":
        """A container cannot claim validation while carrying illustrative parameters.

        `AGENTS.md` §2.14 requires illustrative parameters to be labelled. A
        container that carries a calibrated parameter set which is itself
        illustrative has not been validated, whatever the container's own
        marker says.
        """
        if (
            self.battery_parameters is not None
            and self.battery_parameters.illustrative
            and not self.illustrative
        ):
            raise ValueError(
                "The container declares illustrative='false' but its calibrated battery "
                "parameters are illustrative. A container cannot claim to be validated "
                "while carrying parameters that are not."
            )
        return self


class PCSUnitConfig(IllustrativeConfigModel):
    """PCS Inverter topology specification."""

    pcs_id: str = Field(description="Unique PCS ID e.g. 'PCS_01'")
    plugin_id: str = Field(default="generic_pcs_v1")
    vendor: str = Field(default="Generic Inverter Vendor")
    rated_active_power_w: float = Field(description="Rated active power (+W = Discharge)")
    rated_apparent_power_va: float = Field(description="Max apparent power S_max")
    ac_voltage_v: float = Field(default=690.0, description="AC nominal terminal voltage")
    dc_voltage_min_v: float = Field(default=800.0)
    dc_voltage_max_v: float = Field(default=1200.0)


class TransformerTopologyConfig(IllustrativeConfigModel):
    """Step-Up Transformer topology specification."""

    transformer_id: str = Field(default="XFRM_01")
    rating_va: float = Field(description="Nominal apparent power rating in VA")
    primary_voltage_v: float = Field(default=690.0)
    secondary_voltage_v: float = Field(default=13800.0)


class SwitchgearTopologyConfig(IllustrativeConfigModel):
    """MV Switchgear topology specification."""

    switchgear_id: str = Field(default="SWG_01")
    rated_voltage_v: float = Field(default=13800.0)
    rated_current_a: float = Field(default=2000.0)


class AuxiliaryTopologyConfig(IllustrativeConfigModel):
    """Auxiliary Systems topology specification."""

    aux_id: str = Field(default="AUX_01")
    plugin_id: str = Field(default="dummy_auxiliary_v1")
    aux_base_power_w: float = Field(default=10000.0)


class MeterTopologyConfig(IllustrativeConfigModel):
    """Power Meter topology specification."""

    meter_id: str = Field(default="METER_01")
    nominal_voltage_v: float = Field(default=13800.0)


class POITopologyConfig(IllustrativeConfigModel):
    """Point of Interconnection (POI) topology specification."""

    poi_id: str = Field(default="POI_METER_01")
    nominal_voltage_v: float = Field(default=13800.0)
    max_export_power_w: float = Field(description="Max export power limit (+W)")
    max_import_power_w: float = Field(description="Max import power limit (-W)")


class GridTopologyConfig(IllustrativeConfigModel):
    """Synthetic Grid Model topology specification."""

    grid_id: str = Field(default="GRID_MODEL_01")
    plugin_id: str = Field(default="dummy_grid_v1")
    nominal_frequency_hz: float = Field(default=50.0, description="Grid frequency (50 Hz or 60 Hz)")
    nominal_voltage_v: float = Field(default=13800.0)
    short_circuit_mva: float = Field(default=500.0)


class EquipmentControllerTopologyConfig(IllustrativeConfigModel):
    """Layer A Equipment Controller configuration."""

    controller_id: str = Field(default="EQ_CTRL_01")
    max_container_temp_c: float = Field(default=45.0)


class PPCTopologyConfig(IllustrativeConfigModel):
    """Layer B PPC configuration."""

    ppc_id: str = Field(default="PPC_01")
    plant_rated_active_power_w: float = Field(description="Max plant active power")
    plant_rated_apparent_power_va: float = Field(description="Max plant apparent power")


class EMSTopologyConfig(IllustrativeConfigModel):
    """Layer C EMS configuration."""

    ems_id: str = Field(default="EMS_01")
    mode: str = Field(default="MANUAL_DISPATCH")
    target_soc_pct: float = Field(default=50.0)


class GridServiceTopologyConfig(IllustrativeConfigModel):
    """Grid Service configuration."""

    service_id: str = Field(default="GRID_SVC_01")
    service_type: str = Field(default="FREQUENCY_RESPONSE")


class PlantTopologyConfig(IllustrativeConfigModel):
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

    @model_validator(mode="after")
    def _reconcile_illustrative_marker(self) -> "PlantTopologyConfig":
        """Derive the plant-level marker, and refuse an under-labelled plant.

        The plant-level marker means "this plant contains illustrative
        parameters". It is derived from the equipment markers when the author
        did not state it, and it may never contradict them: a plant whose root
        claims to be validated while one of its items is illustrative would
        under-label the plant, which is exactly what `AGENTS.md` §2.14
        forbids.
        """
        item_markers: list[bool] = [
            *(c.illustrative for c in self.containers),
            *(p.illustrative for p in self.pcs_units),
            *(t.illustrative for t in self.transformers),
            *(s.illustrative for s in self.switchgear),
            *(a.illustrative for a in self.auxiliary_systems),
            *(m.illustrative for m in self.meters),
            self.poi.illustrative,
            self.grid.illustrative,
            self.equipment_controller.illustrative,
            self.ppc.illustrative,
            self.ems.illustrative,
            *(g.illustrative for g in self.grid_services),
        ]
        contains_illustrative = any(item_markers)

        if contains_illustrative and not self.illustrative:
            raise ValueError(
                "The plant declares illustrative='false' but at least one of its "
                "items is marked illustrative. A plant that contains illustrative "
                "parameters must be labelled as illustrative at plant level too."
            )

        if not contains_illustrative and "illustrative" not in self.model_fields_set:
            # Every item was explicitly marked as validated, so the plant is too.
            self.illustrative = False
        return self
