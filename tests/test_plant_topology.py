"""Automated Unit Tests for WP06 Configuration-Driven Plant Topology."""

import pytest

from backend.app.topology.factory import PlantTopologyFactory
from backend.app.topology.schema import (
    ContainerConfig,
    GridTopologyConfig,
    PCSUnitConfig,
    PlantTopologyConfig,
    POITopologyConfig,
    PPCTopologyConfig,
    SwitchgearTopologyConfig,
    TransformerTopologyConfig,
)
from backend.app.topology.validator import TopologyValidationError, TopologyValidator
from plugins.registry import PluginRegistry


def test_reference_10mw_20mwh_plant_topology_loading() -> None:
    """Test loading and building the initial 10 MW / 20 MWh reference plant."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(
        factory.load_config_from_yaml("configs/reference_10mw_20mwh.yaml")
    )

    assert plant.topology_config.rated_power_w == 10_000_000.0
    assert plant.topology_config.rated_energy_wh == 20_000_000.0
    assert len(plant.battery_systems) == 4
    assert len(plant.pcs_units) == 4
    assert len(plant.transformers) == 1
    assert plant.grid.config.nominal_frequency_hz == 50.0


def test_variant_50mw_200mwh_multi_vendor_plant_loading() -> None:
    """Test loading and building the secondary 50 MW / 200 MWh multi-vendor variant plant."""
    factory = PlantTopologyFactory()
    plant = factory.build_plant(
        factory.load_config_from_yaml("configs/variant_50mw_200mwh.yaml")
    )

    assert plant.topology_config.rated_power_w == 50_000_000.0
    assert plant.topology_config.rated_energy_wh == 200_000_000.0
    assert len(plant.battery_systems) == 10
    assert len(plant.pcs_units) == 10
    assert len(plant.transformers) == 2
    assert plant.grid.config.nominal_frequency_hz == 60.0


def test_duplicate_identifier_detection() -> None:
    """Test validator detects duplicate equipment IDs with readable error report."""
    validator = TopologyValidator()
    config = PlantTopologyConfig(
        rated_power_w=10_000_000.0,
        rated_energy_wh=20_000_000.0,
        containers=[
            ContainerConfig(container_id="DUPLICATE_ID", capacity_wh=10_000_000.0),
        ],
        pcs_units=[
            PCSUnitConfig(
                pcs_id="DUPLICATE_ID",
                rated_active_power_w=5_000_000.0,
                rated_apparent_power_va=5_500_000.0,
            ),  # Duplicate ID!
            PCSUnitConfig(
                pcs_id="PCS_02",
                rated_active_power_w=5_000_000.0,
                rated_apparent_power_va=5_500_000.0,
            ),
        ],
        transformers=[TransformerTopologyConfig(rating_va=12_000_000.0)],
        switchgear=[SwitchgearTopologyConfig()],
        auxiliary_systems=[],
        meters=[],
        poi=POITopologyConfig(
            max_export_power_w=10_000_000.0, max_import_power_w=10_000_000.0
        ),
        grid=GridTopologyConfig(),
        ppc=PPCTopologyConfig(
            plant_rated_active_power_w=10_000_000.0,
            plant_rated_apparent_power_va=11_000_000.0,
        ),
    )

    errors = validator.validate_topology(config)
    assert any("Duplicate equipment ID 'DUPLICATE_ID'" in err for err in errors)

    with pytest.raises(TopologyValidationError) as exc_info:
        validator.validate_or_raise(config)
    assert "Duplicate equipment ID 'DUPLICATE_ID'" in str(exc_info.value)


def test_missing_required_components_detection() -> None:
    """Test validator detects missing required components."""
    validator = TopologyValidator()
    config = PlantTopologyConfig(
        rated_power_w=10_000_000.0,
        rated_energy_wh=20_000_000.0,
        containers=[],  # Missing containers!
        pcs_units=[],  # Missing PCS units!
        transformers=[],
        switchgear=[],
        auxiliary_systems=[],
        meters=[],
        poi=POITopologyConfig(
            max_export_power_w=10_000_000.0, max_import_power_w=10_000_000.0
        ),
        grid=GridTopologyConfig(),
        ppc=PPCTopologyConfig(
            plant_rated_active_power_w=10_000_000.0,
            plant_rated_apparent_power_va=11_000_000.0,
        ),
    )

    errors = validator.validate_topology(config)
    assert any("missing required component" in err for err in errors)


def test_incompatible_ratings_detection() -> None:
    """Test validator detects incompatible transformer vs PCS ratings."""
    validator = TopologyValidator()
    config = PlantTopologyConfig(
        rated_power_w=10_000_000.0,
        rated_energy_wh=20_000_000.0,
        containers=[ContainerConfig(container_id="C1", capacity_wh=20_000_000.0)],
        pcs_units=[
            PCSUnitConfig(
                pcs_id="PCS1",
                rated_active_power_w=10_000_000.0,
                rated_apparent_power_va=11_000_000.0,
            )
        ],
        transformers=[
            TransformerTopologyConfig(rating_va=5_000_000.0)
        ],  # 5 MVA < 11 MVA PCS!
        switchgear=[SwitchgearTopologyConfig()],
        auxiliary_systems=[],
        meters=[],
        poi=POITopologyConfig(
            max_export_power_w=10_000_000.0, max_import_power_w=10_000_000.0
        ),
        grid=GridTopologyConfig(),
        ppc=PPCTopologyConfig(
            plant_rated_active_power_w=10_000_000.0,
            plant_rated_apparent_power_va=11_000_000.0,
        ),
    )

    errors = validator.validate_topology(config)
    assert any("Incompatible electrical ratings" in err for err in errors)


def test_unsupported_plugin_version_detection() -> None:
    """Test validator detects un-registered / unsupported plugin_id references."""
    registry = PluginRegistry()  # Empty registry
    validator = TopologyValidator(plugin_registry=registry)

    config = PlantTopologyConfig(
        rated_power_w=10_000_000.0,
        rated_energy_wh=20_000_000.0,
        containers=[
            ContainerConfig(
                container_id="C1",
                plugin_id="unregistered_battery_v99",
                capacity_wh=20_000_000.0,
            )
        ],
        pcs_units=[
            PCSUnitConfig(
                pcs_id="PCS1",
                rated_active_power_w=10_000_000.0,
                rated_apparent_power_va=11_000_000.0,
            )
        ],
        transformers=[TransformerTopologyConfig(rating_va=12_000_000.0)],
        switchgear=[SwitchgearTopologyConfig()],
        auxiliary_systems=[],
        meters=[],
        poi=POITopologyConfig(
            max_export_power_w=10_000_000.0, max_import_power_w=10_000_000.0
        ),
        grid=GridTopologyConfig(),
        ppc=PPCTopologyConfig(
            plant_rated_active_power_w=10_000_000.0,
            plant_rated_apparent_power_va=11_000_000.0,
        ),
    )

    errors = validator.validate_topology(config)
    assert any(
        "Plugin 'unregistered_battery_v99' referenced by Container 'C1' not found"
        in err
        for err in errors
    )
