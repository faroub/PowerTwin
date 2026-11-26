"""An illustrative degradation model for the battery warranty analysis.

`AGENTS.md` §1 lists warranty analysis as a mission item. §2.13 forbids
claiming that a model is manufacturer-accurate unless its behaviour has been
validated against authoritative documentation or test data, and §2.14 requires
illustrative parameters to be clearly labelled.

**Nothing in this module has been validated against any manufacturer
document.** Every parameter below is a representative value chosen to make
the model behave plausibly, and every one of them is marked ILLUSTRATIVE. The
model therefore produces an *indicative* degradation analysis for an operator
to read next to real field data. It is not a warranty calculation, and it
must not be presented as one.

The model is pure, deterministic and side-effect free. It takes the operating
history of a container and returns a state of health and a projection. It
never touches the plant, and the plant never runs on its output: the
degradation is **reported, not applied back**. `AGENTS.md` §3 keeps the
simulation engine independent of the analysis, and a plant that silently
degraded while a screen reported a different number would be a divergence
with no error anywhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "SECONDS_PER_YEAR",
    "WARRANTY_STATUS_AT_END_OF_LIFE",
    "WARRANTY_STATUS_UNKNOWN",
    "WARRANTY_STATUS_WITHIN_WARRANTY",
    "DegradationModel",
    "DegradationParameters",
]

#: The length of a mean calendar year, in seconds. Used to turn a duration
#: into a number of years for the calendar-fade term.
SECONDS_PER_YEAR: float = 365.25 * 24.0 * 3600.0

#: The container is still inside its warranty band.
WARRANTY_STATUS_WITHIN_WARRANTY: str = "WITHIN_WARRANTY"

#: The container has reached the end-of-life threshold of its warranty band.
WARRANTY_STATUS_AT_END_OF_LIFE: str = "AT_END_OF_LIFE"

#: There is not enough information to say anything about the warranty state.
WARRANTY_STATUS_UNKNOWN: str = "UNKNOWN"


@dataclass(frozen=True)
class DegradationParameters:
    """The constants of the illustrative degradation model.

    Every default here is **ILLUSTRATIVE** (`AGENTS.md` §2.14). They are
    representative values, not a manufacturer's published figures, and a
    deployment that has real field data should replace them.

    Attributes:
        calendar_fade_pct_per_year: State-of-health lost per calendar year at
            the reference temperature. ILLUSTRATIVE.
        cycle_fade_pct_per_1000_efc: State-of-health lost per thousand
            equivalent full cycles at the reference temperature. ILLUSTRATIVE.
        reference_temperature_c: The temperature at which the fade rates above
            apply as stated. ILLUSTRATIVE.
        temperature_acceleration_per_c: The factor by which the fade rates grow
            per degree Celsius above the reference temperature. ILLUSTRATIVE.
        warranty_threshold_soh_pct: The state of health at or below which a
            container is considered to have reached the end of its warranty
            band. ILLUSTRATIVE.
        projection_horizon_years: The horizon the projection is made over.
            ILLUSTRATIVE.
        illustrative: True while the constants rest on representative values
            rather than on validated manufacturer data (`AGENTS.md` §2.13).
            A deployment that has validated figures clears it.
    """

    calendar_fade_pct_per_year: float = 2.0
    cycle_fade_pct_per_1000_efc: float = 4.0
    reference_temperature_c: float = 25.0
    temperature_acceleration_per_c: float = 0.02
    warranty_threshold_soh_pct: float = 70.0
    projection_horizon_years: float = 10.0
    illustrative: bool = True

    def temperature_factor(self, temperature_c: float) -> float:
        """Return how much faster the fade runs at a temperature.

        Above the reference temperature the fade accelerates linearly; below
        it the fade does not slow down, because the model has no evidence for
        a slower fade and under-claiming the degradation would flatter the
        container.

        Args:
            temperature_c: The container temperature in degrees Celsius.

        Returns:
            The acceleration factor, never below 1.0.
        """
        excess_c = max(0.0, temperature_c - self.reference_temperature_c)
        return 1.0 + self.temperature_acceleration_per_c * excess_c


@dataclass(frozen=True)
class DegradationModel:
    """Turn an operating history into a state of health and a projection.

    Attributes:
        parameters: The illustrative constants of the model.
    """

    parameters: DegradationParameters = DegradationParameters()

    def observed_soh_pct(
        self,
        elapsed_seconds: float,
        equivalent_full_cycles: float,
        temperature_c: float,
    ) -> float:
        """Return the state of health implied by an operating history.

        The state of health is the configured 100 % minus the calendar fade
        and the cycle fade, both accelerated by the temperature.

        Args:
            elapsed_seconds: The elapsed operating time, in seconds.
            equivalent_full_cycles: The equivalent full cycles the container
                has been through.
            temperature_c: The temperature the fade is evaluated at.

        Returns:
            The state of health in percent, never below zero.
        """
        if elapsed_seconds < 0.0 or equivalent_full_cycles < 0.0:
            raise ValueError(
                "The operating history must not be negative: "
                f"{elapsed_seconds} s and {equivalent_full_cycles} EFC."
            )

        elapsed_years = elapsed_seconds / SECONDS_PER_YEAR
        factor = self.parameters.temperature_factor(temperature_c)

        calendar_fade = self.parameters.calendar_fade_pct_per_year * elapsed_years * factor
        cycle_fade = (
            self.parameters.cycle_fade_pct_per_1000_efc * (equivalent_full_cycles / 1000.0) * factor
        )
        return max(0.0, 100.0 - calendar_fade - cycle_fade)

    def projected_soh_pct(
        self,
        current_soh_pct: float,
        elapsed_seconds: float,
        equivalent_full_cycles: float,
        temperature_c: float,
        horizon_years: float | None = None,
    ) -> float:
        """Return the state of health expected at the end of the horizon.

        The projection continues the **observed duty**: the cycle rate the
        container has actually shown is carried forward over the horizon. A
        container that has not cycled projects on the calendar fade alone.

        Args:
            current_soh_pct: The observed state of health, in percent.
            elapsed_seconds: The elapsed operating time, in seconds.
            equivalent_full_cycles: The equivalent full cycles observed.
            temperature_c: The temperature the fade is evaluated at.
            horizon_years: The horizon. Defaults to the configured one.

        Returns:
            The projected state of health in percent, never below zero.
        """
        years = self.parameters.projection_horizon_years if horizon_years is None else horizon_years
        if years < 0.0:
            raise ValueError(f"The projection horizon must not be negative, got {years}.")

        factor = self.parameters.temperature_factor(temperature_c)
        calendar_fade = self.parameters.calendar_fade_pct_per_year * years * factor

        elapsed_years = elapsed_seconds / SECONDS_PER_YEAR
        if elapsed_years > 0.0:
            annual_efc = equivalent_full_cycles / elapsed_years
        else:
            annual_efc = 0.0
        cycle_fade = (
            self.parameters.cycle_fade_pct_per_1000_efc * (annual_efc * years / 1000.0) * factor
        )
        return max(0.0, current_soh_pct - calendar_fade - cycle_fade)

    def annual_equivalent_full_cycles(
        self,
        elapsed_seconds: float,
        equivalent_full_cycles: float,
    ) -> float:
        """Return the observed cycle rate, in equivalent full cycles per year.

        Args:
            elapsed_seconds: The elapsed operating time, in seconds.
            equivalent_full_cycles: The equivalent full cycles observed.

        Returns:
            The annual cycle rate. Zero when no time has elapsed, because a
            rate over no time is not a rate.
        """
        if elapsed_seconds <= 0.0:
            return 0.0
        elapsed_years = elapsed_seconds / SECONDS_PER_YEAR
        if elapsed_years <= 0.0:
            return 0.0
        return equivalent_full_cycles / elapsed_years

    def warranty_status(self, soh_pct: float | None) -> str:
        """Return the warranty verdict for a state of health.

        Args:
            soh_pct: The state of health in percent, or nothing when it is
                not known.

        Returns:
            One of `WARRANTY_STATUS_WITHIN_WARRANTY`,
            `WARRANTY_STATUS_AT_END_OF_LIFE` or `WARRANTY_STATUS_UNKNOWN`.
        """
        if soh_pct is None or not math.isfinite(soh_pct):
            return WARRANTY_STATUS_UNKNOWN
        if soh_pct <= self.parameters.warranty_threshold_soh_pct:
            return WARRANTY_STATUS_AT_END_OF_LIFE
        return WARRANTY_STATUS_WITHIN_WARRANTY
