"""Query x Provider x VariantClass -> ExecutionPlans + SkipReasons.

THE SINGLE SOURCE OF DEGRADATION TRUTH.

Every decision to weaken or refuse a query is made here, once, and returned as
data. No other module may drop a filter, flatten a bracket, downgrade a term,
cap granularity or decline a provider. That is what guarantees the per-row
``degradation_notes`` in results.tsv can never disagree with the per-pair
summary in outcomes.tsv: both render the same objects.

TWO-AXIS FAN-OUT
    The unit of planning is the (provider, variant_class) PAIR. Selecting two
    classes across three beacons produces six plans or skips, and therefore six
    outcome rows -- so every empty cell has a stated reason.

CLASS SUPPORT: unknown QUERIES, only a declared `no` SKIPS
    The "unknown capability = do not probe" rule governs query FORM and
    DIALECT, where a speculative request may be malformed for that server and
    lands us in a partner's logs as a badly behaved client. It does not govern
    CONTENT class: a class-unknown query is well-formed, legal, user-initiated
    and indistinguishable at the server from any other query. There is nothing
    to protect anyone from, so we label rather than refuse.

        yes      -> query, outcome `ok`
        unknown  -> query, outcome `ok`, noted as class-unverified, with the
                    warning that a zero result is not evidence of absence
        no       -> skip, quoting the operator declaration

    A non-zero result from an unknown-class query is EVIDENCE, and the planner
    flags it for registry upgrade. The tool teaches the registry through
    ordinary use, which beats periodic sweeps.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from .filters import requires_post
from ..registry.schema import ProviderCapability
from .classes import VariantClass
from .model import Query


class DegradationKind(str, Enum):
    BRACKET_FLATTENED = "bracket_flattened_to_range"
    #: EFO term replaced by DEL/DUP, which the specification marks LEGACY.
    EFO_DOWNGRADED = "efo_downgraded_to_legacy"
    TERM_EXPANDED_CLIENT_SIDE = "term_expanded_client_side"
    TERM_EXPANSION_INFERRED = "term_expansion_used_local_inference"
    FILTERS_DROPPED = "filters_dropped"
    FILTER_SCOPE_DROPPED = "filter_scope_dropped"
    SIMILARITY_DROPPED = "similarity_dropped"
    GRANULARITY_CAPPED = "granularity_capped"
    ASSEMBLY_SUBSTITUTED = "assembly_substituted"
    NESTED_PATH_UNAVAILABLE = "nested_path_unavailable"
    COALESCENCE_FALLBACK = "coalescence_rejected_requeried_per_class"
    #: An SO term for the small-variant class, not sent to a provider that
    #: returns nothing for one (adapters.base.wire_query).
    SMALL_VARIANT_TERM_NOT_SENT = "small_variant_term_not_sent"


class SkipKind(str, Enum):
    CLASS_NOT_SERVED = "class_not_served"          # operator declared `no`
    CLASS_NOT_EXPRESSIBLE = "class_not_expressible"  # e.g. REPEAT before VQS
    FORM_UNSUPPORTED = "form_unsupported"
    DIALECT_UNKNOWN = "dialect_unknown"
    NO_REGISTRY_ENTRY = "no_registry_entry"
    DEGRADATION_REFUSED = "degradation_refused"
    #: The class cannot be expressed through this query form at all, e.g. a
    #: copy number variant requested through a reference/alternate sequence
    #: query. A skip for that pair, not a failure of the job.
    CLASS_INCOHERENT = "class_incoherent"
    #: A later page was requested from a provider whose pages are independent
    #: random draws. Refused at plan time rather than sent (R5).
    PAGINATION_UNSUPPORTED = "pagination_unsupported"
    #: A gene query to a provider that resolves genes only by GET, carrying an
    #: alphanumeric filter, which only POST can encode.
    GENE_FILTER_UNSUPPORTED = "gene_filter_unsupported"


@dataclass(frozen=True)
class Degradation:
    """One weakening of the user's intent, attributable to one pair."""

    kind: DegradationKind
    provider_id: str
    variant_class: VariantClass
    detail: str

    def render(self) -> str:
        """Short human-readable form for the degradation_notes column."""
        return self.detail


