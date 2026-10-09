"""Two-axis planning against the real registry. No fixtures needed."""

from __future__ import annotations

from dataclasses import replace

import pytest

from beacon2_import.query.classes import VariantClass
from beacon2_import.query.model import (
    OntologyFilter, Pagination, Position, Query, QueryForm,
)
from beacon2_import.query.planner import (
    DegradationKind, ExecutionPlan, SkipKind, SkipReason, evidence_from_result,
    plan, plan_pair,
)
from beacon2_import.registry.loader import load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def _bracket(klass=VariantClass.CNV, **overrides) -> Query:
    base = dict(form=QueryForm.BRACKET, variant_class=klass, reference_name="3",
                assembly="GRCh38", start=Position((195728637, 195800000)),
                end=Position((198100000, 198169247)))
    base.update(overrides)
    return Query(**base)


def _sequence(klass=VariantClass.SMALL_VARIANT) -> Query:
    return Query(form=QueryForm.SEQUENCE, variant_class=klass, reference_name="17",
                 start=Position((7577119,)), reference_bases="G", alternate_bases="A")


# ---------------- R5 ----------------

def test_later_page_on_random_subset_provider_is_a_skip(registry):
    """R5: refused at plan time as a row, never raised out of the planner."""
    outcome = plan_pair(_bracket(pagination=Pagination(skip=2, limit=100)),
                        registry["org.cancercelllines"], True)
    assert isinstance(outcome, SkipReason)
    assert outcome.kind is SkipKind.PAGINATION_UNSUPPORTED
    assert "random" in outcome.message


def test_later_page_skip_does_not_fail_other_pairs(registry):
    """A later page is refused only where pages cannot be trusted; a provider
    DECLARING contiguous pages is still planned."""
    import dataclasses

    pager = dataclasses.replace(registry["org.progenetix.beacon"], pagination_behaviour="pages")
    providers = [registry["org.cancercelllines"], pager]
    result = plan([_bracket(pagination=Pagination(skip=2, limit=100))], providers)
    assert {s.provider_id for s in result.skips} == {"org.cancercelllines"}
    assert {p.provider.id for p in result.plans} == {"org.progenetix.beacon"}


def test_later_page_is_refused_where_pagination_is_unknown(registry):
    """Unknown pagination must not mean "trust the page"."""
    import dataclasses

    unknown = dataclasses.replace(registry["org.progenetix.beacon"], pagination_behaviour="unknown")
    result = plan([_bracket(pagination=Pagination(skip=2, limit=100))], [unknown])
    assert {s.provider_id for s in result.skips} == {"org.progenetix.beacon"}


# ---------------- the two-axis contract ----------------

def test_every_pair_is_planned_or_skipped(registry):
    providers = [registry[p] for p in
                 ("org.cancercelllines", "org.progenetix.beacon", "test.fixture.bracketless")]
    queries = [_bracket(VariantClass.CNV), _bracket(VariantClass.SV)]
    result = plan(queries, providers)
    assert len(result.pairs()) == 6
    assert len(set(result.pairs())) == 6


def test_declared_no_is_the_only_class_skip(registry):
    fixture = registry["test.fixture.bracketless"]
    no = plan_pair(_bracket(VariantClass.SV), fixture, True)
    assert isinstance(no, SkipReason) and no.kind is SkipKind.CLASS_NOT_SERVED
    assert "does not serve structural variants" in no.message

    unknown = plan_pair(_bracket(VariantClass.SV), registry["org.cancercelllines"], True)
    assert isinstance(unknown, ExecutionPlan) and unknown.class_unverified


def test_repeat_is_a_skip_not_an_error(registry):
    outcome = plan_pair(_bracket(VariantClass.REPEAT), registry["org.cancercelllines"], True)
    assert isinstance(outcome, SkipReason)
    assert outcome.kind is SkipKind.CLASS_NOT_EXPRESSIBLE


def test_incoherent_class_skips_that_pair_only(registry):
    """CNV through a ref/alt sequence query is incoherent; SNV beside it is fine."""
    ccl = registry["org.cancercelllines"]
    cnv = plan_pair(_sequence(VariantClass.CNV), ccl, True)
    snv = plan_pair(_sequence(VariantClass.SMALL_VARIANT), ccl, True)
    assert isinstance(cnv, SkipReason) and cnv.kind is SkipKind.CLASS_INCOHERENT
    assert isinstance(snv, ExecutionPlan)


# ---------------- degradation ----------------

def test_bracket_is_flattened_where_unsupported(registry):
    outcome = plan_pair(_bracket(), registry["test.fixture.bracketless"], True)
    assert isinstance(outcome, ExecutionPlan)
    assert outcome.queries[0].form is QueryForm.RANGE
    assert outcome.degradations[0].kind is DegradationKind.BRACKET_FLATTENED


def test_flattening_can_be_refused(registry):
    outcome = plan_pair(_bracket(), registry["test.fixture.bracketless"], False)
    assert isinstance(outcome, SkipReason)
    assert outcome.kind is SkipKind.DEGRADATION_REFUSED


# ---------------- expansion ----------------

def test_no_client_expansion_where_server_expands(registry):
    outcome = plan_pair(_bracket(variant_type="EFO:0030070"),
                        registry["org.cancercelllines"], True)
    assert len(outcome.queries) == 1
    assert not outcome.expansion_terms


def test_client_expansion_where_server_behaviour_unknown(registry):
    import dataclasses

    unverified = dataclasses.replace(registry["org.progenetix.beacon"],
                                     copy_change_expansion="unknown")
    outcome = plan_pair(_bracket(variant_type="EFO:0030070"), unverified, True)
    assert [q.variant_type for q in outcome.queries] == [
        "EFO:0030070", "EFO:0030071", "EFO:0030072", "EFO:0030073"]
    kinds = {d.kind for d in outcome.degradations}
    assert DegradationKind.TERM_EXPANDED_CLIENT_SIDE in kinds
    assert DegradationKind.TERM_EXPANSION_INFERRED in kinds


def test_expansion_never_requested_is_honoured(registry):
    outcome = plan_pair(_bracket(variant_type="EFO:0030070", expand_hierarchy="never"),
                        registry["org.progenetix.beacon"], True)
    assert len(outcome.queries) == 1


# ---------------- coalescing and evidence ----------------

def test_identical_class_requests_are_grouped(registry):
    ccl = registry["org.cancercelllines"]
    result = plan([_bracket(VariantClass.CNV), _bracket(VariantClass.SV)], [ccl])
    assert len(result.coalesced) == 1
    assert {m.variant_class for m in result.coalesced[0].members} == {
        VariantClass.CNV, VariantClass.SV}


def test_coalescing_never_crosses_providers(registry):
    providers = [registry["org.cancercelllines"], registry["org.progenetix.beacon"]]
    result = plan([_bracket(VariantClass.CNV), _bracket(VariantClass.SV)], providers)
    for group in result.coalesced:
        assert len({m.provider.id for m in group.members}) == 1


def test_unverified_class_hit_is_evidence_and_a_zero_is_not(registry):
    outcome = plan_pair(_bracket(VariantClass.SV), registry["org.cancercelllines"], True)
    assert "upgraded to yes" in evidence_from_result(outcome, 5)
    assert evidence_from_result(outcome, 0) is None
