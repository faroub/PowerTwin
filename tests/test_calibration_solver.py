"""Tests for the rank-aware least-squares solver.

The property these tests pin down above all is the one the calibration relies
on: column pivoting may permute the **columns** of the design, but it must
never reorder the **target observations**. The forced-pivot test builds a
design whose second column is pivoted to the front and proves that a known
system with coefficients [2, 3] comes back exactly, with a near-zero residual.
"""

from __future__ import annotations

import math

import pytest

from backend.app.calibration.solver import solve_least_squares


class TestForcedPivot:
    """A design whose second column must be pivoted to the front."""

    def test_a_forced_pivot_returns_the_known_coefficients_with_near_zero_residual(
        self,
    ) -> None:
        # target = 2 * column0 + 3 * column1 = [17, 15, 15]. The column scales
        # are (1, 5), so the scaled second column [1, 1, 1] (norm sqrt(3))
        # outranks the scaled first column [1, 0, 0] (norm 1) and is pivoted at
        # the first step. A pivot that also swapped two entries of the target
        # would pair the wrong observation with the wrong target and corrupt
        # exactly this fit.
        design = [[1.0, 5.0], [0.0, 5.0], [0.0, 5.0]]
        target = [17.0, 15.0, 15.0]

        result = solve_least_squares(design, target)

        assert result.rank == 2
        assert result.column_scales == (1.0, 5.0)
        assert result.coefficients == pytest.approx((2.0, 3.0), abs=1e-12)
        assert result.residuals == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)
        assert result.rmse == pytest.approx(0.0, abs=1e-12)
        assert result.max_abs_residual == pytest.approx(0.0, abs=1e-12)
        assert result.identified_columns == (0, 1)
        assert result.dropped_columns == ()
        assert result.is_identified(0)
        assert result.is_identified(1)


class TestOrdinaryLeastSquares:
    """Full-rank designs recover the analytic least-squares solution."""

    def test_intercept_and_slope(self) -> None:
        design = [[1.0, 0.0], [1.0, 1.0], [1.0, 2.0], [1.0, 3.0]]
        target = [1.0, 2.1, 2.9, 4.2]

        result = solve_least_squares(design, target)

        # The analytic solution of this system is intercept 0.99, slope 1.04.
        assert result.rank == 2
        assert result.coefficients == pytest.approx((0.99, 1.04), abs=1e-12)
        assert result.rmse == pytest.approx(0.1024695076595959, abs=1e-9)

    def test_a_single_column_is_fitted_and_reports_unit_condition(self) -> None:
        result = solve_least_squares([[2.0], [4.0], [6.0]], [1.0, 2.0, 3.0])

        assert result.rank == 1
        assert result.coefficients == pytest.approx((0.5,), abs=1e-12)
        assert result.condition_estimate == 1.0
        assert result.rmse == pytest.approx(0.0, abs=1e-12)


class TestRankDeficientDesigns:
    """A column the data does not identify is dropped, never fitted to noise."""

    def test_a_duplicated_column_is_dropped(self) -> None:
        design = [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]
        target = [2.0, 4.0, 6.0]

        result = solve_least_squares(design, target)

        assert result.rank == 1
        assert result.identified_columns == (0,)
        assert result.dropped_columns == (1,)
        assert result.coefficients == pytest.approx((2.0, 0.0), abs=1e-12)
        assert result.is_identified(0)
        assert not result.is_identified(1)
        assert result.rmse == pytest.approx(0.0, abs=1e-12)

    def test_pivoting_moves_a_zero_column_out_of_the_way(self) -> None:
        # Column 0 is identically zero. Without pivoting, the rank read off the
        # diagonal would stop at the first (zero) pivot and report rank 0;
        # with pivoting the informative column is found and fitted.
        design = [[0.0, 1.0], [0.0, 2.0], [0.0, 3.0]]
        target = [1.0, 2.0, 3.0]

        result = solve_least_squares(design, target)

        assert result.rank == 1
        assert result.identified_columns == (1,)
        assert result.dropped_columns == (0,)
        assert result.coefficients == pytest.approx((0.0, 1.0), abs=1e-12)

    def test_an_all_zero_design_has_rank_zero_and_infinite_condition(self) -> None:
        result = solve_least_squares([[0.0, 0.0], [0.0, 0.0]], [1.0, 2.0])

        assert result.rank == 0
        assert result.identified_columns == ()
        assert result.dropped_columns == (0, 1)
        assert result.coefficients == (0.0, 0.0)
        assert math.isinf(result.condition_estimate)
        assert result.rmse == pytest.approx(math.sqrt(2.5))

    def test_a_wide_design_never_reports_more_than_the_row_count(self) -> None:
        design = [[1.0, 0.0, 2.0], [0.0, 1.0, 2.0]]
        target = [3.0, 5.0]

        result = solve_least_squares(design, target)

        assert result.rank == 2
        assert len(result.identified_columns) == 2
        assert len(result.dropped_columns) == 1
        assert result.residuals == pytest.approx((0.0, 0.0), abs=1e-12)

    def test_a_barely_constrained_column_is_identified_but_weak(self) -> None:
        epsilon = 1e-8
        design = [[1.0, 1.0], [1.0, 1.0 + epsilon], [1.0, 1.0 + 2.0 * epsilon]]
        target = [2.0, 2.0, 2.0]

        result = solve_least_squares(design, target)

        assert result.rank == 2
        assert result.identified_columns == (0, 1)
        assert len(result.weak_columns) == 1
        weak = result.weak_columns[0]
        assert result.is_identified(weak)
        assert result.is_weak(weak)

    def test_the_tolerances_are_parameters(self) -> None:
        epsilon = 1e-8
        design = [[1.0, 1.0], [1.0, 1.0 + epsilon], [1.0, 1.0 + 2.0 * epsilon]]
        target = [2.0, 2.0, 2.0]

        lenient = solve_least_squares(design, target, rank_tolerance=1e-4)

        assert lenient.rank == 1
        assert lenient.identified_columns == (0,)
        assert lenient.dropped_columns == (1,)
        assert lenient.coefficients == pytest.approx((2.0, 0.0), abs=1e-9)


class TestInvalidInputs:
    """Anything that would make the fit meaningless is refused, loudly."""

    def test_a_row_count_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="same number of rows"):
            solve_least_squares([[1.0], [2.0]], [1.0])

    def test_an_empty_design_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            solve_least_squares([], [])

    def test_a_design_without_columns_raises(self) -> None:
        with pytest.raises(ValueError, match="no columns"):
            solve_least_squares([[], []], [1.0, 2.0])

    def test_ragged_rows_raise(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            solve_least_squares([[1.0, 2.0], [1.0]], [1.0, 2.0])

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_a_non_finite_design_value_raises(self, value: float) -> None:
        with pytest.raises(ValueError, match="non-finite"):
            solve_least_squares([[1.0], [value]], [1.0, 2.0])

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_a_non_finite_target_value_raises(self, value: float) -> None:
        with pytest.raises(ValueError, match="non-finite"):
            solve_least_squares([[1.0], [2.0]], [1.0, value])
