"""Argument groups shared by every tool, and the end-to-end query runner.

Keeping these in one place is what keeps the tools consistent: a provider
selection means the same thing everywhere, and every query tool emits the same
two outputs.

Pipeline: resolve providers -> one Query per class -> plan -> execute each pair
(coalesced groups once, with verification and fallback) -> verify entity type
-> flatten -> label -> deduplicate -> record the outcome -> write both outputs.

A provider-level failure is NEVER a job failure: it becomes a row in
outcomes.tsv. Only a usage error, or an inability to write the outputs, is
fatal. One deliberate exception: FixtureProviderEscaped is a bug -- a synthetic
provider about to reach the network -- and stops the run.
"""

from __future__ import annotations

import argparse
import datetime
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..adapters.base import adapter_for
from ..auth.resolver import CredentialMissing, credential_for, load_credentials, redact
from ..formats import results as results_format
from ..formats.outcomes import Outcome, OutcomeRecorder, Status, note_for
from ..normalise.classify import classify
from ..normalise.envelope import (
    EntityTypeMismatch, MalformedEnvelope, assert_entity_type, combined_precision,
    effective_count_precision, instance_count, is_complete_retrieval, parse, summary_row,
)
from ..normalise.provenance import Provenance, label_random_sample
from ..normalise.variants import deduplicate, flatten_variant, instance_id_anomalies
from ..query.classes import VariantClass
from ..query.filters import build_alphanumeric_filter, build_ontology_filter, years_to_iso8601
from ..query.model import CustomFilter, Query
from ..query.planner import (
    CoalescedGroup, ExecutionPlan, QueryUsageError, evidence_from_result, plan,
    verify_coalescence,
)
from ..query.retrieve import retrieve
from ..registry.evidence import suggestion_from_run
from ..registry.loader import resolve
from ..transport.http import (
    AuthRequired, BeaconClient, BeaconHttpError, FixtureClient,
    FixtureProviderEscaped, ProviderBlocked, ProviderUnavailable,
)

def join_notes(notes) -> str:
    """Join contract notes into one cell without doubled punctuation."""
    parts = [str(n).strip().rstrip(".") for n in notes if n and str(n).strip()]
    return ("; ".join(parts) + ".") if parts else ""


from .. import __version__

#: Derived from the package version so the two cannot drift.
USER_AGENT = f"GalaxyBeacon2/{__version__} (+https://github.com/galaxyproject/tools-iuc)"

#: Failures that become an outcome row. Deliberately narrow: a KeyError or
#: ValueError from our own code is a BUG and must not be dressed up as a
#: provider error.
PROVIDER_FAILURES = (BeaconHttpError, CredentialMissing, EntityTypeMismatch,
                     MalformedEnvelope)


# --------------------------------------------------------------------------
# Argument groups
# --------------------------------------------------------------------------

def add_provider_args(parser: argparse.ArgumentParser) -> None:
    """``--providers`` (comma-separated ids), ``--registry``, ``--provider-table``."""
    group = parser.add_argument_group("providers")
    group.add_argument("--providers", default="",
                       help="comma-separated provider ids from the registry")
    group.add_argument("--registry", type=Path, default=None,
                       help="an alternative beacon_registry.yaml (admin override)")
    group.add_argument("--provider-table", type=Path, default=None,
                       help="rows in beacon_providers.loc format; their base_url and "
                            "enabled columns override the registry")
    group.add_argument("--transport", choices=("api", "mongodb"), default="api")
    group.add_argument("--db-host", default="127.0.0.1")
    group.add_argument("--db-port", type=int, default=27017)
    group.add_argument("--database", default="beacon")
    group.add_argument("--collection", default="")


