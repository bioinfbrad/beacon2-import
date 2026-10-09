"""The provider list a Galaxy server ships with.

Every enabled row must be well formed and resolvable, because a malformed row
in a .loc file fails silently: Galaxy simply omits the provider from the form.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SAMPLE = (Path(__file__).resolve().parent.parent.parent / "tools" / "beacon2-import"
          / "tool-data" / "beacon_providers.loc.sample")
pytestmark = pytest.mark.skipif(not SAMPLE.is_file(), reason="tool-data not present")


def _rows():
    return [l.split("\t") for l in SAMPLE.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def test_every_enabled_row_has_six_columns_and_a_registry_entry():
    from beacon2_import.registry.loader import load_registry

    registry = load_registry()
    for row in _rows():
        assert len(row) == 6, row
        assert row[0] in registry, f"{row[0]} has no registry entry"


def test_progenetix_and_cancercelllines_are_enabled_and_ega_demo_is_not():
    enabled = {row[0] for row in _rows() if row[3] == "1"}
    assert {"org.progenetix.beacon", "org.cancercelllines"} <= enabled
    assert "org.ega-archive.demo" not in enabled


def test_nothing_claims_progenetix_is_blocked():
    text = SAMPLE.read_text().lower()
    assert "blocked" not in text
