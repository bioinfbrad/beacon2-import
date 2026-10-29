"""Complete-or-refuse retrieval, against a stub client and existing fixtures.

The stub answers by the requested page size, so these tests exercise the real
pre-flight, decision, full retrieval and verification paths without a network.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from beacon2_import.adapters.base import adapter_for
from beacon2_import.query.classes import VariantClass
from beacon2_import.query.model import Position, Query, QueryForm
from beacon2_import.query.retrieve import RetrievalMode, retrieve
from beacon2_import.registry.loader import load_registry
from beacon2_import.transport.http import Response

SHAPE = Path(__file__).resolve().parent / "fixtures" / "adapters" / "filtered_retrieval_shape.json"


class StubClient:
    """Serves one full response, trimmed to whatever limit is requested."""

    def __init__(self, full: dict, cap: int | None = None):
        self.full, self.cap, self.limits = full, cap, []

    def post(self, path, body):
        limit = body["query"]["pagination"]["limit"]
        self.limits.append(limit)
        payload = json.loads(json.dumps(self.full))
        results = payload["response"]["resultSets"][0]["results"]
        keep = len(results) if limit == 0 else limit
        if self.cap is not None:
            keep = min(keep, self.cap)
        payload["response"]["resultSets"][0]["results"] = results[:keep]
        return Response(200, payload, path, "POST", 0.0)


@pytest.fixture(scope="module")
def ccl():
    return load_registry()["org.cancercelllines"]


@pytest.fixture
def full():
    return json.loads(SHAPE.read_text())


def _query():
    return Query(form=QueryForm.BRACKET, variant_class=VariantClass.CNV,
                 reference_name="3", start=Position((1, 2)), end=Position((3, 4)))


def test_under_ceiling_retrieves_everything_and_verifies(ccl, full):
    client = StubClient(full)
    result = retrieve(_query(), ccl, adapter_for(ccl), client)
    assert result.decision.mode is RetrievalMode.FULL
    assert result.complete and not result.random_sample
    assert client.limits == [1, 0], "pre-flight of one, then limit 0 for all"
    assert len(result.records) == 3


def test_over_ceiling_refuses_without_fetching(ccl, full):
    small = replace(ccl, full_retrieval_ceiling=3)
    client = StubClient(full)
    result = retrieve(_query(), small, adapter_for(small), client)
    assert result.decision.mode is RetrievalMode.REFUSE
    assert client.limits == [1], "the large retrieval must never be issued"
    assert result.records == []
    message = result.refusal
    assert "4" in message and "3" in message, "states the total and the ceiling"
    assert "narrow" in message and "--sample" in message, "states both remedies"


def test_a_silently_capped_full_retrieval_is_refused(ccl, full):
    """Short of the provider's own total: refuse, never compute. The message
    states what was observed, not a cause the response cannot show."""
    client = StubClient(full, cap=2)
    result = retrieve(_query(), ccl, adapter_for(ccl), client)
    assert result.decision.mode is RetrievalMode.REFUSE
    assert result.records == []
    assert "short of the provider's own total" in result.refusal
    assert "maximum" not in result.refusal and "random subset" not in result.refusal


def test_sampling_is_opt_in_and_labelled(ccl, full):
    client = StubClient(full)
    result = retrieve(_query(), ccl, adapter_for(ccl), client, sample_size=2)
    assert result.decision.mode is RetrievalMode.SAMPLE
    assert result.random_sample is True
    assert client.limits == [1, 2]


def test_a_sample_that_happens_to_be_complete_is_not_labelled_random(ccl, full):
    client = StubClient(full)
    result = retrieve(_query(), ccl, adapter_for(ccl), client, sample_size=500)
    assert result.complete and result.random_sample is False


def test_zero_total_needs_no_second_request(ccl, full):
    empty = json.loads(json.dumps(full))
    empty["responseSummary"]["numTotalResults"] = 0
    empty["response"]["resultSets"][0]["results"] = []
    client = StubClient(empty)
    result = retrieve(_query(), ccl, adapter_for(ccl), client)
    assert result.decision.mode is RetrievalMode.EMPTY
    assert result.complete and client.limits == [1]


def test_pagination_capable_providers_keep_existing_behaviour(full):
    """A provider that DECLARES contiguous pages gets the page it asked for.
    (This test once used Progenetix, undeclared, as its example -- which is how
    the suite came to require the fault it should have caught.)"""
    import dataclasses

    pager = dataclasses.replace(load_registry()["org.progenetix.beacon"],
                                pagination_behaviour="pages")
    client = StubClient(full)
    result = retrieve(_query(), pager, adapter_for(pager), client)
    assert result.decision.mode is RetrievalMode.PAGES
    assert client.limits == [100], "no pre-flight; the requested page is sent"


def test_ceiling_comes_from_the_registry(ccl):
    assert ccl.full_retrieval_ceiling == 10000
