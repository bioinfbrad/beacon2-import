"""The `segments` format: per-sample variant intervals.

    beacon_id  sample_id  individual_id  chromosome  start  end
    variant_class  category  value  variant_type_raw  efo_id

Tab-separated, one header line beginning with ``#``. Coordinates are 1-based
inclusive for display (converted once, at the boundary) and the header declares
this so the file is self-describing.

SNIFFER (proposed): first non-blank line starts with ``#`` and contains the
exact column set above; at least one data line has 3+ tab-separated fields with
integer ``start``/``end`` and ``start <= end``.

Conversion to and from plain tabular is documented and lossless apart from the
header comment, so users are not locked in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SEGMENTS_COLUMNS = (
    "beacon_id", "sample_id", "individual_id", "chromosome", "start", "end",
    "variant_class", "category", "value", "variant_type_raw", "efo_id",
)


def write(rows: list[dict[str, Any]], path: Path) -> None:
    """Write a segments file."""
    raise NotImplementedError


def read(path: Path) -> list[dict[str, Any]]:
    """Read a segments file."""
    raise NotImplementedError


def sniff(path: Path) -> bool:
    """Datatype sniffer predicate."""
    raise NotImplementedError
