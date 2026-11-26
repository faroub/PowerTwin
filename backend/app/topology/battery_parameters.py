"""Apply calibrated battery parameters to a container's physical model.

Why this is not part of the plugin initialisation payload
---------------------------------------------------------
The vendor plugins (``plugins/vendor/catl_enerone.py`` and
``plugins/vendor/tesla_megapack.py``) hand-roll their ``validate_config()``
and ``initialize()`` over a fixed set of four keys and **silently ignore
every other key**. Handing a calibrated parameter set to a plugin as part of
its initialisation payload would therefore leave that container running on
the vendor defaults while the topology claimed calibrated values — a
divergence with no error anywhere.

So the calibrated parameters are applied here, on the authoritative physical
model that every battery plugin wraps, and the plugin payload stays exactly
what it was.
"""

from backend.app.models.battery.system import BatterySystemConfigModel
from backend.app.topology.schema import BatteryParameterOverride

__all__ = ["OVERRIDABLE_BATTERY_PARAMETERS", "merge_battery_parameters"]

#: The calibrated parameters that replace the model's configured value. The
#: capacity is not among them: it already reaches the model through the
#: plugin payload, and every battery plugin copies it.
OVERRIDABLE_BATTERY_PARAMETERS: tuple[str, ...] = (
    "ocv_intercept",
    "ocv_slope",
    "internal_resistance_ohm",
    "cooling_coefficient_per_s",
    "thermal_mass_j_per_c",
    "aux_power_w",
)


def merge_battery_parameters(
    config: BatterySystemConfigModel,
    override: BatteryParameterOverride | None,
) -> BatterySystemConfigModel:
    """Return a configuration with the calibrated parameters applied.

    The merge **builds a new model** rather than assigning onto the existing
    one. ``BatterySystemConfigModel`` does not validate on assignment, so a
    field-by-field assignment would carry every value past the validators; a
    new model runs them all, including the cross-field check that the
    open-circuit voltage stays positive over the state-of-charge range.

    Args:
        config: The configuration the plugin built.
        override: The calibrated parameters, or nothing.

    Returns:
        The merged configuration. The original is returned unchanged when
        there is nothing to merge.
    """
    if override is None:
        return config

    values = config.model_dump()
    for field_name in OVERRIDABLE_BATTERY_PARAMETERS:
        value = getattr(override, field_name)
        if value is not None:
            values[field_name] = value
    return BatterySystemConfigModel(**values)