def add_credential_args(parser: argparse.ArgumentParser) -> None:
    """``--credentials-file``: a PATH, never a value.

    A token passed as a command-line argument would be recorded in the job's
    command line and can surface in job details and error reports.
    """
    parser.add_argument("--credentials-file", type=Path, default=None)


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    """Repeatable ``--filter``, in the forms the tool XML emits:

        <CURIE>                         a bare ontology id, e.g. NCIT:C3058
        ontology:<CURIE>:descendants=true|false:similarity=<s>[:scope=<e>]
        alphanumeric:<id>:<operator>:<value>:age=true|false[:scope=<e>]
        custom:<id>[:scope=<e>]

    Ages arrive in years and are converted to ISO 8601 before transmission.
    """
    parser.add_argument("--filter", action="append", default=[], dest="filters")


def add_granularity_args(parser: argparse.ArgumentParser) -> None:
    """``--granularity``, always sent explicitly: the framework default is boolean."""
    parser.add_argument("--granularity", choices=("record", "count", "boolean"),
                        default="record")


def add_pagination_args(parser: argparse.ArgumentParser) -> None:
    """``--skip`` (PAGES, not records), ``--limit``, and the ``--sample`` opt-in."""
    parser.add_argument("--skip", type=int, default=0, help="PAGES to skip, not records")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--sample", type=int, default=None, metavar="N",
        help="opt into a random sample of N from providers whose pages are random "
             "draws, instead of complete-or-refuse; results are labelled as a sample",
    )


def add_output_args(parser: argparse.ArgumentParser) -> None:
    """``--results`` and ``--outcomes``. Both are always written."""
    parser.add_argument("--results", type=Path, default=Path("results.tsv"))
    parser.add_argument("--outcomes", type=Path, default=Path("outcomes.tsv"))


def add_reference_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reference-name", default=None)
    parser.add_argument("--assembly", default="GRCh38")


def add_class_args(parser: argparse.ArgumentParser, default: str) -> None:
    """``--variant-classes`` (alias ``--variant-class``) and per-class terms."""
    parser.add_argument(
        "--variant-classes", "--variant-class", dest="variant_classes", default=default,
        help="comma-separated: CNV, SMALL_VARIANT (alias SNV), SV, REPEAT",
    )
    parser.add_argument("--class-term", action="append", default=[], dest="class_terms",
                        metavar="CLASS=TERM")
    parser.add_argument(
        "--variant-type", default=None,
        help="a variant type applied to every class's query, e.g. DEL; --class-term "
             "overrides it for one class")
    parser.add_argument("--expand-hierarchy", choices=("auto", "always", "never"),
                        default="auto")
    parser.add_argument("--no-coalescing", action="store_true")


def add_variant_scoping_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--reference-bases", default=None)
    parser.add_argument("--alternate-bases", default=None)
    parser.add_argument("--aminoacid-change", default=None)
    parser.add_argument("--variant-min-length", type=int, default=None)
    parser.add_argument("--variant-max-length", type=int, default=None)
    parser.add_argument(
        "--biosample-ids", default=None, metavar="ID,ID,...",
        help="MongoDB transport only: restrict to variants observed in these biosamples")


def add_field_args(parser: argparse.ArgumentParser) -> None:
    """``--field PATH=VALUE``: exact match on a document field, MongoDB only.

    Deliberately separate from ``--filter`` in code, help and errors. A filter
    is an ontology term that a beacon SERVER maps onto its fields; a raw
    collection has no such mapping, so filters are refused on MongoDB. A field
    is the field itself, which MongoDB matches natively -- and which Beacon v2
    has no parameter for, so fields are refused on the API.
    """
    parser.add_argument(
        "--field", action="append", default=[], dest="fields", metavar="PATH=VALUE",
        help="MongoDB transport only: exact match on a document path, e.g. "
             "tumorGrade.label=G2. Repeatable. Not an ontology filter -- see --filter.",
    )


