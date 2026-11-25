"""Tests for the explicit illustrative-parameter marker of the topology schema.

`AGENTS.md` §2.14 requires illustrative parameters to be clearly labelled.
The label used to live in prose only, which meant nothing stopped a
configuration from shipping unlabelled values. These tests hold the label in
the schema instead: the marker is a field, it travels into the runtime
equipment metadata, and the shipped examples carry it explicitly.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from backend.app.topology.factory import PlantTopologyFactory
from backend.app.topology.schema import PlantTopologyConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "configs"

# The plant configurations the repository ships as examples. Every one of them
# is a demonstration topology built from representative values.
SHIPPED_PLANT_CONFIGS = [
    CONFIG_DIR / "reference_10mw_20mwh.yaml",
    CONFIG_DIR / "variant_50mw_200mwh.yaml",
]

# The sections of the topology that hold equipment. Each entry is either a
# list of items or a single item.
LIST_SECTIONS = [
    "containers",
    "pcs_units",
    "transformers",
    "switchgear",
    "auxiliary_systems",
    "meters",
    "grid_services",
]
SINGLE_SECTIONS = [
    "poi",
    "grid",
    "equipment_controller",
    "ppc",
    "ems",
]


def _minimal_plant_payload() -> dict[str, Any]:
    """A structurally valid plant configuration with no illustrative marker."""
    return {
        "plant_id": "TEST_PLANT",
        "rated_power_w": 1_000_000.0,
        "rated_energy_wh": 2_000_000.0,
        "containers": [{"container_id": "C1", "capacity_wh": 2_000_000.0}],
        "pcs_units": [
            {
                "pcs_id": "P1",
                "rated_active_power_w": 1_000_000.0,
                "rated_apparent_power_va": 1_000_000.0,
            }
        ],
        "transformers": [{"transformer_id": "T1", "rating_va": 1_000_000.0}],
        "switchgear": [{"switchgear_id": "S1"}],
        "auxiliary_systems": [{"aux_id": "A1"}],
        "meters": [{"meter_id": "M1"}],
        "poi": {
            "poi_id": "POI1",
            "max_export_power_w": 1_000_000.0,
            "max_import_power_w": 1_000_000.0,
        },
        "grid": {"grid_id": "G1"},
        "equipment_controller": {"controller_id": "EQ1"},
        "ppc": {
            "ppc_id": "PPC1",
            "plant_rated_active_power_w": 1_000_000.0,
            "plant_rated_apparent_power_va": 1_000_000.0,
        },
        "ems": {"ems_id": "EMS1"},
        "grid_services": [],
    }


def _mark_every_item(payload: dict[str, Any], illustrative: bool) -> dict[str, Any]:
    """Return a copy of the payload with every equipment item marked."""
    marked = dict(payload)
    for section in LIST_SECTIONS:
        marked[section] = [{**item, "illustrative": illustrative} for item in payload[section]]
    for section in SINGLE_SECTIONS:
        marked[section] = {**payload[section], "illustrative": illustrative}
    return marked


class TestShippedConfigurationsAreMarked:
    """Every shipped example configuration must carry the marker explicitly."""

    @pytest.mark.parametrize("config_path", SHIPPED_PLANT_CONFIGS, ids=lambda p: p.stem)
    def test_the_example_configuration_states_the_marker_on_every_item(
        self, config_path: Path
    ) -> None:
        """The label is stated in the file, not merely defaulted by the schema."""
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        assert "illustrative" in raw, f"{config_path.name} does not state the plant-level marker."
        assert raw["illustrative"] is True, (
            f"{config_path.name} declares illustrative={raw['illustrative']}; the shipped "
            "examples are demonstration topologies and must be labelled illustrative."
        )

        for section in LIST_SECTIONS:
            for item in raw.get(section) or []:
                assert "illustrative" in item, (
                    f"{config_path.name}: {section} item {item} does not state the marker."
                )
                assert item["illustrative"] is True

        for section in SINGLE_SECTIONS:
            item = raw.get(section)
            if item is None:
                continue
            assert "illustrative" in item, (
                f"{config_path.name}: {section} does not state the marker."
            )
            assert item["illustrative"] is True

    @pytest.mark.parametrize("config_path", SHIPPED_PLANT_CONFIGS, ids=lambda p: p.stem)
    def test_the_example_configuration_loads_as_illustrative(self, config_path: Path) -> None:
        """The parsed configuration agrees with the file."""
        config = PlantTopologyFactory.load_config_from_yaml(str(config_path))

        assert config.illustrative is True
        assert all(container.illustrative for container in config.containers)
        assert all(pcs.illustrative for pcs in config.pcs_units)
        assert all(transformer.illustrative for transformer in config.transformers)
        assert all(switchgear.illustrative for switchgear in config.switchgear)
        assert all(aux.illustrative for aux in config.auxiliary_systems)
        assert all(meter.illustrative for meter in config.meters)
        assert config.poi.illustrative is True
        assert config.grid.illustrative is True
        assert config.equipment_controller.illustrative is True
        assert config.ppc.illustrative is True
        assert config.ems.illustrative is True


class TestTheMarkerDefaultsToLabelled:
    """An unstated marker must label the parameters, never silence the label."""

    def test_an_equipment_item_without_the_marker_is_illustrative(self) -> None:
        config = PlantTopologyConfig(**_minimal_plant_payload())

        assert config.containers[0].illustrative is True
        assert config.illustrative is True

    def test_a_plant_that_omits_the_marker_is_illustrative(self) -> None:
        config = PlantTopologyConfig(**_minimal_plant_payload())

        assert config.illustrative is True


class TestThePlantLevelMarker:
    """The plant-level marker follows the items and may never under-label."""

    def test_the_plant_marker_is_derived_when_every_item_is_validated(self) -> None:
        payload = _mark_every_item(_minimal_plant_payload(), illustrative=False)

        config = PlantTopologyConfig(**payload)

        assert config.illustrative is False

    def test_the_plant_marker_stays_illustrative_when_one_item_is_illustrative(
        self,
    ) -> None:
        payload = _mark_every_item(_minimal_plant_payload(), illustrative=False)
        payload["containers"][0]["illustrative"] = True

        config = PlantTopologyConfig(**payload)

        assert config.illustrative is True

    def test_a_plant_that_claims_to_be_validated_is_rejected(self) -> None:
        """Under-labelling a plant is a contradiction, and it is refused."""
        payload = _mark_every_item(_minimal_plant_payload(), illustrative=False)
        payload["illustrative"] = False
        payload["grid"]["illustrative"] = True

        with pytest.raises(ValidationError, match="illustrative"):
            PlantTopologyConfig(**payload)

    def test_an_explicit_plant_marker_is_kept(self) -> None:
        payload = _mark_every_item(_minimal_plant_payload(), illustrative=False)
        payload["illustrative"] = True

        config = PlantTopologyConfig(**payload)

        assert config.illustrative is True


class TestTheFactoryCarriesTheMarker:
    """The marker has to reach the runtime equipment, not stop at the schema."""

    def test_the_reference_plant_reports_illustrative_equipment(self) -> None:
        factory = PlantTopologyFactory()
        plant = factory.build_plant(
            factory.load_config_from_yaml(str(CONFIG_DIR / "reference_10mw_20mwh.yaml"))
        )

        assert all(battery.metadata.is_illustrative for battery in plant.battery_systems)
        assert all(pcs.metadata.is_illustrative for pcs in plant.pcs_units)
        assert all(bms.get_state().metadata.is_illustrative for bms in plant.bms_units)
        assert all(xfrm.get_state().metadata.is_illustrative for xfrm in plant.transformers)
        assert all(swg.get_state().metadata.is_illustrative for swg in plant.switchgear)
        assert all(mtr.get_state().metadata.is_illustrative for mtr in plant.meters)
        assert plant.poi.get_state().metadata.is_illustrative is True
        assert plant.grid.get_state().metadata.is_illustrative is True

    def test_a_validated_item_reports_validated_equipment(self) -> None:
        """A configuration that claims validation must not be labelled illustrative."""
        payload = _minimal_plant_payload()
        payload["containers"][0]["illustrative"] = False

        factory = PlantTopologyFactory()
        plant = factory.build_plant(payload)

        assert plant.battery_systems[0].metadata.is_illustrative is False
        # The BMS belongs to the container and follows its label.
        assert plant.bms_units[0].get_state().metadata.is_illustrative is False
        # Everything else keeps the safe default.
        assert plant.pcs_units[0].metadata.is_illustrative is True
        assert plant.transformers[0].get_state().metadata.is_illustrative is True
