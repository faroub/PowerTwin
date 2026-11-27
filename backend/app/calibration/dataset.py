"""The observation dataset a calibration is fitted to.

What this module is responsible for
-----------------------------------
A calibration is only as good as the data it is fitted to, and the first duty of a
calibration tool is therefore to be **ruthless about the data**: every row that
cannot be used is rejected **with a stated reason**, and nothing is dropped
silently. A row that is quietly discarded leaves the operator believing the
calibration was fitted to more evidence than it was.

The gates applied here are the ones that can be judged from a single row or from
the ordering of the rows:

- a value that is not a number, or is not finite;
- a state of charge outside 0-100 %;
- a timestamp that does not move forward;
- a power and a current that disagree in sign;
- a power, a voltage and a current that do not satisfy ``p = v * i``;
- a voltage outside a declared physical band.

The gates that need a **pair** of rows — a state of charge that the model clamps, an
interval that spans a change of direction, an interval too long for the Euler
approximation the thermal fit uses — belong to the fitter, because they are
properties of an interval rather than of a row.
"""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "CalibrationDataset",
    "Observation",
    "RejectedObservation",
    "REJECTION_REASONS",
    "REQUIRED_COLUMNS",
    "load_observations_csv",
    "validate_observations",
]

#: The columns every observation must carry.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "timestamp_ns",
    "soc_pct",
    "voltage_v",
    "current_a",
    "active_power_w",
    "temperature_c",
)

#: The column that names the container a row belongs to. It is optional: a file
#: that carries no container column describes a single container.
CONTAINER_COLUMN: str = "container_id"

#: The reasons a row can be rejected. Every one of them is a plain statement about
#: what was wrong with the row.
REJECTION_REASONS: tuple[str, ...] = (
    "MALFORMED_ROW",
    "MISSING_VALUE",
    "NON_FINITE",
    "SOC_OUT_OF_RANGE",
    "TIMESTAMP_NOT_INCREASING",
    "POWER_CURRENT_SIGN_MISMATCH",
    "POWER_CURRENT_INCONSISTENT",
    "VOLTAGE_OUT_OF_BAND",
)

#: The relative tolerance of the power/voltage/current consistency gate.
POWER_CURRENT_RELATIVE_TOLERANCE: float = 1e-3

#: The absolute floor of that gate, in Watts. Below this power the relative test
#: says nothing useful, so the comparison is made against the floor instead.
POWER_CURRENT_ABSOLUTE_TOLERANCE_W: float = 1.0

#: Below this power, in Watts, the sign of the power and the sign of the current
#: are not compared.
SIGN_GATE_POWER_FLOOR_W: float = 1.0


@dataclass(frozen=True)
class Observation:
    """One measured sample of a container.

    Attributes:
        timestamp_ns: The simulation or measurement timestamp, in nanoseconds.
        soc_pct: The state of charge, in per cent.
        voltage_v: The terminal voltage, in volts.
        current_a: The terminal current, in amperes. Positive is discharge.
        active_power_w: The active power, in watts. Positive is discharge.
        temperature_c: The container temperature, in degrees Celsius.
        container_id: The container the sample belongs to, when the dataset names one.
    """

    timestamp_ns: int
    soc_pct: float
    voltage_v: float
    current_a: float
    active_power_w: float
    temperature_c: float
    container_id: str | None = None


@dataclass(frozen=True)
class RejectedObservation:
    """One row that could not be used, and why.

    Attributes:
        row_number: The line number in the source file, counting the header as line
            one, so the operator can find the row.
        reason: One of :data:`REJECTION_REASONS`.
        detail: A sentence saying what was wrong.
        raw: The row as it was read.
    """

    row_number: int
    reason: str
    detail: str
    raw: str


@dataclass(frozen=True)
class CalibrationDataset:
    """The accepted observations of a dataset, and everything that was rejected.

    Attributes:
        observations: The rows that passed every gate, in timestamp order.
        rejected: The rows that did not, each with its reason.
        sha256: The SHA-256 of the source file, so a report can name the exact
            data it was fitted to.
        source: Where the data came from.
        ignored_columns: The columns of the source that the schema does not
            declare. They are ignored, but they are named rather than vanishing.
    """

    observations: tuple[Observation, ...] = ()
    rejected: tuple[RejectedObservation, ...] = ()
    sha256: str = ""
    source: str = ""
    ignored_columns: tuple[str, ...] = ()
    rejection_counts: dict[str, int] = field(default_factory=dict)

    @property
    def rows_total(self) -> int:
        """Return how many rows the dataset held before the gates were applied."""
        return len(self.observations) + len(self.rejected)

    def by_container(self) -> dict[str, tuple[Observation, ...]]:
        """Return the accepted observations grouped by container.

        Rows that carry no container identifier are grouped under the empty string,
        so a single-container dataset is still addressable.
        """
        grouped: dict[str, list[Observation]] = {}
        for observation in self.observations:
            grouped.setdefault(observation.container_id or "", []).append(observation)
        return {name: tuple(rows) for name, rows in grouped.items()}


