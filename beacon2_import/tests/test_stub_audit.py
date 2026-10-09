"""Stub audit: the progress metric the skip count could never be.

A skip only appears when a test reaches a stub. A stub nothing tests is
invisible to the skip count -- "zero skips" meant no test reached the remaining
stubs, not that they were filled. This audit reads the source instead.

BIDIRECTIONAL, like the fixture-consumer guard:
  * a module not listed in outstanding_stubs.txt may not contain a stub, so
    nothing can be quietly left unfinished;
  * a module listed there must still contain one, so the list cannot go stale
    and quietly overstate what remains.

Stubs are found by AST -- `raise NotImplementedError` statements -- not by text,
so the phrase in a docstring or a test's skip message never counts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).resolve().parent / "outstanding_stubs.txt"


def _stub_sites(path: Path) -> int:
    tree = ast.parse(path.read_text())
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if getattr(target, "id", None) == "NotImplementedError":
            count += 1
    return count


def _source_modules() -> dict[str, int]:
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE)
        if relative.parts[0] == "tests":
            continue
        found[relative.as_posix()] = _stub_sites(path)
    return found


def _manifest() -> dict[str, str]:
    entries = {}
    for line in MANIFEST.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        module, _, reason = line.partition("\t")
        entries[module.strip()] = reason.strip()
    return entries


def test_no_unlisted_module_contains_a_stub():
    """A module not declared outstanding must be fully implemented."""
    listed = _manifest()
    offenders = {m: n for m, n in _source_modules().items() if n and m not in listed}
    assert not offenders, (
        f"stubs in modules not listed as outstanding: {offenders}. Implement them, "
        f"or add them to outstanding_stubs.txt with a reason."
    )


def test_no_listed_module_is_already_done():
    """The list must not overstate what remains."""
    modules = _source_modules()
    stale = [m for m in _manifest() if modules.get(m, 0) == 0]
    assert not stale, (
        f"listed as outstanding but containing no stubs (or missing): {stale}. "
        f"Remove them from outstanding_stubs.txt."
    )


def test_every_listed_module_gives_a_reason():
    missing = [m for m, reason in _manifest().items() if not reason]
    assert not missing, f"no reason given for: {missing}"


def test_report_totals(capsys):
    """Prints the real progress metric; never fails on the numbers themselves."""
    modules = {m: n for m, n in _source_modules().items() if n}
    with capsys.disabled():
        print(f"\n[stub audit] {len(modules)} modules, {sum(modules.values())} stub sites")
