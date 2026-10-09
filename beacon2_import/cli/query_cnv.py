"""Entry point for the beacon2_cnv Galaxy tool: copy number variants.

Restored as its own subcommand because a bracket query cannot express what the
2.2.4 cnv tool offered -- variantInternalId, analysisId, individualId, gene,
primarySite, diseaseType, variantStateId, variantState, sequenceId -- and the
GTN CNV tutorial is built on it.

MongoDB transport: the 2.2.4 `cnv` collection shape. Position by
``--reference-name``/``--start``/``--end``, type by ``--variant-type``, and the
other nine 2.2.4 fields by ``--field``. Start/end keep 2.2.4's CONTAINMENT
semantics (a CNV lies within the window), so tutorial results do not change.

API transport: a range query restricted to the CNV class, with CNV class terms
and ontology ``--filter``s. Beacon's range query is OVERLAP, so the same window
can return more on the API than on MongoDB; the tool help says so.
"""

from __future__ import annotations

import argparse

from ..formats.outcomes import Outcome, OutcomeRecorder, Status
from ..auth.resolver import load_credentials
from ..normalise.provenance import Provenance
from ..normalise.variants import flatten_variant
from ..normalise.verify import Region, verify_records
from ..query.classes import VariantClass
from ..query.coordinates import normalise_chromosome, one_based_to_interbase
from ..query.model import Pagination, Position, Query, QueryForm
from . import common


def add_arguments(parser: argparse.ArgumentParser) -> None:
    common.add_common_query_args(parser)
    common.add_reference_args(parser)
    common.add_class_args(parser, "CNV")
    parser.add_argument("--start", type=int, default=None, help="1-based")
    parser.add_argument("--end", type=int, default=None, help="1-based, inclusive")
    parser.add_argument(
        "--stored-coordinates", action="store_true",
        help="MongoDB transport only: take --start/--end exactly as stored in the "
             "documents, as the 2.2.4 cnv tool did, instead of as 1-based positions")


def _mongo(args: argparse.Namespace) -> int:
    from ..transport.mongo import MongoTransport, cnv_filter_for, parse_fields

    if args.filters:
        raise common.QueryUsageError(
            "--filter is not supported on the direct MongoDB transport; for a field "
            "match use --field PATH=VALUE")
    if not args.collection:
        raise common.QueryUsageError("--collection is required on the MongoDB transport")
    if args.stored_coordinates or args.start is None:
        start = args.start
    else:
        start = one_based_to_interbase(args.start)[0]
    clauses = cnv_filter_for(
        normalise_chromosome(args.reference_name) if args.reference_name else None,
        start, args.end, args.variant_type, parse_fields(args.fields))
    if not clauses:
        raise common.QueryUsageError(
            "give a position, --variant-type or at least one --field: an unconstrained "
            "query would return the whole collection")
    transport = MongoTransport.from_credentials(
        args.db_host, args.db_port, args.database, args.collection,
        load_credentials(args.credentials_file))
    documents = transport.find(clauses, args.limit)
    region = Region(normalise_chromosome(args.reference_name) if args.reference_name else None,
                    "containment", (start,), (args.end,))
    verification = verify_records(documents, [VariantClass.CNV], region,
                                  constrained=bool(args.variant_type))
    rows = []
    for item in verification.kept:
        provenance = Provenance("local.mongodb", "Self-hosted MongoDB", "controlled",
                                item.variant_class.value, item.basis, "record")
        rows += [{**provenance.as_columns(), **row} for row in flatten_variant(item.record)]
    recorder = OutcomeRecorder([("local.mongodb", VariantClass.CNV)])
    recorder.record(Outcome("local.mongodb", "Self-hosted MongoDB", VariantClass.CNV, "",
                            Status.OK, row_count=len(rows), granularity_requested="record",
                            granularity_returned="record",
                            notes=common.join_notes(["start/end matched as containment, as in 2.2.4"]
                                                    + verification.notes())))
    common.write_outputs(rows, recorder, args.results, args.outcomes, "genomicVariant")
    return 0


def _api(args: argparse.Namespace) -> int:
    if args.start is None or args.end is None or not args.reference_name:
        raise common.QueryUsageError(
            "the API transport needs --reference-name, --start and --end: a CNV query "
            "over Beacon v2 is a range query")
    start, end = one_based_to_interbase(args.start, args.end)
    base = Query(
        form=QueryForm.RANGE, variant_class=VariantClass.CNV,
        reference_name=args.reference_name, assembly=args.assembly,
        start=Position((start,)), end=Position((end,)), variant_type=args.variant_type,
        filters=common.parse_filters(args.filters), requested_granularity=args.granularity,
        pagination=Pagination(skip=args.skip, limit=args.limit),
        expand_hierarchy=args.expand_hierarchy,
    )
    return common.run_query(args, base, [VariantClass.CNV], scoped_small_variant=True)


def run(args: argparse.Namespace) -> int:
    return common.run_main(_mongo if args.transport == "mongodb" else _api, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beacon2-query cnv")
    add_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Query copy number variants across the selected providers."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
