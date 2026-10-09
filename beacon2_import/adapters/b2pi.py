"""EGA Beacon v2 Production Implementation adapter.

Dialect, from the B2PI README examples:
  * flat ``requestParameters`` (like bycon)
  * ``filters`` INSIDE ``query`` (like the spec, unlike bycon) -- this is the
    third layout combination, and the reason layout and filter placement are
    two independent registry fields rather than one "dialect" enum
  * ``assemblyId`` camelCase
  * filters may carry ``scope``
  * API lives under a ``/api`` subpath, so the base URL must include it

Operational notes B2PI can enforce and we must respect:
  * counts may be rounded (``imprecise_count``, ``round_to_tens``,
    ``round_to_hundreds``) -- read ``countPrecision`` per result set
  * granularity ceilings are set per dataset x entry type
  * a per-user/per-IP query budget may apply; back off on 429
  * ``/health`` gives liveness without touching a query endpoint
"""

from __future__ import annotations

from typing import Any

from ..query.model import Query
from .base import BeaconAdapter


class B2piAdapter(BeaconAdapter):
    """Flat request parameters with filters inside ``query``."""

    stack = "b2pi"


    def build_post_body(self, query: Query) -> dict[str, Any]:
        """Flat requestParameters with filters inside ``query``.

        UNVALIDATED AGAINST A LIVE SERVER. The demo instance has been down
        since 2026-09-08 (503 on every endpoint plus a bare timeout), so this
        stack's dialect rests on the project README alone. Fixtures cover the
        code paths; the assumptions themselves are untested.
        """
        return self._assemble(query, self._genomic_parameters(query))

    def health_path(self) -> str:
        """B2PI-specific ``/health`` endpoint: liveness without a query."""
        return "/health"
