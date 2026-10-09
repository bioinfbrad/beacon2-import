"""The coverage rule, enforced: nothing 2.2.4 offered is removed unless 3.0 covers it.

2.2.4 is published on PyPI and Bioconda, and 3.0.0 is an upgrade of it. The rule
is about CAPABILITIES. Every option in v2_2_4_cli_inventory.json -- read from
the published wheel's LIVE argparse objects, not its documentation -- must map
onto a beacon2-query or beacon2-import option that exists in the 3.0 parsers.

Names are a different matter. The 2.x command `beacon2-search` and its module
`beacon2_search` are removed in 3.0.0 and replaced by `beacon2-query`; they are
JUSTIFIED here, not covered. That changes nothing about the capability check:
every one of their subcommands and options must still map, and does.

Same family as the stub audit and the fixture-consumer guard: a rule that
would otherwise be a promise is made into a failure.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import tomllib
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PACKAGE = TESTS.parent
INVENTORY = json.loads((TESTS / "v2_2_4_cli_inventory.json").read_text())
TABLE = PACKAGE / "data" / "search_options_2x.tsv"
CONNECTION_TABLE = PACKAGE / "data" / "search_connection_options_2x.tsv"
PYPROJECT = PACKAGE.parent / "pyproject.toml"
README = PACKAGE.parent / "README.md"

REMOVED_IN_3 = ("Removed in 3.0.0 and replaced by beacon2-query, which covers every one of its "
                "subcommands and options (checked below, option by option); the migration is "
                "documented in the README. Scripts not worth migrating can pin "
                "beacon2-import==2.2.4, which stays on PyPI and Bioconda.")

#: 2.2.4 console scripts with no 3.0 counterpart of the same NAME.
JUSTIFIED_SCRIPTS = {"beacon2-search": REMOVED_IN_3}

#: 2.2.4 items with no 3.0 counterpart of the same name, and what covers them.
JUSTIFIED_MODULES = {
    "utils": "A namespace collision, not a feature: 2.2.4 installed a bare top-level "
             "`utils` so that `from utils import *` worked. Its contents are "
             "beacon2_import.importer.utils.",
    "search": "A duplicate of beacon2_search with no entry point, which took the "
              "database password on the command line. Covered by beacon2-query.",
    "beacon2_search": REMOVED_IN_3,
}
#: Justified because REMOVED -- these must genuinely be gone, not merely excused.
REMOVED_MODULES = ("beacon2_search",)

#: Option strings deliberately not accepted verbatim, and why that loses nothing.
JUSTIFIED_OPTION_STRINGS = {
    "--database ": "2.2.4 declared the importer's option with a trailing space. It "
                   "worked only because argparse accepts `--database` as an abbreviation "
                   "of it; the literal string can reach argv only if a shell quotes the "
                   "space. Every real invocation, import.xml's included, passes "
                   "`--database`, which 3.0 accepts exactly.",
}


def _rows() -> list[dict[str, str]]:
    lines = [l for l in TABLE.read_text().splitlines() if l and not l.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {o for a in parser._actions for o in a.option_strings}


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(action.choices)


def _importer_parser() -> argparse.ArgumentParser:
    """Capture the ported importer's parser without running an import."""
    from beacon2_import.importer import importer

    captured = []
    original = argparse.ArgumentParser.parse_args

    def capture(self, *args, **kwargs):
        captured.append(self)
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        importer.beacon2_import()
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    return captured[0]


