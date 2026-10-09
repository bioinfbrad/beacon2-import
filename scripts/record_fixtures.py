#!/usr/bin/env python3
"""Record the Galaxy tool tests' fixtures from the live providers. Development only.

Not part of the package and not exposed in Galaxy. Every Galaxy test is defined
once, in scripts/galaxy_tests.py, with its query as beacon2-query arguments;
this script runs those queries and saves each request -> response pair, keyed on
the request, into tools/beacon2-import/test-data/fixtures/<provider>/.

RECORD, DON'T CONSTRUCT. Constructed fixtures are how a random sample once
passed as an exact answer: a fixture built to fit the code cannot surprise it.
Only test.fixture.bracketless, synthetic by definition, is constructed.

Usage, from the repository root, with the package installed (pip install -e .):

    python3 scripts/record_fixtures.py --list         every test, and where its requests go
    python3 scripts/record_fixtures.py --record       live: Progenetix and cancercelllines
    python3 scripts/record_fixtures.py --construct    the synthetic bracketless provider
    python3 scripts/record_fixtures.py --check        replay every test from the fixtures and
                                                      evaluate its Galaxy assertions locally

`--record` needs a host the providers answer: the Python client reaches both
from an AWS container. (Progenetix's Cloudflare challenge stops curl, not this.)
`--only beacon2_range#1` restricts any mode to one test; repeatable.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import galaxy_tests as spec  # noqa: E402
from beacon2_import.cli import common  # noqa: E402
from beacon2_import.cli.main import main as beacon2_query  # noqa: E402
from beacon2_import.transport.http import (  # noqa: E402
    MANIFEST_FORMAT, Response, canonical_request,
)

TEST_DATA = ROOT / "tools" / "beacon2-import" / "test-data"
FIXTURES = TEST_DATA / "fixtures"
LIVE = (spec.PGX, spec.CCL)
SYNTHETIC = (spec.BRK,)
LARGE = 1_000_000  # bytes; tools-iuc test data should stay small


class Recorder:
    """Sits in front of a real client; keeps every request and its answer."""

    def __init__(self, provider, client, store, test_id):
        self.provider, self.client, self.store, self.test_id = provider, client, store, test_id

    def _keep(self, method, path, params, body, response):
        key = canonical_request(method, path, params, body)
        entry = self.store.setdefault(self.provider.id, {}).setdefault(
            json.dumps(key, sort_keys=True), {"request": key, "body": response.body, "tests": set()})
        entry["tests"].add(self.test_id)
        return response

    def post(self, path, body):
        return self._keep("POST", path, None, body, self.client.post(path, body))

    def get(self, path, params=None):
        return self._keep("GET", path, params, None, self.client.get(path, params))


class Synthetic:
    """The bracketless provider: CNVs inside whatever region is asked for.

    Answers like a random-subset provider -- `limit` records at most -- so
    complete-or-refuse runs its pre-flight and full retrieval against it.
    """

    TOTAL = 2

    def post(self, path, body):
        key = canonical_request("POST", path, None, body)["query"]
        start, end = key.get("start", [0])[0], key.get("end", [1000])[-1]
        limit = key.get("pagination", {}).get("limit", 0)
        count = self.TOTAL if limit in (0, None) or limit >= self.TOTAL else limit
        records = [{
            "variantInternalId": f"synthetic:17:{start + 100 + i}-{end - 100 - i}:EFO_0030067",
            "variation": {"variantState": {"id": "EFO:0030067", "label": "copy number loss"},
                          "location": {"chromosome": "17", "start": start + 100 + i,
                                       "end": end - 100 - i}},
            "caseLevelData": [{"biosampleId": f"synthetic-bs-{i}"}],
        } for i in range(count)]
        body = {"meta": {"apiVersion": "v2.0.0", "returnedGranularity": "record",
                         "returnedSchemas": [{"entityType": "genomicVariant"}],
                         "receivedRequestSummary": {"pagination": {"skip": 0, "limit": limit},
                                                    "testMode": False}},
                "responseSummary": {"exists": True, "numTotalResults": self.TOTAL},
                "response": {"resultSets": [{"id": "synthetic", "exists": True,
                                             "resultsCount": self.TOTAL, "results": records}]}}
        return Response(200, body, f"synthetic:{path}", "POST", 0.0)

    def get(self, path, params=None):  # pragma: no cover - no test sends a GET here
        raise RuntimeError("the synthetic provider answers no GET")


def _run(test, tmp: Path, extra=()) -> tuple[Path, Path, str]:
    names = {"results": "results.tsv", "outcomes": "outcomes.tsv", "terms": "terms.tsv",
             "report": "report.tsv"}
    flags = {"results": "--results", "outcomes": "--outcomes", "terms": "--terms", "report": "--report"}
    first, second = test.output_names
    argv = [*test.argv, *extra, flags[first], str(tmp / names[first]),
            flags[second], str(tmp / names[second])]
    beacon2_query(argv)
    return tmp / names[first], tmp / names[second], " ".join(test.argv)


def _selected(args) -> list:
    tests = [t for t in spec.TESTS if t.requests_to]
    return [t for t in tests if not args.only or t.id in args.only]


def write_fixtures(provider_id: str, entries: dict, origin: str, note: str) -> list[str]:
    """Replace one provider's fixture directory with these request -> response pairs."""
    directory = FIXTURES / provider_id
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    manifest, warnings = [], []
    for key, entry in sorted(entries.items()):
        name = "r-" + hashlib.sha256(key.encode()).hexdigest()[:12] + ".json"
        text = json.dumps(entry["body"], indent=1, sort_keys=True) + "\n"
        (directory / name).write_text(text)
        if len(text.encode()) > LARGE:
            warnings.append(f"{provider_id}/{name} is {len(text.encode()) // 1000} kB, for "
                            f"{sorted(entry['tests'])}: narrow that test's query")
        manifest.append({"request": entry["request"], "response": name, "origin": origin,
                         "note": f"{note}; used by {', '.join(sorted(entry['tests']))}"})
    (directory / "manifest.json").write_text(json.dumps(
        {"format": MANIFEST_FORMAT, "entries": manifest}, indent=1, sort_keys=True) + "\n")
    return warnings


