"""Shared entry point for the six entry-type tools.

beacon2_biosamples, beacon2_individuals, beacon2_cohorts, beacon2_datasets,
beacon2_runs and beacon2_analyses differ only in the entity path and the
response schema, so they share this module and select via ``--entity``. They
remain SIX separate Galaxy tools with their own labels, help and tests.

NESTED VARIANT LOOKUPS (``/biosamples/{id}/g_variants``)
    One request per provider: the nested path takes no class parameter, so
    there is nothing to send per class. Records are filed by their own content.
    When classes are selected, each (provider, class) pair gets its own outcome
    row -- but ONLY if the response is provably complete and exact. Otherwise
    the per-class counts are refused rather than reported, because a partial
    response split by class is precisely the weaker, "not exhaustive" cell the
    design rules out, and a nested lookup cannot be re-asked per class.
"""

from __future__ import annotations

import argparse
from typing import Any

from ..adapters.base import adapter_for
from ..auth.resolver import load_credentials, redact
from ..formats.outcomes import Outcome, OutcomeRecorder, Status, note_for
from ..normalise.entities import FLATTENERS
from ..normalise.envelope import (
    assert_entity_type, effective_count_precision, is_complete_retrieval,
)
from ..normalise.provenance import Provenance
from ..normalise.variants import deduplicate
from ..query.model import Pagination, Query, QueryForm
from ..registry.loader import resolve
from . import common

ENTITIES = ("biosample", "individual", "cohort", "dataset", "run", "analysis")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """``--entity``, optional single-record and nested lookups, and shared args."""
    common.add_common_query_args(parser)
    parser.add_argument("--entity", choices=ENTITIES, required=True)
    parser.add_argument("--entity-id", default=None)
    parser.add_argument("--nested-entity", default=None,
                        choices=("genomicVariant", "analysis", "biosample", "individual",
                                 "run"))
    parser.add_argument("--variant-classes", "--variant-class", dest="variant_classes",
                        default="", help="only for a nested variant lookup")


def build_query(args: argparse.Namespace) -> Query:
    return Query(
        form=QueryForm.ENTITY, variant_class=None, entity=args.entity,
        entity_id=args.entity_id, nested_entity=args.nested_entity,
        filters=common.parse_filters(args.filters),
        requested_granularity=args.granularity,
        pagination=Pagination(skip=args.skip, limit=args.limit),
    )


