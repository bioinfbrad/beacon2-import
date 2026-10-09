"""The `beacon2-query` command: one entry point, one subcommand per tool family.

The tool XMLs call `beacon2-query <subcommand>`; tests/test_cli_surface.py
fails if any XML calls a subcommand or flag this parser does not expose.
"""

from __future__ import annotations

import argparse

from ..commands import IntroducedParser
from . import (filtering_terms, query_bracket, query_cnv, query_entity, query_gene,
               query_range, query_sequence, service_info)

#: subcommand -> module. PR 1 surface only; the analysis commands are PR 2.
SUBCOMMANDS = {
    "range": query_range,
    "bracket": query_bracket,
    "sequence": query_sequence,
    "gene": query_gene,
    "cnv": query_cnv,
    "entity": query_entity,
    "service-info": service_info,
    "filtering-terms": filtering_terms,
}


def build_parser() -> argparse.ArgumentParser:
    parser = IntroducedParser(command="beacon2-query",
        prog="beacon2-query",
        description="Query GA4GH Beacon v2 providers; results.tsv plus a per-provider "
                    "outcomes.tsv run report.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="SUBCOMMAND",
                                parser_class=argparse.ArgumentParser)
    for name, module in SUBCOMMANDS.items():
        module.add_arguments(sub.add_parser(name, help=(module.__doc__ or "").split("\n")[0]))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return SUBCOMMANDS[args.command].run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
