"""bycon adapter (Progenetix, cancercelllines, other Beacon+ instances).

Dialect, from the published implementation notes:
  * flat ``requestParameters`` -- no ``g_variant`` nesting
  * ``filters`` at the ROOT of the body, a sibling of ``query``
  * ``assemblyid`` lowercase in POST bodies (the same page writes ``assemblyId``
    in its GET example; treat both as unconfirmed until observed)
  * ``requestParameters.datasets.datasetIds`` as a nested object
  * the RESPONSE ENTITY TYPE is decided by meta.requestedSchemas[0].entityType
    and NOT by the endpoint path -- the docs say explicitly that POSTing to the
    variants path or the biosamples path makes no difference. Set it every
    time; verify it after parsing.
  * the published examples contain the "schema:" trailing-colon typo as well,
    independently corroborating that examples on these pages need validating
    before use
  * FILTERS GO INSIDE ``query``. The published example placing them at the
    body root was refuted live: at the root they are silently ignored and the
    response is indistinguishable from a correct one.
  * both the nested and flat layouts are accepted, returning identical results
  * CNV term hierarchies are expanded SERVER-SIDE, so the client must not
    expand as well or samples are counted more than once
  * ``receivedRequestSummary`` does NOT echo query parameters -- referenceName,
    start, end, variantType and assembly never appear -- so parameter handling
    cannot be verified from the echo and must be judged from the returned
    records. Filters DO echo, which is what makes the placement finding
    reliable.
  * entity path naming varies BETWEEN bycon instances: Progenetix leads with
    ``/g_variants``, cancercelllines with ``/genomicVariations``. Paths come
    from the registry per provider, never from this class.

Extensions available but OFF by default: ``filterLogic=OR``, phenopacket
schema, geo queries. Enabling a non-standard extension would make one
provider's results follow a different code path from every other beacon.
"""

from __future__ import annotations

from typing import Any

from ..query.model import Query
from .base import BeaconAdapter


class ByconAdapter(BeaconAdapter):
    """Flat request parameters with root-level filters."""

    stack = "bycon"


    def build_post_body(self, query: Query) -> dict[str, Any]:
        """Flat requestParameters, filters wherever the registry says.

        FILTER PLACEMENT IS NOT A STYLE CHOICE HERE. Observed live: the same
        filter inside ``query`` matched 60 records and at the body root matched
        2591 -- the whole unfiltered set -- with no filter echoed and a
        well-formed response either way. Root placement is silently ignored, so
        the registry value governs and is validated as live-verified before
        ``root`` may be used at all.
        """
        return self._assemble(query, self._genomic_parameters(query))


    def filtering_terms_params(self, prefixes: list[str] | None = None) -> dict[str, str]:
        """Parameters for /filtering_terms. MUST NOT pass ``prefixes`` on.

        Verified against a live instance: ``?filters=EFO`` is interpreted as a
        filter term whose id is literally ``EFO``, matches nothing, and returns
        empty arrays with no error. Prefix selection is done client-side by
        query.filters.filter_terms_by_prefix. This signature keeps the argument
        only so that a caller passing one is ignored rather than silently
        producing an empty result.
        """
        params: dict[str, str] = {}
        if self.provider.default_pagination_limit:
            params["limit"] = str(self.provider.default_pagination_limit)
        return params