def _run_entities(args, base: Query) -> int:
    credentials = load_credentials(args.credentials_file)
    ids = [p.strip() for p in str(args.providers).split(",") if p.strip()]
    if not ids:
        raise common.QueryUsageError("no providers selected (--providers)")
    nested_variants = base.nested_entity == "genomicVariant"
    classes = common.parse_classes(args.variant_classes) if nested_variants else []
    keys = [(p, k) for p in ids for k in classes] if classes else [(p, None) for p in ids]
    recorder = OutcomeRecorder(keys)
    providers, unresolvable = resolve(ids, args.provider_table, args.registry)
    for provider_id, reason in unresolvable:
        for _, klass in [k for k in keys if k[0] == provider_id]:
            recorder.record(Outcome(provider_id, provider_id, klass, "", Status.SKIPPED,
                                    notes=reason))
    output_entity = "genomicVariant" if nested_variants else (base.nested_entity or base.entity)
    rows: list[dict[str, Any]] = []
    for provider in providers:
        mine_keys = [k for k in keys if k[0] == provider.id]
        adapter = adapter_for(provider)
        try:
            client = common.make_client(provider, credentials)
            envelope, records, result = common.execute_query(
                base, provider, adapter, client, args.sample)
        except common.FixtureProviderEscaped:
            raise
        except common.PROVIDER_FAILURES as exc:
            for _, klass in mine_keys:
                recorder.record(common.failure_outcome(provider, klass, "", exc, credentials))
            continue
        if result is not None and result.refusal:
            for _, klass in mine_keys:
                recorder.record(Outcome(provider.id, provider.name, klass, "",
                                        Status.SKIPPED, notes=result.refusal))
            continue
        try:
            notes = assert_entity_type(envelope, adapter.requested_entity_type(base))
        except common.EntityTypeMismatch as exc:
            for _, klass in mine_keys:
                recorder.record(common.failure_outcome(provider, klass, "", exc, credentials))
            continue
        precision, basis = effective_count_precision(envelope)

        if base.requested_granularity != "record":
            batch = common.summary_rows(provider, envelope, None)
        elif nested_variants:
            batch, _ = deduplicate(common.variant_rows(records, provider, envelope, None, ()))
        else:
            flatten = FLATTENERS[base.nested_entity or base.entity]
            provenance = Provenance(provider.id, provider.name, provider.tier.value, "n/a",
                                    "not a variant query",
                                    str(envelope.returned_granularity or ""),
                                    precision, basis)
            batch = [{**provenance.as_columns(), **flatten(r)} for r in records]
        rows += batch
        common_fields = dict(granularity_requested=base.requested_granularity,
                             granularity_returned=str(envelope.returned_granularity or ""),
                             count_precision=precision, count_precision_basis=basis)

        if not classes:
            recorder.record(Outcome(provider.id, provider.name, None, "", Status.OK,
                                    row_count=len(batch), **common_fields,
                                    notes=redact(common.join_notes(notes), credentials)))
            continue
        provable = (is_complete_retrieval(records, envelope.num_total_results)
                    and precision == "exact")
        for _, klass in mine_keys:
            status = provider.class_support(klass).status.value
            if not provable:
                recorder.record(Outcome(
                    provider.id, provider.name, klass, status, Status.SKIPPED,
                    **common_fields,
                    notes=("per-class counts not reported: the lookup could not be shown "
                           "complete and exact, and a nested lookup cannot be re-asked per "
                           "class. All returned rows are in the results, each labelled by "
                           "its own content.")))
                continue
            count = sum(1 for r in batch if r["variant_class"] == klass.value)
            recorder.record(Outcome(provider.id, provider.name, klass, status, Status.OK,
                                    row_count=count, coalesced="yes", **common_fields,
                                    notes=note_for("coalesced_complete")))
    common.write_outputs(rows, recorder, args.results, args.outcomes, output_entity)
    return 0


def _run_entities_mongo(args, base: Query) -> int:
    """Entity records from a self-hosted collection, matched by id when given.

    Filters are refused, as for variant queries over MongoDB.
    """
    from ..transport.mongo import COLLECTIONS, MongoTransport

    if base.filters:
        raise common.QueryUsageError(
            "filters are not supported on the direct MongoDB transport")
    if base.nested_entity:
        raise common.QueryUsageError(
            "nested lookups are not supported on the direct MongoDB transport")
    transport = MongoTransport.from_credentials(
        args.db_host, args.db_port, args.database,
        args.collection or COLLECTIONS[base.entity], load_credentials(args.credentials_file))
    from ..transport.mongo import parse_fields

    clauses = parse_fields(args.fields)
    if base.entity_id:
        clauses["id"] = base.entity_id
    if not clauses:
        raise common.QueryUsageError(
            "give --entity-id or at least one --field: an unconstrained MongoDB entity "
            "query would return the whole collection")
    documents = transport.find(clauses, args.limit)
    provenance = Provenance("local.mongodb", "Self-hosted MongoDB", "controlled", "n/a",
                            "not a variant query", "record")
    flatten = FLATTENERS[base.entity]
    rows = [{**provenance.as_columns(), **flatten(d)} for d in documents]
    recorder = OutcomeRecorder([("local.mongodb", None)])
    recorder.record(Outcome("local.mongodb", "Self-hosted MongoDB", None, "", Status.OK,
                            row_count=len(rows), granularity_requested="record",
                            granularity_returned="record"))
    common.write_outputs(rows, recorder, args.results, args.outcomes, base.entity)
    return 0


def run(args: argparse.Namespace) -> int:
    def handler(args):
        base = build_query(args)
        if args.transport == "mongodb":
            return _run_entities_mongo(args, base)
        return _run_entities(args, base)
    return common.run_main(handler, args)


def build_parser() -> argparse.ArgumentParser:
    """Build the parser, including ``--entity`` and optional nested lookups."""
    parser = argparse.ArgumentParser(prog="beacon2-query entity")
    add_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Query one entry type across the selected providers."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
