"""The tool XML and the CLI must agree.

Fails if any tool's <command> calls a subcommand, or passes a flag, that the
CLI does not expose. Macro tokens are expanded first, so a flag hidden inside
@PROVIDER_ARGS@ is checked like any other.

Skips cleanly when the tool directory is not present, e.g. against an installed
wheel, which carries the package but not the Galaxy wrappers.
"""

from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from beacon2_import.cli.main import SUBCOMMANDS, build_parser
from beacon2_import.query.retrieve import refusal_message, short_retrieval_message

PACKAGE = Path(__file__).resolve().parent.parent
TOOLS = PACKAGE.parent / "tools" / "beacon2-import"
pytestmark = pytest.mark.skipif(not TOOLS.is_dir(), reason="tool XML not present")


def _tokens() -> dict[str, str]:
    macros = (TOOLS / "macros.xml").read_text()
    return dict(re.findall(
        r'<token name="(@[A-Z_0-9]+@)">(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</token>', macros, re.S))


def _command(xml: Path) -> str:
    text = ET.parse(xml).getroot().find("command").text
    tokens = _tokens()
    for _ in range(4):
        for name, value in tokens.items():
            text = text.replace(name, value)
    return text


def _subparser_options() -> dict[str, set[str]]:
    sub = build_parser()._subparsers._group_actions[0].choices
    return {name: {o for a in parser._actions for o in a.option_strings}
            for name, parser in sub.items()}


QUERY_TOOLS = sorted(p for p in TOOLS.glob("beacon2_*.xml")) if TOOLS.is_dir() else []


@pytest.mark.parametrize("xml", QUERY_TOOLS, ids=[p.stem for p in QUERY_TOOLS])
def test_every_subcommand_the_xml_calls_exists(xml):
    called = set(re.findall(r"beacon2-query\s+([\w-]+)", _command(xml)))
    assert called, f"{xml.name} calls no beacon2-query subcommand"
    missing = called - set(SUBCOMMANDS)
    assert not missing, f"{xml.name} calls subcommands the CLI lacks: {sorted(missing)}"


@pytest.mark.parametrize("xml", QUERY_TOOLS, ids=[p.stem for p in QUERY_TOOLS])
def test_every_flag_the_xml_passes_is_accepted(xml):
    command = _command(xml)
    options = _subparser_options()
    for sub in set(re.findall(r"beacon2-query\s+([\w-]+)", command)):
        flags = set(re.findall(r"(?<![\w$])(--[a-z][a-z0-9-]*)", command))
        unknown = flags - options[sub]
        assert not unknown, f"{xml.name} passes flags `{sub}` does not accept: {sorted(unknown)}"


def test_import_xml_flags_exist_in_the_ported_importer():
    """The unchanged import tool calls `beacon2-import`, the ported 2.2.4 parser.

    Read from the importer's own add_argument calls -- which is also how a
    2.2.4-style trailing space in an option string would be caught.
    """
    importer = PACKAGE / "importer" / "importer.py"
    accepted = set()
    for node in ast.walk(ast.parse(importer.read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and str(arg.value).startswith("-"):
                    assert arg.value == arg.value.strip(), f"whitespace in {arg.value!r}"
                    accepted.add(arg.value)
    command = ET.parse(TOOLS / "import.xml").getroot().find("command").text
    assert "beacon2-import" in command
    passed = set(re.findall(r"(?<![\w$])(--[a-zA-Z][a-zA-Z0-9_-]*)", command))
    unknown = passed - accepted
    assert not unknown, f"import.xml passes flags the importer lacks: {sorted(unknown)}"


# ---------------- --sample: the advice must be real ----------------

def test_the_refusal_messages_name_sample():
    assert "--sample" in refusal_message("X", 20000, 10000)
    assert "--sample" in short_retrieval_message("X", 10, 60)


@pytest.mark.parametrize("sub", ["range", "bracket", "sequence", "gene", "entity"])
def test_every_query_subcommand_accepts_sample(sub):
    """A refusal pointing at a flag the CLI lacks is worse than no advice."""
    assert "--sample" in _subparser_options()[sub]


def test_the_form_offers_sample():
    pagination = re.search(r'<xml name="beacon_pagination">(.*?)</xml>',
                           (TOOLS / "macros.xml").read_text(), re.S).group(1)
    assert 'argument="--sample"' in pagination


RETRIEVING_TOOLS = [p for p in QUERY_TOOLS
                    if p.stem not in ("beacon2_filtering_terms", "beacon2_service_info")]


@pytest.mark.parametrize("xml", RETRIEVING_TOOLS, ids=[p.stem for p in RETRIEVING_TOOLS])
def test_every_api_query_tool_passes_sample(xml):
    """Only tools that retrieve records can be refused, so only they need it."""
    command = _command(xml)
    api_branch = command.split("#else")[0]
    assert "--sample" in api_branch, f"{xml.name} never passes --sample to the CLI"
