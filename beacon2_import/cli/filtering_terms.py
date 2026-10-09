"""Entry point for beacon2_filtering_terms.

Lists available filters per provider, with optional prefix selection, plus a
merged view: every row carries ``shared_with``, the other providers offering
the same term, so one file answers both "what can I filter on here" and "what
can I filter on everywhere".

PREFIX SELECTION IS ALWAYS CLIENT-SIDE. Observed live: ``?filters=EFO`` is read
as a filter term whose id is literally EFO, matches nothing, and returns empty
arrays with no error. Sending the prefix to the server would return nothing
for a perfectly good prefix.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..adapters.base import adapter_for
from ..auth.resolver import load_credentials, redact
from ..formats.outcomes import Outcome, OutcomeRecorder, Status
from ..query.filters import filter_terms_by_prefix
from ..registry.loader import resolve
from . import common

COLUMNS = ("beacon_id", "term_id", "label", "type", "count", "prefix", "shared_with")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    common.add_provider_args(parser)
    common.add_credential_args(parser)
    parser.add_argument("--prefix", action="append", default=[], dest="prefixes",
                        help="keep only terms with this CURIE prefix; repeatable")
    parser.add_argument("--terms", type=Path, default=Path("filtering_terms.tsv"))
    parser.add_argument("--outcomes", type=Path, default=Path("outcomes.tsv"))


def run(args: argparse.Namespace) -> int:
    def handler(args):
        credentials = load_credentials(args.credentials_file)
        ids = [p.strip() for p in str(args.providers).split(",") if p.strip()]
        if not ids:
            raise common.QueryUsageError("no providers selected (--providers)")
        providers, unresolvable = resolve(ids, args.provider_table, args.registry)
        recorder = OutcomeRecorder([(p, None) for p in ids])
        for provider_id, reason in unresolvable:
            recorder.record(Outcome(provider_id, provider_id, None, "", Status.SKIPPED,
                                    notes=reason))
        collected: dict[str, list[dict]] = {}
        for provider in providers:
            adapter = adapter_for(provider)
            try:
                client = common.make_client(provider, credentials)
                params = (adapter.filtering_terms_params()
                          if hasattr(adapter, "filtering_terms_params") else {})
                body = client.get(adapter.informational_paths()["filtering_terms"],
                                  params or None).body
                terms = ((body or {}).get("response") or {}).get("filteringTerms") or []
                kept = filter_terms_by_prefix(terms, args.prefixes)
                collected[provider.id] = kept
                note = (f"{len(kept)} of {len(terms)} terms match prefix "
                        f"{','.join(args.prefixes)} (selected client-side)"
                        if args.prefixes else "")
                recorder.record(Outcome(provider.id, provider.name, None, "", Status.OK,
                                        row_count=len(kept), notes=note))
            except common.FixtureProviderEscaped:
                raise
            except common.PROVIDER_FAILURES as exc:
                recorder.record(common.failure_outcome(provider, None, "", exc, credentials))

        holders: dict[str, set[str]] = {}
        for beacon_id, terms in collected.items():
            for term in terms:
                holders.setdefault(str(term.get("id", "")), set()).add(beacon_id)
        lines = ["\t".join(COLUMNS)]
        for beacon_id, terms in collected.items():
            for term in terms:
                term_id = str(term.get("id", ""))
                others = sorted(holders.get(term_id, set()) - {beacon_id})
                values = (beacon_id, term_id, str(term.get("label", "")),
                          str(term.get("type", "")), str(term.get("count", "")),
                          term_id.split(":", 1)[0] if ":" in term_id else "",
                          ",".join(others))
                lines.append("\t".join(v.replace("\t", " ") for v in values))
        Path(args.terms).write_text("\n".join(lines) + "\n")
        recorder.write(args.outcomes)
        return 0
    return common.run_main(handler, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beacon2-query filtering-terms")
    add_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Fetch and merge filtering terms across providers."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
