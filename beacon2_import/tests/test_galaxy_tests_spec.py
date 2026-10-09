"""Every Galaxy test is defined once, in scripts/galaxy_tests.py.

Each test there carries the Galaxy form values AND the same query as
beacon2-query arguments, which the fixture recorder runs. Fixtures are keyed on
the request, so if the two encodings disagreed, the recorded fixture would not
match the request Galaxy sends. This checks that the XML holds exactly the
rendered tests, and that each test's arguments agree with its form values.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
TOOLS = ROOT / "tools" / "beacon2-import"
pytestmark = pytest.mark.skipif(not (SCRIPTS / "galaxy_tests.py").is_file() or not TOOLS.is_dir(),
                                reason="scripts or tool XML not present")
if (SCRIPTS / "galaxy_tests.py").is_file():
    sys.path.insert(0, str(SCRIPTS))
    import galaxy_tests as spec

    TESTS = spec.TESTS
else:  # pragma: no cover
    TESTS = []

#: form parameter -> beacon2-query flag
FLAGS = {"reference_name": "--reference-name", "start": "--start", "end": "--end",
         "start_min": "--start-min", "start_max": "--start-max", "end_min": "--end-min",
         "end_max": "--end-max", "gene_id": "--gene-id", "reference_bases": "--reference-bases",
         "alternate_bases": "--alternate-bases", "granularity": "--granularity",
         "prefixes": "--prefix", "variant_classes": "--variant-classes", "providers": "--providers"}


def _params(test) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name, value in re.findall(r'<param name="([^"]+)" value="([^"]*)"/>', "\n".join(test.params)):
        found.setdefault(name, []).append(value)
    return found


def _after(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


@pytest.mark.parametrize("tool", sorted({t.tool for t in TESTS}))
def test_the_xml_holds_exactly_the_rendered_tests(tool):
    xml = (TOOLS / f"{tool}.xml").read_text()
    assert spec.render_tests(tool) in xml, f"{tool}.xml drifted: run python3 scripts/galaxy_tests.py"


def test_every_beacon2_tool_has_tests_in_the_spec():
    tools = {p.stem for p in TOOLS.glob("beacon2_*.xml")}
    assert tools == {t.tool for t in TESTS}


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_the_arguments_parse(test):
    from beacon2_import.cli.main import build_parser

    build_parser().parse_args(test.argv)


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_the_arguments_agree_with_the_form(test):
    params, argv = _params(test), test.argv
    for name, flag in FLAGS.items():
        for value in params.get(name, []):
            assert value in _after(argv, flag), f"{name}={value} but argv {flag} {_after(argv, flag)}"
    for term, mode in zip(params.get("term", []), params.get("mode", []) + [None] * 9):
        if mode in ("efo", "legacy"):
            assert f"CNV={term}" in _after(argv, "--class-term")
    descendants = params.get("include_descendant_terms", [])
    for term in [v for n, v in re.findall(r'name="(kind|term)" value="([^"]+)"', "\n".join(test.params))
                 if n == "term" and v.startswith("NCIT:")]:
        expected = [f for f in _after(argv, "--filter") if f.startswith(f"ontology:{term}:")]
        assert expected, f"filter {term} in the form but not in argv"
        if descendants:
            assert f"descendants={descendants[0]}" in expected[0]
    if params.get("allow_degradation") == ["false"]:
        assert "--no-degradation" in argv
        assert '<section name="advanced">' in "\n".join(test.params), \
            "allow_degradation lives in the advanced section; at top level Galaxy ignores it"


@pytest.mark.parametrize("test", [t for t in TESTS if t.requests_to], ids=lambda t: t.id)
def test_every_provider_a_test_sends_to_is_in_the_test_table(test):
    loc = (TOOLS / "test-data" / "beacon_providers.loc").read_text()
    table = {l.split("\t")[0] for l in loc.splitlines() if l.strip() and not l.startswith("#")}
    assert set(test.requests_to) <= table
