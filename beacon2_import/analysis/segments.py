"""Per-sample variant intervals, any variant class.

Input is normalised, case-level-exploded rows; output is the `segments` format.
"""

from __future__ import annotations

from typing import Any


def build_segments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert normalised variant rows into per-sample interval records."""
    raise NotImplementedError


def categorise(row: dict[str, Any]) -> str | None:
    """Map a row onto an analysis category, using the row's own class.

    The class is read from the row rather than passed in, because by this point
    it has already been decided -- pinned by the query or assigned by
    normalise/classify.py -- and a caller-supplied class could contradict it.

    This mapping is the whole extension point: CNV maps to gain/loss, SNV to a
    molecular consequence or codon, SV to a breakpoint class. Adding a variant
    class means adding a mapping here, not new plotting code.
    """
    raise NotImplementedError
