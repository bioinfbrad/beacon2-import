"""The precision ruling, against the raw bycon response.

g_limit100_run1.json is verbatim: 55 records, 60 caseLevelData instances,
numTotalResults 60, and no countPrecision or countAdjustedTo anywhere -- the
shape of every bycon response examined.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from beacon2_import.normalise.envelope import (
    PRECISION_DECLARED, PRECISION_DECLARED_ADJUSTMENT, PRECISION_DEFAULT, PRECISION_PARTIAL,
    PRECISION_INFERRED, EntityTypeMismatch, assert_entity_type,
    effective_count_precision, instance_count, parse,
)
from beacon2_import.normalise.variants import (
    deduplicate, flatten_variant, instance_id_anomalies,
)

RAW = Path(__file__).resolve().parent / "fixtures" / "adapters" / "g_limit100_run1.json"


@pytest.fixture
def raw():
    return json.loads(RAW.read_text())


def _result_set(payload):
    return payload["response"]["resultSets"][0]


def test_the_raw_response_is_what_it_claims(raw):
    records = _result_set(raw)["results"]
    assert len(records) == 55
    assert instance_count(records) == 60
    assert raw["responseSummary"]["numTotalResults"] == 60
    text = json.dumps(raw)
    assert "countPrecision" not in text and "countAdjustedTo" not in text


# ---------------- condition 2: complete record retrieval ----------------

def test_complete_retrieval_infers_exact(raw):
    assert effective_count_precision(parse(raw)) == ("exact", PRECISION_INFERRED)


def test_inferred_is_labelled_distinctly_from_declared(raw):
    declared = copy.deepcopy(raw)
    _result_set(declared)["countPrecision"] = "exact"
    assert effective_count_precision(parse(declared)) == ("exact", PRECISION_DECLARED)
    assert PRECISION_INFERRED != PRECISION_DECLARED


def test_incomplete_retrieval_does_not_infer(raw):
    """One record short of the total: observed as partial, never inferred exact."""
    _result_set(raw)["results"].pop()
    assert effective_count_precision(parse(raw)) == ("imprecise", PRECISION_PARTIAL)


def test_no_inference_below_record_granularity(raw):
    raw["meta"]["returnedGranularity"] = "count"
    assert effective_count_precision(parse(raw))[1] == PRECISION_DEFAULT


def test_no_inference_for_aggregated_granularity(raw):
    """bycon's non-standard `aggregated` is not record-level."""
    raw["meta"]["returnedGranularity"] = "aggregated"
    assert effective_count_precision(parse(raw))[0] == "imprecise"


# ---------------- condition 1: a declaration always wins ----------------

@pytest.mark.parametrize("declared", ["imprecise", "rounded"])
def test_an_explicit_approximation_refuses_even_when_complete(raw, declared):
    _result_set(raw)["countPrecision"] = declared
    precision, basis = effective_count_precision(parse(raw))
    assert precision == declared and basis == PRECISION_DECLARED


def test_a_declared_adjustment_refuses_even_when_complete(raw):
    _result_set(raw)["countAdjustedTo"] = 10
    assert effective_count_precision(parse(raw)) == (
        "imprecise", PRECISION_DECLARED_ADJUSTMENT)


# ---------------- the accepted residual risk, pinned ----------------

def test_accepted_residual_risk_round_and_truncate_to_match(raw):
    """A server rounding its total to 50 AND truncating delivery to exactly 50
    instances passes. Accepted in the ruling as two independent behaviours
    coinciding to the instance. If this test ever starts failing, the
    behaviour changed: revisit the ruling rather than just updating the test.
    """
    records = _result_set(raw)["results"]
    kept, instances = [], 0
    for record in records:
        n = len(record.get("caseLevelData") or []) or 1
        if instances + n > 50:
            break
        kept.append(record)
        instances += n
    _result_set(raw)["results"] = kept
    raw["responseSummary"]["numTotalResults"] = instances
    assert effective_count_precision(parse(raw)) == ("exact", PRECISION_INFERRED)


# ---------------- the entity check on real bycon data ----------------

def test_bycon_returned_schemas_use_id_and_are_checked(raw):
    """bycon writes returnedSchemas[].id, not entityType. The check must run."""
    assert "entityType" not in raw["meta"]["returnedSchemas"][0]
    envelope = parse(raw)
    assert envelope.returned_entity_type == "genomicVariant"
    assert assert_entity_type(envelope, "genomicVariant") == []


def test_bycon_wrong_entity_raises(raw):
    with pytest.raises(EntityTypeMismatch):
        assert_entity_type(parse(raw), "biosample")


# ---------------- dedup on real data ----------------

def _rows(raw):
    return [{"beacon_id": "org.cancercelllines", **row}
            for record in parse(raw).records for row in flatten_variant(record)]


def test_composite_key_is_unique_per_real_instance(raw):
    rows = _rows(raw)
    assert len(rows) == 60
    kept, removed = deduplicate(rows)
    assert removed == 0 and len(kept) == 60


def test_run_id_is_always_empty_on_bycon(raw):
    assert {row["run_id"] for row in _rows(raw)} == {""}


def test_variant_id_cross_check_finds_no_anomaly_in_real_data(raw):
    rows = _rows(raw)
    assert len({row["instance_id"] for row in rows}) == 60
    assert instance_id_anomalies(rows) == []


def test_variant_id_cross_check_reports_a_split_instance(raw):
    rows = _rows(raw)
    rows[1] = {**rows[1], "instance_id": rows[0]["instance_id"]}
    anomalies = instance_id_anomalies(rows)
    assert len(anomalies) == 1 and rows[0]["instance_id"] in anomalies[0]
