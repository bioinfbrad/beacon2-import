"""The adapter interface and the shared request-building machinery.

An adapter converts a provider-agnostic :class:`Query` into a concrete request
for one stack's dialect, and knows how that stack lays out its paths. It does
NOT decide degradations -- the planner has already done that -- and it does not
parse results, which is normalise/'s job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..query import coordinates
from ..query.filters import requires_post, to_get_parameter
from ..query.model import AlphanumericFilter, CustomFilter, OntologyFilter, Query
from ..registry.schema import FiltersLocation, GetListStyle, ProviderCapability, ReferenceStyle

class PaginationUnsupported(ValueError):
    """A multi-page request was made against a provider whose pages are random.

    Raised rather than sent: concatenating independent random draws produces a
    sample with replacement that looks like a contiguous result set.
    """


#: Entity -> entityType value for meta.requestedSchemas[0].
ENTITY_TYPES = {
    "genomicVariant": "genomicVariant",
    "biosample": "biosample",
    "individual": "individual",
    "analysis": "analysis",
    "run": "run",
    "cohort": "cohort",
    "dataset": "dataset",
}

#: Informational endpoints. `/map` is the normative name; `/beaconMap` is the
#: documented-but-wrong alternative we fall back to on 404.
INFORMATIONAL_PATHS = {
    "root": "/",
    "info": "/info",
    "service_info": "/service-info",
    "configuration": "/configuration",
    "entry_types": "/entry_types",
    "map": "/map",
    "map_fallback": "/beaconMap",
    "filtering_terms": "/filtering_terms",
}


class BeaconAdapter(ABC):
    """Translate a planned query into a request for one stack."""

    stack: str = "base"

    def __init__(self, provider: ProviderCapability) -> None:
        self.provider = provider

    # ---- entity type -----------------------------------------------------

    def requested_entity_type(self, query: Query) -> str:
        """The entityType to place in ``meta.requestedSchemas[0]``.

        Never inferred from the path. At least one stack decides the response
        entity type from this field alone, so leaving it unset or wrong yields
        a well-formed response of the wrong type with no error raised.
        """
        entity = query.nested_entity or query.entity
        return ENTITY_TYPES.get(entity, entity)

    # ---- paths -----------------------------------------------------------

    def entity_path(self, entity: str, entity_id: str | None = None,
                    nested_entity: str | None = None) -> str:
        """Resolve the path for an entity, single record, or nested lookup."""
        if entity_id and nested_entity:
            key = f"{entity}.{nested_entity}"
            template = self.provider.nested_paths.get(key)
            if template:
                return "/" + template.format(id=entity_id).lstrip("/")
            return (
                f"/{self.provider.entity_path(entity)}/{entity_id}"
                f"/{self.provider.entity_path(nested_entity)}"
            )
        if entity_id:
            return f"/{self.provider.entity_path(entity)}/{entity_id}"
        return f"/{self.provider.entity_path(entity)}"

    def informational_paths(self) -> dict[str, str]:
        """Paths for the root informational endpoints."""
        paths = dict(INFORMATIONAL_PATHS)
        paths["map"] = self.provider.map_endpoint or "/map"
        return paths

    # ---- transport choice ------------------------------------------------

    def prefers_post(self, query: Query) -> bool:
        """Whether this query must go by POST for this provider.

        POST whenever a filter has no faithful GET encoding, and for the
        bracket form, whose two-valued start and end are awkward and
        inconsistently supported as repeated or comma-joined GET values.
        """
        if requires_post(query.filters):
            return True
        return getattr(query.form, "value", query.form) == "bracket"

    # ---- expansion ------------------------------------------------------

    def expands_server_side(self) -> bool:
        """Whether this provider expands a CNV term hierarchy itself.

        On the base class, not on one stack's adapter: the registry field is
        stack-neutral, and a b2pi or spec provider declared ``server`` must get
        the same answer. Observed on cancercelllines, where querying EFO:0030070
        also returned EFO:0030071 and EFO:0030072.

        Where this is true the client MUST NOT also expand. Only an explicit
        ``server`` counts; ``unknown`` is not read as expansion.
        """
        return self.provider.copy_change_expansion == "server"

    # ---- retrieval strategy ---------------------------------------------

    def may_paginate(self) -> bool:
        """Whether successive pages from this provider can be concatenated.

        True ONLY where contiguous pages are declared. Some providers return a
        RANDOM SUBSET below the total -- observed on cancercelllines and on
        Progenetix: identical requests return largely different records -- and
        paging those is sampling with replacement. So an UNKNOWN provider gets
        complete-or-refuse, not trust: "unknown" must never mean "the page is the
        answer". The test was once `!= "random_subset_below_total"`, which, with
        an unset field defaulting to "pages", treated six of seven providers as
        verified pagers and reported a 7% random sample as complete.
        """
        return self.provider.pagination_behaviour == "pages"

    def full_retrieval_pagination(self, total: int | None = None) -> "Pagination":
        """Pagination for retrieving EVERYTHING in one request.

        ``limit: 0`` where the provider is OBSERVED to honour it as "all"
        (cancercelllines: ~1700 records in one shot, no cap encountered).
        Otherwise ask for the reported total itself. Asking only for the
        documented page size would be a request already known to fall short
        whenever the total exceeds it -- not an attempt at the full answer. A
        server may still cap the request without saying so, which is why the
        caller always verifies the delivered instances against the total.
        """
        from ..query.model import Pagination

        if self.provider.full_retrieval == "limit_0_honoured":
            return Pagination(skip=0, limit=0)
        page = self.provider.default_pagination_limit or 100
        return Pagination(skip=0, limit=max(int(total or 0), page))

    def is_random_sample(self, records: list[dict], num_total_results: int | None) -> bool:
        """Whether a response from this provider is a random sample of the matches.

        True for a random-subset provider whenever retrieval was incomplete.
        Note this applies at ``skip: 0`` too, not only to later pages: below the
        total, the FIRST page is itself a random draw. A query matching 2591
        records with a page size of 100 returns a random 100, which looks
        exactly like a first page.

        Completeness is judged in INSTANCES, because that is the unit
        ``numTotalResults`` is expressed in on this stack. An absent total on a
        random-subset provider is treated as a sample: nothing certifies
        otherwise.
        """
        from ..normalise.envelope import is_complete_retrieval

        if self.may_paginate():
            return False
        return not is_complete_retrieval(records, num_total_results)

    def retrieval_pagination(self, query: Query) -> "Pagination":
        """The pagination to actually send for a query.

        Respects the user's pagination where pages are meaningful. Where they
        are not, a request for anything beyond the first page is REFUSED rather
        than sent: a later page would be a fresh random draw presented as a
        continuation.
        """
        if self.may_paginate():
            return query.pagination
        if query.pagination.skip:
            raise PaginationUnsupported(
                f"{self.provider.id} returns a random subset below the total, so "
                f"page {query.pagination.skip} would be an independent random draw "
                f"rather than a continuation. Request all results instead."
            )
        return query.pagination

    # ---- shared pieces ---------------------------------------------------

    def _reference(self, query: Query) -> tuple[str, str | None]:
        """Return ``(referenceName, assembly)`` in this provider's style."""
        if not query.reference_name:
            return "", None
        assembly = query.assembly or (
            self.provider.assemblies[0] if self.provider.assemblies else "GRCh38"
        )
        if self.provider.reference_style is ReferenceStyle.REFSEQ_ACCESSION:
            return coordinates.to_refseq_accession(query.reference_name, assembly), None
        return coordinates.normalise_chromosome(query.reference_name), assembly

    def _genomic_parameters(self, query: Query) -> dict[str, Any]:
        """The g_variant parameter block, before layout is applied."""
        reference, assembly = self._reference(query)
        params: dict[str, Any] = {}
        if reference:
            params["referenceName"] = reference
        if assembly and self.provider.assembly_param:
            params[self.provider.assembly_param] = assembly
        if query.start is not None:
            params["start"] = query.start.as_array()
        if query.end is not None:
            params["end"] = query.end.as_array()
        for key, value in (
            ("referenceBases", query.reference_bases),
            ("alternateBases", query.alternate_bases),
            ("variantType", query.variant_type),
            ("aminoacidChange", query.aminoacid_change),
            ("geneId", query.gene_id),
            ("variantMinLength", query.variant_min_length),
            ("variantMaxLength", query.variant_max_length),
        ):
            if value not in (None, ""):
                params[key] = value
        return params

    def _filters(self, query: Query) -> list[dict[str, Any]]:
        """Serialise filters for a POST body."""
        serialised: list[dict[str, Any]] = []
        for item in query.filters:
            entry: dict[str, Any] = {"id": item.id}
            if isinstance(item, OntologyFilter):
                entry["includeDescendantTerms"] = item.include_descendant_terms
                if item.similarity and item.similarity != "exact":
                    entry["similarity"] = item.similarity
            elif isinstance(item, AlphanumericFilter):
                entry["operator"] = item.operator
                entry["value"] = item.value
            elif not isinstance(item, CustomFilter):  # pragma: no cover
                raise TypeError(f"unknown filter type: {item!r}")
            if getattr(item, "scope", None) and self.provider.filter_scope_supported:
                entry["scope"] = item.scope
            serialised.append(entry)
        return serialised

    def _meta(self, query: Query) -> dict[str, Any]:
        return {
            "apiVersion": "2.0",
            "requestedSchemas": [{"entityType": self.requested_entity_type(query)}],
        }

    def _query_block(self, query: Query) -> dict[str, Any]:
        block: dict[str, Any] = {
            "requestedGranularity": query.requested_granularity,
            "includeResultsetResponses":
                self.provider.include_resultset_responses_default or "HIT",
            "pagination": {
                "skip": query.pagination.skip,
                "limit": query.pagination.limit,
            },
        }
        if query.test_mode:
            block["testMode"] = True
        return block

    def _assemble(self, query: Query, genomic: dict[str, Any]) -> dict[str, Any]:
        """Place parameters and filters according to the declared dialect."""
        body: dict[str, Any] = {"meta": self._meta(query)}
        query_block = self._query_block(query)

        request_parameters: dict[str, Any] = {}
        if self.provider.request_layout.value == "nested_g_variant":
            if genomic:
                request_parameters["g_variant"] = genomic
        else:
            request_parameters.update(genomic)
        if query.dataset_ids:
            request_parameters["datasets"] = {"datasetIds": list(query.dataset_ids)}
        if request_parameters:
            query_block["requestParameters"] = request_parameters

        filters = self._filters(query)
        if filters:
            if self.provider.filters_location is FiltersLocation.ROOT:
                body["filters"] = filters
            else:
                query_block["filters"] = filters

        body["query"] = query_block
        return body

    @abstractmethod
    def build_post_body(self, query: Query) -> dict[str, Any]:
        """Build the JSON POST body.

        MUST set ``meta.requestedSchemas[0].entityType`` explicitly, from
        :meth:`requested_entity_type`, for every query and every stack.
        """

    def build_get_params(self, query: Query) -> dict[str, str]:
        """Build GET query parameters.

        Multi-valued parameters follow the provider's ``get_list_style``:
        comma-concatenated by default, repeated where a provider needs it.
        Repeated style returns a list value, which the client encodes as
        repeated keys.
        """
        params: dict[str, Any] = {}
        for key, value in self._genomic_parameters(query).items():
            if isinstance(value, list):
                if self.provider.get_list_style is GetListStyle.REPEATED:
                    params[key] = [str(v) for v in value]
                else:
                    params[key] = ",".join(str(v) for v in value)
            else:
                params[key] = str(value)
        params["requestedGranularity"] = query.requested_granularity
        params["includeResultsetResponses"] = (
            self.provider.include_resultset_responses_default or "HIT"
        )
        params["skip"] = str(query.pagination.skip)
        params["limit"] = str(query.pagination.limit)
        if query.test_mode:
            params["testMode"] = "true"
        if query.dataset_ids:
            params["datasetIds"] = ",".join(query.dataset_ids)
        encoded = to_get_parameter(query.filters)
        if encoded:
            params["filters"] = encoded
        return params


def adapter_for(provider: ProviderCapability) -> BeaconAdapter:
    """Select the adapter for a provider's declared stack."""
    from .b2pi import B2piAdapter
    from .bycon import ByconAdapter
    from .spec import SpecAdapter

    adapters = {
        "bycon": ByconAdapter,
        "b2pi": B2piAdapter,
        "spec": SpecAdapter,
    }
    return adapters.get(provider.stack, SpecAdapter)(provider)
