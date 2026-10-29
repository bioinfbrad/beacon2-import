"""Trust the response: every record is checked against the query that produced it.

Both failures these tests exist for came from the first real Galaxy run, where
the fixture answered EVERY request with one recorded chr3 CNV response:

  * a SMALL_VARIANT sequence query reported sixty copy-number records as sixty
    small variants -- "pinned by query" -- and offered them as evidence to
    upgrade the registry to `yes`;
  * a chr17 range query reported chromosome 3 records as its answers.

The stub below reproduces that fixture exactly: the real recorded response,
whatever is asked. The real CLI, retrieval, classifier and writers run on top.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from beacon2_import.normalise.envelope import PRECISION_FAILED_VERIFICATION
from beacon2_import.normalise.verify import Region, verify_records
from beacon2_import.query.classes import VariantClass
from beacon2_import.transport.http import Response

RAW = Path(__file__).resolve().parent / "fixtures" / "adapters" / "g_limit100_run1.json"


class SameAnswerForEverything:
    """The Galaxy fixture's flaw, on purpose: one canned response per endpoint."""

    def post(self, path, body):
        return Response(200, json.loads(RAW.read_text()), f"stub://{path}", "POST", 0.0)


@pytest.fixture
def run(monkeypatch, tmp_path, capsys):
    from beacon2_import.cli import common
    from beacon2_import.cli.main import main

    def _run(*argv, **registry):
        import dataclasses

        if registry:
            original = common.resolve

            def resolve(ids, table, reg):
                providers, unresolvable = original(ids, table, reg)
                return [dataclasses.replace(p, **registry) for p in providers], unresolvable

            monkeypatch.setattr(common, "resolve", resolve)
        monkeypatch.setattr(common, "make_client", lambda p, c: SameAnswerForEverything())
        results, outcomes = tmp_path / "results.tsv", tmp_path / "outcomes.tsv"
        assert main([*argv, "--providers", "org.cancercelllines",
                     "--results", str(results), "--outcomes", str(outcomes)]) == 0
        read = lambda p: list(csv.DictReader(p.open(), delimiter="\t"))
        return read(results), read(outcomes)[0], capsys.readouterr().err

    return _run


# ---------------- bug 1: class is observed, never stamped ----------------

def test_a_small_variant_query_answered_with_cnv_records(run):
    # Server mode, as the sequence query was sent when this failure was found:
    # the request carried bases, so CNVs coming back mean a parameter was ignored.
    rows, outcome, stderr = run(
        "sequence", "--variant-class", "SMALL_VARIANT", "--reference-name", "17",
        "--start", "7577121", "--reference-bases", "G", "--alternate-bases", "A",
        sequence_query_mode="server")
    assert rows == [], "no copy-number record may appear as a small variant"
    assert outcome["variant_class"] == "SMALL_VARIANT" and outcome["row_count"] == "0"
    assert "did not match the requested class (got CNV)" in outcome["notes"]
    assert "may have ignored a query parameter" in outcome["notes"]
    assert outcome["count_precision"] != "exact"
    assert outcome["count_precision_basis"] == PRECISION_FAILED_VERIFICATION
    assert 'status: "yes"' not in stderr, "a stamped class was offered as registry evidence"


def test_no_row_is_ever_labelled_by_the_query(run):
    rows, _, _ = run("range", "--variant-class", "CNV", "--reference-name", "3",
                     "--start", "195728638", "--end", "198169247")
    assert rows and not any("pinned" in r["classification_basis"] for r in rows)
    assert {r["variant_class"] for r in rows} == {"CNV"}


def test_records_of_the_requested_class_still_count(run):
    """The real response, asked for what it actually holds: all 60 instances kept."""
    rows, outcome, _ = run("range", "--variant-class", "CNV", "--reference-name", "3",
                           "--start", "195728638", "--end", "198169247")
    assert outcome["row_count"] == "60" and len(rows) == 60
    assert outcome["count_precision"] == "exact"


# ---------------- bug 2: region is observed, never assumed ----------------

def test_a_chr17_query_answered_with_chr3_records(run):
    rows, outcome, _ = run("range", "--variant-class", "CNV", "--reference-name", "17",
                           "--start", "7572837", "--end", "7578641")
    assert rows == [], "chromosome 3 records presented as chromosome 17 answers"
    assert "outside the requested region" in outcome["notes"]
    assert "chromosome 3 for a chromosome 17 query" in outcome["notes"]
    assert outcome["count_precision_basis"] == PRECISION_FAILED_VERIFICATION