def _connection_rows() -> list[dict[str, str]]:
    lines = [l for l in CONNECTION_TABLE.read_text().splitlines() if l and not l.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _query_parsers() -> dict[str, argparse.ArgumentParser]:
    from beacon2_import.cli.main import build_parser

    return _subparsers(build_parser())


# ---------------- console scripts and modules ----------------

@pytest.mark.parametrize("script", sorted(INVENTORY["console_scripts"]))
def test_every_console_script_survives_or_is_justified(script):
    scripts = tomllib.loads(PYPROJECT.read_text())["project"]["scripts"]
    if script in JUSTIFIED_SCRIPTS:
        assert JUSTIFIED_SCRIPTS[script].strip()
        assert script not in scripts, f"{script} is justified as removed but still installed"
        return
    assert script in scripts, f"2.2.4 console script {script!r} is gone from 3.0"


@pytest.mark.parametrize("module", INVENTORY["importable_modules"])
def test_every_module_is_importable_or_justified(module):
    if module in JUSTIFIED_MODULES:
        assert JUSTIFIED_MODULES[module].strip()
        if module in REMOVED_MODULES:
            assert importlib.util.find_spec(module) is None, f"{module!r} is justified as removed but importable"
        return
    assert importlib.util.find_spec(module) is not None, f"{module!r} is not importable"


def test_the_2_2_4_entry_point_paths_still_resolve():
    """Except where the command itself is justified as removed."""
    for script, target in INVENTORY["console_scripts"].items():
        if script in JUSTIFIED_SCRIPTS:
            continue
        module, _, attribute = target.partition(":")
        assert callable(getattr(importlib.import_module(module), attribute)), target


# ---------------- beacon2-search: every capability maps onto beacon2-query ----------------

SEARCH = INVENTORY["beacon2_search"]


@pytest.mark.parametrize("subcommand", sorted(SEARCH))
def test_every_search_subcommand_maps_onto_beacon2_query(subcommand):
    """Every 2.x subcommand, and every one of its options, has a beacon2-query home."""
    rows = {r["dest"]: r for r in _rows() if r["subcommand"] == subcommand}
    targets = {r["3.0_subcommand"] for r in rows.values()}
    assert len(targets) == 1, f"{subcommand} maps onto several subcommands: {targets}"
    assert targets <= set(_query_parsers()), f"beacon2-query has no {targets} subcommand"
    unmapped = [o["dest"] for o in SEARCH[subcommand]["query_options"] if o["dest"] not in rows]
    assert not unmapped, f"beacon2-search {subcommand}: unmapped options {unmapped}"
    connection = {r["dest"] for r in _connection_rows()}
    missing = [o["dest"] for o in SEARCH[subcommand]["connection_options"] if o["dest"] not in connection]
    assert not missing, f"beacon2-search {subcommand}: unmapped connection options {missing}"


def test_every_connection_option_maps_to_a_beacon2_query_flag():
    """The six connection options every 2.x subcommand took, on every subcommand they reach."""
    parsers = _query_parsers()
    reached = {r["3.0_subcommand"] for r in _rows()}
    inventory = {o["dest"] for spec in SEARCH.values() for o in spec["connection_options"]}
    rows = {r["dest"]: r for r in _connection_rows()}
    assert set(rows) == inventory, f"connection map vs inventory: {sorted(set(rows) ^ inventory)}"
    for row in rows.values():
        for subcommand in reached:
            assert row["target"] in _option_strings(parsers[subcommand]), \
                f"beacon2-query {subcommand} lacks {row['target']} (for 2.x {row['long']})"


def test_every_2_2_4_query_option_has_a_mapping_and_no_mapping_is_stale():
    inventory = {(s, o["dest"]) for s, spec in SEARCH.items() for o in spec["query_options"]}
    table = {(r["subcommand"], r["dest"]) for r in _rows()}
    assert not inventory - table, f"unmapped 2.2.4 options: {sorted(inventory - table)}"
    assert not table - inventory, f"mappings for options 2.2.4 never had: {sorted(table - inventory)}"
    assert len(inventory) == 94


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r['subcommand']}.{r['dest']}")
def test_every_mapping_points_at_something_beacon2_query_has(row):
    from beacon2_import.cli.main import build_parser

    options = _option_strings(_subparsers(build_parser())[row["3.0_subcommand"]])
    if row["kind"] == "flag":
        assert row["target"] in options, f"beacon2-query {row['3.0_subcommand']} lacks {row['target']}"
    elif row["kind"] == "field":
        assert "--field" in options and row["target"]
    elif row["kind"] == "entity_id":
        assert "--entity-id" in options
    else:
        pytest.fail(f"unknown coverage kind {row['kind']!r}")


