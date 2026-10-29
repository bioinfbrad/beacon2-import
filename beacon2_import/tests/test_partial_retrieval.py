"""A random sample must never be reported as an exact, complete answer.

THE BLOCKER THESE TESTS EXIST FOR. Live against Progenetix:

    beacon2-query range --providers org.progenetix.beacon --variant-class CNV \\
      --reference-name 9 --start 21967753 --end 21995301 \\
      --class-term CNV=EFO:0030067 --filter ontology:NCIT:C3058

sent four requests at limit 100 (client-side expansion of EFO:0030067), each
answered with 100 instances of totals 4182, 2831, 911 and 0 -- and reported
297 rows as `exact, inferred_from_complete_retrieval`. Two faults combined:
  (a) unknown pagination was treated as trustworthy pages, so complete-or-refuse
      never ran (the registry default was "pages");
  (b) the outcome's precision was taken from the LAST query's envelope only --
      0 of 0, trivially complete -- ignoring 100 of 4182, 2831 and 911.
Principle (c): partiality is OBSERVED in each response, never declared.

The provider here is stubbed at the network edge, nothing else: the real CLI,
planner, retrieval, parser and writers run. It answers as Progenetix did --
at most `limit` instances of each term's total, a random subset below it.
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

import pytest

from beacon2_import.normalise.envelope import (
    PRECISION_INFERRED, PRECISION_PARTIAL, combined_precision, effective_count_precision, parse,
)
from beacon2_import.transport.http import Response

#: The real numbers, per variantType, from the live run.
TOTALS = {"EFO:0030067": 4182, "EFO:0020073": 2831, "EFO:0030068": 911, "EFO:0030069": 0}
PAGE = 100


def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find(value, key)
            if found is not None:
                return found
    return None


def _envelope(term: str, total: int, delivered: int) -> dict:
    records = [{
        "variantInternalId": f"NC_000009.12:{21967753 + i}-{21995301 + i}:{term}",
        "variation": {"variantState": {"id": term},
                      "location": {"sequence_id": "refseq:NC_000009.12", "type": "SequenceLocation",
                                   "interval": {"start": {"value": 21967752 + i},
                                                "end": {"value": 21995301 + i}}}},
        "caseLevelData": [{"biosampleId": f"pgxbs-{term}-{i}", "analysisId": f"pgxcs-{term}-{i}"}],
    } for i in range(delivered)]
    return {"meta": {"apiVersion": "v2.3.0-beaconplus", "returnedGranularity": "record",
                     "returnedSchemas": [{"id": "genomicVariant"}],
                     "receivedRequestSummary": {"pagination": {"skip": 0, "limit": PAGE},
                                                "testMode": False}},
            "responseSummary": {"exists": total > 0, "numTotalResults": total},
            "response": {"resultSets": [{"id": "progenetix", "exists": total > 0,
                                         "resultsCount": total, "results": records}]}}


class ProgenetixLike:
    """Answers as Progenetix did: at most `limit` instances; a random subset below
    the total. `cap` models a server maximum per request, applied silently."""

    def __init__(self, cap: int | None = None):
        self.cap = cap
        self.requests: list[tuple[str, int]] = []

    def post(self, path, body):
        term = _find(body, "variantType")
        limit = int(_find(body, "limit") if _find(body, "limit") is not None else PAGE)
        total = TOTALS[term]
        if _find(body, "requestedGranularity") == "count":
            # The filter-efficacy check's count requests: the filter restricts
            # (no filter means a 10x larger universe). Not retrieval; not logged.
            universe = total if _find(body, "filters") else total * 10 + 1
            return Response(200, _envelope(term, universe, 0), f"stub://{path}", "POST", 0.0)
        self.requests.append((term, limit))
        delivered = min(total, total if limit == 0 else limit, self.cap or total)
        return Response(200, _envelope(term, total, delivered), f"stub://{path}", "POST", 0.0)

    def get(self, path, params=None):  # pragma: no cover - not used by range
        raise AssertionError("no GET expected")


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Run the live command; `pagination` and `expansion` override the registry."""
    from beacon2_import.cli import common
    from beacon2_import.cli.main import main

    def _run(client, pagination="unknown", expansion="none", extra=(), real_registry=False):
        original = common.resolve

        def resolve(ids, table, registry):
            providers, unresolvable = original(ids, table, registry)
            return [dataclasses.replace(p, pagination_behaviour=pagination,
                                        copy_change_expansion=expansion,
                                        filters_effective="unknown") for p in providers], unresolvable

        def filters_checked(ids, table, registry):
            # The observed registry, but with the filter checked at run time
            # rather than refused: this file is about retrieval, not filters.
            providers, unresolvable = original(ids, table, registry)
            return [dataclasses.replace(p, filters_effective="unknown") for p in providers], unresolvable

        monkeypatch.setattr(common, "resolve", filters_checked if real_registry else resolve)
        monkeypatch.setattr(common, "make_client", lambda provider, credentials: client)
        results, outcomes = tmp_path / "results.tsv", tmp_path / "outcomes.tsv"
        code = main(["range", "--providers", "org.progenetix.beacon", "--variant-class", "CNV",
                     "--reference-name", "9", "--start", "21967753", "--end", "21995301",
                     "--class-term", "CNV=EFO:0030067", "--filter", "ontology:NCIT:C3058",
                     "--granularity", "record", *extra,
                     "--results", str(results), "--outcomes", str(outcomes)])
        read = lambda p: list(csv.DictReader(p.open(), delimiter="\t"))
        assert code == 0
        return read(results), read(outcomes)

    return _run


