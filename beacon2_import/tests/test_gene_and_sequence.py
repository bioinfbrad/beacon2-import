"""Gene and sequence queries on bycon: the two silent zeros, and their fixes.

Live, on both bycon providers (Progenetix and cancercelllines):
  * GET geneId=TP53 returned 69,662 / 2,487; every POST form of geneId returned
    0 -- the parameter is read (a misspelling gets 422) but never resolved.
  * every sequence query for R273H returned 0, though an exhaustive range
    listing holds it at exactly 7673801 C>T (0-based).
The stubs below answer as bycon did; the real CLI, adapter and verifier run.
Records are MODELLED on the live listings, not recorded.
"""

from __future__ import annotations

import csv
import dataclasses

import pytest

from beacon2_import.transport.http import RequestRejected, Response, canonical_request

GENE_SPAN = (7668420, 7687490)  # TP53, 0-based half-open, GRCh38


def _cnv(i, start=7660000, end=7700000):
    return {"variantInternalId": f"NC_000017.11:{start + i}-{end}:EFO_0030067",
            "variation": {"variantState": {"id": "EFO:0030067"},
                          "location": {"chromosome": "17", "start": start + i, "end": end}},
            "caseLevelData": [{"biosampleId": f"bs-cnv-{i}"}]}


def _snv(start, ref, alt, label="SO:0001059"):
    return {"variantInternalId": f"NC_000017.11:{start}:{alt}",
            "variation": {"variantState": {"id": label},
                          "location": {"chromosome": "17", "start": start, "end": start + 1},
                          "referenceBases": ref, "alternateBases": alt},
            "caseLevelData": [{"biosampleId": f"bs-{start}-{alt}"}]}


#: The codon-273 records from the exhaustive live listing on cancercelllines.
CODON_273 = [_snv(7673801, "C", "A"), _snv(7673801, "C", "T"), _snv(7673802, "G", "A"),
             _snv(7673805, "C", "A"), _snv(7673805, "C", "T")]
#: A Progenetix-style "SNV": a 1-base deletion with no alternate allele.
NO_ALTERNATE = {"variantInternalId": "NC_000017.11:7673801:",
                "variation": {"type": "Allele", "variantState": {"id": "SO:0001483", "label": "SNV"},
                              "location": {"chromosome": "17", "start": 7673801, "end": 7673802},
                              "referenceSequence": "C",
                              "state": {"type": "ReferenceLengthExpression", "length": 0,
                                        "repeatSubunitLength": 1, "sequence": ""}},
                "caseLevelData": [{"biosampleId": "pgx-1"}]}


def _envelope(records):
    return {"meta": {"returnedGranularity": "record", "returnedSchemas": [{"id": "genomicVariant"}],
                     "receivedRequestSummary": {"pagination": {"limit": 0}, "testMode": False}},
            "responseSummary": {"exists": bool(records), "numTotalResults": sum(
                len(r.get("caseLevelData") or [1]) for r in records)},
            "response": {"resultSets": [{"id": "x", "exists": bool(records),
                                         "resultsCount": len(records), "results": records}]}}


class LikeBycon:
    """Answers as both bycon providers did, live."""

    def __init__(self, extra_at_position=()):
        self.requests = []
        self.window = CODON_273 + [_cnv(0)] + list(extra_at_position)

    def get(self, path, params=None):
        key = canonical_request("GET", path, params)
        self.requests.append(key)
        gene = key["query"].get("geneId")
        if gene == "NOTAREALGENE1":
            raise RequestRejected(f"{path} returned 422", 422)
        # A filter that restricts: without one, the universe is larger.
        n = 3 if key["query"].get("filters") else 30
        records = [_cnv(i) for i in range(n)] if gene == "TP53" else []
        if key["query"].get("requestedGranularity") == "count":
            env = _envelope(records); env["response"]["resultSets"][0]["results"] = []
            return Response(200, env, path, "GET", 0.0)
        return Response(200, _envelope(records), path, "GET", 0.0)

    def post(self, path, body):
        key = canonical_request("POST", path, None, body)
        self.requests.append(key)
        q = key["query"]
        if "geneId" in q or "referenceBases" in q:
            records = []  # the silent zero: accepted, never resolved
        else:  # a range: everything the listing holds, as the server returned it
            records = self.window
        return Response(200, _envelope(records), path, "POST", 0.0)


@pytest.fixture
def run(monkeypatch, tmp_path):
    from beacon2_import.cli import common
    from beacon2_import.cli.main import main

    def _run(client, argv, **registry):
        original = common.resolve

        def resolve(ids, table, reg):
            providers, unresolvable = original(ids, table, reg)
            return [dataclasses.replace(p, **registry) for p in providers], unresolvable

        monkeypatch.setattr(common, "resolve", resolve)
        monkeypatch.setattr(common, "make_client", lambda p, c: client)
        results, outcomes = tmp_path / "r.tsv", tmp_path / "o.tsv"
        assert main([*argv, "--providers", "org.cancercelllines",
                     "--results", str(results), "--outcomes", str(outcomes)]) == 0
        read = lambda f: list(csv.DictReader(f.open(), delimiter="\t"))
        return read(results), read(outcomes)[0]

    return _run


