"""Sample x bin (or sample x feature) matrices for clustering and heatmaps."""

from __future__ import annotations

from typing import Any

from .binning import Scale


def build_matrix(
    segments: list[dict[str, Any]], scale: Scale, assembly: str, width: int = 1_000_000
) -> dict[str, Any]:
    """Build a sample-by-bin matrix with a category-coded value per cell."""
    raise NotImplementedError