@dataclass(frozen=True)
class SkipReason:
    """Why one pair was not queried.

    ``message`` is written for a biologist reading outcomes.tsv, e.g.
    "Beacon X does not serve copy number variants (operator declaration)" --
    never "class unsupported".
    """

    provider_id: str
    variant_class: VariantClass
    kind: SkipKind
    message: str


@dataclass(frozen=True)
class ExecutionPlan:
    """Everything needed to execute one (provider, class) pair.

    ``queries`` is a list because client-side term expansion issues one request
    per descendant term where the provider does not expand server-side.
    """

    provider: ProviderCapability
    variant_class: VariantClass
    queries: tuple[Query, ...]
    degradations: tuple[Degradation, ...]
    use_post: bool
    class_status: str                       # yes | unknown, as declared
    expansion_terms: tuple[str, ...] = ()

    @property
    def class_unverified(self) -> bool:
        """True when this pair is being queried on an unverified class claim."""
        return self.class_status == "unknown"


@dataclass(frozen=True)
class CoalescedGroup:
    """Several class plans that produce a byte-identical request.

    Issued once, then verified. See :func:`verify_coalescence` -- the group is
    only allowed to answer for its members if the single response is provably
    complete.
    """

    provider: ProviderCapability
    representative: ExecutionPlan
    members: tuple[ExecutionPlan, ...]


@dataclass(frozen=True)
class CoalescenceVerdict:
    """Whether one response may answer for every class in its group.

    A PRECONDITION FIRST: the response must not be a testMode response.
    bycon documents testMode as returning "some random documents", so its
    records are a sample of the collection and not the result of the query. A
    testMode response is never coalescable regardless of its counts.

    Then coalescing weakens a claim only when the response was truncated.
    Three conditions must ALL hold:

      * ``responseSummary.numTotalResults`` is present, and
      * it is <= the EFFECTIVE limit (nothing was truncated), and
      * ``countPrecision`` is ``exact``

    THE EFFECTIVE LIMIT COMES FROM THE RESPONSE, NOT THE REQUEST.
    Read ``receivedRequestSummary.pagination.limit`` -- the limit the server
    actually applied, which it may cap or expand. ``effective_limit`` and
    ``limit_source`` below record which value was used and where it came from,
    so a verdict can be audited afterwards.

    No page size may be hardcoded anywhere in this check. Provider defaults
    differ by more than an order of magnitude -- one documented default is
    2000 against another's 200 -- and that changes how often coalescing fires,
    not whether the condition is correct. A 2000-record page makes the
    condition much easier to satisfy, which is good for rate limits, but any
    assumption of a small page would quietly turn the condition into a
    rubber stamp.

    All true -> classify per record and populate every member's outcome row at
    full strength, noting "answered from a single unconstrained query;
    complete for this region".

    Any false -> discard the coalesced result and issue the per-class queries,
    recording COALESCENCE_FALLBACK. The extra request is spent only in the case
    where coalescing would have cost correctness.

    An imprecise count cannot certify completeness any more than it can support
    a frequency: the same rule, applied to the same field, for the same reason.
    """

    holds: bool
    #: Checked BEFORE the arithmetic, because the arithmetic is meaningless
    #: when false. testMode returns RANDOM documents rather than the answer to
    #: the query, so per-record classification cannot speak for classes that
    #: were never separately requested -- however complete the count looks.
    not_test_mode: bool
    has_total: bool
    within_limit: bool
    count_exact: bool
    #: The page size the condition was evaluated against, and where it came
    #: from: `response` (receivedRequestSummary) or `request` (fallback only).
    effective_limit: int | float
    limit_source: str
    reason: str
    count_precision_basis: str = ""


@dataclass(frozen=True)
class PlanSet:
    """The complete two-axis plan for one run."""

    plans: tuple[ExecutionPlan, ...]
    skips: tuple[SkipReason, ...]
    coalesced: tuple[CoalescedGroup, ...]

    def pairs(self) -> tuple[tuple[str, VariantClass], ...]:
        """Every (provider_id, class) pair, planned or skipped.

        outcomes.tsv must contain exactly this set, no more and no fewer.
        """
        planned = [(p.provider.id, p.variant_class) for p in self.plans]
        skipped = [(s.provider_id, s.variant_class) for s in self.skips]
        return tuple(planned + skipped)


