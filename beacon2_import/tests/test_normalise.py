"""Normaliser behaviour: deduplication (R4), random-sample labelling (R1), outcomes.

Consumes tests/fixtures/normalise/ and the live bycon record.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from beacon2_import.formats.outcomes import Outcome, OutcomeRecorder, Status, note_for
from beacon2_import.normalise.envelope import parse
from beacon2_import.normalise.provenance import (
    PROVENANCE_COLUMNS,
    Provenance,
    label_random_sample,
)
from beacon2_import.normalise.variants import deduplicate, flatten_variant
from beacon2_import.query.classes import VariantClass

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "normalise"
LIVE = Path(__file__).resolve().parent / "fixtures" / "classify" / "bycon_cnv_live.json"


def _rows_from(payload: dict, beacon_id: str = "org.cancercelllines") -> list[dict]:
    rows = []
    for record in parse(payload).records:
        for row in flatten_variant(record):
            rows.append({"beacon_id": beacon_id, **row})
    return rows


@pytest.fixture(scope="module")
def double_expansion():
    payload = json.loads((FIXTURES / "double_expansion_responses.json").read_text())
    rows = [row for response in payload["responses"] for row in _rows_from(response)]
    return payload["_expected"], rows


# ---------------- R4 ----------------

def test_double_expansion_inflates_rows(double_expansion):
    expected, rows = double_expansion
    assert len(rows) == expected["rows_before"]


def test_deduplication_removes_exactly_the_overlap(double_expansion):
    expected, rows = double_expansion
    kept, removed = deduplicate(rows)
    assert len(kept) == expected["rows_after"]
    assert removed == expected["removed"]


def test_frequency_was_already_immune(double_expansion):
    """Distinct biosamples are unchanged -- the exposure was in row counts."""
    expected, rows = double_expansion
    kept, _ = deduplicate(rows)
    assert len({r["biosample_id"] for r in rows}) == expected["distinct_biosamples_before"]
    assert len({r["biosample_id"] for r in kept}) == expected["distinct_biosamples_after"]


def test_rows_from_different_beacons_are_never_merged(double_expansion):
    _, rows = double_expansion
    other = [{**row, "beacon_id": "org.progenetix.beacon"} for row in rows[:2]]
    kept, removed = deduplicate(rows[:2] + other)
    assert removed == 0 and len(kept) == 4


def test_replicate_analyses_of_one_biosample_both_survive():
    row = {"beacon_id": "b", "variant_internal_id": "v", "biosample_id": "bs-1",
           "analysis_id": "an-1", "run_id": ""}
    kept, removed = deduplicate([row, {**row, "analysis_id": "an-2"}])
    assert removed == 0 and len(kept) == 2


def test_rows_without_an_id_are_never_treated_as_duplicates():
    row = {"beacon_id": "b", "variant_internal_id": "", "biosample_id": "bs-1"}
    kept, removed = deduplicate([row, dict(row)])
    assert removed == 0 and len(kept) == 2


# ---------------- the live record ----------------

def test_live_record_flattens_to_the_fourth_location_layout():
    rows = _rows_from(json.loads(LIVE.read_text()))
    assert len(rows) == 1
    row = rows[0]
    assert row["chromosome"] == "3"
    # Wire: 0-based half-open 195728637-198169247. Display: 1-based inclusive.
    assert (row["start"], row["end"]) == (195728638, 198169247)
    assert row["efo_id"] == "EFO:0030070"
    assert row["variant_length"] == 2440610
    assert row["biosample_id"] == "cellzbs-kftvksg5"


# ---------------- R1 ----------------

def _provenance(**overrides) -> Provenance:
    base = dict(beacon_id="org.cancercelllines", beacon_name="Cancer Cell Lines",
                access_tier="public", variant_class="CNV",
                classification_basis="pinned by query", granularity_returned="record")
    base.update(overrides)
    return Provenance(**base)


def test_random_sample_is_labelled_on_the_row():
    labelled = label_random_sample(_provenance(), 100, 2591)
    columns = labelled.as_columns()
    assert columns["query_degraded"] == "true"
    assert "random sample" in columns["degradation_notes"]
    assert "100 of 2591" in columns["degradation_notes"]
    assert "repeat run" in columns["degradation_notes"]


def test_random_sample_label_keeps_existing_notes():
    labelled = label_random_sample(
        _provenance(degradation_notes="bracket flattened to range"), 10, 50)
    notes = labelled.as_columns()["degradation_notes"]
    assert notes.startswith("bracket flattened to range; random sample")


def test_provenance_renders_every_column_in_order():
    assert tuple(_provenance().as_columns()) == PROVENANCE_COLUMNS


def test_random_sample_outcome_note():
    note = note_for("random_sample", retrieved=100, total=2591).lower()
    assert "random sample" in note and "100 of 2591" in note
    assert "repeat run" in note


# ---------------- the outcome contract ----------------

def test_outcomes_have_one_row_per_planned_pair(tmp_path):
    pairs = [("a", VariantClass.CNV), ("a", VariantClass.SMALL_VARIANT),
             ("b", VariantClass.CNV)]
    recorder = OutcomeRecorder(pairs)
    recorder.record(Outcome("a", "A", VariantClass.CNV, "yes", Status.OK, 3))
    path = tmp_path / "outcomes.tsv"
    recorder.write(path)
    lines = path.read_text().splitlines()
    assert len(lines) == 1 + len(pairs)
    unrecorded = [l for l in lines[1:] if "\terror\t" in l]
    assert len(unrecorded) == 2, "unrecorded pairs must appear as errors, not vanish"


def test_an_outcome_cannot_be_recorded_twice():
    recorder = OutcomeRecorder([("a", VariantClass.CNV)])
    outcome = Outcome("a", "A", VariantClass.CNV, "yes", Status.OK)
    recorder.record(outcome)
    with pytest.raises(ValueError, match="twice"):
        recorder.record(outcome)


def test_an_unplanned_pair_cannot_be_recorded():
    recorder = OutcomeRecorder([("a", VariantClass.CNV)])
    with pytest.raises(KeyError, match="not planned"):
        recorder.record(Outcome("z", "Z", VariantClass.CNV, "yes", Status.OK))
