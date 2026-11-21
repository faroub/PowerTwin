"""Plant Topology Validator — Electrical and Logical Consistency Checking."""

from plugins.registry import PluginRegistry

from backend.app.topology.schema import PlantTopologyConfig


class TopologyValidationError(Exception):
    """Raised when topology configuration validation fails with readable error reports."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        error_summary = "\n  - ".join(errors)
        super().__init__(f"Plant topology configuration validation failed:\n  - {error_summary}")


class TopologyValidator:
    """Validates electrical, structural, and logical consistency of a BESS plant topology."""

    def __init__(self, plugin_registry: PluginRegistry | None = None) -> None:
        self.plugin_registry: PluginRegistry = (
            plugin_registry if plugin_registry is not None else PluginRegistry()
        )

    def validate_topology(self, config: PlantTopologyConfig) -> list[str]:
        """Perform comprehensive electrical and logical validation on plant topology.

        Returns:
            List of human-readable error messages. Empty list if validation passes.
        """
        errors: list[str] = []

        # 1. Missing Components Check
        if not config.containers:
            errors.append("Topology missing required component: At least 1 Container is required.")
        if not config.pcs_units:
            errors.append("Topology missing required component: At least 1 PCS unit is required.")
        if not config.transformers:
            errors.append(
                "Topology missing required component: At least 1 Transformer is required."
            )
        if not config.switchgear:
            errors.append(
                "Topology missing required component: At least 1 Switchgear breaker is required."
            )

        # 2. Duplicate Equipment Identifiers Check
        seen_ids: set[str] = set()
        all_ids: list[tuple[str, str]] = []

        for c in config.containers:
            all_ids.append((c.container_id, "Container"))
        for pcs in config.pcs_units:
            all_ids.append((pcs.pcs_id, "PCS"))
        for xfrm in config.transformers:
            all_ids.append((xfrm.transformer_id, "Transformer"))
        for swg in config.switchgear:
            all_ids.append((swg.switchgear_id, "Switchgear"))
        for aux in config.auxiliary_systems:
            all_ids.append((aux.aux_id, "AuxiliarySystem"))
        for mtr in config.meters:
            all_ids.append((mtr.meter_id, "Meter"))

        for eq_id, eq_type in all_ids:
            if eq_id in seen_ids:
                msg = f"Duplicate equipment ID '{eq_id}' detected across topology ({eq_type})."
                errors.append(msg)
            seen_ids.add(eq_id)

        # 3. Electrical Rating Compatibility Check
        total_pcs_power_w = sum(pcs.rated_active_power_w for pcs in config.pcs_units)
        total_pcs_s_va = sum(pcs.rated_apparent_power_va for pcs in config.pcs_units)
        total_xfrm_s_va = sum(xfrm.rating_va for xfrm in config.transformers)
        total_container_energy_wh = sum(c.capacity_wh for c in config.containers)

        if total_xfrm_s_va < total_pcs_s_va:
            msg = (
                f"Incompatible electrical ratings: Total transformer rating "
                f"({total_xfrm_s_va / 1e6:.1f} MVA) is less than total PCS apparent "
                f"capacity ({total_pcs_s_va / 1e6:.1f} MVA)."
            )
            errors.append(msg)

        if total_pcs_power_w < config.rated_power_w:
            msg = (
                f"Incompatible active capacity: Total PCS active power "
                f"({total_pcs_power_w / 1e6:.1f} MW) is less than plant rated "
                f"power ({config.rated_power_w / 1e6:.1f} MW)."
            )
            errors.append(msg)

        if total_container_energy_wh < config.rated_energy_wh:
            msg = (
                f"Incompatible energy capacity: Total container energy "
                f"({total_container_energy_wh / 1e6:.1f} MWh) is less than plant rated "
                f"energy ({config.rated_energy_wh / 1e6:.1f} MWh)."
            )
            errors.append(msg)

        # 4. Voltage Matching Check
        if config.pcs_units and config.transformers:
            pcs_ac_v = config.pcs_units[0].ac_voltage_v
            xfrm_pri_v = config.transformers[0].primary_voltage_v
            if pcs_ac_v != xfrm_pri_v:
                msg = (
                    f"Voltage mismatch: PCS AC voltage ({pcs_ac_v:.1f} V) does not match "
                    f"Transformer primary voltage ({xfrm_pri_v:.1f} V)."
                )
                errors.append(msg)

        if config.transformers and config.poi:
            xfrm_sec_v = config.transformers[0].secondary_voltage_v
            poi_v = config.poi.nominal_voltage_v
            if xfrm_sec_v != poi_v:
                msg = (
                    f"Voltage mismatch: Transformer secondary voltage ({xfrm_sec_v:.1f} V) "
                    f"does not match POI nominal voltage ({poi_v:.1f} V)."
                )
                errors.append(msg)

        # 5. Plugin Availability & Compatibility Check
        reg_manifests = {m.plugin_id: m for m in self.plugin_registry.get_registered_manifests()}

        for c in config.containers:
            if c.plugin_id not in reg_manifests and c.plugin_id != "generic_battery_v1":
                msg = (
                    f"Plugin '{c.plugin_id}' referenced by Container '{c.container_id}' "
                    f"not found in registry."
                )
                errors.append(msg)

        for pcs in config.pcs_units:
            if pcs.plugin_id not in reg_manifests and pcs.plugin_id != "generic_pcs_v1":
                msg = (
                    f"Plugin '{pcs.plugin_id}' referenced by PCS '{pcs.pcs_id}' "
                    f"not found in registry."
                )
                errors.append(msg)

        for aux in config.auxiliary_systems:
            if aux.plugin_id not in reg_manifests and aux.plugin_id != "dummy_auxiliary_v1":
                msg = (
                    f"Plugin '{aux.plugin_id}' referenced by Aux '{aux.aux_id}' "
                    f"not found in registry."
                )
                errors.append(msg)

        if config.grid.plugin_id not in reg_manifests and config.grid.plugin_id != "dummy_grid_v1":
            msg = f"Plugin '{config.grid.plugin_id}' referenced by Grid not found in registry."
            errors.append(msg)

        return errors

    def validate_or_raise(self, config: PlantTopologyConfig) -> None:
        """Validate topology configuration and raise TopologyValidationError if invalid."""
        errors = self.validate_topology(config)
        if errors:
            raise TopologyValidationError(errors)