class QueryUsageError(ValueError):
    """A query that is malformed independently of any provider.

    Fatal by design: it would be wrong for EVERY pair, so producing one skipped
    row per provider would bury a usage error under a wall of identical skips.
    """


def plan(
    queries: Sequence[Query],
    providers: Sequence[ProviderCapability],
    allow_degradation: bool = True,
    allow_coalescing: bool = True,
) -> PlanSet:
    """Build the full two-axis plan.

    ``queries`` holds one Query per selected class. Never raises for a single
    pair: anything unrunnable becomes a :class:`SkipReason`, which becomes a
    ``skipped`` row. Partial failure is normal. Only a provider-independent
    usage error raises (:class:`QueryUsageError`).
    """
    plans: list[ExecutionPlan] = []
    skips: list[SkipReason] = []
    for query in queries:
        for provider in providers:
            outcome = plan_pair(query, provider, allow_degradation)
            (plans if isinstance(outcome, ExecutionPlan) else skips).append(outcome)
    groups: list[CoalescedGroup] = []
    if allow_coalescing:
        groups, _ = coalesce(plans)
    return PlanSet(plans=tuple(plans), skips=tuple(skips), coalesced=tuple(groups))


def _skip(query: Query, provider: ProviderCapability, kind: SkipKind,
          message: str) -> SkipReason:
    return SkipReason(provider.id, query.variant_class, kind, message)


def plan_pair(
    query: Query, provider: ProviderCapability, allow_degradation: bool
) -> ExecutionPlan | SkipReason:
    """Plan one (provider, class) pair.

    Checks run from the most fundamental reason not to query to the least, so
    the skip a user reads is the one that actually decided it.
    """
    if (getattr(query.form, "value", query.form) == "geneId"
            and provider.gene_query_transport == "get" and requires_post(query.filters)):
        return _skip(query, provider, SkipKind.GENE_FILTER_UNSUPPORTED,
                     f"{provider.name} resolves gene symbols only by GET, which cannot carry "
                     f"an alphanumeric filter. Query the gene's coordinates with a range "
                     f"query instead, which can.")
    from ..adapters.base import PaginationUnsupported, adapter_for
    from ..registry.schema import ClassStatus
    from .classes import incoherent_parameters, is_queryable_today, legal_for
    from .classes import profile as class_profile

    klass = query.variant_class
    label = class_profile(klass).label
    plural = label.lower() + ("s" if not label.endswith("s") else "")
    support = provider.class_support(klass)

    # 1. A declared `no` is the only CLASS reason to skip.
    if support.status is ClassStatus.NO:
        evidence = support.evidence.strip() or "operator declaration"
        return _skip(query, provider, SkipKind.CLASS_NOT_SERVED,
                     f"{provider.name} does not serve {plural} ({evidence})")

    # 2. Coherent, but nothing this provider speaks can express it.
    if not is_queryable_today(klass, provider):
        return _skip(query, provider, SkipKind.CLASS_NOT_EXPRESSIBLE,
                     f"{label} queries cannot be expressed in the query standard "
                     f"{provider.name} speaks; no configured beacon supports "
                     f"them yet")

    # 3. The class contradicts the query form or its parameters.
    form = getattr(query.form, "value", query.form)
    clashes = incoherent_parameters(klass, query._supplied_parameters())
    if not legal_for(klass, form) or clashes:
        detail = (f"{', '.join(clashes)} cannot be combined with it" if clashes
                  else f"it cannot be expressed as a {form} query")
        return _skip(query, provider, SkipKind.CLASS_INCOHERENT,
                     f"{label}: {detail}")

    # 4. A dialect we do not know is never guessed at.
    if any(getattr(provider, f).value == "unknown" for f in
           ("request_layout", "filters_location", "get_list_style", "reference_style")):
        return _skip(query, provider, SkipKind.DIALECT_UNKNOWN,
                     f"{provider.name}'s request dialect is not known, so it was "
                     f"not queried rather than sent a guess")

    try:
        query.validate()
    except ValueError as exc:
        raise QueryUsageError(str(exc)) from exc

    degradations: list[Degradation] = []

    # 5. Query form support, degrading a bracket to a range where allowed.
    if not provider.supports(form):
        if form == "bracket" and provider.supports("range"):
            if not allow_degradation:
                return _skip(query, provider, SkipKind.DEGRADATION_REFUSED,
                             f"{provider.name} does not support bracket queries, and "
                             f"widening to a range query was not allowed")
            query, degradation = _degrade_bracket_to_range(query, provider)
            degradations.append(degradation)
        else:
            return _skip(query, provider, SkipKind.FORM_UNSUPPORTED,
                         f"{provider.name} does not support {form} queries")

    if (query.variant_class is VariantClass.SMALL_VARIANT
            and provider.small_variant_type_filter == "unsupported"
            and str(query.variant_type or "").startswith("SO:")):
        degradations.append(Degradation(
            DegradationKind.SMALL_VARIANT_TERM_NOT_SENT, provider.id, query.variant_class,
            f"{query.variant_type} not sent: {provider.name} returns nothing for small-variant "
            f"SO terms, so every small variant in the region was retrieved and the term was "
            f"not applied"))

    query, capped = _cap_granularity(query, provider)
    degradations.extend(capped)

    queries, expansion_degradations, expansion_terms = _resolve_copy_change(
        query, provider
    )
    degradations.extend(expansion_degradations)

    # 6. R5: a refused later page is a skipped row, never an exception.
    adapter = adapter_for(provider)
    try:
        adapter.retrieval_pagination(query)
    except PaginationUnsupported as exc:
        return _skip(query, provider, SkipKind.PAGINATION_UNSUPPORTED, str(exc))

    return ExecutionPlan(
        provider=provider,
        variant_class=klass,
        queries=tuple(queries),
        degradations=tuple(degradations),
        use_post=adapter.prefers_post(query),
        class_status=support.status.value,
        expansion_terms=tuple(expansion_terms),
    )


