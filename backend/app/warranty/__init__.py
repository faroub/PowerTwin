"""Battery warranty analysis for the PowerTwin BESS platform.

`AGENTS.md` §1 lists warranty analysis as a mission item. This package holds
the analysis and the recorder that feeds it.

The degradation model behind the analysis is **illustrative**: its constants
have not been validated against any manufacturer document (`AGENTS.md` §2.13)
and every one of them is labelled as such (§2.14). The analysis is reported
to the operator and is never applied back to the plant.
"""

from backend.app.warranty.assessment import WarrantyAssessment, assess_warranty
from backend.app.warranty.degradation import (
    WARRANTY_STATUS_AT_END_OF_LIFE,
    WARRANTY_STATUS_UNKNOWN,
    WARRANTY_STATUS_WITHIN_WARRANTY,
    DegradationModel,
    DegradationParameters,
)
from backend.app.warranty.recorder import WarrantyRecorder, WarrantySink

__all__ = [
    "DegradationModel",
    "DegradationParameters",
    "WARRANTY_STATUS_AT_END_OF_LIFE",
    "WARRANTY_STATUS_UNKNOWN",
    "WARRANTY_STATUS_WITHIN_WARRANTY",
    "WarrantyAssessment",
    "WarrantyRecorder",
    "WarrantySink",
    "assess_warranty",
]