def refuse_fields_on_api(args: argparse.Namespace) -> None:
    """Fields and biosample-id lists have no Beacon v2 request parameter."""
    if getattr(args, "transport", "api") != "api":
        return
    if getattr(args, "fields", None):
        raise QueryUsageError(
            "--field is supported only on the direct MongoDB transport: the Beacon v2 "
            "API has no field-equality parameter. To narrow an API query, use --filter "
            "with an ontology term, e.g. --filter ontology:NCIT:C3058:descendants=true")
    if getattr(args, "biosample_ids", None):
        raise QueryUsageError(
            "--biosample-ids is supported only on the direct MongoDB transport. On the "
            "API, retrieve one biosample's variants with: beacon2-query entity --entity "
            "biosample --entity-id ID --nested-entity genomicVariant")


def add_common_query_args(parser: argparse.ArgumentParser) -> None:
    add_field_args(parser)
    add_provider_args(parser)
    add_credential_args(parser)
    add_filter_args(parser)
    add_granularity_args(parser)
    add_pagination_args(parser)
    add_output_args(parser)


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

FILTER_KINDS = ("ontology", "alphanumeric", "custom")


def _filter_kind(spec: str) -> tuple[str, str]:
    """Split a --filter spec into (kind, rest), defaulting to an ontology term.

    A bare ontology id -- `--filter NCIT:C3058` -- is by far the commonest
    filter, so a spec without a recognised kind is read as one. Where that
    reading cannot be right, the error says what was probably meant.
    """
    from ..query.filters import VALID_OPERATORS

    kind, _, rest = spec.partition(":")
    if kind in FILTER_KINDS:
        return kind, rest
    if ":" not in spec:
        raise QueryUsageError(
            f"filter {spec!r} is not an ontology term id, which has the form PREFIX:ID. "
            f"Did you mean something like ontology:NCIT:{spec}? Use the prefix of the "
            f"ontology the term comes from")
    if any(part in VALID_OPERATORS for part in spec.split(":")):
        raise QueryUsageError(
            f"filter {spec!r} contains a comparison operator, so it is not an ontology "
            f"term. Did you mean alphanumeric:{spec}?")
    return "ontology", spec


def parse_filters(specs: list[str]) -> tuple:
    out = []
    for spec in specs:
        kind, rest = _filter_kind(spec)
        options: dict[str, str] = {}
        positional: list[str] = []
        for part in rest.split(":"):
            key = part.split("=", 1)[0]
            if "=" in part and key in ("descendants", "similarity", "scope", "age"):
                options[key] = part.split("=", 1)[1]
            else:
                positional.append(part)
        scope = options.get("scope") or None
        if kind == "ontology":
            out.append(build_ontology_filter(
                ":".join(positional), options.get("descendants", "true") == "true",
                options.get("similarity") or None, scope))
        elif kind == "alphanumeric":
            if len(positional) < 4:
                raise QueryUsageError(f"malformed alphanumeric filter {spec!r}")
            field_id, operator = ":".join(positional[:2]), positional[2]
            value = ":".join(positional[3:])
            if options.get("age") == "true":
                value = years_to_iso8601(float(value))
            out.append(build_alphanumeric_filter(field_id, operator, value, scope))
        elif kind == "custom":
            out.append(CustomFilter(id=":".join(positional), scope=scope))
        else:
            raise QueryUsageError(f"unknown filter kind {kind!r} in {spec!r}")
    return tuple(out)


def parse_classes(value: str) -> list[VariantClass]:
    return [VariantClass.from_cli(v) for v in str(value).split(",") if v.strip()]


def parse_class_terms(specs: list[str]) -> dict[VariantClass, str]:
    terms: dict[VariantClass, str] = {}
    for spec in specs:
        klass, sep, term = spec.partition("=")
        if not sep:
            raise QueryUsageError(f"--class-term must be CLASS=TERM, got {spec!r}")
        terms[VariantClass.from_cli(klass)] = term
    return terms


