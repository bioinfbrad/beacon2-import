"""Adapter behaviour, against the registry and tests/fixtures/adapters/.

Every assertion here runs against implemented code -- this suite has no
skips. It encodes six findings from live POST probes against a bycon instance,
each of which changes what an adapter sends or how a response may be read.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from beacon2_import.adapters.base import PaginationUnsupported, adapter_for
from beacon2_import.auth.resolver import Secret
from beacon2_import.normalise.envelope import (
    instance_count,
    is_complete_retrieval,
    parse_test_mode,
)
from beacon2_import.query.classes import VariantClass
from beacon2_import.query.model import (
    AlphanumericFilter,
    OntologyFilter,
    Pagination,
    Position,
    Query,
    QueryForm,
)
from beacon2_import.registry.loader import load_registry
from beacon2_import.registry.schema import (
    FiltersLocation,
    GetListStyle,
    RegistryValidationError,
    RequestLayout,
    validate,
)
from beacon2_import.transport.http import (
    BeaconClient,
    FixtureClient,
    FixtureMiss,
    FixtureProviderEscaped,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "adapters"


@pytest.fixture(scope="module")
def registry():
    return load_registry()


@pytest.fixture(scope="module")
def ccl(registry):
    return registry["org.cancercelllines"]


def _bracket(**overrides) -> Query:
    base = dict(
        form=QueryForm.BRACKET,
        variant_class=VariantClass.CNV,
        reference_name="3",
        assembly="GRCh38",
        start=Position((195728637, 195800000)),
        end=Position((198100000, 198169247)),
        variant_type="EFO:0030070",
        filters=(OntologyFilter(id="NCIT:C3058"),),
    )
    base.update(overrides)
    return Query(**base)


# --------------------------------------------------------------------------
# Finding 2 -- filters inside `query`; at the root they are silently ignored
# --------------------------------------------------------------------------


def test_filters_go_inside_query_for_the_observed_provider(ccl):
    """Root placement dropped the filter live: 2591 matches instead of 60."""
    body = adapter_for(ccl).build_post_body(_bracket())
    assert "filters" not in body, "filters at the root are silently ignored"
    assert body["query"]["filters"] == [
        {"id": "NCIT:C3058", "includeDescendantTerms": True}
    ]


def test_root_placement_is_honoured_when_declared(ccl):
    """The adapter follows the registry; the guard lives in validation."""
    rooted = replace(ccl, filters_location=FiltersLocation.ROOT)
    body = adapter_for(rooted).build_post_body(_bracket())
    assert body["filters"][0]["id"] == "NCIT:C3058"
    assert "filters" not in body["query"]


def test_unverified_root_placement_is_rejected():
    """filters_location: root may only be used once live-verified."""
    raw = {
        "providers": {
            "x.root": {
                "enabled": True,
                "base_url": "https://example.org/beacon",
                "request_layout": "flat",
                "filters_location": "root",
                "get_list_style": "comma",
                "reference_style": "name_plus_assembly",
                "variant_classes_served": {
                    "CNV": {"status": "unknown"},
                    "SMALL_VARIANT": {"status": "unknown"},
                    "SV": {"status": "unknown"},
                },
                "verification": {"observed": []},
            }
        }
    }
    with pytest.raises(RegistryValidationError, match="silently ignored"):
        validate(raw)

    raw["providers"]["x.root"]["verification"]["observed"] = ["filters_location"]
    validate(raw)


# --------------------------------------------------------------------------
# Finding 1 -- both layouts accepted
# --------------------------------------------------------------------------


def test_observed_provider_accepts_both_layouts(ccl):
    assert ccl.accepts_layout(RequestLayout.FLAT)
    assert ccl.accepts_layout(RequestLayout.NESTED_G_VARIANT)


def test_layouts_differ_only_in_nesting(ccl):
    """Same parameters, different placement -- what makes them interchangeable."""
    flat = adapter_for(ccl).build_post_body(_bracket())
    nested = adapter_for(
        replace(ccl, request_layout=RequestLayout.NESTED_G_VARIANT)
    ).build_post_body(_bracket())

    flat_params = dict(flat["query"]["requestParameters"])
    nested_params = dict(nested["query"]["requestParameters"]["g_variant"])
    assert flat_params == nested_params
    assert flat_params["start"] == [195728637, 195800000]
    assert "g_variant" not in flat["query"]["requestParameters"]


# --------------------------------------------------------------------------
# Finding 3 -- server-side expansion: the client must not expand as well
# --------------------------------------------------------------------------


def test_observed_provider_expands_server_side(ccl):
    """Expanding twice would count the same samples two or three times."""
    adapter = adapter_for(ccl)
    assert adapter.expands_server_side() is True


def test_unverified_expansion_is_not_trusted(registry):
    """`unknown` must not be read as server-side expansion. (This used Progenetix
    as its example until its expansion was observed, 4182 = 440+2831+911+0.)"""
    import dataclasses

    unverified = adapter_for(dataclasses.replace(registry["org.progenetix.beacon"],
                                                 copy_change_expansion="unknown"))
    assert unverified.provider.copy_change_expansion == "unknown"
    assert unverified.expands_server_side() is False


def test_progenetix_expansion_is_observed_server_side(registry):
    assert adapter_for(registry["org.progenetix.beacon"]).expands_server_side() is True


# --------------------------------------------------------------------------
# Findings 5 and 6 -- never paginate; limit 0 is "all"
# --------------------------------------------------------------------------


def test_random_subset_pages_are_disjoint():
    """Self-consistency: the fixture really shows independent draws."""
    payload = json.loads((FIXTURES / "random_subset_pages.json").read_text())
    pages = [set(page["ids"]) for page in payload["pages"]]
    for i, left in enumerate(pages):
        for right in pages[i + 1:]:
            assert not (left & right)
    totals = {page["numTotalResults"] for page in payload["pages"]}
    assert totals == {payload["_expected"]["num_total_results"]}


def test_random_subset_provider_may_not_paginate(ccl):
    assert adapter_for(ccl).may_paginate() is False


def test_requesting_a_later_page_is_refused(ccl):
    """A later page would be a fresh random draw presented as a continuation."""
    adapter = adapter_for(ccl)
    with pytest.raises(PaginationUnsupported, match="random"):
        adapter.retrieval_pagination(_bracket(pagination=Pagination(skip=1, limit=100)))


def test_first_page_below_total_is_a_random_sample(ccl):
    """skip 0 is not safe either: below the total the first page is a draw."""
    payload, records = _filtered_shape()
    total = payload["responseSummary"]["numTotalResults"]
    adapter = adapter_for(ccl)
    assert adapter.is_random_sample(records, total) is False
    assert adapter.is_random_sample(records[:2], total) is True
    assert adapter.is_random_sample(records, None) is True


def test_ordinary_pagination_is_never_a_random_sample(registry):
    """Only a provider DECLARING contiguous pages gets its pages trusted."""
    import dataclasses

    _, records = _filtered_shape()
    pager = dataclasses.replace(registry["org.progenetix.beacon"], pagination_behaviour="pages")
    assert adapter_for(pager).is_random_sample(records[:1], 9999) is False


def test_progenetix_pages_are_not_trusted(registry):
    """This test once asserted the opposite, using Progenetix as the example of
    an ordinary pager. Observed live: two identical runs overlapped on 22 of ~295
    rows. A page below the total from Progenetix is a random sample."""
    _, records = _filtered_shape()
    assert adapter_for(registry["org.progenetix.beacon"]).is_random_sample(records[:1], 9999) is True


def test_expansion_check_is_stack_neutral(ccl):
    """A spec-stack provider declared `server` must get the same answer."""
    as_spec = replace(ccl, stack="spec")
    assert adapter_for(as_spec).stack == "spec"
    assert adapter_for(as_spec).expands_server_side() is True


def test_full_retrieval_uses_limit_zero(ccl):
    page = adapter_for(ccl).full_retrieval_pagination()
    assert (page.skip, page.limit) == (0, 0)


def test_full_retrieval_falls_back_to_a_page_size_where_unproven(registry):
    """Where limit 0 is not known to work, use a real page size and verify."""
    page = adapter_for(registry["org.progenetix.beacon"]).full_retrieval_pagination()
    assert page.limit == 2000


# --------------------------------------------------------------------------
# Finding 7 -- numTotalResults counts instances, limit counts records
# --------------------------------------------------------------------------


def _filtered_shape():
    payload = json.loads((FIXTURES / "filtered_retrieval_shape.json").read_text())
    records = payload["response"]["resultSets"][0]["results"]
    return payload, records


def test_total_is_in_instances_not_records():
    payload, records = _filtered_shape()
    expected = payload["_expected"]
    assert len(records) == expected["records"]
    assert instance_count(records) == expected["instances"]
    assert payload["responseSummary"]["numTotalResults"] == expected["instances"]
    assert len(records) != expected["instances"], (
        "the fixture must have records != instances, or it cannot tell the "
        "units apart"
    )


def test_completeness_uses_the_instance_sum():
    payload, records = _filtered_shape()
    total = payload["responseSummary"]["numTotalResults"]
    assert is_complete_retrieval(records, total) is True
    assert is_complete_retrieval(records[:-1], total) is False


def test_a_record_count_comparison_would_get_this_wrong():
    """Why the instance sum is required: records < total even when complete."""
    payload, records = _filtered_shape()
    total = payload["responseSummary"]["numTotalResults"]
    assert len(records) < total
    assert is_complete_retrieval(records, total)


def test_absent_total_certifies_nothing():
    _, records = _filtered_shape()
    assert is_complete_retrieval(records, None) is False


def test_observed_original_numbers_are_recorded():
    payload, _ = _filtered_shape()
    original = payload["_observed_original"]
    assert original == {
        "records": 55, "instances": 60, "numTotalResults": 60, "limit": 100,
    }


def test_registry_declares_the_count_unit(ccl):
    assert ccl.total_counts_unit == "variant_instances"


# --------------------------------------------------------------------------
# Finding 10 -- testMode echo forms
# --------------------------------------------------------------------------


def test_test_mode_echo_forms_parse_correctly():
    cases = json.loads((FIXTURES / "test_mode_echo_forms.json").read_text())["_expected"]
    for case in cases:
        assert parse_test_mode(case["echo"]) is case["parsed"], case["label"]


def test_test_mode_type_check_would_fail():
    """The trap: `{}` is not a bool, so a type check misreads GET-unset."""
    assert not isinstance({}, bool)
    assert parse_test_mode({}) is False


def test_test_mode_is_sent_only_when_requested(ccl):
    adapter = adapter_for(ccl)
    assert "testMode" not in adapter.build_post_body(_bracket())["query"]
    assert adapter.build_post_body(_bracket(test_mode=True))["query"]["testMode"] is True


# --------------------------------------------------------------------------
# Entity type -- always set, never inferred from the path
# --------------------------------------------------------------------------


def test_entity_type_is_always_requested(registry):
    for provider_id in ("org.cancercelllines", "org.progenetix.beacon",
                        "test.fixture.bracketless"):
        body = adapter_for(registry[provider_id]).build_post_body(_bracket())
        assert body["meta"]["requestedSchemas"][0]["entityType"] == "genomicVariant"


def test_nested_lookup_requests_the_nested_entity(ccl):
    """/biosamples/{id}/g_variants must ask for variants, not biosamples."""
    query = Query(
        form=QueryForm.RANGE, variant_class=VariantClass.CNV,
        entity="biosample", entity_id="cellzbs-kftvksg5",
        nested_entity="genomicVariant",
    )
    adapter = adapter_for(ccl)
    assert adapter.requested_entity_type(query) == "genomicVariant"
    assert adapter.entity_path("biosample", "cellzbs-kftvksg5", "genomicVariant") == (
        "/biosamples/cellzbs-kftvksg5/g_variants"
    )


def test_entity_paths_differ_between_bycon_instances(registry):
    assert adapter_for(registry["org.cancercelllines"]).entity_path(
        "genomicVariant") == "/genomicVariations"
    assert adapter_for(registry["org.progenetix.beacon"]).entity_path(
        "genomicVariant") == "/g_variants"


# --------------------------------------------------------------------------
# Wire format
# --------------------------------------------------------------------------


def test_positions_are_arrays_even_when_single(ccl):
    query = Query(
        form=QueryForm.SEQUENCE, variant_class=VariantClass.SMALL_VARIANT,
        reference_name="17", start=Position((7577119,)),
        reference_bases="G", alternate_bases="A",
    )
    params = adapter_for(ccl).build_post_body(query)["query"]["requestParameters"]
    assert params["start"] == [7577119]


def test_get_lists_are_comma_joined_by_default(ccl):
    params = adapter_for(ccl).build_get_params(_bracket(filters=()))
    assert params["start"] == "195728637,195800000"
    assert params["end"] == "198100000,198169247"


def test_repeated_get_style_returns_lists(ccl):
    repeated = replace(ccl, get_list_style=GetListStyle.REPEATED)
    params = adapter_for(repeated).build_get_params(_bracket(filters=()))
    assert params["start"] == ["195728637", "195800000"]


def test_alphanumeric_filters_force_post(ccl):
    query = _bracket(filters=(AlphanumericFilter(id="PATO:0000011", operator=">",
                                                  value="P70Y"),))
    assert adapter_for(ccl).prefers_post(query) is True


def test_refseq_style_sends_an_accession(registry):
    body = adapter_for(registry["test.fixture.bracketless"]).build_post_body(_bracket())
    params = body["query"]["requestParameters"]["g_variant"]
    assert params["referenceName"] == "refseq:NC_000003.12"
    assert "assemblyId" not in params


def test_identical_requests_share_a_wire_signature(ccl):
    """The coalescing precondition: different class, same bytes, same key."""
    cnv = _bracket(variant_type=None, filters=())
    sv = cnv.for_class(VariantClass.SV)
    assert cnv.wire_signature(ccl) == sv.wire_signature(ccl)
    assert cnv.wire_signature(ccl) != _bracket().wire_signature(ccl)


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


def test_fixture_client_round_trip():
    client = FixtureClient(str(FIXTURES / "fixture_provider"))
    response = client.post("/g_variants", {"meta": {}})
    assert response.status == 200
    assert response.body["responseSummary"]["numTotalResults"] == 1


def test_fixture_miss_is_loud():
    """A miss must never look like an empty result."""
    client = FixtureClient(str(FIXTURES / "fixture_provider"))
    with pytest.raises(FixtureMiss, match="no fixture"):
        client.get("/biosamples")


def test_fixture_provider_cannot_reach_the_network(registry):
    """Belt to the registry's braces: refused before any socket opens."""
    provider = replace(registry["test.fixture.bracketless"],
                       base_url="https://example.org/beacon")
    client = BeaconClient(base_url=provider.base_url, user_agent="test",
                          provider=provider, max_retries=0)
    with pytest.raises(FixtureProviderEscaped):
        client.get("/info")


def test_credentials_never_render():
    secret = Secret("tok-12345")
    assert "tok-12345" not in repr(secret)
    assert "tok-12345" not in str(secret)
    assert "tok-12345" not in f"{secret}"
    client = BeaconClient(base_url="https://example.org", user_agent="t",
                          credential=secret)
    assert client._auth_headers() == {"Authorization": "Bearer tok-12345"}
