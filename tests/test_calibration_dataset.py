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
    def test_simultaneous_samples_from_different_containers_are_valid(self, tmp_path: Path) -> None:
        rows = [(1_000, "A"), (1_000, "B"), (2_000, "A"), (2_000, "B"), (3_000, "A")]
        text = HEADER_WITH_CONTAINER + "\n" + "\n".join(_row(ts, c) for ts, c in rows) + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.rejected == ()
        assert len(dataset.observations) == 5
        grouped = dataset.by_container()
        assert set(grouped) == {"A", "B"}
        assert [o.timestamp_ns for o in grouped["A"]] == [1_000, 2_000, 3_000]
        assert [o.timestamp_ns for o in grouped["B"]] == [1_000, 2_000]

    def test_a_duplicate_timestamp_within_one_container_is_rejected(self, tmp_path: Path) -> None:
        text = (
            HEADER_WITH_CONTAINER
            + "\n"
            + _row(1_000, "A")
            + "\n"
            + _row(1_000, "A")
            + "\n"
            + _row(2_000, "B")
            + "\n"
        )

        dataset = load_observations_csv(_write(tmp_path, text))

        assert [o.timestamp_ns for o in dataset.observations] == [1_000, 2_000]
        assert dataset.rejection_counts == {"TIMESTAMP_NOT_INCREASING": 1}
        assert "container 'A'" in dataset.rejected[0].detail

    def test_a_reversed_timestamp_within_one_container_is_rejected(self, tmp_path: Path) -> None:
        text = HEADER_WITH_CONTAINER + "\n" + _row(2_000, "A") + "\n" + _row(1_000, "A") + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert [o.timestamp_ns for o in dataset.observations] == [2_000]
        assert dataset.rejection_counts == {"TIMESTAMP_NOT_INCREASING": 1}

    def test_a_container_repeating_its_own_timestamp_is_rejected_even_when_another_moved_on(
        self, tmp_path: Path
    ) -> None:
        text = (
            HEADER_WITH_CONTAINER
            + "\n"
            + _row(1_000, "A")
            + "\n"
            + _row(2_000, "B")
            + "\n"
            + _row(1_000, "A")
            + "\n"
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


class TestRowGates:
    """Every gate rejects what it should, with a stated reason."""

    @pytest.mark.parametrize("cell", ["nan", "inf", "-inf"])
    def test_a_non_finite_measured_value_is_rejected(self, tmp_path: Path, cell: str) -> None:
        text = HEADER + "\n" + f"1000,50.0,{cell},10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"NON_FINITE": 1}

    @pytest.mark.parametrize("soc", ["-0.1", "100.1", "101"])
    def test_a_soc_outside_0_100_is_rejected(self, tmp_path: Path, soc: str) -> None:
        text = HEADER + "\n" + f"1000,{soc},1000.0,10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"SOC_OUT_OF_RANGE": 1}

    @pytest.mark.parametrize("voltage,power", [("50.0", "500.0"), ("2001.0", "20010.0")])
    def test_a_voltage_outside_the_declared_band_is_rejected(
        self, tmp_path: Path, voltage: str, power: str
    ) -> None:
        text = HEADER + "\n" + f"1000,50.0,{voltage},10.0,{power},25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"VOLTAGE_OUT_OF_BAND": 1}

    def test_a_power_and_current_that_disagree_in_sign_are_rejected(self, tmp_path: Path) -> None:
        text = HEADER + "\n" + "1000,50.0,1000.0,-10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"POWER_CURRENT_SIGN_MISMATCH": 1}

    def test_a_power_that_contradicts_voltage_times_current_is_rejected(
        self, tmp_path: Path
    ) -> None:
        text = HEADER + "\n" + "1000,50.0,1000.0,10.0,10100.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"POWER_CURRENT_INCONSISTENT": 1}

    def test_a_power_within_tolerance_of_voltage_times_current_is_accepted(
        self, tmp_path: Path
    ) -> None:
        text = HEADER + "\n" + "1000,50.0,1000.0,10.0,10005.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert len(dataset.observations) == 1
        assert dataset.rejected == ()

    def test_the_sign_gate_is_not_applied_below_the_power_floor(self, tmp_path: Path) -> None:
        # 0.5 W is below the 1 W floor of the sign gate, so the sign of the
        # current is not compared; the consistency gate still holds the row to
        # v * i.
        text = HEADER + "\n" + "1000,50.0,1000.0,0.0005,-0.5,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert len(dataset.observations) == 1
        assert dataset.rejected == ()

    def test_an_empty_cell_is_a_missing_value(self, tmp_path: Path) -> None:
        text = HEADER + "\n" + "1000,50.0,,10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"MISSING_VALUE": 1}
        assert "voltage_v" in dataset.rejected[0].detail

    def test_a_non_numeric_cell_is_malformed(self, tmp_path: Path) -> None:
        text = HEADER + "\n" + "1000,50.0,abc,10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"MALFORMED_ROW": 1}

    def test_a_row_with_the_wrong_number_of_fields_is_malformed(self, tmp_path: Path) -> None:
        text = HEADER + "\n" + "1000,50.0,1000.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.observations == ()
        assert dataset.rejection_counts == {"MALFORMED_ROW": 1}

    def test_every_declared_rejection_reason_can_occur(self, tmp_path: Path) -> None:
        rows = [
            "not-a-number,50.0,1000.0,10.0,10000.0,25.0",
            "1000,50.0,1000.0,10.0,10000.0",
            "2000,,1000.0,10.0,10000.0,25.0",
            "3000,nan,1000.0,10.0,10000.0,25.0",
            "4000,120.0,1000.0,10.0,10000.0,25.0",
            "5000,50.0,1000.0,-10.0,10000.0,25.0",
            "6000,50.0,1000.0,10.0,20000.0,25.0",
            "7000,50.0,5.0,10.0,50.0,25.0",
            "8000,50.0,1000.0,10.0,10000.0,25.0",
            "8000,50.0,1000.0,10.0,10000.0,25.0",
        ]
        text = HEADER + "\n" + "\n".join(rows) + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert set(dataset.rejection_counts) == set(REJECTION_REASONS)
        assert [o.timestamp_ns for o in dataset.observations] == [8_000]


class TestTheLoader:
    def test_the_sha256_names_the_exact_file(self, tmp_path: Path) -> None:
        path = _write(tmp_path, HEADER + "\n" + _row(1_000) + "\n")

        dataset = load_observations_csv(path)

        assert dataset.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert dataset.source == str(path)

    def test_a_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No observation file"):
            load_observations_csv(tmp_path / "does-not-exist.csv")

    def test_an_empty_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            load_observations_csv(_write(tmp_path, ""))

    def test_a_missing_required_column_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "timestamp_ns,soc_pct\n1000,50.0\n")

        with pytest.raises(ValueError, match="missing the required column"):
            load_observations_csv(path)

    def test_undeclared_columns_are_ignored_but_named(self, tmp_path: Path) -> None:
        text = HEADER + ",operator_note\n" + _row(1_000) + ",hello\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.ignored_columns == ("operator_note",)
        assert len(dataset.observations) == 1

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        text = HEADER + "\n\n" + _row(1_000) + "\n   \n" + _row(2_000) + "\n\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert len(dataset.observations) == 2
        assert dataset.rejected == ()

    def test_rows_total_counts_accepted_and_rejected(self, tmp_path: Path) -> None:
        text = HEADER + "\n" + _row(1_000) + "\n" + "2000,150.0,1000.0,10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        assert dataset.rows_total == 2
        assert len(dataset.observations) == 1
        assert len(dataset.rejected) == 1

    def test_rows_without_a_container_group_under_the_empty_string(self, tmp_path: Path) -> None:
        text = HEADER + "\n" + _row(1_000) + "\n" + _row(2_000) + "\n"

        dataset = load_observations_csv(_write(tmp_path, text))

        grouped = dataset.by_container()
        assert set(grouped) == {""}
        assert len(grouped[""]) == 2

    def test_the_summary_reports_every_count(self, tmp_path: Path) -> None:
        text = HEADER + "\n" + _row(1_000) + "\n" + "2000,150.0,1000.0,10.0,10000.0,25.0\n"

        dataset = load_observations_csv(_write(tmp_path, text))
        summary = dataset_summary(dataset)

        assert summary["rows_total"] == 2
        assert summary["rows_accepted"] == 1
        assert summary["rows_rejected"] == 1
        assert summary["rejection_reasons"] == {"SOC_OUT_OF_RANGE": 1}
        assert summary["sha256"] == dataset.sha256
        assert summary["source"] == dataset.source
        assert summary["ignored_columns"] == []