def coalesce(plans: Sequence[ExecutionPlan]) -> tuple[list[CoalescedGroup], list[ExecutionPlan]]:
    """Group plans whose wire request is identical.

    Returns ``(groups, ungrouped)``. Grouping is by (provider, wire signature),
    and only ever across classes of the same provider -- never across providers,
    whose responses must stay separately attributable. Plans that fan out into
    several requests through client-side expansion are never grouped.
    """
    buckets: dict[tuple[str, str], list[ExecutionPlan]] = {}
    ungrouped: list[ExecutionPlan] = []
    for candidate in plans:
        if len(candidate.queries) != 1:
            ungrouped.append(candidate)
            continue
        key = (candidate.provider.id,
               candidate.queries[0].wire_signature(candidate.provider))
        buckets.setdefault(key, []).append(candidate)
    groups: list[CoalescedGroup] = []
    for members in buckets.values():
        if len(members) > 1:
            groups.append(CoalescedGroup(members[0].provider, members[0],
                                         tuple(members)))
        else:
            ungrouped.extend(members)
    return groups, ungrouped


def verify_coalescence(envelope, requested_limit: int) -> CoalescenceVerdict:
    """Decide whether a coalesced response may answer for its whole group.

    ``requested_limit`` is a FALLBACK, used only when the provider did not
    echo ``receivedRequestSummary.pagination.limit``. The effective limit is
    resolved through ``normalise.envelope.effective_limit``, which treats an
    echoed 0 as unbounded rather than as zero or as absent.

    Every field is computed even when the testMode precondition has already
    decided the verdict, so a rejection reports the full picture.
    """
    from ..normalise.envelope import effective_count_precision, effective_limit

    limit, source = effective_limit(envelope, requested_limit)
    not_test_mode = not envelope.test_mode
    total = envelope.num_total_results
    has_total = total is not None
    within_limit = has_total and total <= limit
    precision, precision_basis = effective_count_precision(envelope)
    count_exact = precision == "exact"

    failures = []
    if not not_test_mode:
        failures.append("testMode responses contain random documents, not the "
                        "query result")
    if not has_total:
        failures.append("no numTotalResults, so completeness cannot be shown")
    elif not within_limit:
        failures.append(f"{total} results exceed the applied limit of {limit}, so "
                        f"the response was truncated")
    if not count_exact:
        failures.append(f"count precision is {precision} ({precision_basis}), "
                        f"not exact")
    holds = not failures
    reason = ("complete for this region" if holds else "; ".join(failures))
    return CoalescenceVerdict(
        holds=holds, not_test_mode=not_test_mode, has_total=has_total,
        within_limit=within_limit, count_exact=count_exact,
        effective_limit=limit, limit_source=source, reason=reason,
        count_precision_basis=precision_basis,
    )


