"""Circular genome layouts, including SV adjacency arcs."""

from __future__ import annotations

from typing import Any


def circos(series_by_pair: dict[tuple[str, str], list[Any]], **kwargs) -> Any:
    """Draw a circos-style layout."""
    raise NotImplementedError
