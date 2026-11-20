"""Equivalent Circuit Model (ECM) Interface Definition for Future Electro-Chemical Extensions.

This interface defines the mathematical parameter placeholders for 1-RC or 2-RC equivalent
circuit models (R_0, R_ct, C_dl).

DOCUMENTED LIMITATION: This model interface is NOT IMPLEMENTED in the initial release.
Do not use this interface as a certified operational substitute for validated factory test data.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class ECMParameters(BaseModel):
    """1-RC Equivalent Circuit Model parameter parameters."""

    ocv_v: float = Field(description="Open Circuit Voltage in Volts")
    r0_ohm: float = Field(description="Ohmic internal resistance in Ohms")
    r1_ct_ohm: float = Field(description="Charge-transfer resistance in Ohms")
    c1_dl_farad: float = Field(description="Double-layer capacitance in Farads")


class EquivalentCircuitModelInterface(ABC):
    """Abstract interface for high-fidelity electro-chemical equivalent circuit models."""

    @abstractmethod
    def calculate_ecm_voltage(
        self, current_a: float, soc_pct: float, temp_c: float, delta_t_s: float
    ) -> float:
        """Calculate terminal DC voltage under current load using ECM differential equations."""
        pass


class ECMStub(EquivalentCircuitModelInterface):
    """Placeholder stub for Equivalent Circuit Model.

    UNIMPLEMENTED MODEL: Raises NotImplementedError if invoked directly.
    """

    def calculate_ecm_voltage(
        self, current_a: float, soc_pct: float, temp_c: float, delta_t_s: float
    ) -> float:
        raise NotImplementedError(
            "EquivalentCircuitModelInterface (ECM) is an unvalidated placeholder stub. "
            "Use energy-based GenericBatterySystemModel for WP04A."
        )
