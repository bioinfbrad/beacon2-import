"""Meta-tests: every fixture set must be read by something.

WHY THIS EXISTS
    A fixture nothing reads is not a specification, it is a document. It
    provides zero protection against the failure it was written to prevent,
    and it is indistinguishable from a fixture that is simply wrong, because
    nothing has ever evaluated it.

    Worse, the directory looks like coverage. That is the combination that
    makes this worth a test rather than a note: correct, inert, and reassuring.

    The gap appeared twice in three deliveries -- the classify fixtures, then
    the transport fixtures. That is not carelessness, it is ORDERING: fixtures
    get written while designing, consumers while implementing, so there is
    always a window in which they exist unread. The ordering is correct and
    should not change. Discipline cannot close a structural window; a test can.

    Same move as the YAML boolean lint in test_registry_lint.py: take a
    recurring problem that produces no failure of its own, and give it one.

THE CONVENTION THIS ENFORCES
    A consuming test refers to its fixture directory by its quoted name, e.g.

        FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transport"

    Building the path from an unquoted variable will read as unconsumed. That
    is a deliberate constraint: the convention is cheap, and the alternative is
    a matcher loose enough to be satisfied by an incidental mention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_ROOT = TESTS_DIR / "fixtures"
PACKAGE_ROOT = TESTS_DIR.parent
TOOL_FIXTURES = (
    PACKAGE_ROOT.parent / "tools" / "beacon2-import" / "test-data" / "fixtures"
)

#: This module names every fixture directory while explaining itself, so it
#: must not count as a consumer or it would vacuously satisfy every check.
SELF = Path(__file__).name


def _fixture_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _test_sources() -> dict[str, str]:
    return {
        path.name: path.read_text()
        for path in sorted(TESTS_DIR.glob("test_*.py"))
        if path.name != SELF
    }


PY_FIXTURE_DIRS = _fixture_dirs(FIXTURES_ROOT)
PY_IDS = [p.name for p in PY_FIXTURE_DIRS] or ["<none>"]

TOOL_FIXTURE_DIRS = _fixture_dirs(TOOL_FIXTURES)
TOOL_IDS = [p.name for p in TOOL_FIXTURE_DIRS] or ["<none>"]


@pytest.mark.parametrize("fixture_dir", PY_FIXTURE_DIRS, ids=PY_IDS)
def test_every_fixture_directory_has_a_consumer(fixture_dir):
    """A fixture nothing reads is not a specification, it is a document.

    This gap has appeared twice. Both times the fixtures were correct and
    inert -- which is the worst combination, because the directory looks like
    coverage.
    """
    name = fixture_dir.name
    quoted = (f'"{name}"', f"'{name}'")
    consumers = [
        filename
        for filename, source in _test_sources().items()
        if any(form in source for form in quoted)
    ]
    assert consumers, (
        f"fixtures/{name}/ is read by no test. It contains "
        f"{len(list(fixture_dir.iterdir()))} file(s) providing no protection "
        f"against anything. Add a consumer that references it as \"{name}\", "
        f"following the pattern in test_classify.py."
    )


@pytest.mark.parametrize("fixture_dir", PY_FIXTURE_DIRS, ids=PY_IDS)
def test_no_fixture_directory_is_empty(fixture_dir):
    """An empty fixture directory is inert in the same way as an unread one.

    It also satisfies the consumer check above while testing nothing, so the
    two run together.
    """
    contents = [p for p in fixture_dir.iterdir() if p.name != "README.md"]
    assert contents, f"fixtures/{fixture_dir.name}/ is empty"


@pytest.mark.parametrize("fixture_dir", TOOL_FIXTURE_DIRS, ids=TOOL_IDS)
def test_tool_fixture_directories_are_reachable(fixture_dir):
    """Tool-level fixture directories must be wired into the test data table.

    These are consumed by Galaxy tool tests rather than by pytest: the `.test`
    data table points each provider's base_url at one of these directories via
    a file:// URL. A directory not named there is unreachable, which is the
    same inert state by a different route.
    """
    loc = TOOL_FIXTURES.parent / "beacon_providers.loc"
    if not loc.is_file():
        pytest.skip("test data table not present")

    referenced = loc.read_text()
    assert fixture_dir.name in referenced, (
        f"test-data/fixtures/{fixture_dir.name}/ is not referenced by "
        f"test-data/beacon_providers.loc, so no tool test can reach it."
    )


def test_every_provider_in_the_test_table_has_a_fixture_directory():
    """And the converse: a table row pointing at nothing fails at run time.

    Without this, a provider id could be enabled for tests with no fixtures
    behind it, and every request against it would miss.
    """
    loc = TOOL_FIXTURES.parent / "beacon_providers.loc"
    if not loc.is_file():
        pytest.skip("test data table not present")

    missing = []
    for line in loc.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        provider_id = line.split("\t")[0]
        if not (TOOL_FIXTURES / provider_id).is_dir():
            missing.append(provider_id)
    assert not missing, (
        "providers enabled in the test data table with no fixture directory: "
        + ", ".join(missing)
    )


def test_this_module_is_not_its_own_consumer():
    """Guard the guard.

    This file names every fixture directory in its own docstrings and error
    messages. If it counted as a consumer, every check above would pass
    vacuously forever.
    """
    assert SELF not in _test_sources()