def specialise(base: Query, klass: VariantClass, args: argparse.Namespace,
               scoped_small_variant: bool) -> Query:
    """Build the Query for one class.

    Class terms apply to their own class only. Reference and alternate bases
    depend on the tool: in the sequence tool they ARE the query, so they apply
    to every class and make a copy-number class incoherent -- a skip for that
    pair. In the range and bracket tools they sit in the SNV / small indel
    section, so they apply to that class's query and nowhere else.
    """
    terms = parse_class_terms(getattr(args, "class_terms", []))
    query = replace(base.for_class(klass), variant_type=terms.get(klass, base.variant_type))
    if scoped_small_variant and klass is not VariantClass.SMALL_VARIANT:
        query = replace(query, reference_bases=None, alternate_bases=None,
                        aminoacid_change=None)
    return query


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

def make_client(provider, credentials):
    """A FixtureClient for file:// base URLs, otherwise a real BeaconClient."""
    url = str(provider.base_url or "")
    if url.startswith("file://"):
        return FixtureClient(url[len("file://"):])
    return BeaconClient(url, USER_AGENT, provider.rate_limit_per_minute,
                        credential_for(provider, credentials), provider=provider)


def failure_outcome(provider, klass, class_status, exc, credentials) -> Outcome:
    """Map a provider-level failure onto its status and an actionable note."""
    if isinstance(exc, CredentialMissing):
        status, note = Status.AUTH_MISSING, str(exc)
    elif isinstance(exc, ProviderBlocked):
        status, note = Status.BLOCKED, note_for("provider_blocked", name=provider.name)
    elif isinstance(exc, ProviderUnavailable):
        status, note = Status.UNAVAILABLE, note_for(
            "provider_unavailable", name=provider.name, detail=str(exc))
    elif isinstance(exc, AuthRequired):
        status = Status.ERROR if provider.credential_key else Status.AUTH_MISSING
        note = f"{provider.name} refused the request as unauthorised"
    elif isinstance(exc, EntityTypeMismatch):
        status, note = Status.ERROR, note_for(
            "entity_type_mismatch", name=provider.name,
            returned=exc.returned, requested=exc.requested)
    else:
        status, note = Status.ERROR, f"{type(exc).__name__}: {exc}"
    return Outcome(provider.id, provider.name, klass, class_status, status,
                   notes=redact(note, credentials))


def variant_rows(records, provider, envelope, pinned_class, degradations,
                 sample: tuple[int, int | None] | None = None) -> list[dict[str, Any]]:
    """Flatten variant records into provenance-carrying rows.

    With ``pinned_class`` the class came from the query; a record whose content
    says otherwise keeps the pinned class and says so in its basis. Without it
    -- a coalesced or nested lookup -- each record is filed by its own content.
    """
    precision, basis = effective_count_precision(envelope)
    notes = "; ".join(d.render() for d in degradations)
    expansion = "; ".join(d.render() for d in degradations if "expan" in d.kind.value)
    rows = []
    for record in records:
        content_class, evidence = classify(record)
        if pinned_class is not None:
            row_class = pinned_class.value
            if content_class in (pinned_class, VariantClass.UNCLASSIFIED):
                row_basis = f"pinned by query; {evidence}"
            else:
                row_basis = (f"pinned by query ({pinned_class.value}); record content "
                             f"indicates {content_class.value}: {evidence}")
        else:
            row_class, row_basis = content_class.value, evidence
        provenance = Provenance(
            beacon_id=provider.id, beacon_name=provider.name,
            access_tier=provider.tier.value, variant_class=row_class,
            classification_basis=row_basis,
            granularity_returned=str(envelope.returned_granularity or ""),
            count_precision=precision, count_precision_basis=basis,
            query_degraded=bool(degradations), degradation_notes=notes,
            expansion_notes=expansion,
        )
        if sample is not None:
            provenance = label_random_sample(provenance, *sample)
        for row in flatten_variant(record):
            rows.append({**provenance.as_columns(), **row})
    return rows