# ---------------- (c) partiality is observed, never declared ----------------

def test_100_of_4182_is_partial_never_exact_or_inferred():
    """Whatever any registry says: the envelope alone decides."""
    envelope = parse(_envelope("EFO:0030067", 4182, 100))
    precision, basis = effective_count_precision(envelope)
    assert precision != "exact"
    assert basis == PRECISION_PARTIAL and basis != PRECISION_INFERRED


def test_partial_wins_even_over_a_declared_exact_count():
    payload = _envelope("EFO:0030067", 4182, 100)
    payload["response"]["resultSets"][0]["countPrecision"] = "exact"
    assert effective_count_precision(parse(payload)) == ("imprecise", PRECISION_PARTIAL)


def test_the_last_query_cannot_vouch_for_the_others():
    """Fault (b): 0 of 0 last must not make 100 of 4182 first look complete."""
    envelopes = [parse(_envelope(t, n, min(n, PAGE))) for t, n in TOTALS.items()]
    assert effective_count_precision(envelopes[-1])[1] == PRECISION_INFERRED  # 0 of 0
    precision, basis, shortfalls = combined_precision(envelopes)
    assert (precision, basis) == ("imprecise", PRECISION_PARTIAL)
    assert shortfalls == [(100, 4182), (100, 2831), (100, 911)]


# ---------------- (a) unknown pagination means complete-or-refuse ----------------

def test_unknown_pagination_runs_preflight_then_full_retrieval(run):
    """The live run sent four requests at limit 100. Now: a pre-flight at limit 1,
    then limit 0, for every term with matches."""
    client = ProgenetixLike()
    rows, outcomes = run(client, pagination="unknown")
    for term, total in TOTALS.items():
        sent = [limit for t, limit in client.requests if t == term]
        assert sent[0] == 1, f"{term}: no pre-flight"
        if total:
            assert len(sent) == 2 and (sent[1] == 0 or sent[1] >= total), \
                f"{term}: the second request {sent[1:]} does not ask for all {total}"
    assert PAGE not in [limit for _, limit in client.requests], "a page was trusted"
    outcome = outcomes[0]
    assert (outcome["status"], outcome["row_count"]) == ("ok", str(4182 + 2831 + 911))
    assert outcome["count_precision"] == "exact"


