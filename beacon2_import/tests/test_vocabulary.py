"""Vocabulary rule: no "deprecated" at all, and "legacy" only in the specification's sense.

A reader of this code must never come away believing that the import tool is
legacy, or that there are two search systems. Both mistakes were invited by
words: the active import code lived in a folder called `legacy/`, and "legacy"
carried three meanings at once. Same family as the stub audit -- a recurring
clarity problem made into a failing check.

The rules:
  * DEPRECATED: nothing. The one thing that was on its way out, the 2.x
    beacon2-search command, is removed in 3.0.0, so the word has no legitimate
    use left and any occurrence fails.
  * LEGACY: only the Beacon specification's own designation of the VCF-derived
    variantType values DEL/DUP, and the default model's `LegacyVariation`.
    The term is the specification's, so it is kept where it refers to that.

Provenance ("ported from 2.2.4") is not status, and needs neither word.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE = ROOT / "beacon2_import"

#: Identifiers and phrases that ARE the specification's LEGACY variantType usage.
SPEC_LEGACY = ("DEL", "DUP", "variantType", "legacy_term_expansion", "legacy_to_efo",
               "efo_to_legacy", "_LEGACY_CNV", "efo_downgraded_to_legacy",
               "LegacyVariation", 'value="legacy"')


def _scanned() -> list[Path]:
    files = [p for p in PACKAGE.rglob("*.py") if "tests" not in p.relative_to(PACKAGE).parts]
    files += list((ROOT / "scripts").glob("*.py"))
    files += list((ROOT / "tools" / "beacon2-import").glob("*.xml"))
    files += list((ROOT / "tools" / "beacon2-import").glob("*.md"))
    files += list(PACKAGE.rglob("*.yaml")) + list(PACKAGE.glob("*.md"))
    files += list((PACKAGE / "data").glob("*.tsv"))
    files += [p for p in (ROOT / "README.md", ROOT / "CHANGELOG.md", ROOT / "pyproject.toml",
                          ROOT / "recipe" / "meta.yaml") if p.is_file()]
    return sorted(set(files))


def _violations(path: Path) -> list[str]:
    found = []
    for number, line in enumerate(path.read_text(errors="ignore").splitlines(), start=1):
        if re.search(r"deprecat", line, re.I):
            found.append(f"{path.relative_to(ROOT)}:{number}: deprecated: {line.strip()[:90]}")
        if re.search(r"legacy", line, re.I) and not any(m in line for m in SPEC_LEGACY):
            found.append(f"{path.relative_to(ROOT)}:{number}: legacy: {line.strip()[:90]}")
    return found


def test_there_is_something_to_scan():
    assert len(_scanned()) > 50


def test_reserved_words_only_in_their_reserved_meaning():
    violations = [v for path in _scanned() for v in _violations(path)]
    assert not violations, (
        "\"deprecated\" has no remaining use, and \"legacy\" is reserved for the "
        "specification's DEL/DUP variantType designation. Rename what each of these is "
        "actually for:\n  " + "\n  ".join(violations))


def test_no_module_or_folder_is_named_legacy():
    ignored = {
        ".git", ".venv", "venv", "env",
        "build", "dist", "__pycache__",
        ".pytest_cache", ".tox"
    }

    named = [
        p for p in ROOT.rglob("*")
        if "legacy" in p.name.lower()
        and "fixtures" not in p.parts
        and not any(part in ignored for part in p.relative_to(ROOT).parts)
    ]

    assert not named, f"named legacy: {named}"
