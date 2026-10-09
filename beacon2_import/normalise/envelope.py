"""Unwrap the Beacon response envelope, whatever shape it arrives in.

Handled shapes:
  * ``response.resultSets[].results`` (record granularity, normative)
  * flat ``response.results`` (used by some bycon endpoints)
  * ``responseSummary`` with an EMPTY ``resultSets`` -- a legitimate "no
    matches", which must be distinguishable from an error and from
    "never queried"
  * boolean and count granularity, which yield ONE summary row carrying
    ``exists`` and ``numTotalResults``. Never an empty result: an empty table
    would be indistinguishable from no matches.

Also captures, per result set, the fields that decide whether a count may be
divided later: ``countPrecision`` (normative default ``imprecise``) and
``countAdjustedTo``.

ENTITY TYPE MUST BE VERIFIED, NOT ASSUMED FROM THE PATH
    Beacon+ determines the response entity type from
    ``meta.requestedSchemas[0].entityType``, not from the endpoint path -- its
    documentation states that POSTing to the variants path or the biosamples
    path makes no difference, because the first requested schema decides what
    comes back.

    That fails SILENTLY. Query the variants path with entityType unset or
    wrong and a well-formed response of the wrong entity type arrives with no
    error anywhere, after which the normaliser would flatten biosample records
    into variant columns. Nothing downstream could detect it.

    So :func:`assert_entity_type` compares
    ``meta.returnedSchemas[0].entityType`` against what was requested, and a
    mismatch is an ERROR rather than a warning -- the same discipline as
    reading ``returnedGranularity`` instead of assuming the requested
    granularity was honoured.

THE ENTITY TYPE APPEARS IN THREE PLACES
    ``meta.requestedSchemas[0].entityType`` (what we asked for),
    ``meta.returnedSchemas[0]`` (what the framework says came back) and
    ``response.resultSets[].responseEntityId`` (what bycon puts on each result
    set). On the live record examined they agree.

    :func:`assert_entity_type` treats ``returnedSchemas`` as authoritative,
    because it is the framework-normative field, and reports disagreement
    between it and ``responseEntityId`` as a degradation rather than choosing
    silently. If they ever diverge we want to have been told, not to have
    guessed.

EFFECTIVE PAGINATION LIMIT
    ``receivedRequestSummary.pagination.limit`` is the limit the server
    actually applied, which may be lower or higher than the one requested.
    Completeness checks must use it, never the requested value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

#: The applied limit when a request asked for everything. A `limit: 0` request
#: echoes back as literally 0 -- the server does not translate it into its real
#: maximum -- and 0 means UNBOUNDED, not zero. Taken literally,
#: `numTotalResults <= 0` would fail every complete retrieval, defeating
#: coalescing in exactly the case it should hold.
UNBOUNDED = math.inf

GRANULARITY_RANK = {"boolean": 0, "count": 1, "aggregated": 2, "record": 3}


class MalformedEnvelope(ValueError):
    """The body is not a Beacon response envelope at all.

    Distinct from a valid envelope with no matches, which is a normal result.
    """


@dataclass(frozen=True)
class ResultSetMeta:
    """Per-result-set metadata that survives into every row."""

    id: str | None
    set_type: str | None
    exists: bool | None
    results_count: int | None
    count_precision: str = "imprecise"
    count_adjusted_to: str | None = None
    #: Whether the server SENT countPrecision. Without this, an absent field and
    #: an explicit "imprecise" are indistinguishable -- and the precision ruling
    #: treats them oppositely: an explicit statement always wins, an absence may
    #: be overridden by observation.
    count_precision_declared: bool = False


class EntityTypeMismatch(Exception):
    """The response entity type differs from the one requested.

    An error, never a warning: the alternative is silently filing one kind of
    record under another kind's columns.
    """

    def __init__(self, requested: str, returned: str) -> None:
        self.requested = requested
        self.returned = returned
        super().__init__(
            f"requested {requested!r} records but the response declares "
            f"{returned!r}; discarded rather than flattened into the wrong columns"
        )


@dataclass(frozen=True)
class Envelope:
    """A parsed response, independent of which shape it arrived in."""

    exists: bool | None
    num_total_results: int | None
    returned_granularity: str | None
    returned_schemas: tuple[str, ...]
    result_sets: tuple[ResultSetMeta, ...]
    records: tuple[dict[str, Any], ...]
    api_version_reported: str | None
    test_mode: bool | None
    #: From meta.returnedSchemas[0].entityType. Must be checked, not trusted.
    returned_entity_type: str | None = None
    #: From response.resultSets[].responseEntityId -- bycon's per-result-set
    #: entity declaration. A third source for the same fact; carried so
    #: disagreement can be reported instead of silently resolved.
    response_entity_ids: tuple[str, ...] = ()
    #: From receivedRequestSummary.pagination.limit -- the limit the server
    #: actually applied. None when the server did not echo it.
    received_request_limit: int | None = None
    is_empty_but_valid: bool = False


def _int_or_none(value: Any) -> int | None:
    """Coerce to int, keeping None and refusing bools masquerading as ints."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse(body: dict[str, Any]) -> Envelope:
    """Parse any Beacon response body into an :class:`Envelope`.

    Raises :class:`MalformedEnvelope` only when the body is not a Beacon
    envelope at all. A valid envelope with no matches is a normal result.
    """
    if not isinstance(body, dict):
        raise MalformedEnvelope(f"expected a JSON object, got {type(body).__name__}")
    meta = body.get("meta")
    summary = body.get("responseSummary")
    response = body.get("response")
    if not isinstance(meta, dict) and not isinstance(summary, dict) \
            and not isinstance(response, dict):
        raise MalformedEnvelope(
            "no meta, responseSummary or response: not a Beacon envelope"
        )
    meta = meta if isinstance(meta, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    response = response if isinstance(response, dict) else {}
    received = meta.get("receivedRequestSummary") or {}

    returned_schemas = meta.get("returnedSchemas") or []
    returned_entity_type = None
    schema_ids: list[str] = []
    for schema in returned_schemas:
        if isinstance(schema, dict):
            # The framework writes `entityType`; bycon writes `id` (observed in
            # every raw bycon response). Reading only `entityType` left the
            # entity check silently disabled on the very stack it was built for.
            declared = schema.get("entityType") or schema.get("id")
            if returned_entity_type is None and declared:
                returned_entity_type = str(declared)
            reference = schema.get("schema") or schema.get("referenceToSchemaDefinition")
            if reference:
                schema_ids.append(str(reference))

    pagination = received.get("pagination") if isinstance(received, dict) else None
    received_limit = None
    if isinstance(pagination, dict):
        received_limit = _int_or_none(pagination.get("limit"))

    test_mode_raw = received.get("testMode") if isinstance(received, dict) else None
    if test_mode_raw is None:
        test_mode_raw = meta.get("testMode")

    result_sets: list[ResultSetMeta] = []
    records: list[dict[str, Any]] = []
    entity_ids: list[str] = []
    for result_set in response.get("resultSets") or []:
        if not isinstance(result_set, dict):
            continue
        result_sets.append(ResultSetMeta(
            id=result_set.get("id"),
            set_type=result_set.get("setType"),
            exists=result_set.get("exists"),
            results_count=_int_or_none(result_set.get("resultsCount")),
            # Absent means the NORMATIVE default, which is imprecise.
            count_precision=str(result_set.get("countPrecision") or "imprecise"),
            count_adjusted_to=result_set.get("countAdjustedTo"),
            count_precision_declared="countPrecision" in result_set,
        ))
        if result_set.get("responseEntityId"):
            entity_ids.append(str(result_set["responseEntityId"]))
        for record in result_set.get("results") or []:
            if isinstance(record, dict):
                records.append(record)
    for record in response.get("results") or []:
        if isinstance(record, dict):
            records.append(record)

    exists = summary.get("exists")
    total = _int_or_none(summary.get("numTotalResults"))
    is_empty_but_valid = bool(summary) and not records and (
        exists is False or total == 0
    )

    return Envelope(
        exists=exists if isinstance(exists, bool) else None,
        num_total_results=total,
        returned_granularity=meta.get("returnedGranularity"),
        returned_schemas=tuple(schema_ids),
        result_sets=tuple(result_sets),
        records=tuple(records),
        api_version_reported=meta.get("apiVersion"),
        test_mode=parse_test_mode(test_mode_raw),
        returned_entity_type=returned_entity_type,
        response_entity_ids=tuple(entity_ids),
        received_request_limit=received_limit,
        is_empty_but_valid=is_empty_but_valid,
    )


def summary_row(envelope: Envelope) -> dict[str, Any]:
    """Build the single row that represents a boolean or count response."""
    return {
        "exists": "" if envelope.exists is None else str(envelope.exists).lower(),
        "num_total_results": ""
        if envelope.num_total_results is None else str(envelope.num_total_results),
    }


def assert_entity_type(envelope: Envelope, requested_entity_type: str) -> list[str]:
    """Raise :class:`EntityTypeMismatch` unless the returned type matches.

    Called immediately after :func:`parse`, before any flattener runs. Skipped
    only when the provider omitted ``returnedSchemas`` entirely, which is
    recorded as a degradation rather than passed over in silence.

    Also compares ``returnedSchemas`` against every ``responseEntityId``;
    disagreement is returned as a note, with ``returnedSchemas`` treated as
    authoritative because it is the framework-normative field.
    """
    notes: list[str] = []
    returned = envelope.returned_entity_type
    if returned is None:
        notes.append("provider omitted returnedSchemas; entity type not verifiable")
    elif returned != requested_entity_type:
        raise EntityTypeMismatch(requested_entity_type, returned)

    disagreeing = sorted({e for e in envelope.response_entity_ids if e != returned})
    if returned is not None and disagreeing:
        notes.append(
            f"responseEntityId {disagreeing} disagrees with returnedSchemas "
            f"{returned!r}; returnedSchemas treated as authoritative"
        )
    return notes


def effective_limit(envelope: Envelope,
                    requested_limit: int | None) -> tuple[int | float, str]:
    """Return ``(limit, source)`` for completeness arithmetic.

    Prefers ``receivedRequestSummary.pagination.limit``, which bycon echoes on
    every request; falls back to the requested value only when the server did
    not echo one, and says which was used so a coalescing verdict is auditable.

    TWO TRAPS, both about zero:

    * ABSENCE IS TESTED WITH ``is None``, never by truthiness. ``echoed or
      requested`` treats an echoed 0 as missing and silently substitutes a page
      size.
    * ZERO MEANS UNBOUNDED. A `limit: 0` request echoes back as literally 0.
      It returns :data:`UNBOUNDED` with source ``"unbounded"``, so a verdict
      says why it held rather than failing every complete retrieval on
      ``total <= 0``.
    """
    echoed = envelope.received_request_limit
    if echoed is not None:
        if echoed == 0:
            return UNBOUNDED, "unbounded"
        return echoed, "response"
    if requested_limit is None:
        raise ValueError("no echoed limit and no requested limit to fall back on")
    if int(requested_limit) == 0:
        return UNBOUNDED, "unbounded"
    return int(requested_limit), "request"


def instance_count(records: list[dict[str, Any]]) -> int:
    """Number of per-sample variant INSTANCES in a set of records.

    One per ``caseLevelData`` entry. A record with no case-level data counts
    once, because it still represents one observed variant.

    This is the unit ``numTotalResults`` is expressed in on at least one stack
    (observed: 55 records carrying 60 instances, numTotalResults 60) -- a
    different unit from ``limit``, which counts records.
    """
    total = 0
    for record in records:
        cases = record.get("caseLevelData")
        total += len(cases) if isinstance(cases, list) and cases else 1
    return total


def is_complete_retrieval(records: list[dict[str, Any]],
                          num_total_results: int | None) -> bool:
    """Whether every matching record was retrieved, in the unit-correct sense.

    ``sum(len(record.caseLevelData)) == numTotalResults``. This is what proved
    completeness live. Comparing a record count against numTotalResults would
    compare records to instances and declare complete results incomplete
    whenever a variant occurs in more than one sample.

    False when the total is absent: an absent total certifies nothing.
    """
    if num_total_results is None:
        return False
    return instance_count(records) == int(num_total_results)


PRECISION_DECLARED = "declared"
PRECISION_DECLARED_ADJUSTMENT = "declared_adjustment"
PRECISION_INFERRED = "inferred_from_complete_retrieval"
PRECISION_DEFAULT = "normative_default"
#: OBSERVED in the response: fewer instances delivered than numTotalResults.
PRECISION_PARTIAL = "partial_retrieval"


def effective_count_precision(envelope: Envelope) -> tuple[str, str]:
    """Return ``(count_precision, count_precision_basis)`` for a response.

    THE RULING. bycon sends neither countPrecision nor countAdjustedTo -- in
    any of fifteen raw responses examined -- so under the normative default
    every bycon response would be imprecise and frequency-ineligible, leaving
    the frequency engine nothing it could compute on. Exactness may therefore
    be INFERRED, under three conditions:

      1. countPrecision AND countAdjustedTo are both absent. An explicit
         `imprecise` or `rounded`, or any declared adjustment, refuses. A
         server stating its counts are approximate always wins.
      2. Record granularity, with complete retrieval by the unit-correct test:
         the caseLevelData instance sum equals numTotalResults.
      3. The result is LABELLED inferred, never declared: basis
         ``inferred_from_complete_retrieval``, distinct from a server-declared
         exact, so a downstream reader can tell an inference from a
         declaration.

    Why it is sound: at record granularity the frequency numerator is computed
    from the delivered records, not from numTotalResults -- the total only
    certifies that retrieval was complete. A rounded total would not equal the
    instance sum except by coincidence. And rounding protects the count tier;
    once the records themselves are returned, rounding their total protects
    nothing.

    ACCEPTED RESIDUAL RISK: a server that rounds its total AND truncates
    delivery to exactly the rounded value would pass. That is two independent
    behaviours coinciding to the instance, and such a server would trip
    condition 1 the moment it declared its rounding. Pinned by a test.
    """
    # PARTIALITY FIRST, BY OBSERVATION. Whether a result is partial is a fact
    # about this response, not a property of the provider: fewer delivered
    # instances than the reported total is partial whatever the registry or the
    # server declares, and is never exact or complete.
    if envelope.returned_granularity == "record" and envelope.num_total_results is not None:
        if instance_count(list(envelope.records)) < int(envelope.num_total_results):
            return "imprecise", PRECISION_PARTIAL

    sets = envelope.result_sets
    declared = [rs.count_precision for rs in sets if rs.count_precision_declared]
    if any(p != "exact" for p in declared):
        worst = "rounded" if "rounded" in declared else "imprecise"
        return worst, PRECISION_DECLARED
    if any(rs.count_adjusted_to is not None for rs in sets):
        return "imprecise", PRECISION_DECLARED_ADJUSTMENT
    if sets and len(declared) == len(sets):
        return "exact", PRECISION_DECLARED
    if (envelope.returned_granularity == "record"
            and is_complete_retrieval(list(envelope.records), envelope.num_total_results)):
        return "exact", PRECISION_INFERRED
    return "imprecise", PRECISION_DEFAULT


def parse_test_mode(value: Any) -> bool:
    """Read a testMode echo defensively.

    Three representations observed: ``{}`` on GET when unset, ``False`` on POST
    when unset, ``True`` when set. Truthiness reads all three correctly; an
    ``is True`` or bool type check would misread the GET-unset case as
    malformed. Strings are accepted for servers that echo query-string values.
    """
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def granularity_was_downgraded(requested: str, envelope: Envelope) -> bool:
    """Whether the provider returned less detail than we asked for.

    Compares against ``meta.returnedGranularity``, which is authoritative over
    anything the registry declares. An unrecognised returned value counts as a
    downgrade: it cannot be shown to be at least as detailed as requested.
    """
    returned = envelope.returned_granularity
    if returned is None:
        return False
    if returned not in GRANULARITY_RANK:
        return True
    return GRANULARITY_RANK[returned] < GRANULARITY_RANK.get(requested, 3)


def combined_precision(envelopes: list[Envelope]) -> tuple[str, str, list[tuple[int, int]]]:
    """One outcome's precision across ALL the queries that produced it.

    A (provider, class) pair can take several requests -- client-side term
    expansion sends one per term. The outcome is exact only if every one is;
    if ANY is partial the outcome is partial, and the shortfalls are returned as
    (retrieved, total) so the note can state N of M. Taking only the last
    request's envelope reported a 7% sample as exact: the last of four
    expansion queries matched nothing, and 0 of 0 is trivially complete.
    """
    judged = [(effective_count_precision(e), e) for e in envelopes if e is not None]
    shortfalls = [(instance_count(list(e.records)), int(e.num_total_results))
                  for (_, basis), e in judged if basis == PRECISION_PARTIAL]
    if shortfalls:
        return "imprecise", PRECISION_PARTIAL, shortfalls
    for (precision, basis), _ in judged:
        if precision != "exact":
            return precision, basis, []
    if judged and all(basis == PRECISION_DECLARED for (_, basis), _ in judged):
        return "exact", PRECISION_DECLARED, []
    if judged:
        return "exact", PRECISION_INFERRED, []
    return "imprecise", PRECISION_DEFAULT, []