GENE = ["gene", "--variant-classes", "CNV", "--gene-id"]
R273H = ["sequence", "--variant-classes", "SMALL_VARIANT", "--reference-name", "17",
         "--start", "7673802", "--reference-bases", "C", "--alternate-bases", "T"]
BYCON = dict(gene_query_transport="get", sequence_query_mode="range_then_filter",
             small_variant_type_filter="unsupported", filters_effective="unknown")


# ---------------- A: gene queries by GET ----------------

def test_a_bycon_gene_query_goes_by_get_and_finds_the_records(run):
    client = LikeBycon()
    rows, outcome = run(client, [*GENE, "TP53"], **BYCON)
    assert {r["method"] for r in client.requests} == {"GET"}
    assert outcome["status"] == "ok" and outcome["row_count"] == "30" and len(rows) == 30


def test_the_same_query_by_post_was_the_silent_zero(run):
    """What 3.0.0 sent before: POST. Kept as the evidence the GET rule rests on."""
    rows, outcome = run(LikeBycon(), [*GENE, "TP53"], gene_query_transport="post")
    assert outcome["row_count"] == "0" and rows == []


def test_ontology_filters_go_comma_separated_on_get(run):
    client = LikeBycon()
    run(client, [*GENE, "TP53", "--filter", "NCIT:C3058", "--filter", "NCIT:C4017"], **BYCON)
    filtered = [r for r in client.requests if r["query"].get("filters")]
    assert filtered and all(r["method"] == "GET" for r in filtered)
    assert {f["id"] for f in filtered[-1]["query"]["filters"]} == {"NCIT:C3058", "NCIT:C4017"}


def test_an_alphanumeric_filter_with_a_bycon_gene_query_is_refused(run):
    client = LikeBycon()
    _, outcome = run(client, [*GENE, "TP53", "--filter", "alphanumeric:age:years:>=:40:age=true"],
                     **BYCON)
    assert outcome["status"] == "skipped" and client.requests == []
    assert "range query" in outcome["notes"]


def test_an_unknown_gene_symbol_is_named(run):
    _, outcome = run(LikeBycon(), [*GENE, "NOTAREALGENE1"], **BYCON)
    assert outcome["status"] == "error"
    assert "does not recognise the gene symbol 'NOTAREALGENE1'" in outcome["notes"]


def test_a_422_is_a_rejection_never_an_auth_failure():
    from beacon2_import.transport.http import BeaconClient, TransportFailure

    failure = BeaconClient.classify_transport_failure(
        422, "application/json", '{"meta": {}, "error": {"errorCode": 422}}', 40)
    assert failure is TransportFailure.REJECTED


def test_the_spec_stack_keeps_post_for_genes():
    from beacon2_import.adapters.base import adapter_for
    from beacon2_import.registry.loader import load_registry

    spec = next(p for p in load_registry().values()
                if str(getattr(p.stack, "value", p.stack)) == "spec")
    assert spec.gene_query_transport == "post"


# ---------------- B: sequence queries as range, then alleles matched here ----------------

def test_r273h_is_found_and_its_neighbours_are_not(run):
    client = LikeBycon()
    rows, outcome = run(client, R273H, **BYCON)
    assert [(r["start"], r["reference_bases"], r["alternate_bases"]) for r in rows] == [
        ("7673802", "C", "T")], "R273H only: not C>A at the same position, not G>A beside it"
    assert outcome["row_count"] == "1" and outcome["count_precision"] == "exact"
    assert "matched client-side" in outcome["notes"]


def test_what_is_sent_is_a_range_over_the_position_without_bases(run):
    client = LikeBycon()
    run(client, R273H, **BYCON)
    sent = client.requests[-1]["query"]
    assert (sent["start"], sent["end"]) == ([7673801], [7673802])
    assert "referenceBases" not in sent and "alternateBases" not in sent


def test_expected_misses_are_not_an_accusation(run):
    _, outcome = run(LikeBycon(), R273H, **BYCON)
    assert "may have ignored" not in outcome["notes"]
    assert outcome["count_precision_basis"] != "failed_verification"


def test_records_without_an_alternate_allele_are_named_not_hidden(run):
    _, outcome = run(LikeBycon(extra_at_position=[NO_ALTERNATE]), R273H, **BYCON)
    assert "1 records at this position have no recorded alternate allele and cannot be matched" \
        in outcome["notes"]