def summary_rows(provider, envelope, klass) -> list[dict[str, Any]]:
    precision, basis = effective_count_precision(envelope)
    provenance = Provenance(provider.id, provider.name, provider.tier.value,
                            klass.value if klass else "n/a", "pinned by query",
                            str(envelope.returned_granularity or ""), precision, basis)
    return [{**provenance.as_columns(), **summary_row(envelope)}]


def execute_query(query: Query, provider, adapter, client, sample_size):
    """One Query: complete-or-refuse where pages are random, a single call otherwise.

    Returns ``(envelope, records, retrieval_result_or_None)``.
    """
    if query.requested_granularity != "record":
        path = adapter.entity_path(query.entity, query.entity_id, query.nested_entity)
        envelope = parse(client.post(path, adapter.build_post_body(query)).body)
        return envelope, [], None
    result = retrieve(query, provider, adapter, client, sample_size)
    return result.envelope, result.records, result


def class_notes(execution: ExecutionPlan, n_rows: int, provider) -> list[str]:
    """The evidence-loop notes for an unverified class, and the YAML fragment."""
    notes: list[str] = []
    klass = execution.variant_class
    if not execution.class_unverified or klass is None:
        return notes
    if evidence_from_result(execution, n_rows):
        notes.append(note_for("class_unverified_hit", klass=klass.value))
        suggestion = suggestion_from_run(provider.id, klass, provider.class_support(klass),
                                         n_rows, datetime.date.today().isoformat())
        if suggestion is not None:
            print(suggestion.as_yaml_fragment(), file=sys.stderr)
    elif n_rows == 0:
        notes.append(note_for("class_unverified_zero", klass=klass.value))
    return notes


def run_pair(execution: ExecutionPlan, args, credentials, results, recorder,
             coalesced: str = "no", extra_notes: tuple[str, ...] = ()) -> None:
    """Execute one (provider, class) pair and record exactly one outcome."""
    provider, klass = execution.provider, execution.variant_class
    adapter = adapter_for(provider)
    requested = execution.queries[0].requested_granularity
    try:
        client = make_client(provider, credentials)
        rows: list[dict[str, Any]] = []
        notes: list[str] = [d.render() for d in execution.degradations] + list(extra_notes)
        envelope = None
        envelopes = []
        sampled = False
        for query in execution.queries:
            envelope, records, result = execute_query(query, provider, adapter, client,
                                                      getattr(args, "sample", None))
            envelopes.append(envelope)
            if result is not None and result.refusal:
                recorder.record(Outcome(
                    provider.id, provider.name, klass, execution.class_status,
                    Status.SKIPPED, granularity_requested=requested, coalesced=coalesced,
                    notes=note_for("retrieval_refused", reason=result.refusal)))
                return
            notes += assert_entity_type(envelope, adapter.requested_entity_type(query))
            if requested != "record":
                rows += summary_rows(provider, envelope, klass)
                continue
            sample = None
            if result is not None and result.random_sample:
                sampled = True
                sample = (instance_count(records), envelope.num_total_results)
                notes.append(note_for("random_sample", retrieved=sample[0],
                                      total=sample[1]))
            rows += variant_rows(records, provider, envelope, klass,
                                 execution.degradations, sample)

        rows, removed = deduplicate(rows)
        if removed:
            notes.append(f"{removed} duplicate observations removed")
        notes += instance_id_anomalies(rows)
        notes += class_notes(execution, len(rows) if requested == "record" else 0, provider)
        if provider.data_notes and "ynthetic" in provider.data_notes:
            notes.append(note_for("synthetic_data"))
        # EVERY query's envelope, never just the last one's.
        precision, basis, shortfalls = combined_precision(envelopes)
        if shortfalls:
            notes.append(note_for("partial_retrieval", shortfall=", ".join(
                f"{got} of {total}" for got, total in shortfalls)))
        results.extend(rows)
        recorder.record(Outcome(
            provider.id, provider.name, klass, execution.class_status, Status.OK,
            row_count=len(rows), granularity_requested=requested,
            granularity_returned=str(envelope.returned_granularity or ""),
            count_precision=precision, count_precision_basis=basis,
            query_degraded=bool(execution.degradations) or sampled, coalesced=coalesced,
            notes=redact(join_notes(notes), credentials)))
    except FixtureProviderEscaped:
        raise
    except PROVIDER_FAILURES as exc:
        recorder.record(failure_outcome(provider, klass, execution.class_status, exc,
                                        credentials))


