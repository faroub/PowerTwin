"""Turn the recorded warranty metrics into a verdict and a projection.

The recorder and the read path have to agree on the numbers they publish. A
screen that showed a projection different from the one the recorder had
already written would be a divergence with no error anywhere, so both go
through this module.

The assessment reads only what the historian's snapshot row holds, so the
read path can reproduce the recorder's arithmetic exactly from the stored
columns — no extra database column is needed and no migration is added.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.warranty.degradation import (
    DegradationModel,
    DegradationParameters,
)

__all__ = ["WarrantyAssessment", "assess_warranty"]


@dataclass(frozen=True)
class WarrantyAssessment:
    """The verdict and the projection for one container.

    Attributes:
        warranty_status: `WITHIN_WARRANTY`, `AT_END_OF_LIFE` or `UNKNOWN`.
        warranty_threshold_pct: The state of health at or below which the
            container is considered to have reached the end of its warranty
            band.
        current_soh_pct: The observed state of health, or nothing when it is
            not known.
        projected_soh_pct: The state of health expected at the end of the
            horizon, or nothing when it is not known.
        projection_horizon_years: The horizon the projection is made over.
        annual_equivalent_full_cycles: The observed cycle rate.
        illustrative: True when the assessment rests on the illustrative
            degradation model rather than on validated manufacturer data.
    """

    warranty_status: str
    warranty_threshold_pct: float
    current_soh_pct: float | None
    projected_soh_pct: float | None
    projection_horizon_years: float
    annual_equivalent_full_cycles: float
    illustrative: bool


def assess_warranty(
    *,
    current_soh_pct: float | None,
    equivalent_full_cycles: float | None,
    elapsed_seconds: float,
    max_temperature_recorded_c: float | None,
    parameters: DegradationParameters | None = None,
    horizon_years: float | None = None,
) -> WarrantyAssessment:
    """Return the warranty verdict and the projection for a container.

    The projection is evaluated at the **highest recorded container
    temperature**, not at an average. The snapshot row holds no temperature
    average, and the highest recorded temperature is the conservative choice:
    it accelerates the fade, so the projection errs towards a shorter
    remaining life rather than a longer one. The recorder evaluates its own
    projection at the same temperature, so the two agree exactly.

    Args:
        current_soh_pct: The observed state of health, in percent.
        equivalent_full_cycles: The equivalent full cycles observed.
        elapsed_seconds: The elapsed operating time, in seconds.
        max_temperature_recorded_c: The highest recorded temperature, or
            nothing when it is not known.
        parameters: The degradation constants. Defaults to the illustrative
            ones.
        horizon_years: The projection horizon. Defaults to the configured one.

    Returns:
        The assessment.
    """
    resolved = parameters if parameters is not None else DegradationParameters()
    model = DegradationModel(resolved)

    cycles = equivalent_full_cycles if equivalent_full_cycles is not None else 0.0
    annual_efc = model.annual_equivalent_full_cycles(elapsed_seconds, cycles)

    projected: float | None = None
    if current_soh_pct is not None and max_temperature_recorded_c is not None:
        projected = model.projected_soh_pct(
            current_soh_pct=current_soh_pct,
            elapsed_seconds=elapsed_seconds,
            equivalent_full_cycles=cycles,
            temperature_c=max_temperature_recorded_c,
            horizon_years=horizon_years,
        )

    status = model.warranty_status(current_soh_pct)

    return WarrantyAssessment(
        warranty_status=status,
        warranty_threshold_pct=resolved.warranty_threshold_soh_pct,
        current_soh_pct=current_soh_pct,
        projected_soh_pct=projected,
        projection_horizon_years=(
            resolved.projection_horizon_years if horizon_years is None else horizon_years
        ),
        annual_equivalent_full_cycles=annual_efc,
        illustrative=resolved.illustrative,
    )