def test_the_server_sequence_query_was_the_silent_zero(run):
    rows, outcome = run(LikeBycon(), R273H, gene_query_transport="get",
                        sequence_query_mode="server")
    assert rows == [] and outcome["row_count"] == "0"


def test_alleles_are_read_from_vrs_forms_too():
    from beacon2_import.normalise.verify import record_alleles

    lse = {"variation": {"referenceSequence": "C",
                         "state": {"type": "LiteralSequenceExpression", "sequence": "t"}}}
    assert record_alleles(lse) == ("C", "T")
    assert record_alleles(NO_ALTERNATE) == ("C", "")


def test_a_spanning_repeat_indel_never_answers_an_snv_query():
    from beacon2_import.normalise.verify import Region, verify_records
    from beacon2_import.query.classes import VariantClass

    indel = {"variation": {"location": {"chromosome": "17", "start": 7673799, "end": 7673804},
                           "referenceSequence": "CCCCC",
                           "state": {"type": "ReferenceLengthExpression", "length": 4,
                                     "repeatSubunitLength": 1}}}
    snv = Region("17", "position", (7673801,), alleles=("C", "T"))
    deletion = Region("17", "position", (7673801,), alleles=("CC", "C"))
    assert not verify_records([indel], [VariantClass.SMALL_VARIANT], snv).kept
    assert verify_records([indel], [VariantClass.SMALL_VARIANT], deletion).kept


# ---------------- C: small-variant SO terms, per provider ----------------

CODON_WINDOW = ["range", "--variant-classes", "SMALL_VARIANT", "--reference-name", "17",
                "--start", "7673800", "--end", "7673806"]
PROGENETIX_LIKE = dict(sequence_query_mode="range_then_filter",
                       small_variant_type_filter="SO:0001059")


def test_an_so_term_is_not_sent_where_it_returns_nothing_and_says_so(run):
    """cancercelllines: 0 for SO:0001483 and SO:0001059, though it labels its own
    small variants SO:0001059. Sending the term would be a silent zero."""
    client = LikeBycon()
    rows, outcome = run(client, [*CODON_WINDOW, "--class-term", "SMALL_VARIANT=SO:0001483"], **BYCON)
    assert "variantType" not in client.requests[-1]["query"]
    assert outcome["query_degraded"] == "true"
    assert "SO:0001483 not sent" in outcome["notes"] and len(rows) == 5


def test_a_declared_prefilter_is_sent_with_every_small_variant_query(run):
    client = LikeBycon()
    run(client, CODON_WINDOW, **PROGENETIX_LIKE)
    assert client.requests[-1]["query"]["variantType"] == "SO:0001059"
    client = LikeBycon()
    run(client, R273H, **PROGENETIX_LIKE)
    assert client.requests[-1]["query"]["variantType"] == "SO:0001059"


def test_copy_number_queries_are_untouched(run):
    client = LikeBycon()
    run(client, ["range", "--variant-classes", "CNV", "--reference-name", "17",
                 "--start", "7673800", "--end", "7673806"], **PROGENETIX_LIKE)
    assert "variantType" not in client.requests[-1]["query"]


# ---------------- D: a label its own structure contradicts ----------------

def test_a_conflicting_label_is_named_on_the_row_and_counted(run):
    rows, outcome = run(LikeBycon(extra_at_position=[NO_ALTERNATE]), CODON_WINDOW, **BYCON)
    conflicted = [r for r in rows if "conflicts with structure" in r["classification_basis"]]
    assert len(conflicted) == 1
    assert ("provider label SO:0001483 (SNV) conflicts with structure: 1-base deletion, "
            "no alternate allele") in conflicted[0]["classification_basis"]
    assert "1 rows carry a provider label that conflicts" in outcome["notes"]
    assert conflicted[0]["variant_class"] == "SMALL_VARIANT", "classified by structure, still"


def test_a_label_its_structure_agrees_with_is_not_flagged():
    from beacon2_import.normalise.classify import label_conflict

    assert label_conflict(_snv(7673801, "C", "T", label="SO:0001483")) is None


def test_a_vrs_form_row_carries_its_alleles():
    """bycon small variants are VRS-form: referenceSequence plus a state."""
    from beacon2_import.normalise.variants import flatten_variant

    vrs = {"variantInternalId": "NC_000017.11:7673801:T",
           "variation": {"location": {"chromosome": "17", "start": 7673801, "end": 7673802},
                         "referenceSequence": "C",
                         "state": {"type": "LiteralSequenceExpression", "sequence": "T"}},
           "caseLevelData": [{"biosampleId": "b1"}]}
    row = flatten_variant(vrs)[0]
    assert (row["reference_bases"], row["alternate_bases"]) == ("C", "T")
    row = flatten_variant(NO_ALTERNATE)[0]
    assert (row["reference_bases"], row["alternate_bases"]) == ("C", "")
