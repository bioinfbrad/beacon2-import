"""Filtering-terms behaviour, driven by tests/fixtures/filtering_terms/.

Records a negative finding: server-side prefix filtering does not exist on the
bycon stack. A bare ontology prefix is accepted, interpreted as a filter term
whose id is literally that prefix, and matches nothing -- silently.

Silent-and-empty is the reason these fixtures exist. Shipping prefix filtering
as a server-side parameter would hand users an empty result for a perfectly
good prefix with no sign that the parameter had been misread.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "filtering_terms"
PREFIX_EMPTY = FIXTURES / "prefix_query_returns_nothing.json"
UNFILTERED = FIXTURES / "unfiltered_returns_terms.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_bare_prefix_is_read_as_a_literal_term_id():
    """The echo proves the prefix was accepted, not rejected.

    Had it errored, ordinary error handling would surface it. It did not: it
    was taken as a term id of `EFO` and matched nothing.
    """
    payload = _json(PREFIX_EMPTY)
    echoed = payload["meta"]["receivedRequestSummary"]["filters"]
    assert echoed == [{"id": "EFO"}]
    assert "error" not in payload
    assert payload["response"]["filteringTerms"] == []
    assert payload["response"]["resources"] == []


def test_the_endpoint_itself_works():
    """The contrast case. Without it, the empty result could be a dead endpoint.

    Both fixtures are needed: one shows nothing comes back with the prefix, the
    other shows plenty comes back without it. Only the pair localises the fault
    to the parameter.
    """
    payload = _json(UNFILTERED)
    terms = payload["response"]["filteringTerms"]
    assert terms
    assert all("count" in term for term in terms)
    assert all(":" in term["id"] for term in terms)


def test_registry_declares_prefix_filtering_unavailable():
    """The observed finding must be reflected in the contract.

    A registry still claiming server-side prefix filtering would have the tool
    send a parameter that silently returns nothing.
    """
    import yaml

    registry_path = (
        Path(__file__).resolve().parent.parent / "registry" / "beacon_registry.yaml"
    )
    registry = yaml.safe_load(registry_path.read_text())
    cancercelllines = registry["providers"]["org.cancercelllines"]
    assert cancercelllines["filtering_terms_prefix_filter"] is False


def test_prefix_filtering_happens_client_side():
    """Prefix selection must be applied locally, over the full term list."""
    from beacon2_import.query.filters import filter_terms_by_prefix

    terms = _json(UNFILTERED)["response"]["filteringTerms"]
    try:
        selected = filter_terms_by_prefix(terms, ["EDAM"])
    except NotImplementedError:
        pytest.skip("filter_terms_by_prefix() not yet implemented")

    assert len(selected) == len(terms)
    assert filter_terms_by_prefix(terms, ["EFO"]) == []
