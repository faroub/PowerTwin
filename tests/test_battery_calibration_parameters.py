"""Tests for the calibrated battery parameters and the topology plumbing.

`AGENTS.md` §1 lists digital-twin calibration as a mission item, and §2.14
requires illustrative parameters to be labelled. These tests hold three
things together:

* the new parameters are **behaviour-preserving** at their defaults — the
  model must behave exactly as it did before the parameters existed, because
  the endurance fingerprint depends on it;
* a calibrated parameter set actually reaches the running plant, whichever
  plugin the container uses, so that a vendor container cannot silently run
  on vendor defaults while the topology claims calibrated values;
* a parameter set that is not labelled cannot be loaded.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from backend.app.models.battery.system import BatterySystemConfigModel, GenericBatterySystemModel
from backend.app.topology.battery_parameters import merge_battery_parameters
from backend.app.topology.factory import PlantTopologyFactory
from backend.app.topology.schema import BatteryParameterOverride, ContainerConfig
from plugins.generic_battery import GenericBatteryPlugin
from plugins.registry import PluginRegistry
from plugins.vendor.catl_enerone import CATLEnerOneBatteryPlugin
from plugins.vendor.tesla_megapack import TeslaMegapackBatteryPlugin


class TestTheDefaultsAreBehaviourPreserving:
    """The defaults must reproduce the model exactly as it was."""

    def test_the_default_open_circuit_voltage_is_the_old_hard_coded_line(self) -> None:
        model = GenericBatterySystemModel()

        model.soc_pct = 37.5
        expected = model.config.nominal_voltage_v * (0.85 + 0.30 * (37.5 / 100.0))

        assert model.open_circuit_voltage_v() == expected

    def test_a_zero_resistance_leaves_the_terminal_voltage_at_the_open_circuit_voltage(
        self,
    ) -> None:
        model = GenericBatterySystemModel()
        model.soc_pct = 42.0

        for power_w in (-5_000_000.0, 0.0, 5_000_000.0):
            assert model.solve_terminal_voltage(power_w) == model.open_circuit_voltage_v()

    def test_the_default_step_reproduces_the_old_voltage_and_current(self) -> None:
        model = GenericBatterySystemModel()
        model.soc_pct = 50.0

        model.step(1_000_000.0, 0.01, timestamp_ns=1)

        expected_voltage = model.config.nominal_voltage_v * (0.85 + 0.30 * (50.0 / 100.0))
        assert model.voltage_v == expected_voltage
        assert model.current_a == model.active_power_w / expected_voltage
        # The power and the current still agree with the voltage.
        assert model.voltage_v * model.current_a == pytest.approx(model.active_power_w)

    def test_the_default_thermal_update_is_the_old_hard_coded_line(self) -> None:
        model = GenericBatterySystemModel()
        model.soc_pct = 50.0
        model.temperature_c = 30.0

        before = model.temperature_c
        model.step(0.0, 1.0, timestamp_ns=1)

        # The old line: (T - 25.0) * (0.01 * dt), plus the auxiliary heat that
        # the old line also carried.
        heating = model.config.aux_power_w / model.config.thermal_mass_j_per_c
        cooling = (before - 25.0) * 0.01
        assert model.temperature_c == pytest.approx(before + heating - cooling)

    def test_the_thermal_update_follows_the_configured_ambient_and_cooling(self) -> None:
        """The reference ambient and the cooling rate are the calibrated pair."""
        model = GenericBatterySystemModel(
            config=BatterySystemConfigModel(
                ambient_reference_c=30.0,
                cooling_coefficient_per_s=0.05,
                aux_power_w=0.0,
            )
        )
        model.temperature_c = 40.0

        model.step(0.0, 1.0, timestamp_ns=1)

        # Cooling is measured against the configured reference, not a hard-coded 25.
        assert model.temperature_c == pytest.approx(40.0 - (40.0 - 30.0) * 0.05)

        model.temperature_c = 50.0
        model.step(0.0, 1.0, timestamp_ns=1)
        assert model.temperature_c == pytest.approx(50.0 - (50.0 - 30.0) * 0.05)


class TestTheOhmicDrop:
    """The series resistance must be physical, not a decoration."""

    def test_the_terminal_voltage_falls_under_a_discharge_current(self) -> None:
        model = GenericBatterySystemModel(
            config=BatterySystemConfigModel(nominal_voltage_v=1000.0, internal_resistance_ohm=0.01)
        )

        v_oc = model.open_circuit_voltage_v()
        voltage = model.solve_terminal_voltage(1_000_000.0)

        assert voltage < v_oc
        # The power, the current and the voltage still agree with each other.
        current = 1_000_000.0 / voltage
        assert voltage * current == pytest.approx(1_000_000.0)
        assert v_oc - 0.01 * current == pytest.approx(voltage)

    def test_the_terminal_voltage_rises_under_a_charge_current(self) -> None:
        model = GenericBatterySystemModel(
            config=BatterySystemConfigModel(nominal_voltage_v=1000.0, internal_resistance_ohm=0.01)
        )

        v_oc = model.open_circuit_voltage_v()
        voltage = model.solve_terminal_voltage(-1_000_000.0)

        assert voltage > v_oc
        assert voltage * (-1_000_000.0 / voltage) == pytest.approx(-1_000_000.0)

    def test_the_physical_root_is_taken_and_not_the_short_circuit_branch(self) -> None:
        """The smaller quadratic root collapses the voltage while the current runs away."""
        model = GenericBatterySystemModel(
            config=BatterySystemConfigModel(nominal_voltage_v=1000.0, internal_resistance_ohm=0.05)
        )
        model.soc_pct = 5.0
        v_oc = model.open_circuit_voltage_v()

        voltage = model.solve_terminal_voltage(1_000_000.0)
        short_circuit_branch = (v_oc - math.sqrt(v_oc * v_oc - 4.0 * 0.05 * 1_000_000.0)) / 2.0

        assert voltage != pytest.approx(short_circuit_branch)
        assert voltage > v_oc / 2.0

    def test_the_discharge_limit_is_the_maximum_power_point(self) -> None:
        model = GenericBatterySystemModel(
            config=BatterySystemConfigModel(nominal_voltage_v=1000.0, internal_resistance_ohm=0.05)
        )
        model.soc_pct = 50.0
        v_oc = model.open_circuit_voltage_v()

        assert model.maximum_discharge_power_w() == pytest.approx(v_oc * v_oc / 0.2)

    def test_a_zero_resistance_imposes_no_discharge_limit(self) -> None:
        model = GenericBatterySystemModel(
            config=BatterySystemConfigModel(max_discharge_power_w=12_000_000.0)
        )

        assert model.maximum_discharge_power_w() == 12_000_000.0

    def test_the_step_stays_finite_beyond_the_maximum_power_point(self) -> None:
        """A demand past the limit is clamped, never answered with a fictitious voltage."""
        model = GenericBatterySystemModel(
            config=BatterySystemConfigModel(nominal_voltage_v=1000.0, internal_resistance_ohm=0.05)
        )
        model.soc_pct = 50.0

        model.step(50_000_000.0, 0.01, timestamp_ns=1)

        assert math.isfinite(model.voltage_v)
        assert math.isfinite(model.current_a)
        assert model.voltage_v > 0.0


class TestTheParameterValidators:
    """A configuration that cannot be modelled is refused."""

    def test_a_negative_resistance_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="negative"):
            BatterySystemConfigModel(internal_resistance_ohm=-0.01)

    def test_a_negative_cooling_coefficient_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="negative"):
            BatterySystemConfigModel(cooling_coefficient_per_s=-0.1)

    def test_a_non_finite_coefficient_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="finite"):
            BatterySystemConfigModel(ocv_slope=float("inf"))

    def test_an_open_circuit_voltage_that_crosses_zero_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="open-circuit voltage"):
            BatterySystemConfigModel(nominal_voltage_v=1000.0, ocv_intercept=0.10, ocv_slope=-0.20)


class TestTheTopologyPlumbing:
    """A calibrated parameter set has to reach the running plant."""

    def test_the_merge_leaves_the_configuration_alone_without_an_override(self) -> None:
        config = BatterySystemConfigModel()

        assert merge_battery_parameters(config, None) is config

    def test_the_merge_applies_every_calibrated_parameter(self) -> None:
        override = BatteryParameterOverride(
            ocv_intercept=0.80,
            ocv_slope=0.35,
            internal_resistance_ohm=0.02,
            cooling_coefficient_per_s=0.02,
            thermal_mass_j_per_c=60_000_000.0,
            aux_power_w=12_000.0,
        )

        merged = merge_battery_parameters(BatterySystemConfigModel(), override)

        assert merged.ocv_intercept == 0.80
        assert merged.ocv_slope == 0.35
        assert merged.internal_resistance_ohm == 0.02
        assert merged.cooling_coefficient_per_s == 0.02
        assert merged.thermal_mass_j_per_c == 60_000_000.0
        assert merged.aux_power_w == 12_000.0

    def test_the_merge_keeps_the_parameters_the_override_does_not_mention(self) -> None:
        merged = merge_battery_parameters(
            BatterySystemConfigModel(nominal_voltage_v=1331.0),
            BatteryParameterOverride(ocv_slope=0.31),
        )

        assert merged.nominal_voltage_v == 1331.0
        assert merged.ocv_slope == 0.31

    def test_the_merge_runs_the_validators(self) -> None:
        """A merge builds a new model, so an invalid calibration is refused."""
        with pytest.raises(ValidationError):
            merge_battery_parameters(
                BatterySystemConfigModel(),
                BatteryParameterOverride(ocv_intercept=0.05, ocv_slope=-0.10),
            )

    def test_an_unknown_parameter_is_refused(self) -> None:
        """A misspelled parameter must not disappear silently."""
        with pytest.raises(ValidationError):
            BatteryParameterOverride(ocv_slop=0.31)  # type: ignore[call-arg]

    def test_a_container_may_not_claim_validation_with_illustrative_parameters(self) -> None:
        with pytest.raises(ValidationError, match="illustrative"):
            ContainerConfig(
                container_id="C1",
                capacity_wh=1_000_000.0,
                illustrative=False,
                battery_parameters=BatteryParameterOverride(ocv_slope=0.31),
            )

    def test_a_container_may_claim_validation_with_validated_parameters(self) -> None:
        container = ContainerConfig(
            container_id="C1",
            capacity_wh=1_000_000.0,
            illustrative=False,
            battery_parameters=BatteryParameterOverride(ocv_slope=0.31, illustrative=False),
        )

        assert container.battery_parameters is not None
        assert container.battery_parameters.ocv_slope == 0.31

    def test_the_calibrated_parameters_reach_a_generic_container(self) -> None:
        payload = {
            "plant_id": "TEST_PLANT",
            "rated_power_w": 1_000_000.0,
            "rated_energy_wh": 2_000_000.0,
            "containers": [
                {
                    "container_id": "C1",
                    "capacity_wh": 2_000_000.0,
                    "battery_parameters": {"ocv_slope": 0.31, "internal_resistance_ohm": 0.02},
                }
            ],
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

        factory = PlantTopologyFactory()
        plant = factory.build_plant(payload)

        battery = plant.battery_systems[0]
        assert battery.config.ocv_slope == 0.31
        assert battery.config.internal_resistance_ohm == 0.02

    def test_the_calibrated_parameters_reach_a_vendor_container(self) -> None:
        """The vendor plugins ignore every unknown key, so the factory merge is the
        only path that can carry a calibration into a vendor container.

        Without it the container would run on vendor defaults while the
        topology claimed calibrated values, and nothing anywhere would say so.
        """
        registry = PluginRegistry()
        registry.register_plugin_class(CATLEnerOneBatteryPlugin)
        registry.register_plugin_class(TeslaMegapackBatteryPlugin)

        payload = {
            "plant_id": "TEST_PLANT",
            "rated_power_w": 1_000_000.0,
            "rated_energy_wh": 2_000_000.0,
            "containers": [
                {
                    "container_id": "CATL_CONT_01",
                    "plugin_id": "CATL_EnerOne_v1",
                    "vendor": "CATL",
                    "capacity_wh": 2_000_000.0,
                    "battery_parameters": {"ocv_slope": 0.31, "internal_resistance_ohm": 0.02},
                },
                {
                    "container_id": "TESLA_CONT_01",
                    "plugin_id": "Tesla_Megapack_v1",
                    "vendor": "Tesla",
                    "capacity_wh": 2_000_000.0,
                    "battery_parameters": {"ocv_slope": 0.29, "internal_resistance_ohm": 0.03},
                },
            ],
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

        factory = PlantTopologyFactory(plugin_registry=registry)
        plant = factory.build_plant(payload)

        catl = plant.battery_systems[0]
        assert catl.config.ocv_slope == 0.31
        assert catl.config.internal_resistance_ohm == 0.02

        tesla = plant.battery_systems[1]
        assert tesla.config.ocv_slope == 0.29
        assert tesla.config.internal_resistance_ohm == 0.03

    def test_a_vendor_container_keeps_the_vendor_capacity_through_the_merge(self) -> None:
        """The merge replaces the calibrated parameters only. The capacity and the
        vendor power limits arrive through the plugin payload and must survive.
        """
        registry = PluginRegistry()
        registry.register_plugin_class(CATLEnerOneBatteryPlugin)

        payload = {
            "plant_id": "TEST_PLANT",
            "rated_power_w": 1_000_000.0,
            "rated_energy_wh": 2_000_000.0,
            "containers": [
                {
                    "container_id": "CATL_CONT_01",
                    "plugin_id": "CATL_EnerOne_v1",
                    "vendor": "CATL",
                    "capacity_wh": 2_000_000.0,
                    "battery_parameters": {"ocv_slope": 0.31},
                }
            ],
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

        factory = PlantTopologyFactory(plugin_registry=registry)
        plant = factory.build_plant(payload)

        battery = plant.battery_systems[0]
        assert battery.config.capacity_wh == 2_000_000.0
        assert battery.config.ocv_slope == 0.31


class TestTheCapabilityReporting:
    """A container has to be able to say what it actually runs with."""

    def test_the_generic_plugin_reports_its_calibrated_parameters(self) -> None:
        plugin = GenericBatteryPlugin("GEN_01")
        plugin.physical_model.config = merge_battery_parameters(
            plugin.physical_model.config,
            BatteryParameterOverride(ocv_slope=0.31, internal_resistance_ohm=0.02),
        )

        capabilities = plugin.get_capabilities()

        assert capabilities["ocv_slope"] == 0.31
        assert capabilities["internal_resistance_ohm"] == 0.02
        assert capabilities["capacity_wh"] == plugin.physical_model.config.capacity_wh

    def test_the_vendor_plugin_reports_its_calibrated_parameters(self) -> None:
        plugin = CATLEnerOneBatteryPlugin("CATL_01")
        plugin.physical_model.config = merge_battery_parameters(
            plugin.physical_model.config,
            BatteryParameterOverride(ocv_slope=0.29),
        )

        capabilities = plugin.get_capabilities()

        assert capabilities["ocv_slope"] == 0.29
        assert capabilities["capacity_wh"] == plugin.physical_model.config.capacity_wh
