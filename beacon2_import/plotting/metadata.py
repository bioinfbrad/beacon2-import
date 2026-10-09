"""Group comparison over metadata fields, with significance testing.

The test used, the n per group and the multiple-testing correction are reported
on the figure and in a sidecar table -- a p-value without its n and its
correction is not interpretable.
"""

from __future__ import annotations

from typing import Any


def group_comparison(rows: list[dict[str, Any]], field: str, groups: list[str],
                     test: str = "logrank", **kwargs) -> Any:
    """Compare groups over a metadata field and annotate significance."""
    raise NotImplementedError
