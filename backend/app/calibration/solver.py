"""A dependency-free least-squares solver with a rank-aware verdict.

Why this exists
---------------
NumPy and SciPy are **not** dependencies of the backend: ``backend/requirements.txt``
declares neither and no module in the repository imports them. Adding a numerical
dependency for a calibration fitter would mean re-pinning the lock and pulling a
compiled wheel into a simulator whose numerical needs are modest. So the solver is
hand-written, and it is written to do the one thing a calibration needs that a naive
Gaussian elimination cannot: say **which** of the unknowns the data actually
identifies.

The method
----------
A Householder QR factorisation with **column pivoting**, applied to the
**column-scaled** design:

- scaling every column to unit maximum magnitude makes the pivoting meaningful,
  because otherwise the column with the largest raw units (a current in amperes, say)
  would always be pivoted first regardless of how much information it carries;
- pivoting puts the most independent columns first, so a deficiency shows up at the
  **end** of the factorisation rather than somewhere in the middle;
- the rank is read off the diagonal of ``R``, and the columns beyond the rank are
  **dropped** rather than fitted to noise.

The consequence is the property the calibration relies on: an unknown that the data
does not identify is reported as such, and the unknowns it *does* identify are still
fitted. That is not a nicety — a rank-deficient fit that silently returns a number
for an unidentifiable parameter is how a calibration ends up writing a made-up
resistance into a plant.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "LinearSolveResult",
    "RANK_TOLERANCE",
    "WEAK_TOLERANCE",
    "solve_least_squares",
]

#: A pivot smaller than this fraction of the largest pivot is treated as zero, and
#: the column is reported as not identified.
RANK_TOLERANCE: float = 1e-10

#: A pivot smaller than this fraction of the largest pivot is reported as *weak*:
#: the parameter is identified, but the data barely constrains it.
WEAK_TOLERANCE: float = 1e-6


@dataclass(frozen=True)
class LinearSolveResult:
    """The outcome of one least-squares solve.

    Attributes:
        coefficients: The fitted coefficient of every column of the design, in the
            order the columns were given. A column that was dropped carries zero;
            the caller must not read it as a fitted value.
        rank: The number of columns the data identifies.
        identified_columns: The indices of the columns that were fitted.
        dropped_columns: The indices of the columns the data does not identify.
        weak_columns: The indices of the identified columns the data barely
            constrains.
        residuals: The residual of every row, in the order the rows were given.
        rmse: The root-mean-square residual.
        max_abs_residual: The largest absolute residual.
        condition_estimate: A rough conditioning figure, the ratio of the largest
            to the smallest pivot of the factorisation. A large figure means the
            design is close to rank-deficient.
        column_scales: The magnitude each column was scaled by.
    """

    coefficients: tuple[float, ...]
    rank: int
    identified_columns: tuple[int, ...]
    dropped_columns: tuple[int, ...]
    weak_columns: tuple[int, ...]
    residuals: tuple[float, ...]
    rmse: float
    max_abs_residual: float
    condition_estimate: float
    column_scales: tuple[float, ...]

    def is_identified(self, column: int) -> bool:
        """Return whether the data identifies the given column."""
        return column in self.identified_columns

    def is_weak(self, column: int) -> bool:
        """Return whether the given column is identified but barely constrained."""
        return column in self.weak_columns


def solve_least_squares(
    design: Sequence[Sequence[float]],
    target: Sequence[float],
    *,
    rank_tolerance: float = RANK_TOLERANCE,
    weak_tolerance: float = WEAK_TOLERANCE,
) -> LinearSolveResult:
    """Solve ``design @ x ~= target`` in the least-squares sense.

    Args:
        design: The design matrix, one row per observation and one column per
            unknown. Every row must have the same length.
        target: The observed values, one per row.
        rank_tolerance: The relative size below which a pivot is treated as zero.
        weak_tolerance: The relative size below which a pivot is reported as weak.

    Returns:
        The fitted coefficients, the rank, the columns that were identified and
        dropped, and the residuals.

    Raises:
        ValueError: When the design and the target do not have the same number of
            rows, when the design has no columns, or when the rows are ragged.
    """
    row_count = len(target)
    if len(design) != row_count:
        raise ValueError(
            f"The design has {len(design)} row(s) and the target has {row_count}; "
            "they must have the same number of rows."
        )
    if row_count == 0:
        raise ValueError("The design is empty; there is nothing to fit.")

    column_count = len(design[0])
    if column_count == 0:
        raise ValueError("The design has no columns; there is nothing to fit.")
    for index, row in enumerate(design):
        if len(row) != column_count:
            raise ValueError(
                f"Row {index} of the design has {len(row)} column(s) and the first row "
                f"has {column_count}; every row must have the same length."
            )

    scales = _column_scales(design, column_count)
    matrix = [
        [float(design[row][column]) / scales[column] for column in range(column_count)]
        for row in range(row_count)
    ]
    rhs = [float(value) for value in target]

    permutation, diagonal = _pivoted_qr(matrix, rhs, row_count, column_count)

    reference = abs(diagonal[0]) if diagonal else 0.0
    rank = 0
    for value in diagonal:
        if reference > 0.0 and abs(value) > rank_tolerance * reference:
            rank += 1
        else:
            break

    identified = tuple(sorted(permutation[:rank]))
    dropped = tuple(sorted(permutation[rank:]))

    weak: list[int] = []
    for position in range(rank):
        if reference > 0.0 and abs(diagonal[position]) <= weak_tolerance * reference:
            weak.append(permutation[position])

    scaled_solution = _back_substitute(matrix, rhs, rank)
    coefficients = [0.0] * column_count
    for position in range(rank):
        column = permutation[position]
        coefficients[column] = scaled_solution[position] * scales[column]

    residuals: list[float] = []
    for row in range(row_count):
        predicted = 0.0
        for column in range(column_count):
            predicted += float(design[row][column]) * coefficients[column]
        residuals.append(float(target[row]) - predicted)

    rmse = math.sqrt(sum(value * value for value in residuals) / row_count)
    max_abs_residual = max((abs(value) for value in residuals), default=0.0)

    if rank == 0:
        condition = math.inf
    elif rank == 1:
        condition = 1.0
    else:
        smallest = min(abs(diagonal[position]) for position in range(rank))
        condition = (reference / smallest) if smallest > 0.0 else math.inf

    return LinearSolveResult(
        coefficients=tuple(coefficients),
        rank=rank,
        identified_columns=identified,
        dropped_columns=dropped,
        weak_columns=tuple(sorted(weak)),
        residuals=tuple(residuals),
        rmse=rmse,
        max_abs_residual=max_abs_residual,
        condition_estimate=condition,
        column_scales=tuple(scales),
    )


def _column_scales(design: Sequence[Sequence[float]], column_count: int) -> list[float]:
    """Return the magnitude each column is scaled by.

    A column of zeros keeps a scale of one, so it stays a column of zeros and is
    reported as dropped rather than blowing the scaling up.
    """
    scales: list[float] = []
    for column in range(column_count):
        largest = max(abs(float(design[row][column])) for row in range(len(design)))
        scales.append(largest if largest > 0.0 else 1.0)
    return scales


def _pivoted_qr(
    matrix: list[list[float]],
    rhs: list[float],
    row_count: int,
    column_count: int,
) -> tuple[list[int], list[float]]:
    """Factorise the scaled design in place and return the pivot order and diagonal.

    The right-hand side is transformed alongside the matrix, so the caller can
    back-substitute without ever forming ``Q``.
    """
    permutation = list(range(column_count))
    norms = [
        math.sqrt(sum(matrix[row][column] ** 2 for row in range(row_count)))
        for column in range(column_count)
    ]
    diagonal: list[float] = []

    for step in range(min(row_count, column_count)):
        pivot = step
        best = -1.0
        for column in range(step, column_count):
            if norms[column] > best + 1e-300:
                best = norms[column]
                pivot = column
        if pivot != step:
            for row in range(row_count):
                matrix[row][step], matrix[row][pivot] = matrix[row][pivot], matrix[row][step]
            rhs[step], rhs[pivot] = rhs[pivot], rhs[step]
            norms[step], norms[pivot] = norms[pivot], norms[step]
            permutation[step], permutation[pivot] = permutation[pivot], permutation[step]

        column_values = [matrix[row][step] for row in range(step, row_count)]
        column_norm = math.sqrt(sum(value * value for value in column_values))
        if column_norm == 0.0:
            diagonal.append(0.0)
            norms[step] = 0.0
            continue

        alpha = -column_norm if column_values[0] >= 0.0 else column_norm
        reflector = list(column_values)
        reflector[0] -= alpha
        reflector_norm = math.sqrt(sum(value * value for value in reflector))
        if reflector_norm == 0.0:
            diagonal.append(matrix[step][step])
            norms[step] = 0.0
            continue
        reflector = [value / reflector_norm for value in reflector]

        for column in range(step, column_count):
            projection = sum(
                reflector[offset] * matrix[step + offset][column]
                for offset in range(row_count - step)
            )
            factor = 2.0 * projection
            for offset in range(row_count - step):
                matrix[step + offset][column] -= factor * reflector[offset]

        projection = sum(
            reflector[offset] * rhs[step + offset] for offset in range(row_count - step)
        )
        factor = 2.0 * projection
        for offset in range(row_count - step):
            rhs[step + offset] -= factor * reflector[offset]

        diagonal.append(matrix[step][step])
        for column in range(step + 1, column_count):
            norms[column] = math.sqrt(
                sum(matrix[step + 1 + offset][column] ** 2 for offset in range(row_count - step - 1))
            )
        norms[step] = 0.0

    return permutation, diagonal


def _back_substitute(matrix: list[list[float]], rhs: list[float], rank: int) -> list[float]:
    """Solve the leading triangular system and return the solution in pivot order."""
    solution = [0.0] * len(rhs)
    for row in range(rank - 1, -1, -1):
        accumulator = rhs[row]
        for column in range(row + 1, rank):
            accumulator -= matrix[row][column] * solution[column]
        diagonal = matrix[row][row]
        solution[row] = accumulator / diagonal if diagonal != 0.0 else 0.0
    return solution
