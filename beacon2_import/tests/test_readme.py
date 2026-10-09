"""The README states the model first, and its generated regions cannot drift.

The command table comes from commands.py; the beacon2-search migration map from
the coverage inventory and the option map. A README edited by hand inside a
generated region, or one left behind by a change to either source, fails here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
README = ROOT / "README.md"
GENERATOR = ROOT / "scripts" / "generate_readme_sections.py"
INVENTORY = Path(__file__).resolve().parent / "v2_2_4_cli_inventory.json"
pytestmark = pytest.mark.skipif(not README.is_file(), reason="README.md not present")

ORDER = ["What this package does", "The two commands", "Which command do I want?",
         "beacon2-query", "beacon2-import", "Migrating 2.x beacon2-search scripts",
         "Why is the package called beacon2-import?", "Licence"]


def test_sections_come_in_the_required_order():
    headings = re.findall(r"^## (.+)$", README.read_text(), re.M)
    assert headings == ORDER


@pytest.mark.skipif(not GENERATOR.is_file(), reason="generator not present")
def test_generated_regions_are_current():
    result = subprocess.run([sys.executable, str(GENERATOR), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_2_x_option_appears_in_the_migration_map():
    text = README.read_text().split("## Migrating 2.x beacon2-search scripts", 1)[1]
    inventory = json.loads(INVENTORY.read_text())["beacon2_search"]
    missing = sorted({s for spec in inventory.values()
                      for o in spec["connection_options"] + spec["query_options"]
                      for s in o["option_strings"] if f"`{s}`" not in text})
    assert not missing, f"2.x options absent from the migration map: {missing}"
    assert all(f"`beacon2-search {sub}`" in text for sub in inventory)


def test_the_vmin_vmax_warning_is_there():
    text = README.read_text()
    assert "-vmin" in text and "-vmax" in text and "swap them back" in text


def test_the_package_is_not_described_as_only_an_api_client():
    for path in (README, ROOT / "pyproject.toml"):
        if path.is_file():
            assert "API client" not in path.read_text(), path.name


def _migration() -> str:
    return README.read_text().split("## Migrating 2.x beacon2-search scripts", 1)[1].split("\n## ", 1)[0]


def test_the_coordinate_rule_is_stated_before_any_table():
    text = _migration()
    rule = text.index("Start positions: add 1. End positions: unchanged.")
    assert rule < text.index("|"), "the coordinate rule must come before the mapping tables"


def test_pinning_2_2_4_is_offered():
    assert "beacon2-import==2.2.4" in _migration()


@pytest.mark.skipif(not GENERATOR.is_file(), reason="generator not present")
def test_worked_examples_add_one_to_starts_and_leave_ends_alone():
    """The README's examples apply the rule the 2.x command applied, exactly."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("readme_gen", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    for subcommand, given, database, collection in gen.EXAMPLES:
        command = gen.equivalent(subcommand, given, database, collection)
        assert command in _migration(), f"{subcommand} example missing from the README"
        rows = {r["dest"]: r for r in gen._option_rows() if r["subcommand"] == subcommand}
        for dest, value in given.items():
            row = rows[dest]
            if row["kind"] == "field":
                continue
            expected = value + 1 if dest in gen.START_DESTS else value
            assert f"{row['target']} '{expected}'" in command, (subcommand, dest)
