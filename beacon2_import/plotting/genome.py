"""Genome-wide and per-chromosome multi-panel frequency plots.

Series are never merged across beacons or across variant classes. The API
accepts a mapping keyed by (beacon_id, variant_class) and renders separate
panels or a labelled overlay. There is no signature that could collapse two
pairs into one series.

Each class routes to its own default: CNV to the genome frequency profile,
small variants to lollipop and type composition, SV to breakpoint histogram and
circos arcs.
"""

from __future__ import annotations

from typing import Any


def genome_wide(series_by_pair: dict[tuple[str, str], list[Any]], **kwargs) -> Any:
    """Draw a genome-wide profile, one series or panel per (beacon, class)."""
    raise NotImplementedError


def per_chromosome(series_by_pair: dict[tuple[str, str], list[Any]], **kwargs) -> Any:
    """Draw a per-chromosome panel grid."""
    raise NotImplementedError
