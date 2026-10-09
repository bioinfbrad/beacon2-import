"""The provider-agnostic query.

One Query object is built from user input, then translated per provider by an
adapter. Nothing in this module knows about any specific beacon.

Coordinate convention: positions here are ALWAYS 0-based half-open (interbase),
matching the wire format. Conversion from the 1-based numbers users type
happens once, in coordinates.py, at the CLI boundary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from enum import Enum

from .classes import VariantClass, incoherent_parameters
from .classes import profile as class_profile


class QueryForm(str, Enum):
    SEQUENCE = "sequence"
    RANGE = "range"
    BRACKET = "bracket"
    GENE_ID = "geneId"
    #: An entry-type query -- biosamples, individuals and so on -- which has no
    #: genomic form. Variant class does not apply to it.
    ENTITY = "entity"


@dataclass(frozen=True)
class Position:
    """A start or end coordinate: one value, or two for a bracket query.

    Serialises to a JSON array in POST bodies even when single-valued
    (normative: ``minItems: 1, maxItems: 2``).
    """

    values: tuple[int, ...]

    def as_array(self) -> list[int]:
        """Return the wire representation: always a list, never a bare int."""
        return [int(v) for v in self.values]


@dataclass(frozen=True)
class OntologyFilter:
    id: str
    include_descendant_terms: bool = True
    similarity: str | None = None   # exact | high | medium | low (default exact)
    scope: str | None = None        # entry type, e.g. "biosamples"


@dataclass(frozen=True)
class AlphanumericFilter:
    id: str
    operator: str                   # = < > ! >= <=
    value: str                      # ages ALWAYS ISO 8601 periods, e.g. P70Y
    scope: str | None = None


@dataclass(frozen=True)
class CustomFilter:
    id: str
    scope: str | None = None


Filter = OntologyFilter | AlphanumericFilter | CustomFilter


@dataclass(frozen=True)
class Pagination:
    """Beware: ``skip`` counts PAGES, not records. Offset = skip * limit."""

    skip: int = 0
    limit: int = 100


@dataclass(frozen=True)
class Query:
    """A single user intent, before any provider-specific degradation."""

    form: QueryForm
    #: None for an entity query, where variant class does not apply.
    variant_class: VariantClass | None
    entity: str = "genomicVariant"

    reference_name: str | None = None     # as typed: 17, chr17 or NC_000017.11
    assembly: str | None = None           # GRCh38 / GRCh37, if user-supplied
    start: Position | None = None
    end: Position | None = None
    reference_bases: str | None = None
    alternate_bases: str | None = None
    variant_type: str | None = None       # EFO CURIE or legacy DUP/DEL
    aminoacid_change: str | None = None
    gene_id: str | None = None
    variant_min_length: int | None = None
    variant_max_length: int | None = None

    entity_id: str | None = None          # for /{entity}/{id} and nested paths
    nested_entity: str | None = None      # e.g. biosample -> genomicVariant

    filters: tuple[Filter, ...] = ()
    requested_granularity: str = "record"
    pagination: Pagination = field(default_factory=Pagination)
    dataset_ids: tuple[str, ...] = ()
    test_mode: bool = False
    #: auto | always | never. `auto` expands client-side unless the provider is
    #: OBSERVED to expand server-side; `unknown` server behaviour is not trusted.
    expand_hierarchy: str = "auto"

    def _supplied_parameters(self) -> dict:
        """The user-supplied genomic parameters, for class coherence checks."""
        return {
            "referenceBases": self.reference_bases,
            "alternateBases": self.alternate_bases,
            "aminoacidChange": self.aminoacid_change,
            "variantType": self.variant_type,
            "geneId": self.gene_id,
        }

    def validate(self) -> None:
        """Check internal consistency before any provider is contacted.

        Two layers:

        * Spec constraints, e.g. a range query takes single ``start`` and
          ``end`` values while a bracket query takes two of each, and ``start``
          without ``end`` requires ``alternateBases``.
        * Class constraints, from query/classes.py. A copy-number term
          combined with ``alternateBases`` is incoherent and is caught here,
          rather than producing an opaque 400 from one beacon and silent
          acceptance from another.
        """
        form = QueryForm(self.form)
        if form is QueryForm.ENTITY:
            return
        if form is QueryForm.SEQUENCE:
            if self.start is None or len(self.start.values) != 1:
                raise ValueError("a sequence query takes exactly one start value")
            if not self.alternate_bases:
                raise ValueError("a sequence query requires alternateBases")
        elif form is QueryForm.RANGE:
            for name, position in (("start", self.start), ("end", self.end)):
                if position is None or len(position.values) != 1:
                    raise ValueError(f"a range query takes exactly one {name} value")
        elif form is QueryForm.BRACKET:
            for name, position in (("start", self.start), ("end", self.end)):
                if position is None or len(position.values) != 2:
                    raise ValueError(f"a bracket query takes two {name} values")
        elif form is QueryForm.GENE_ID:
            if not self.gene_id:
                raise ValueError("a geneId query requires geneId")

        if form in (QueryForm.SEQUENCE, QueryForm.RANGE, QueryForm.BRACKET):
            if not self.reference_name:
                raise ValueError(f"a {form.value} query requires referenceName")

        clashes = incoherent_parameters(self.variant_class, self._supplied_parameters())
        if clashes:
            profile_label = class_profile(self.variant_class).label
            raise ValueError(
                f"{', '.join(clashes)} cannot be combined with variant class "
                f"{profile_label}: that class makes a "
                f"{class_profile(self.variant_class).claim} claim"
            )

    def for_class(self, variant_class: VariantClass) -> "Query":
        """Return a copy specialised to one class.

        The CLI builds one Query per selected class; the planner then fans out
        over providers. One Query therefore always carries exactly one class,
        which is what keeps the (provider, class) pair the unit of planning,
        execution and reporting.
        """
        return replace(self, variant_class=variant_class)

    def wire_signature(self, provider) -> str:
        """Stable digest of the request this Query produces for a provider.

        Two Queries of different classes that yield a byte-identical request
        share a signature and become candidates for coalescing. Computed from
        the adapter's built request, never from the Query's own fields, so it
        cannot drift from what is actually sent.
        """
        from ..adapters.base import adapter_for

        adapter = adapter_for(provider)
        payload = json.dumps(
            {
                "path": adapter.entity_path(
                    self.entity, self.entity_id, self.nested_entity
                ),
                "body": adapter.build_post_body(self),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
