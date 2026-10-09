"""SNV recurrence plots: amino-acid position versus count, and type composition."""

from __future__ import annotations

from typing import Any


def lollipop(rows: list[dict[str, Any]], gene: str, **kwargs) -> Any:
    """Draw recurrence against amino-acid position for one gene."""
    raise NotImplementedError


def variant_type_composition(rows: list[dict[str, Any]], **kwargs) -> Any:
    """Draw variant-class composition per group."""
    raise NotImplementedError