def record(args, construct: bool) -> int:
    targets = SYNTHETIC if construct else LIVE
    store: dict = {}
    original = common.make_client
    current = {"test": None}

    def make_client(provider, credentials):
        if provider.id not in targets:
            raise RuntimeError(f"{provider.id} is not being {'constructed' if construct else 'recorded'} "
                               f"in this run")
        client = Synthetic() if construct else original(provider, credentials)
        return Recorder(provider, client, store, current["test"])

    common.make_client = make_client
    try:
        tests = [t for t in _selected(args) if set(t.requests_to) <= set(targets)]
        # The synthetic provider is disabled in the packaged registry and enabled
        # only by the test table, so construction reads that table too.
        extra = []
        if construct:
            table = Path(tempfile.mkdtemp()) / "providers.loc"
            table.write_text((TEST_DATA / "beacon_providers.loc").read_text()
                             .replace("${__HERE__}", str(TEST_DATA)))
            extra = ["--provider-table", str(table)]
        for test in tests:
            current["test"] = test.id
            with tempfile.TemporaryDirectory() as tmp:
                _, outcomes, _ = _run(test, Path(tmp), extra)
                for line in outcomes.read_text().splitlines()[1:]:
                    cells = line.split("\t")
                    print(f"  {test.id:26s} {cells[0]:24s} {cells[2]:14s} {cells[4]:8s} rows={cells[5]}")
    finally:
        # Restore the real factory: anything run later in this process must not
        # go through the recorder.
        common.make_client = original
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    warnings = []
    for provider_id, entries in store.items():
        if construct:
            note = "CONSTRUCTED: a synthetic provider by definition"
            origin = "constructed"
        else:
            from beacon2_import.registry.loader import load_registry

            note = f"recorded {stamp} from {load_registry()[provider_id].base_url}"
            origin = "recorded"
        warnings += write_fixtures(provider_id, entries, origin, note)
        print(f"wrote {len(entries)} request(s) for {provider_id}")
    for warning in warnings:
        print("WARNING:", warning)
    return 0


def _assertion_failures(test, files: dict[str, str]) -> list[str]:
    """Evaluate the test's own Galaxy assertions, with Galaxy's semantics."""
    failures = []
    for name, checks in zip(test.output_names, (test.results, test.outcomes)):
        content = files.get(name, "")
        for check in checks:
            kind = check.split()[0].lstrip("<")
            value = re.search(r'(?:expression|text|n)="([^"]*)"', check).group(1)
            value = value.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            if kind == "has_line_matching":
                ok = re.search(f"^{value}$", content, re.M) is not None
            elif kind == "has_text":
                ok = value in content
            elif kind == "has_n_lines":
                ok = len(content.splitlines()) == int(value)
            else:
                ok, value = False, f"unknown assertion {kind}"
            if not ok:
                failures.append(f"{name}: {kind} {value[:80]}")
    return failures


def check(args) -> int:
    """Replay every test from the fixture tree, as Galaxy would, and evaluate it."""
    table = Path(tempfile.mkdtemp()) / "providers.loc"
    table.write_text((TEST_DATA / "beacon_providers.loc").read_text()
                     .replace("${__HERE__}", str(TEST_DATA)))
    problems = 0
    for test in [t for t in spec.TESTS if not args.only or t.id in args.only]:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                first, second, _ = _run(test, Path(tmp), ["--provider-table", str(table)])
                files = {test.output_names[0]: first.read_text() if first.exists() else "",
                         test.output_names[1]: second.read_text() if second.exists() else ""}
                failures = _assertion_failures(test, files)
            except SystemExit as exc:
                failures = [f"exited {exc.code}"]
        problems += bool(failures)
        print(f"{'PASS' if not failures else 'FAIL':4s}  {test.id:26s} {test.purpose}")
        for failure in failures:
            print(f"        {failure}")
    print(f"\n{len(spec.TESTS) - problems} of {len(spec.TESTS)} Galaxy tests would pass.")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--construct", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--only", action="append", default=[], metavar="TOOL#N")
    args = parser.parse_args()
    if args.list:
        for test in spec.TESTS:
            where = ", ".join(test.requests_to) or "(no request: skipped by the planner)"
            print(f"{test.id:26s} -> {where}\n    beacon2-query {' '.join(test.argv)}")
        return 0
    if args.check:
        return check(args)
    return record(args, construct=args.construct)


if __name__ == "__main__":
    raise SystemExit(main())
