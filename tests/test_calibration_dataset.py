"""Tests for the calibration observation dataset.

Two properties are pinned down above all:

* ``timestamp_ns`` is parsed as an **exact integer** from its CSV token, never
  through a float — near 10**18 ns a double carries fewer significant digits
  than the integer has, and a float round trip would silently move the sample
  in time;
* the "timestamps must increase" gate runs **per container**, so two
  containers sampled at the same instant are both valid observations.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from backend.app.calibration.dataset import (
    REJECTION_REASONS,
    dataset_summary,
    load_observations_csv,
    validate_observations,
)

HEADER = "timestamp_ns,soc_pct,voltage_v,current_a,active_power_w,temperature_c"
HEADER_WITH_CONTAINER = HEADER + ",container_id"


def _row(timestamp: object, container: str | None = None) -> str:
    """One valid row: 1000 V x 10 A = 10000 W, signs agreeing, SoC in range."""
    cells = [str(timestamp), "50.0", "1000.0", "10.0", "10000.0", "25.0"]
    if container is not None:
        cells.append(container)
    return ",".join(cells)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "observations.csv"
    path.write_text(text, encoding="utf-8")
    return path


class TestExactTimestampParsing:
    def test_a_timestamp_near_10_18_ns_is_preserved_exactly(self, tmp_path: Path) -> None:
        big = 10**18
        text = HEADER + "\n" + _row(big) + "\n" + _row(big + 1) + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        # A float cannot tell 10**18 and 10**18 + 1 apart; the integer can.
        assert float(big) == float(big + 1)
        assert [o.timestamp_ns for o in dataset.observations] == [big, big + 1]
        assert dataset.rejected == ()

    @pytest.mark.parametrize(
        "token",
        ["1e18", "1000000000000000000.5", "0x10", "abc", "nan", "inf", "1 2"],
    )
    def test_a_token_that_is_not_a_whole_number_is_malformed(
        self, tmp_path: Path, token: str
    ) -> None:
        text = HEADER + "\n" + f"{token},50.0,1000.0,10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"MALFORMED_ROW": 1}
        assert "timestamp_ns" in dataset.rejected[0].detail


class TestPerContainerOrdering:
    def test_simultaneous_samples_from_different_containers_are_valid(
        self, tmp_path: Path
    ) -> None:
        rows = [(1_000, "A"), (1_000, "B"), (2_000, "A"), (2_000, "B"), (3_000, "A")]
        text = HEADER_WITH_CONTAINER + "\n" + "\n".join(_row(ts, c) for ts, c in rows) + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.rejected == ()
        assert len(dataset.observations) == 5
        grouped = dataset.by_container()
        assert set(grouped) == {"A", "B"}
        assert [o.timestamp_ns for o in grouped["A"]] == [1_000, 2_000, 3_000]
        assert [o.timestamp_ns for o in grouped["B"]] == [1_000, 2_000]

    def test_a_duplicate_timestamp_within_one_container_is_rejected(
        self, tmp_path: Path
    ) -> None:
        text = (
            HEADER_WITH_CONTAINER + "\n"
            + _row(1_000, "A") + "\n"
            + _row(1_000, "A") + "\n"
            + _row(2_000, "B") + "\n"
        )

        dataset = load_observations_csv(_write(tmp_path, text))

        assert [o.timestamp_ns for o in dataset.observations] == [1_000, 2_000]
        assert dataset.rejection_counts == {"TIMESTAMP_NOT_INCREASING": 1}
        assert "container 'A'" in dataset.rejected[0].detail

    def test_a_reversed_timestamp_within_one_container_is_rejected(
        self, tmp_path: Path
    ) -> None:
        text = HEADER_WITH_CONTAINER + "\n" + _row(2_000, "A") + "\n" + _row(1_000, "A") + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert [o.timestamp_ns for o in dataset.observations] == [2_000]
        assert dataset.rejection_counts == {"TIMESTAMP_NOT_INCREASING": 1}

    def test_a_container_repeating_its_own_timestamp_is_rejected_even_when_another_moved_on(
        self, tmp_path: Path
    ) -> None:
        text = (
            HEADER_WITH_CONTAINER + "\n"
            + _row(1_000, "A") + "\n"
            + _row(2_000, "B") + "\n"
            + _row(1_000, "A") + "\n"
        )

        dataset = load_observations_csv(_write(tmp_path, text))

        assert [(o.container_id, o.timestamp_ns) for o in dataset.observations] == [
            ("A", 1_000),
            ("B", 2_000),
        ]
        assert dataset.rejection_counts == {"TIMESTAMP_NOT_INCREASING": 1}

    def test_without_a_container_column_the_ordering_gate_still_applies(
        self, tmp_path: Path
    ) -> None:
        text = HEADER + "\n" + _row(2_000) + "\n" + _row(1_000) + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert [o.timestamp_ns for o in dataset.observations] == [2_000]
        assert dataset.rejection_counts == {"TIMESTAMP_NOT_INCREASING": 1}
        assert "the dataset" in dataset.rejected[0].detail

    def test_validate_observations_applies_the_same_gates_without_a_file(self) -> None:
        dataset = validate_observations(
            [(2, _row(5).split(",")), (3, _row(4).split(","))],
            header=HEADER.split(","),
        )

        assert [o.timestamp_ns for o in dataset.observations] == [5]
        assert dataset.rejection_counts == {"TIMESTAMP_NOT_INCREASING": 1}


class TestVoltageBandArguments:
    @pytest.mark.parametrize("nominal", [0.0, -5.0, math.nan, math.inf, -math.inf])
    def test_an_invalid_nominal_voltage_raises(self, tmp_path: Path, nominal: float) -> None:
        path = _write(tmp_path, HEADER + "\n" + _row(1_000) + "\n")

        with pytest.raises(ValueError, match="nominal voltage"):
            load_observations_csv(path, nominal_voltage_v=nominal)

    @pytest.mark.parametrize("ratio", [0.0, -0.1, math.nan, math.inf])
    def test_an_invalid_minimum_ratio_raises(self, tmp_path: Path, ratio: float) -> None:
        path = _write(tmp_path, HEADER + "\n" + _row(1_000) + "\n")

        with pytest.raises(ValueError, match="minimum voltage-band ratio"):
            load_observations_csv(path, voltage_band_min_ratio=ratio)

    @pytest.mark.parametrize("ratio", [math.nan, math.inf, -math.inf])
    def test_a_non_finite_maximum_ratio_raises(self, tmp_path: Path, ratio: float) -> None:
        path = _write(tmp_path, HEADER + "\n" + _row(1_000) + "\n")

        with pytest.raises(ValueError, match="maximum voltage-band ratio must be a finite"):
            load_observations_csv(path, voltage_band_max_ratio=ratio)

    @pytest.mark.parametrize("min_ratio,max_ratio", [(0.5, 0.5), (0.5, 0.2), (2.0, 0.1)])
    def test_a_maximum_not_above_the_minimum_raises(
        self, tmp_path: Path, min_ratio: float, max_ratio: float
    ) -> None:
        path = _write(tmp_path, HEADER + "\n" + _row(1_000) + "\n")

        with pytest.raises(ValueError, match="must exceed the minimum ratio"):
            load_observations_csv(
                path, voltage_band_min_ratio=min_ratio, voltage_band_max_ratio=max_ratio
            )

    def test_validate_observations_rejects_an_invalid_band_without_a_file(self) -> None:
        with pytest.raises(ValueError, match="nominal voltage"):
            validate_observations([], header=HEADER.split(","), nominal_voltage_v=0.0)

    def test_the_band_boundaries_are_inclusive(self, tmp_path: Path) -> None:
        # Nominal 1000 V with ratios 0.1-2.0: the band is [100, 2000] V, and
        # both edges are admissible; anything outside is rejected.
        rows = [
            "1000,50.0,100.0,10.0,1000.0,25.0",
            "2000,50.0,2000.0,10.0,20000.0,25.0",
            "3000,50.0,99.9,10.0,999.0,25.0",
            "4000,50.0,2000.1,10.0,20001.0,25.0",
        ]
        text = HEADER + "\n" + "\n".join(rows) + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert [o.timestamp_ns for o in dataset.observations] == [1_000, 2_000]
        assert dataset.rejection_counts == {"VOLTAGE_OUT_OF_BAND": 2}

    def test_a_custom_band_is_applied(self, tmp_path: Path) -> None:
        path = _write(tmp_path, HEADER + "\n" + _row(1_000) + "\n")

        dataset = load_observations_csv(
            path, nominal_voltage_v=500.0, voltage_band_min_ratio=0.5, voltage_band_max_ratio=1.5
        )

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"VOLTAGE_OUT_OF_BAND": 1}
