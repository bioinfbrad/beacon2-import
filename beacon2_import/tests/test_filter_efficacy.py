"""A filter the server receives but does not apply must never pass as applied.

Observed on both bycon providers: the same filtered requests that returned 60,
313 and 400 on 9 October returned 2,938, 5,581 and 21,594 later -- echoing the
filter back each time. A glioblastoma search returned every cancer, labelled ok.
Nothing in a variant record names its disease, so verify.py cannot catch it.
"""

from __future__ import annotations

import csv
import dataclasses

import pytest

from beacon2_import.transport.http import RequestRejected, Response, canonical_request

ARGV = ["range", "--providers", "org.cancercelllines", "--variant-classes", "CNV",
        "--reference-name", "17", "--start", "7668421", "--end", "7687490",
        "--filter", "NCIT:C3058"]


def _records(n):
    return [{"variantInternalId": f"x{i}", "variation": {"variantState": {"id": "EFO:0030067"},
             "location": {"chromosome": "17", "start": 7668500 + i, "end": 7670000}},
             "caseLevelData": [{"biosampleId": f"b{i}"}]} for i in range(n)]


class Counts:
    """Answers count requests with fixed totals; records requests with `filtered` records."""

    def __init__(self, filtered, unfiltered, reject_unfiltered=False):
        self.filtered, self.unfiltered, self.reject = filtered, unfiltered, reject_unfiltered
        self.requests = []

    def post(self, path, body):
        q = canonical_request("POST", path, None, body)["query"]
        self.requests.append(q)
        has_filter = bool(q.get("filters"))
        if not has_filter and self.reject:
            raise RequestRejected(f"{path} returned 422", 422)
        total = self.filtered if has_filter else self.unfiltered
        records = [] if q.get("requestedGranularity") == "count" else _records(total)
        return Response(200, {"meta": {"returnedGranularity": q.get("requestedGranularity"),
                                       "returnedSchemas": [{"id": "genomicVariant"}],
                                       "receivedRequestSummary": {"pagination": {"limit": 0}}},
                              "responseSummary": {"exists": total > 0, "numTotalResults": total},
                              "response": {"resultSets": [{"id": "x", "results": records}]}},
                        path, "POST", 0.0)


@pytest.fixture
def run(monkeypatch, tmp_path):
    from beacon2_import.cli import common
    from beacon2_import.cli.main import main

    def _run(client, **registry):
        original = common.resolve

        def resolve(ids, table, reg):
            providers, unresolvable = original(ids, table, reg)
            return [dataclasses.replace(p, **registry) for p in providers], unresolvable

        monkeypatch.setattr(common, "resolve", resolve)
        monkeypatch.setattr(common, "make_client", lambda p, c: client)
        assert main([*ARGV, "--results", str(tmp_path / "r.tsv"),
                     "--outcomes", str(tmp_path / "o.tsv")]) == 0
        read = lambda f: list(csv.DictReader(f.open(), delimiter="\t"))
        return read(tmp_path / "r.tsv"), read(tmp_path / "o.tsv")[0]

    return _run


UNKNOWN = dict(filters_effective="unknown")


@pytest.mark.parametrize("filtered, unfiltered", [(10, 10), (12, 10)])
def test_no_restriction_is_refused(run, filtered, unfiltered):
    rows, outcome = run(Counts(filtered, unfiltered), **UNKNOWN)
    assert outcome["status"] == "skipped" and rows == []
    assert "returned the same total with and without filter NCIT:C3058" in outcome["notes"]
    assert "would not be restricted to NCIT:C3058" in outcome["notes"]


def test_a_restriction_passes_and_is_recorded(run):
    rows, outcome = run(Counts(2, 10), **UNKNOWN)
    assert outcome["status"] == "ok" and len(rows) == 2
    assert "filter NCIT:C3058 restricted the total from 10 to 2" in outcome["notes"]


def test_an_unverifiable_filter_says_so(run):
    """Entities answer an unfiltered request with 422: efficacy cannot be shown."""
    _, outcome = run(Counts(2, 10, reject_unfiltered=True), **UNKNOWN)
    assert "could not be verified" in outcome["notes"]


def test_an_observed_non_applying_provider_is_refused_before_any_request(run):
    client = Counts(2, 10)
    rows, outcome = run(client, filters_effective="no", filters_note="observed: 2,934 vs 2,772")
    assert client.requests == [] and rows == [] and outcome["status"] == "skipped"
    assert "observed not to apply filters" in outcome["notes"]


def test_both_bycon_providers_are_recorded_as_not_applying_filters():
    from beacon2_import.registry.loader import load_registry

    registry = load_registry()
    for pid in ("org.progenetix.beacon", "org.cancercelllines"):
        assert registry[pid].filters_effective == "no" and "observed" in registry[pid].filters_note


def test_a_filtered_entity_query_is_refused_too(monkeypatch, tmp_path):
    """Entity queries bypass the planner; the observed refusal must reach them."""
    import dataclasses

    from beacon2_import.cli import common
    from beacon2_import.cli.main import main

    client = Counts(2, 10)
    original = common.resolve
    monkeypatch.setattr(common, "resolve", lambda i, t, r: (
        [dataclasses.replace(p, filters_effective="no", filters_note="observed")
         for p in original(i, t, r)[0]], []))
    monkeypatch.setattr(common, "make_client", lambda p, c: client)
    main(["entity", "--entity", "biosample", "--providers", "org.cancercelllines",
          "--filter", "NCIT:C3058", "--results", str(tmp_path / "r.tsv"),
          "--outcomes", str(tmp_path / "o.tsv")])
    outcome = (tmp_path / "o.tsv").read_text()
    assert client.requests == [] and "\tskipped\t0\t" in outcome
    assert "observed not to apply filters" in outcome
