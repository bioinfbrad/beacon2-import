"""The `matrix` format: sample x bin (or sample x feature).

Header line lists bin ids; first column is ``beacon_id:sample_id`` so that rows
from different beacons remain distinguishable after any downstream join.

SNIFFER (proposed): first line starts with ``#matrix``; declares
``scale=`` and ``assembly=``; all subsequent lines have the same field count as
the header.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write(matrix: dict[str, Any], path: Path) -> None:
    """Write a matrix file."""
    raise NotImplementedError


def read(path: Path) -> dict[str, Any]:
    """Read a matrix file."""
    raise NotImplementedError


def sniff(path: Path) -> bool:
    """Datatype sniffer predicate."""
    raise NotImplementedError