def load_observations_csv(
    path: str | Path,
    *,
    nominal_voltage_v: float = 1000.0,
    voltage_band_min_ratio: float = 0.1,
    voltage_band_max_ratio: float = 2.0,
) -> CalibrationDataset:
    """Read a CSV of observations and apply every row-level gate.

    The expected header is
    ``timestamp_ns,soc_pct,voltage_v,current_a,active_power_w,temperature_c``
    with an optional ``container_id`` column. A column the schema does not declare
    is ignored, but it is reported in :attr:`CalibrationDataset.ignored_columns`.

    Args:
        path: The file to read.
        nominal_voltage_v: The container's nominal voltage, used to declare the
            physical band a terminal voltage must fall in.
        voltage_band_min_ratio: The lowest admissible voltage, as a fraction of the
            nominal voltage.
        voltage_band_max_ratio: The highest admissible voltage, as a fraction of the
            nominal voltage.

    Returns:
        The dataset, with every rejected row and its reason.

    Raises:
        FileNotFoundError: When the file does not exist.
        ValueError: When the file has no header, or is missing a required column.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"No observation file at '{source}'.")

    raw_bytes = source.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()

    text = raw_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError(f"The observation file '{source}' is empty.") from exc

    names = [name.strip() for name in header]
    missing = [column for column in REQUIRED_COLUMNS if column not in names]
    if missing:
        raise ValueError(
            f"The observation file '{source}' is missing the required column(s) "
            f"{', '.join(missing)}. The header must carry {', '.join(REQUIRED_COLUMNS)}."
        )

    ignored = tuple(
        name
        for name in names
        if name not in REQUIRED_COLUMNS and name != CONTAINER_COLUMN and name != ""
    )

    rows: list[tuple[int, list[str]]] = []
    for number, row in enumerate(reader, start=2):
        if not row or all(cell.strip() == "" for cell in row):
            continue
        rows.append((number, row))

    return validate_observations(
        rows,
        source=str(source),
        sha256=digest,
        nominal_voltage_v=nominal_voltage_v,
        voltage_band_min_ratio=voltage_band_min_ratio,
        voltage_band_max_ratio=voltage_band_max_ratio,
        ignored_columns=ignored,
        header=names,
    )


def validate_observations(
    rows: Iterable[tuple[int, list[str]]],
    *,
    source: str = "",
    sha256: str = "",
    nominal_voltage_v: float = 1000.0,
    voltage_band_min_ratio: float = 0.1,
    voltage_band_max_ratio: float = 2.0,
    ignored_columns: Sequence[str] = (),
    header: Sequence[str] = (),
) -> CalibrationDataset:
    """Apply every row-level gate to the rows read from a file.

    Args:
        rows: The rows, each with its line number and its cells.
        source: Where the rows came from.
        sha256: The digest of the source file.
        nominal_voltage_v: The container's nominal voltage.
        voltage_band_min_ratio: The lowest admissible voltage, as a fraction of the
            nominal voltage.
        voltage_band_max_ratio: The highest admissible voltage, as a fraction of the
            nominal voltage.
        ignored_columns: The columns of the source that the schema does not declare.
        header: The header of the source file.

    Returns:
        The dataset, with every rejected row and its reason.
    """
    index_of = {name: position for position, name in enumerate(header)}
    has_container = CONTAINER_COLUMN in index_of

    voltage_min = nominal_voltage_v * voltage_band_min_ratio
    voltage_max = nominal_voltage_v * voltage_band_max_ratio

    accepted: list[Observation] = []
    rejected: list[RejectedObservation] = []
    counts: dict[str, int] = {}
    last_timestamp: int | None = None

    for row_number, cells in rows:
        raw = ",".join(cells)

        if len(cells) != len(header):
            _record(
                rejected,
                counts,
                row_number,
                "MALFORMED_ROW",
                f"The row has {len(cells)} field(s) and the header declares {len(header)}.",
                raw,
            )
            continue

        values: dict[str, float] = {}
        container_id: str | None = None
        malformed = False
        for name in REQUIRED_COLUMNS:
            cell = cells[index_of[name]].strip()
            if cell == "":
                _record(
                    rejected,
                    counts,
                    row_number,
                    "MISSING_VALUE",
                    f"The column '{name}' is empty.",
                    raw,
                )
                malformed = True
                break
            try:
                values[name] = float(cell)
            except ValueError:
                _record(
                    rejected,
                    counts,
                    row_number,
                    "MALFORMED_ROW",
                    f"The column '{name}' holds '{cell}', which is not a number.",
                    raw,
                )
                malformed = True
                break
        if malformed:
            continue

        if has_container:
            container_id = cells[index_of[CONTAINER_COLUMN]].strip() or None

        if not all(math.isfinite(value) for value in values.values()):
            _record(
                rejected,
                counts,
                row_number,
                "NON_FINITE",
                "At least one of the measured values is not a finite number.",
                raw,
            )
            continue

        soc_pct = values["soc_pct"]
        if soc_pct < 0.0 or soc_pct > 100.0:
            _record(
                rejected,
                counts,
                row_number,
                "SOC_OUT_OF_RANGE",
                f"The state of charge is {soc_pct:g} %, outside the 0-100 % range.",
                raw,
            )
            continue

        voltage_v = values["voltage_v"]
        if voltage_v < voltage_min or voltage_v > voltage_max:
            _record(
                rejected,
                counts,
                row_number,
                "VOLTAGE_OUT_OF_BAND",
                (
                    f"The terminal voltage is {voltage_v:g} V, outside the declared band "
                    f"{voltage_min:g}-{voltage_max:g} V "
                    f"({voltage_band_min_ratio:g}-{voltage_band_max_ratio:g} of the nominal "
                    f"{nominal_voltage_v:g} V)."
                ),
                raw,
            )
            continue

        current_a = values["current_a"]
        power_w = values["active_power_w"]

        if (
            abs(power_w) > SIGN_GATE_POWER_FLOOR_W
            and abs(current_a) > 1e-6
            and math.copysign(1.0, power_w) != math.copysign(1.0, current_a)
        ):
            _record(
                rejected,
                counts,
                row_number,
                "POWER_CURRENT_SIGN_MISMATCH",
                (
                    f"The power is {power_w:g} W and the current is {current_a:g} A; the two "
                    "disagree in sign."
                ),
                raw,
            )
            continue

        residual = power_w - voltage_v * current_a
        tolerance = POWER_CURRENT_ABSOLUTE_TOLERANCE_W + POWER_CURRENT_RELATIVE_TOLERANCE * abs(
            power_w
        )
        if abs(residual) > tolerance:
            _record(
                rejected,
                counts,
                row_number,
                "POWER_CURRENT_INCONSISTENT",
                (
                    f"The power, the voltage and the current disagree: "
                    f"{power_w:g} W against {voltage_v:g} V x {current_a:g} A "
                    f"= {voltage_v * current_a:g} W, a residual of {residual:g} W "
                    f"against a tolerance of {tolerance:g} W."
                ),
                raw,
            )
            continue

        timestamp_ns = int(values["timestamp_ns"])
        if timestamp_ns != values["timestamp_ns"]:
            _record(
                rejected,
                counts,
                row_number,
                "MALFORMED_ROW",
                "The timestamp is not a whole number of nanoseconds.",
                raw,
            )
            continue

        if last_timestamp is not None and timestamp_ns <= last_timestamp:
            _record(
                rejected,
                counts,
                row_number,
                "TIMESTAMP_NOT_INCREASING",
                (
                    f"The timestamp {timestamp_ns} ns does not follow the previous accepted "
                    f"timestamp {last_timestamp} ns."
                ),
                raw,
            )
            continue

        last_timestamp = timestamp_ns
        accepted.append(
            Observation(
                timestamp_ns=timestamp_ns,
                soc_pct=soc_pct,
                voltage_v=voltage_v,
                current_a=current_a,
                active_power_w=power_w,
                temperature_c=values["temperature_c"],
                container_id=container_id,
            )
        )

    return CalibrationDataset(
        observations=tuple(accepted),
        rejected=tuple(rejected),
        sha256=sha256,
        source=source,
        ignored_columns=tuple(ignored_columns),
        rejection_counts=counts,
    )


def _record(
    rejected: list[RejectedObservation],
    counts: dict[str, int],
    row_number: int,
    reason: str,
    detail: str,
    raw: str,
) -> None:
    """Record one rejected row and count its reason."""
    rejected.append(
        RejectedObservation(row_number=row_number, reason=reason, detail=detail, raw=raw)
    )
    counts[reason] = counts.get(reason, 0) + 1


def dataset_summary(dataset: CalibrationDataset) -> dict[str, Any]:
    """Return a JSON-serialisable summary of a dataset."""
    return {
        "source": dataset.source,
        "sha256": dataset.sha256,
        "rows_total": dataset.rows_total,
        "rows_accepted": len(dataset.observations),
        "rows_rejected": len(dataset.rejected),
        "rejection_reasons": dict(sorted(dataset.rejection_counts.items())),
        "ignored_columns": list(dataset.ignored_columns),
    }