def run_group(group: CoalescedGroup, args, credentials, results, recorder) -> None:
    """Issue a coalesced request once; split it by class only if provably complete.

    Falls back to separate per-class requests whenever the verdict does not
    hold. A weaker, "not exhaustive" cell is never emitted.
    """
    provider = group.provider
    representative = group.representative
    query = representative.queries[0]
    adapter = adapter_for(provider)
    try:
        client = make_client(provider, credentials)
        envelope, records, result = execute_query(query, provider, adapter, client,
                                                  getattr(args, "sample", None))
    except FixtureProviderEscaped:
        raise
    except PROVIDER_FAILURES as exc:
        for member in group.members:
            recorder.record(failure_outcome(provider, member.variant_class,
                                            member.class_status, exc, credentials))
        return
    if result is not None and result.refusal:
        for member in group.members:
            recorder.record(Outcome(
                provider.id, provider.name, member.variant_class, member.class_status,
                Status.SKIPPED, coalesced="yes",
                notes=note_for("retrieval_refused", reason=result.refusal)))
        return

    verdict = verify_coalescence(envelope, query.pagination.limit)
    usable = (verdict.holds and query.requested_granularity == "record"
              and not (result is not None and result.random_sample))
    if not usable:
        for member in group.members:
            run_pair(member, args, credentials, results, recorder, coalesced="fallback",
                     extra_notes=(note_for("coalesced_fallback", reason=verdict.reason),))
        return

    entity_notes = assert_entity_type(envelope, adapter.requested_entity_type(query))
    rows = variant_rows(records, provider, envelope, None, representative.degradations)
    rows, _ = deduplicate(rows)
    member_classes = {m.variant_class.value for m in group.members}
    unclassified = [r for r in rows if r["variant_class"] not in member_classes]
    results.extend(rows)
    precision, basis = effective_count_precision(envelope)
    for member in group.members:
        mine = [r for r in rows if r["variant_class"] == member.variant_class.value]
        notes = [note_for("coalesced_complete")] + entity_notes
        if unclassified:
            notes.append(f"{len(unclassified)} returned records could not be filed under "
                         f"any requested class and are labelled unclassified")
        notes += class_notes(member, len(mine), provider)
        recorder.record(Outcome(
            provider.id, provider.name, member.variant_class, member.class_status,
            Status.OK, row_count=len(mine), granularity_requested="record",
            granularity_returned=str(envelope.returned_granularity or ""),
            count_precision=precision, count_precision_basis=basis, coalesced="yes",
            notes=redact(join_notes(notes), credentials)))


