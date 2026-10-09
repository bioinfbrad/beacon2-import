"""Reference adapter: the specification's own dialect.

Layout: ``query.requestParameters.g_variant.*`` with ``query.filters``.

It now has a LIVE VALIDATION TARGET. cancercelllines accepts the nested form
and the flat form interchangeably, returning identical results, so this adapter
can be exercised against a real server -- which matters more since the EGA
outage left the b2pi adapter with none.

It is still not a default and not a fallback: a provider's declared layout is
what we send. This remains the conformance target for the Beacon Verifier and
for the self-hosted instance stood up via the MongoDB import path.

Known documentation hazards this adapter deliberately does not reproduce:
  * the range-query POST example is missing an opening brace after ``g_variant``
  * every POST example writes the key as ``"schema:"``, with a trailing colon
    inside the key name
"""

from __future__ import annotations

from typing import Any

from ..query.model import Query
from .base import BeaconAdapter


class SpecAdapter(BeaconAdapter):
    """Nested ``g_variant`` layout with filters inside ``query``."""

    stack = "spec"


    def build_post_body(self, query: Query) -> dict[str, Any]:
        """Nested ``g_variant`` with filters inside ``query``.

        The layout comes from the registry rather than from this class, so a
        provider declared ``nested_g_variant`` is served identically by any
        adapter. What makes this the spec adapter is the default dialect it is
        paired with, not special-cased assembly here.
        """
        body = self._assemble(query, self._genomic_parameters(query))
        body["$schema"] = (
            "https://raw.githubusercontent.com/ga4gh-beacon/beacon-v2/main/"
            "framework/json/requests/beaconRequestBody.json"
        )
        return body
