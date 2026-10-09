"""Every command introduces itself, and every tool says whether it reads or writes.

Two things a reader must never come away believing: that the import tool is
legacy, or that there are two search systems. The first line of each --help,
each package docstring and each Galaxy tool's help state the model directly.
"""

from __future__ import annotations

import argparse
import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from beacon2_import.commands import COMMANDS, INTRO

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = ROOT / "tools" / "beacon2-import"


def _importer_help() -> str:
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
    return captured[0].format_help()


def _help(command: str) -> str:
    if command == "beacon2-query":
        from beacon2_import.cli.main import build_parser
        return build_parser().format_help()
    return _importer_help()


@pytest.mark.parametrize("command", sorted(INTRO))
def test_help_opens_with_the_intro(command):
    intro = INTRO[command].splitlines()
    assert _help(command).splitlines()[:len(intro)] == intro


@pytest.mark.parametrize("command", sorted(INTRO))
def test_first_line_of_help_states_the_job(command):
    first = _help(command).splitlines()[0]
    assert first == INTRO[command].splitlines()[0]
    assert ("(read)" in first) != ("(write)" in first)


def test_each_intro_names_its_job_and_points_at_the_other():
    assert "(read)" in INTRO["beacon2-query"] and "beacon2-import" in INTRO["beacon2-query"]
    assert "(write)" in INTRO["beacon2-import"] and "beacon2-query" in INTRO["beacon2-import"]


def test_the_migration_is_discoverable_from_beacon2_query_help():
    assert "Replaces the 2.x beacon2-search command." in _help("beacon2-query").splitlines()[:3]


def test_the_model_has_two_commands_and_one_writer():
    assert [c for c, _, _ in COMMANDS] == ["beacon2-import", "beacon2-query"]
    assert [c for c, job, _ in COMMANDS if job.startswith("WRITE")] == ["beacon2-import"]


PACKAGES = sorted(p for p in (ROOT / "beacon2_import").rglob("__init__.py")
                  if "tests" not in p.parts)


@pytest.mark.parametrize("init", PACKAGES, ids=lambda p: str(p.parent.relative_to(ROOT)))
def test_every_package_states_its_role(init):
    first = (ast.get_docstring(ast.parse(init.read_text())) or "").splitlines()[0]
    assert any(c in first for c in INTRO), f"{init}: first docstring line names no command: {first!r}"


pytestmark_tools = pytest.mark.skipif(not TOOLS.is_dir(), reason="tool XML not present")
TOOL_XML = sorted(p for p in TOOLS.glob("*.xml") if p.name != "macros.xml") if TOOLS.is_dir() else []


@pytestmark_tools
@pytest.mark.parametrize("xml", TOOL_XML, ids=lambda p: p.stem)
def test_every_tool_says_whether_it_reads_or_writes(xml):
    help_text = ET.parse(xml).getroot().find("help").text
    if xml.name == "import.xml":
        assert "@HELP_WRITES@" in help_text and "@HELP_READS@" not in help_text
    else:
        assert "@HELP_READS@" in help_text and "@HELP_WRITES@" not in help_text
    assert help_text.index("@HELP_") < help_text.index("**What it does**") + 40, \
        "the read/write statement should open the help"