def run_query(args: argparse.Namespace, base: Query, classes: list[VariantClass],
              scoped_small_variant: bool) -> int:
    """Plan, execute, normalise and write the two outputs.

    Returns a process exit code. A provider-level failure is NOT a job failure:
    it becomes a row in outcomes.tsv.
    """
    credentials = load_credentials(args.credentials_file)
    ids = [p.strip() for p in str(args.providers).split(",") if p.strip()]
    if not ids:
        raise QueryUsageError("no providers selected (--providers)")
    if not classes:
        raise QueryUsageError("no variant classes selected (--variant-classes)")
    providers, unresolvable = resolve(ids, args.provider_table, args.registry)
    queries = [specialise(base, k, args, scoped_small_variant) for k in classes]
    planned = plan(queries, providers,
                   allow_degradation=not getattr(args, "no_degradation", False),
                   allow_coalescing=not getattr(args, "no_coalescing", False))

    pairs = [(pid, k) for pid, _ in unresolvable for k in classes] + list(planned.pairs())
    recorder = OutcomeRecorder(pairs)
    for provider_id, reason in unresolvable:
        for klass in classes:
            recorder.record(Outcome(provider_id, provider_id, klass, "", Status.SKIPPED,
                                    notes=reason))
    by_id = {p.id: p for p in providers}
    for skip in planned.skips:
        provider = by_id[skip.provider_id]
        recorder.record(Outcome(
            skip.provider_id, provider.name, skip.variant_class,
            provider.class_support(skip.variant_class).status.value,
            Status.SKIPPED, notes=skip.message))

    results: list[dict[str, Any]] = []
    grouped = {id(m) for g in planned.coalesced for m in g.members}
    for group in planned.coalesced:
        run_group(group, args, credentials, results, recorder)
    for execution in planned.plans:
        if id(execution) not in grouped:
            run_pair(execution, args, credentials, results, recorder)

    write_outputs(results, recorder, args.results, args.outcomes, base.entity)
    return 0


def write_outputs(rows, recorder, results_path: Path, outcomes_path: Path,
                  entity: str) -> None:
    """Write results.tsv and outcomes.tsv, in that order, always both."""
    results_format.write(rows, results_path, entity)
    recorder.write(outcomes_path)


def run_main(handler, args: argparse.Namespace) -> int:
    """Shared exit-code handling: a usage error is fatal, with a clean message."""
    try:
        refuse_fields_on_api(args)
        return handler(args)
    except QueryUsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def run_mongo(args: argparse.Namespace, base: Query, classes: list[VariantClass]) -> int:
    """The direct-MongoDB transport: one self-hosted source.

    Filters are refused, not dropped -- see transport/mongo.py. One outcome row
    per class, attributed to the pseudo-provider `local.mongodb`.
    """
    from ..query.coordinates import to_refseq_accession
    from ..transport.mongo import (COLLECTIONS, MongoFiltersUnsupported, MongoTransport,
                                   filter_for, parse_fields)

    if base.filters:
        raise QueryUsageError(
            "filters are not supported on the direct MongoDB transport: a raw "
            "collection has no filtering-term mapping, and a dropped filter would "
            "return unfiltered results")
    credentials = load_credentials(args.credentials_file)
    entity = base.nested_entity or base.entity
    transport = MongoTransport.from_credentials(
        args.db_host, args.db_port, args.database,
        args.collection or COLLECTIONS.get(entity, entity), credentials)
    recorder = OutcomeRecorder([("local.mongodb", k) for k in classes])
    rows: list[dict[str, Any]] = []
    for klass in classes:
        query = specialise(base, klass, args, scoped_small_variant=True)
        reference = (to_refseq_accession(query.reference_name, query.assembly or "GRCh38")
                     if query.reference_name else None)
        ids = [i.strip() for i in str(args.biosample_ids or "").split(",") if i.strip()]
        try:
            documents = transport.find(
                filter_for(query, reference, parse_fields(args.fields), ids), args.limit)
        except MongoFiltersUnsupported as exc:
            raise QueryUsageError(str(exc)) from exc
        provenance = Provenance("local.mongodb", "Self-hosted MongoDB", "controlled",
                                klass.value, "pinned by query", "record")
        mine = [{**provenance.as_columns(), **row}
                for doc in documents for row in flatten_variant(doc)]
        rows += mine
        recorder.record(Outcome("local.mongodb", "Self-hosted MongoDB", klass, "",
                                Status.OK, row_count=len(mine),
                                granularity_requested="record",
                                granularity_returned="record"))
    write_outputs(rows, recorder, args.results, args.outcomes, entity)
    return 0
