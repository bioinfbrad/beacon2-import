#!/usr/bin/env python3
"""Regenerate the README's generated regions, so they cannot drift from the code.

  * the command table   -- from beacon2_import/commands.py, where the model lives
  * the migration map   -- from the coverage inventory (2.2.4's live argparse) and
                           beacon2_import/data/search_options_2x.tsv

    python3 scripts/generate_readme_sections.py          rewrite README.md
    python3 scripts/generate_readme_sections.py --check  exit 1 if README.md is stale

tests/test_readme.py runs the check, so a README edited by hand inside a
generated region, or left behind by a change to the inventory or the option
map, fails the suite.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
sys.path.insert(0, str(ROOT))

from beacon2_import.commands import COMMANDS  # noqa: E402

INVENTORY = ROOT / "beacon2_import" / "tests" / "v2_2_4_cli_inventory.json"
OPTION_MAP = ROOT / "beacon2_import" / "data" / "search_options_2x.tsv"
ENTITY = {"analyses": "analysis", "biosamples": "biosample", "cohorts": "cohort",
          "datasets": "dataset", "individuals": "individual", "runs": "run"}
#: 2.2.4 passed these to MongoDB AS STORED; beacon2-query takes them 1-based.
#: Ends are unchanged: a stored half-open end equals the 1-based inclusive end.
#: This is the rule the 2.x compatibility command applied when it printed each
#: run's beacon2-query equivalent before its removal; moved here, and checked
#: against it before it went, so the README states it exactly.
START_DESTS = ("start", "start_minimum", "start_maximum")

#: Worked examples: (2.x subcommand, {2.x dest: value}, database, collection).
EXAMPLES = (
    ("range", {"referenceName": "refseq:NC_000017.11", "start": 7572836, "end": 7578641,
               "variantType": "DEL"}, "beacon", "genomicVariations"),
    ("bracket", {"referenceName": "refseq:NC_000017.11", "start_minimum": 5000000,
                 "start_maximum": 7676592, "end_minimum": 7669607, "end_maximum": 10000000,
                 "variantType": "DEL"}, "beacon", "genomicVariations"),
    ("sequence", {"referenceName": "refseq:NC_000017.11", "start": 7577119,
                  "referenceBases": "G", "alternateBases": "A"}, "beacon", "genomicVariations"),
    ("cnv", {"chromosome": "1", "start": 243618689, "end": 243620819, "variantType": "DEL"},
     "beacon", "cnv"),
    ("runs", {"platform": "Illumina", "libraryStrategy": "WGS"}, "beacon", "runs"),
)
CONNECTION_MAP = ROOT / "beacon2_import" / "data" / "search_connection_options_2x.tsv"


def _option_rows() -> list[dict[str, str]]:
    lines = [l for l in OPTION_MAP.read_text().splitlines() if l and not l.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def _flags(option_strings: list[str]) -> str:
    longs = [s for s in option_strings if s.startswith("--")]
    shorts = [s for s in option_strings if not s.startswith("--")]
    return ", ".join(f"`{s}`" for s in longs + shorts)


def command_2x(subcommand: str, given: dict, database: str, collection: str) -> str:
    """The 2.x invocation, spelled with 2.2.4's own long options."""
    inventory = json.loads(INVENTORY.read_text())["beacon2_search"][subcommand]
    parts = ["beacon2-search", subcommand, "--database", f"'{database}'",
             "--collection", f"'{collection}'"]
    for option in inventory["query_options"]:
        if option["dest"] in given:
            long = next(s for s in option["option_strings"] if s.startswith("--"))
            parts += [long, f"'{given[option['dest']]}'"]
    return " ".join(parts)


def equivalent(subcommand: str, given: dict, database: str, collection: str) -> str:
    """The beacon2-query command meaning the same: starts +1, ends unchanged."""
    rows = [r for r in _option_rows() if r["subcommand"] == subcommand]
    target = rows[0]["3.0_subcommand"]
    parts = ["beacon2-query", target, "--transport", "mongodb"]
    if target == "entity":
        parts += ["--entity", ENTITY[subcommand]]
    for row in rows:
        if row["dest"] not in given:
            continue
        value = given[row["dest"]]
        if row["kind"] == "field":
            parts += ["--field", f"'{row['target']}={value}'"]
        else:
            shown = value + 1 if row["dest"] in START_DESTS else value
            parts += [row["target"], f"'{shown}'"]
    parts += ["--database", f"'{database}'", "--collection", f"'{collection}'"]
    return " ".join(parts)


def examples() -> str:
    out = []
    for subcommand, given, database, collection in EXAMPLES:
        out += [f"**{subcommand}**", "", "```",
                command_2x(subcommand, given, database, collection),
                "```", "becomes", "```",
                equivalent(subcommand, given, database, collection), "```", ""]
    return "\n".join(out).rstrip()


def commands_table() -> str:
    lines = ["| Command | Job | Status |", "|---|---|---|"]
    for command, job, status in COMMANDS:
        lines.append(f"| `{command}` | {job} | {status} |")
    return "\n".join(lines)


def migration_map() -> str:
    inventory = json.loads(INVENTORY.read_text())["beacon2_search"]
    rows = _option_rows()
    lines = [l for l in CONNECTION_MAP.read_text().splitlines() if l and not l.startswith("#")]
    connection = {r["dest"]: r for r in csv.DictReader(lines, delimiter="\t")}
    out = ["### Connection options, every subcommand", "",
           "| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |", "|---|---|---|"]
    for option in next(iter(inventory.values()))["connection_options"]:
        row = connection[option["dest"]]
        out.append(f"| {_flags(option['option_strings'])} | `{row['target']}` | {row['note']} |")
    for subcommand, spec in inventory.items():
        mine = {r["dest"]: r for r in rows if r["subcommand"] == subcommand}
        target = mine[spec["query_options"][0]["dest"]]["3.0_subcommand"]
        equivalent = f"beacon2-query {target} --transport mongodb"
        if target == "entity":
            equivalent += f" --entity {ENTITY[subcommand]}"
        out += ["", f"### `beacon2-search {subcommand}` \u2192 `{equivalent}`", "",
                "| 2.x option (as 2.2.4 wired it) | beacon2-query | Note |", "|---|---|---|"]
        for option in spec["query_options"]:
            row = mine[option["dest"]]
            if row["kind"] == "field":
                new = f"`--field '{row['target']}=VALUE'`"
            else:
                new = f"`{row['target']}`"
            notes = []
            if option["dest"] in START_DESTS:
                notes.append("1-based in beacon2-query: add 1 to the 2.x value")
            if row["note"]:
                notes.append(row["note"])
            out.append(f"| {_flags(option['option_strings'])} | {new} | {'; '.join(notes)} |")
    return "\n".join(out)


REGIONS = {"commands": commands_table, "search-examples": examples,
           "search-migration": migration_map}


def render(text: str) -> str:
    for name, build in REGIONS.items():
        # The region may be empty (a fresh README) or hold a previous rendering.
        pattern = re.compile(
            rf"(<!-- BEGIN GENERATED: {name} -->\n)(?:.*?\n)?(<!-- END GENERATED: {name} -->)", re.S)
        if not pattern.search(text):
            raise SystemExit(f"README.md has no generated region {name!r}")
        text = pattern.sub(lambda m: m.group(1) + build() + "\n" + m.group(2), text)
    return text


def main() -> int:
    current = README.read_text()
    fresh = render(current)
    if "--check" in sys.argv:
        if fresh != current:
            print("README.md is stale: run scripts/generate_readme_sections.py", file=sys.stderr)
            return 1
        return 0
    README.write_text(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