def evidence_from_result(plan: ExecutionPlan, row_count: int) -> str | None:
    """Return a registry-upgrade suggestion when an unverified class delivers.

    Returns None for a zero result: absence in one query is not evidence of
    absence, and nothing here may ever suggest writing ``no``.
    """
    if plan.class_unverified and row_count > 0:
        return (f"records returned for {plan.variant_class.value}; this class can "
                f"be upgraded to yes in the registry")
    return None


def _degrade_bracket_to_range(query: Query, provider: ProviderCapability):
    """Flatten a bracket query for a provider lacking bracket support.

    Widens to the outer envelope, which changes the result set: a range query
    matches any partial overlap, so this is more permissive than the bracket
    the user asked for. That difference is why the degradation must appear on
    every affected row.
    """
    from dataclasses import replace

    from .model import Position, QueryForm

    outer_start, outer_end = query.start.values[0], query.end.values[-1]
    flattened = replace(query, form=QueryForm.RANGE,
                        start=Position((outer_start,)), end=Position((outer_end,)))
    return flattened, Degradation(
        DegradationKind.BRACKET_FLATTENED, provider.id, query.variant_class,
        f"bracket flattened to range {outer_start}-{outer_end}; matches any "
        f"overlap, so more permissive than the bracket requested",
    )


def _resolve_copy_change(query: Query, provider: ProviderCapability):
    """Decide how a CNV term travels and whether we expand it ourselves.

    ``copy_change_expansion: unknown`` is treated as client-side. Trusting an
    unverified server-side expansion risks silent false negatives, which is the
    failure class that cannot be detected from the output. Where the provider
    is OBSERVED to expand, `auto` does not expand again -- doing so would
    return overlapping result sets.

    Returns ``(queries, degradations, expansion_terms)``.
    """
    from dataclasses import replace

    from ..normalise.classify import normalise_efo_term
    from .terms import expand, expansion_crosses_inference

    term = normalise_efo_term(query.variant_type)
    mode = (query.expand_hierarchy or "auto").lower()
    if term is None or mode == "never":
        return [query], [], []
    server_expands = provider.copy_change_expansion == "server"
    if server_expands and mode == "auto":
        return [query], [], []

    expanded = expand(term)
    if len(expanded) == 1:
        return [query], [], []
    degradations = [Degradation(
        DegradationKind.TERM_EXPANDED_CLIENT_SIDE, provider.id, query.variant_class,
        f"{term} expanded client-side to {', '.join(expanded)}",
    )]
    if expansion_crosses_inference(term, expanded):
        degradations.append(Degradation(
            DegradationKind.TERM_EXPANSION_INFERRED, provider.id, query.variant_class,
            "expansion included EFO:0030073 via a locally inferred edge beneath "
            "high-level gain, not a published hierarchy",
        ))
    queries = [replace(query, variant_type=e) for e in expanded]
    return queries, degradations, expanded


def _cap_granularity(query: Query, provider: ProviderCapability):
    """Cap requested granularity to the per-entity declared ceiling."""
    from dataclasses import replace

    from ..normalise.envelope import GRANULARITY_RANK

    entity = query.nested_entity or query.entity
    ceiling = provider.ceiling_for(entity).value
    requested = query.requested_granularity
    if ceiling not in GRANULARITY_RANK or requested not in GRANULARITY_RANK:
        return query, []
    if GRANULARITY_RANK[ceiling] >= GRANULARITY_RANK[requested]:
        return query, []
    return replace(query, requested_granularity=ceiling), [Degradation(
        DegradationKind.GRANULARITY_CAPPED, provider.id, query.variant_class,
        f"{requested} requested; {provider.name} serves at most {ceiling} for "
        f"{entity} records",
    )]
