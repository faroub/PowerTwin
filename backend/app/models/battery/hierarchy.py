"""Configurable Battery System Structural Hierarchy.

Hierarchy Model: Plant -> Container -> Master BMS -> Rack -> Module -> Cell.
Supports topology aggregation for initial WP04A release while preserving physical counts.
"""

from pydantic import BaseModel, Field


class CellSpec(BaseModel):
    """Individual battery cell technical specification."""

    chemistry: str = Field(default="LFP", description="Cell chemistry e.g. LFP, NMC")
    nominal_voltage_v: float = Field(default=3.2, description="Nominal cell OCV in Volts")
    max_voltage_v: float = Field(default=3.65, description="Upper voltage cutoff in Volts")
    min_voltage_v: float = Field(default=2.5, description="Lower voltage cutoff in Volts")
    capacity_ah: float = Field(default=280.0, description="Cell capacity in Ampere-hours")


class ModuleSpec(BaseModel):
    """Battery module specification composed of series/parallel cells."""

    cells_in_series: int = Field(default=16, description="Number of series cells per module")
    cells_in_parallel: int = Field(default=1, description="Number of parallel cell strings")

    @property
    def total_cells(self) -> int:
        return self.cells_in_series * self.cells_in_parallel


class RackSpec(BaseModel):
    """Battery rack specification composed of series modules and a Rack BMS."""

    rack_id: str = Field(default="RACK_01")
    modules_count: int = Field(default=12, description="Number of modules per rack")


class ContainerSpec(BaseModel):
    """Battery container enclosure specification housing multiple racks."""

    container_id: str = Field(default="CONTAINER_01")
    racks_count: int = Field(default=16, description="Number of racks per container")
    hvac_unit_id: str = Field(default="HVAC_01")


class BatteryHierarchyConfig(BaseModel):
    """Top-level Plant battery structural hierarchy configuration."""

    containers_count: int = Field(default=2, description="Number of containers in plant")
    racks_per_container: int = Field(default=16, description="Racks per container")
    modules_per_rack: int = Field(default=12, description="Modules per rack")
    cell_spec: CellSpec = Field(default_factory=CellSpec)
    module_spec: ModuleSpec = Field(default_factory=ModuleSpec)

    @property
    def total_racks(self) -> int:
        return self.containers_count * self.racks_per_container

    @property
    def total_modules(self) -> int:
        return self.total_racks * self.modules_per_rack

    @property
    def total_cells(self) -> int:
        return self.total_modules * self.module_spec.total_cells

    def calculate_nominal_dc_voltage_v(self) -> float:
        """Calculate nominal DC rack/container voltage in Volts."""
        series_cells = self.modules_per_rack * self.module_spec.cells_in_series
        return series_cells * self.cell_spec.nominal_voltage_v

    def calculate_total_energy_wh(self) -> float:
        """Calculate total plant nominal energy capacity in Watt-hours."""
        cell_energy_wh = self.cell_spec.nominal_voltage_v * self.cell_spec.capacity_ah
        return self.total_cells * cell_energy_wh
