"""Per-sample summary statistics over genomic scales."""

from __future__ import annotations

from typing import Any

from .binning import Scale


def per_sample_statistics(
    segments: list[dict[str, Any]], scale: Scale, assembly: str
) -> list[dict[str, Any]]:
    """Summarise each sample's variant burden at the requested scale.

    Reports covered fraction and segment count per category, per bin.
    """
    raise NotImplementedError
