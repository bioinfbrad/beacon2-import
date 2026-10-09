"""Entry point for beacon2_service_info -- discovery AND registry drift detection.

Probes the informational endpoints and DIFFS what each server reports against
what beacon_registry.yaml claims. Output: one row per provider per checked
field, with ``declared``, ``observed`` and ``agrees``, so drift is data, not
prose.

STRUCTURALLY READ-ONLY. This module reports; it never writes the registry and
imports nothing that can. In particular it cannot write a variant class `no`:
the informational endpoints carry no content signal, and only an operator
declaration may ever write `no`.

`/map` is the normative endpoint name; `/beaconMap` is requested only as a
fallback when `/map` is missing.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..adapters.base import adapter_for
from ..auth.resolver import load_credentials, redact
from ..formats.outcomes import Outcome, OutcomeRecorder, Status
from ..registry.loader import resolve
from ..transport.http import BeaconHttpError, FixtureMiss
from . import common

COLUMNS = ("beacon_id", "field", "declared", "observed", "agrees", "endpoint", "note")


def _get(client, path: str, failures: list | None = None) -> dict[str, Any] | None:
    """One informational endpoint. A failure is tolerated here -- /map may be
    missing where /beaconMap is not -- but recorded, so that a provider where
    NOTHING answered is reported as failing rather than as healthy."""
    try:
        return client.get(path).body
    except (FixtureMiss, BeaconHttpError) as exc:
        if failures is not None:
            failures.append(exc)
        return None


def _probe(provider, client, adapter) -> list[tuple[str, ...]]:
    paths = adapter.informational_paths()
    rows: list[tuple[str, ...]] = []
    failures: list[Exception] = []
    asked = 0

    def get(path):
        nonlocal asked
        asked += 1
        return _get(client, path, failures)

    def row(field, declared, observed, endpoint, note=""):
        agrees = ("" if observed in (None, "") or declared in (None, "")
                  else str(str(declared) == str(observed)).lower())
        rows.append((provider.id, field, "" if declared is None else str(declared),
                     "" if observed is None else str(observed), agrees, endpoint, note))

    info = get(paths["info"]) or get(paths["root"]) or {}
    meta = info.get("meta") or {}
    response = info.get("response") or {}
    row("beacon_id_reported", provider.beacon_id_reported,
        meta.get("beaconId") or response.get("id"), paths["info"],
        "meta.beaconId and response.id may legitimately differ")
    row("api_version_reported", provider.api_version_reported, meta.get("apiVersion"),
        paths["info"], "compared verbatim, never as semver")

    configuration = (get(paths["configuration"]) or {}).get("response") or {}
    maturity = (configuration.get("maturityAttributes") or {}).get("productionStatus")
    row("production_status", None, maturity, paths["configuration"],
        "DEV or TEST data should not be reported as findings")
    security = configuration.get("securityAttributes") or {}
    row("default_granularity", None, security.get("defaultGranularity"),
        paths["configuration"])
    levels = security.get("securityLevels")
    row("security_levels", provider.tier.value.upper(),
        ",".join(levels) if isinstance(levels, list) else levels, paths["configuration"])

    entry_types = (get(paths["entry_types"]) or {}).get("response") or {}
    observed_types = sorted((entry_types.get("entryTypes") or {}).keys())
    row("entry_types", None, ",".join(observed_types), paths["entry_types"],
        "says nothing about which variant classes are held")

    beacon_map = get(paths["map"])
    endpoint = paths["map"]
    if beacon_map is None:
        beacon_map, endpoint = get(paths["map_fallback"]), paths["map_fallback"]
    sets = ((beacon_map or {}).get("response") or {}).get("endpointSets") or {}
    row("map_endpoint_sets", None, ",".join(sorted(sets)), endpoint,
        "" if beacon_map else "neither /map nor /beaconMap answered")
    if failures and len(failures) == asked:
        # Every endpoint failed: this provider answered nothing at all.
        raise failures[0]
    return rows


def add_arguments(parser: argparse.ArgumentParser) -> None:
    common.add_provider_args(parser)
    common.add_credential_args(parser)
    parser.add_argument("--report", type=Path, default=Path("service_info.tsv"))
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
        lines = ["\t".join(COLUMNS)]
        for provider in providers:
            try:
                client = common.make_client(provider, credentials)
                rows = _probe(provider, client, adapter_for(provider))
            except common.FixtureProviderEscaped:
                raise
            except common.PROVIDER_FAILURES as exc:
                recorder.record(common.failure_outcome(provider, None, "", exc, credentials))
                continue
            lines += ["\t".join(v.replace("\t", " ") for v in r) for r in rows]
            drift = [r[1] for r in rows if r[4] == "false"]
            recorder.record(Outcome(
                provider.id, provider.name, None, "", Status.OK, row_count=len(rows),
                notes=redact(("drift in: " + ", ".join(drift)) if drift else "", credentials)))
        Path(args.report).write_text("\n".join(lines) + "\n")
        recorder.write(args.outcomes)
        return 0
    return common.run_main(handler, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beacon2-query service-info")
    add_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Probe the informational endpoints and report registry drift."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
