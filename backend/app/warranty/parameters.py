"""Build the degradation parameters this deployment runs with.

The fade rates, the reference temperature and the temperature acceleration are
**constants of the illustrative model**, not configuration. The recorder
writes the state of health it derived from them into the historian, so a rate
that could change between the recording and the read would make the stored
history irreproducible: the screen would recompute a different number from
the very row the recorder wrote. Keeping them fixed is what makes the two
paths agree exactly.

The warranty threshold and the projection horizon are **policy**, not
physics. The verdict is decided when the screen asks for it, and a
deployment may reasonably run a different warranty band. Both the recorder
and the read path build their parameters here, so they never disagree about
which policy is in force.

Every value these settings carry is ILLUSTRATIVE (`AGENTS.md` §2.13, §2.14):
none of them has been validated against a manufacturer document.
"""

from __future__ import annotations

from backend.app.core.config import settings
from backend.app.warranty.degradation import DegradationParameters

__all__ = ["deployment_parameters"]


def deployment_parameters() -> DegradationParameters:
    """Return the degradation parameters this deployment runs with.

    Returns:
        The illustrative parameters, with the warranty threshold and the
        projection horizon taken from the deployment's settings.
    """
    return DegradationParameters(
        warranty_threshold_soh_pct=settings.WARRANTY_THRESHOLD_SOH_PCT,
        projection_horizon_years=settings.WARRANTY_PROJECTION_HORIZON_YEARS,
    )
