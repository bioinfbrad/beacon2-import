"""The `frequency` format: per-bin, per-category counts AND frequency.

    beacon_id  bin_id  chromosome  start  end  category
    numerator  denominator  frequency  count_precision  denominator_source

Carrying numerator, denominator and frequency as three separate columns is what
makes the counts-versus-frequency distinction auditable downstream, rather than
a claim buried in an axis label.

``frequency`` is EMPTY -- not zero, not computed -- when the denominator is
unknown or ``count_precision`` is not ``exact``. An empty cell is honest; a
computed value would be plausible and wrong.

SNIFFER (proposed): header comment carrying the exact column set; every data
line has a numeric ``numerator``; ``frequency`` is either empty or in [0, 1];
where ``frequency`` is non-empty, ``denominator`` is a positive integer and
``count_precision`` is ``exact``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

FREQUENCY_COLUMNS = (
    "beacon_id", "bin_id", "chromosome", "start", "end", "category",
    "numerator", "denominator", "frequency", "count_precision",
    "denominator_source",
)


def write(rows: list[Any], path: Path) -> None:
    """Write a frequency file."""
    raise NotImplementedError


def read(path: Path) -> list[dict[str, Any]]:
    """Read a frequency file."""
    raise NotImplementedError


def sniff(path: Path) -> bool:
    """Datatype sniffer predicate."""
    raise NotImplementedError
