"""Width check across every packaged data table.

Every row must have exactly as many fields as its header. A short row shifts
its remaining values one column left without any error -- which is what the
EFO:0030064 row of efo_cnv_terms.tsv did, putting its `source` in the `vrs`
column, until it was caught by reading the file by eye.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"
TABLES = sorted(DATA.rglob("*.tsv"))


def test_there_is_packaged_data_to_check():
    assert TABLES, "no .tsv files found under data/"


@pytest.mark.parametrize("table", TABLES, ids=[t.name for t in TABLES])
def test_every_row_matches_its_header(table):
    rows = [l for l in table.read_text().splitlines() if l and not l.startswith("#")]
    width = len(rows[0].split("\t"))
    bad = [(i, len(r.split("\t"))) for i, r in enumerate(rows[1:], start=2)
           if len(r.split("\t")) != width]
    assert not bad, f"{table.name}: header has {width} fields; rows {bad} do not"


@pytest.mark.parametrize("table", TABLES, ids=[t.name for t in TABLES])
def test_no_field_has_stray_whitespace(table):
    rows = [l for l in table.read_text().splitlines() if l and not l.startswith("#")]
    bad = [i for i, r in enumerate(rows, start=1)
           if any(f != f.strip() for f in r.split("\t"))]
    assert not bad, f"{table.name}: leading/trailing whitespace in rows {bad}"