# ---------------- the 2.2.4 fixes, now held by beacon2-query ----------------

def _mongo_filter(monkeypatch, tmp_path, argv):
    """Run beacon2-query on MongoDB, intercepting only the driver call.

    The returned filter is exactly what beacon2-query built from the arguments.
    A plain function is patched in, so it binds as a method like the original.
    """
    from beacon2_import.cli.main import main
    from beacon2_import.transport import mongo

    filters = []

    def find(self, query, limit=0):
        filters.append(query)
        return []

    monkeypatch.setattr(mongo.MongoTransport, "find", find)
    assert main([*argv, "--transport", "mongodb", "--collection", "c",
                 "--results", str(tmp_path / "r.tsv"), "--outcomes", str(tmp_path / "o.tsv")]) == 0
    return filters[0]


def _row(subcommand, dest):
    return next(r for r in _rows() if r["subcommand"] == subcommand and r["dest"] == dest)


def test_min_and_max_length_map_by_name(monkeypatch, tmp_path):
    """2.2.4 wired -vmax to the minimum and -vmin to the maximum. beacon2-query
    does not repeat it: the 2.x options map by name, and bound what they say."""
    assert _row("range", "variantMinLength")["target"] == "--variant-min-length"
    assert _row("range", "variantMaxLength")["target"] == "--variant-max-length"
    clauses = _mongo_filter(monkeypatch, tmp_path, [
        "range", "--reference-name", "17", "--start", "101", "--end", "200",
        "--variant-min-length", "10", "--variant-max-length", "50"])
    bounds = clauses["$expr"]["$and"]
    assert bounds[0]["$gte"][1] == 10 and bounds[1]["$lte"][1] == 50


def test_the_2_2_4_range_bug_is_not_revived(monkeypatch, tmp_path):
    """2.2.4 sent no positional constraint for a range query. beacon2-query does."""
    clauses = _mongo_filter(monkeypatch, tmp_path, [
        "range", "--reference-name", "17", "--start", "7572837", "--end", "7578641"])
    assert clauses["variation.location.interval.start.value"] == {"$lt": 7578641}
    assert clauses["variation.location.interval.end.value"] == {"$gt": 7572836}


def test_collection_ids_maps_to_a_biosample_id_list(monkeypatch, tmp_path):
    """2.2.4 passed one string to $in, which MongoDB rejects; now a list."""
    assert _row("sequence", "collectionIds")["target"] == "--biosample-ids"
    clauses = _mongo_filter(monkeypatch, tmp_path, [
        "sequence", "--reference-name", "17", "--start", "6", "--reference-bases", "G",
        "--alternate-bases", "A", "--biosample-ids", "bs1,bs2"])
    assert clauses["caseLevelData.biosampleId"] == {"$in": ["bs1", "bs2"]}


def test_diagnostic_markers_now_does_something(monkeypatch, tmp_path):
    """Declared but ignored by 2.2.4; now matched."""
    row = _row("biosamples", "diagnosticMarkers")
    assert (row["kind"], row["target"]) == ("field", "diagnosticMarkers.label")
    clauses = _mongo_filter(monkeypatch, tmp_path, [
        "entity", "--entity", "biosample", "--field", "diagnosticMarkers.label=KRAS"])
    assert clauses == {"diagnosticMarkers.label": "KRAS"}


# ---------------- beacon2-import ----------------

def test_every_import_option_string_survives():
    accepted = _option_strings(_importer_parser())
    wanted = {s for o in INVENTORY["beacon2_import"] for s in o["option_strings"]}
    for literal, reason in JUSTIFIED_OPTION_STRINGS.items():
        if literal in wanted:
            assert reason.strip() and literal.strip() in accepted, literal
            wanted.discard(literal)
    missing = wanted - accepted
    assert not missing, f"beacon2-import no longer accepts {sorted(missing)}"
    assert len(INVENTORY["beacon2_import"]) == 17
