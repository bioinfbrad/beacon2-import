"""Entry point for the beacon2_bracket Galaxy tool (bracket query form)."""

from __future__ import annotations

import argparse

from ..query.classes import VariantClass
from ..query.coordinates import one_based_to_interbase
from ..query.model import Pagination, Position, Query, QueryForm
from . import common

#: Classes selected when the tool sends none.
DEFAULT_CLASSES = "CNV"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The bracket query's arguments, plus everything every query tool shares."""
    common.add_common_query_args(parser)
    common.add_reference_args(parser)
    common.add_class_args(parser, DEFAULT_CLASSES)
    common.add_variant_scoping_args(parser)
    for flag in ("--start-min", "--start-max", "--end-min", "--end-max"):
        parser.add_argument(flag, type=int, required=True, help="1-based")
    parser.add_argument("--no-degradation", action="store_true",
                        help="skip beacons lacking bracket support instead of widening")


def build_query(args: argparse.Namespace) -> Query:
    """Turn 1-based user input into the 0-based Query the wire format uses."""
    start_min, _ = one_based_to_interbase(args.start_min)
    start_max, _ = one_based_to_interbase(args.start_max)
    return Query(
        form=QueryForm.BRACKET, variant_class=VariantClass.CNV,
        start=Position((start_min, start_max)), end=Position((args.end_min, args.end_max)),
        reference_name=args.reference_name, assembly=args.assembly,
        reference_bases=args.reference_bases, alternate_bases=args.alternate_bases,
        aminoacid_change=args.aminoacid_change,
        variant_min_length=args.variant_min_length,
        variant_max_length=args.variant_max_length,
        filters=common.parse_filters(args.filters),
        requested_granularity=args.granularity,
        pagination=Pagination(skip=args.skip, limit=args.limit),
        expand_hierarchy=args.expand_hierarchy,
        variant_type=args.variant_type,
    )


def run(args: argparse.Namespace) -> int:
    def handler(args):
        base = build_query(args)
        classes = common.parse_classes(args.variant_classes)
        if args.transport == "mongodb":
            return common.run_mongo(args, base, classes)
        return common.run_query(args, base, classes, scoped_small_variant=True)
    return common.run_main(handler, args)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the bracket query form."""
    parser = argparse.ArgumentParser(prog="beacon2-query bracket")
    add_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run a bracket query across the selected providers."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
