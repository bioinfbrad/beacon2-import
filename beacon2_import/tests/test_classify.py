"""Record classification, driven by tests/fixtures/classify/expected.tsv.

Mirrors the coalescence pattern: the fixtures and their expectations ARE the
specification, and the suite skips loudly until classify() has a body rather
than passing vacuously.

This matters more than it looks. Under the ruling that a class-``unknown``
provider is queried anyway, classify() runs on every record returned by every
unverified-class query -- which is most records, out of the box, given how much
of the registry starts as unknown. It is therefore the function whose untested
state is least visible and most consequential, and it should not have been the
one fixture set with no consumer.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "classify"
EXPECTATIONS = FIXTURES / "expected.tsv"


def _expectations() -> list[dict[str, str]]:
    with EXPECTATIONS.open() as handle:
        rows = [line for line in handle if not line.startswith("#")]
    return list(csv.DictReader(rows, delimiter="\t"))


CASES = _expectations()
IDS = [case["fixture"] for case in CASES]


def _load(name: str) -> dict:
    """Load a fixture as the RECORD classify() expects.

    Most fixtures are bare records. bycon_cnv_live.json is a verbatim response
    envelope, kept that way because it is a real capture -- so the record is
    unwrapped here. classify() takes a record and must not grow an
    envelope-unwrapping branch to accommodate a fixture's shape.
    """
    payload = json.loads((FIXTURES / name).read_text())
    response = payload.get("response")
    if isinstance(response, dict):
        return response["resultSets"][0]["results"][0]
    return payload


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_class_and_basis(case):
    """Each fixture classifies to its expected class, for the expected reason.

    The basis is asserted as a substring so wording can be refined, but the
    reason CATEGORY is pinned -- a record reaching the right class by the wrong
    route is still a bug.
    """
    from beacon2_import.normalise.classify import classify

    try:
        variant_class, basis = classify(_load(case["fixture"]))
    except NotImplementedError:
        pytest.skip("classify() not yet implemented -- these fixtures are its spec")

    assert str(variant_class.value) == case["expected_class"], case["fixture"]
    assert case["basis_contains"].lower() in basis.lower(), (
        f"{case['fixture']}: basis {basis!r} does not mention "
        f"{case['basis_contains']!r}"
    )


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_variant_length(case):
    """variant_length is computed independently of class."""
    from beacon2_import.normalise.classify import variant_length

    try:
        length = variant_length(_load(case["fixture"]))
    except NotImplementedError:
        pytest.skip("variant_length() not yet implemented")

    assert length == int(case["expected_variant_length"]), case["fixture"]


def test_size_never_decides_class():
    """The paired fixtures are the same size and different classes.

    This is the regression test for rule 4b, the rejected proposal that size
    could reassign class. If someone reintroduces a length-based branch, these
    two records -- identical at 120 bp, one sequence-specified and one not --
    are what catches it.
    """
    paired = ("large_indel_boundary.json", "large_no_sequence_no_junction.json")
    expected = {case["fixture"]: case for case in CASES}

    lengths = {expected[name]["expected_variant_length"] for name in paired}
    assert len(lengths) == 1, f"the paired fixtures must be the same size: {lengths}"

    classes = {expected[name]["expected_class"] for name in paired}
    assert len(classes) == 2, f"the paired fixtures must differ in class: {classes}"


def test_every_fixture_has_an_expectation():
    """No fixture may sit in the directory unclaimed by expected.tsv."""
    on_disk = {p.name for p in FIXTURES.glob("*.json")}
    claimed = {case["fixture"] for case in CASES}
    assert on_disk == claimed, {
        "unclaimed": sorted(on_disk - claimed),
        "missing": sorted(claimed - on_disk),
    }


# ---------------- VRS 2.0 Allele states ----------------

def _rle_record():
    return json.loads((FIXTURES / "progenetix_rle_deletion.json").read_text())


def test_a_reference_length_expression_is_a_small_variant_not_a_repeat():
    """A real Progenetix testMode record: a 1-base deletion of C, VRS-normalised."""
    from beacon2_import.normalise.classify import classify
    from beacon2_import.query.classes import VariantClass

    klass, basis = classify(_rle_record())
    assert klass is VariantClass.SMALL_VARIANT
    assert "ReferenceLengthExpression" in basis and "deletion" in basis
    assert "repeat" not in basis.lower()


def test_the_type_label_does_not_drive_the_class():
    """Progenetix labels it SO:0001483 (SNP); the basis must come from the state."""
    from beacon2_import.normalise.classify import classify

    _, basis = classify(_rle_record())
    assert "SNP" not in basis and "SO:0001483" not in basis


def test_repeat_subunit_length_alone_is_not_repeat_evidence():
    from beacon2_import.normalise.classify import classify
    from beacon2_import.query.classes import VariantClass

    record = _rle_record()
    record["variation"]["state"] = {"type": "ReferenceLengthExpression", "length": 6,
                                    "repeatSubunitLength": 3}
    record["variation"]["referenceSequence"] = "CAG"
    klass, basis = classify(record)
    assert klass is VariantClass.SMALL_VARIANT and "insertion" in basis


def test_a_repeated_sequence_expression_is_a_repeat():
    """The explicit repeat claim: a unit with a copy count (VRS 1.x)."""
    from beacon2_import.normalise.classify import classify
    from beacon2_import.query.classes import VariantClass

    record = {"variation": {"type": "Allele", "state": {
        "type": "RepeatedSequenceExpression", "count": {"value": 40},
        "seq_expr": {"type": "LiteralSequenceExpression", "sequence": "CAG"}}}}
    assert classify(record)[0] is VariantClass.REPEAT


def test_a_literal_sequence_expression_allele_is_a_small_variant():
    from beacon2_import.normalise.classify import classify
    from beacon2_import.query.classes import VariantClass

    record = {"variation": {"type": "Allele", "referenceSequence": "G",
                            "location": {"start": 10, "end": 11},
                            "state": {"type": "LiteralSequenceExpression", "sequence": "A"}}}
    klass, basis = classify(record)
    assert klass is VariantClass.SMALL_VARIANT and "substitution" in basis


def test_a_large_reference_length_expression_discloses_its_length():
    from beacon2_import.normalise.classify import classify
    from beacon2_import.query.classes import VariantClass

    record = _rle_record()
    record["variation"]["state"] = {"type": "ReferenceLengthExpression", "length": 400,
                                    "repeatSubunitLength": 1}
    klass, basis = classify(record)
    assert klass is VariantClass.SMALL_VARIANT and "exceeds" in basis
