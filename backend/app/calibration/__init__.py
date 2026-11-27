"""Digital-twin calibration prototype for the PowerTwin BESS platform.

`AGENTS.md` §1 lists digital-twin calibration as a mission item. This package
holds the prototype's two halves: the ruthless observation dataset
(:mod:`backend.app.calibration.dataset`) and the rank-aware least-squares
solver (:mod:`backend.app.calibration.solver`).

The package is a **prototype**: it reads a CSV of observations and solves for
parameters. It is deliberately not wired into the topology, the battery model,
the API, the database or any control path, and no fitted parameter is claimed
to be manufacturer-accurate (`AGENTS.md` §2.13) — a fit is only as good as the
data it was given, and the dataset says so by rejecting every row it cannot
use, with a stated reason.
"""

from backend.app.calibration.dataset import (
    REJECTION_REASONS,
    REQUIRED_COLUMNS,
    CalibrationDataset,
    Observation,
    RejectedObservation,
    dataset_summary,
    load_observations_csv,
    validate_observations,
)
from backend.app.calibration.solver import (
    RANK_TOLERANCE,
    WEAK_TOLERANCE,
    LinearSolveResult,
    solve_least_squares,
)

__all__ = [
    "CalibrationDataset",
    "LinearSolveResult",
    "Observation",
    "RANK_TOLERANCE",
    "REJECTION_REASONS",
    "REQUIRED_COLUMNS",
    "RejectedObservation",
    "WEAK_TOLERANCE",
    "dataset_summary",
    "load_observations_csv",
    "solve_least_squares",
    "validate_observations",
]
