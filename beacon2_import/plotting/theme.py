"""Shared figure styling, and the subtitle rules that keep figures honest.

Any figure drawn from counts rather than frequencies, or from imprecise counts,
carries that fact in its subtitle. A reader who sees only the figure must not be
able to mistake a count for a frequency.
"""

from __future__ import annotations


def apply_theme(ax) -> None:
    """Apply consistent styling."""
    raise NotImplementedError


def provenance_subtitle(beacon_id: str, denominator_source: str,
                        count_precision: str) -> str:
    """Build the mandatory provenance subtitle for a plotted series."""
    raise NotImplementedError