def test_the_right_chromosome_but_the_wrong_place_is_excluded(run):
    rows, outcome, _ = run("range", "--variant-class", "CNV", "--reference-name", "3",
                           "--start", "1000", "--end", "2000")
    assert rows == [] and "outside the requested region" in outcome["notes"]


# ---------------- the semantics of each form, unit level ----------------

def _record(chromosome, start, end, term="EFO:0030067", state=None):
    variation = {"variantState": {"id": term},
                 "location": {"chromosome": chromosome, "start": start, "end": end}}
    if state:
        variation = {"location": {"chromosome": chromosome, "start": start, "end": end},
                     "referenceSequence": "C", "state": state}
    return {"variantInternalId": f"{chromosome}:{start}-{end}", "variation": variation}


@pytest.mark.parametrize("spelling", ["9", "chr9", "refseq:NC_000009.12", "NC_000009.12"])
def test_chromosome_is_normalised_as_outgoing_names_are(spelling):
    from beacon2_import.query.coordinates import normalise_chromosome

    region = Region(normalise_chromosome(spelling), "overlap", (100,), (200,))
    for stored in ("9", "chr9", "refseq:NC_000009.12"):
        assert verify_records([_record(stored, 150, 160)], [VariantClass.CNV], region).kept


def test_overlap_for_range():
    region = Region("9", "overlap", (100,), (200,))
    kept = verify_records([_record("9", 50, 101), _record("9", 199, 300), _record("9", 0, 100),
                           _record("9", 200, 250)], [VariantClass.CNV], region).kept
    assert [c.record["variantInternalId"] for c in kept] == ["9:50-101", "9:199-300"]


def test_both_windows_for_bracket():
    region = Region("9", "bracket", (100, 110), (500, 510))
    verdict = verify_records([_record("9", 105, 505), _record("9", 99, 505),
                              _record("9", 105, 511)], [VariantClass.CNV], region)
    assert len(verdict.kept) == 1 and verdict.outside_region == 2


def test_exact_position_for_sequence():
    region = Region("1", "position", (35359149,))
    snv = {"variation": {"location": {"chromosome": "1", "start": 35359149, "end": 35359150},
                         "referenceBases": "C", "alternateBases": "T"}}
    shifted = {"variation": {"location": {"chromosome": "1", "start": 35359150, "end": 35359151},
                             "referenceBases": "C", "alternateBases": "T"}}
    verdict = verify_records([snv, shifted], [VariantClass.SMALL_VARIANT], region)
    assert len(verdict.kept) == 1 and verdict.outside_region == 1


def test_a_vrs_normalised_indel_spanning_the_position_answers_a_sequence_query():
    """VRS widens an indel in a repeat over the whole repeat (normalization.rst)."""
    region = Region("1", "position", (35359150,))
    rle = _record("1", 35359147, 35359152,
                  state={"type": "ReferenceLengthExpression", "length": 4, "repeatSubunitLength": 1})
    rle["variation"]["referenceSequence"] = "CCCCC"
    assert verify_records([rle], [VariantClass.SMALL_VARIANT], region).kept


def test_containment_for_the_mongodb_cnv_path():
    region = Region("1", "containment", (1000,), (2000,))
    verdict = verify_records([_record("1", 1000, 2000), _record("1", 999, 1500)],
                             [VariantClass.CNV], region)
    assert len(verdict.kept) == 1


def test_gene_queries_check_class_only():
    verdict = verify_records([_record("5", 1, 2), _record("X", 9, 10)], [VariantClass.CNV], None)
    assert len(verdict.kept) == 2


def test_expanded_descendant_terms_are_kept():
    """Server-side expansion returns low-level loss for a loss query: same class."""
    region = Region("9", "overlap", (100,), (200,))
    verdict = verify_records([_record("9", 150, 160, term="EFO:0030068")], [VariantClass.CNV], region)
    assert verdict.kept and not verdict.parameter_ignored


def test_other_classes_from_an_unconstrained_request_are_not_an_accusation():
    """A range query for CNV with no term legitimately returns SNVs too."""
    snv = {"variation": {"location": {"chromosome": "9", "start": 150, "end": 151},
                         "referenceBases": "G", "alternateBases": "A"}}
    verdict = verify_records([snv], [VariantClass.CNV], Region("9", "overlap", (100,), (200,)),
                             constrained=False)
    assert not verdict.kept and not verdict.parameter_ignored
    assert "as a request without a class constraint allows" in verdict.notes()[0]


def test_a_record_without_coordinates_is_excluded_and_counted():
    verdict = verify_records([{"variation": {"variantState": {"id": "EFO:0030067"}}}],
                             [VariantClass.CNV], Region("9", "overlap", (1,), (2,)))
    assert not verdict.kept and verdict.no_location == 1