def test_unknown_pagination_never_reports_the_live_sample_as_complete(run):
    """The live failure, replayed: a server that never delivers more than 100."""
    client = ProgenetixLike(cap=100)
    rows, outcomes = run(client, pagination="unknown")
    outcome = outcomes[0]
    assert outcome["count_precision"] != "exact"
    assert outcome["count_precision_basis"] != PRECISION_INFERRED
    assert outcome["status"] == "skipped" and rows == []
    assert "100" in outcome["notes"] and "4182" in outcome["notes"]


# ---------------- (b) the four-query sequence: outcome and rows agree ----------------

def test_four_query_sequence_is_partial_and_rows_agree(run):
    """Even where pages are DECLARED trustworthy, a page below the total is
    partial -- the declaration chooses the remedy, never the reporting."""
    client = ProgenetixLike()
    rows, outcomes = run(client, pagination="pages")
    assert [limit for _, limit in client.requests] == [PAGE] * 4
    outcome = outcomes[0]
    assert outcome["count_precision"] == "imprecise"
    assert outcome["count_precision_basis"] == PRECISION_PARTIAL
    assert "100 of 4182" in outcome["notes"] and "100 of 2831" in outcome["notes"]
    assert "100 of 911" in outcome["notes"]
    assert {(r["count_precision"], r["count_precision_basis"]) for r in rows} == {
        ("imprecise", PRECISION_PARTIAL)}, "row level and outcome level must agree"


def test_server_side_expansion_sends_one_query(run):
    """With copy_change_expansion server, the four requests become one."""
    client = ProgenetixLike()
    run(client, pagination="random_subset_below_total", expansion="server")
    assert {term for term, _ in client.requests} == {"EFO:0030067"}


def test_an_undeclared_provider_is_not_trusted_to_page():
    """The root of fault (a) was a DEFAULT: an unset pagination_behaviour became
    "pages" -- in the schema and, separately, in the loader. Read from the real
    registry, so either default reverting is caught."""
    import yaml

    from beacon2_import.adapters.base import adapter_for
    from beacon2_import.registry.loader import DEFAULT_REGISTRY, load_registry

    raw = yaml.safe_load(Path(DEFAULT_REGISTRY).read_text())["providers"]
    registry = load_registry()
    undeclared = [pid for pid, entry in raw.items() if "pagination_behaviour" not in entry]
    assert undeclared, "no undeclared provider left to check the default with"
    for pid in undeclared:
        assert registry[pid].pagination_behaviour == "unknown", pid
        assert adapter_for(registry[pid]).may_paginate() is False, pid


def test_the_live_command_with_the_observed_registry(run):
    """Progenetix as now registered -- server-side expansion, random subset below
    the total: ONE query, a pre-flight, then a request for all 4182."""
    client = ProgenetixLike()
    rows, outcomes = run(client, real_registry=True)
    assert client.requests[0] == ("EFO:0030067", 1)
    assert {term for term, _ in client.requests} == {"EFO:0030067"}, "four queries did not become one"
    assert len(client.requests) == 2 and (client.requests[1][1] in (0,) or client.requests[1][1] >= 4182)
    outcome = outcomes[0]
    assert (outcome["status"], outcome["row_count"]) == ("ok", "4182")
    assert (outcome["count_precision"], outcome["count_precision_basis"]) == (
        "exact", PRECISION_INFERRED)
    assert len(rows) == 4182


def test_the_live_command_against_a_capped_server_says_so(run):
    """The same, against a server that never delivers more than 100: refused,
    and the refusal states how many of how many."""
    rows, outcomes = run(ProgenetixLike(cap=100), real_registry=True)
    outcome = outcomes[0]
    assert outcome["status"] == "skipped" and rows == []
    assert outcome["count_precision"] != "exact"
    assert "4182" in outcome["notes"] and "100" in outcome["notes"]
