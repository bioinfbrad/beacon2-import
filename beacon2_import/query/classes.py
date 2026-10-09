"""Variant classes: the second axis of the query fan-out.

A beacon's support for a query FORM says nothing about the CONTENT it holds. A
resource can implement sequence queries flawlessly and hold almost no small
variants. Class is therefore a first-class query axis, not a filter applied
afterwards, and every (provider, class) pair is planned, executed and reported
independently.

THE CNV / SV BOUNDARY
    A CNV is a structural variant in most taxonomies, so the split needs a
    principled cut. We use the one VCF 4.4 draws with ``SVCLAIM``: ``D`` for
    events known only through a change in abundance or read depth, ``J`` for
    events with a known break junction.

    That cut is not cosmetic. An abundance event is an INTERVAL property and
    bins naturally across a genome; a junction event is a POINT-PAIR and bins
    as breakpoint density. Two things that bin differently cannot share a
    series, which is why the no-merging rule falls out of the boundary rather
    than being imposed on top of it.

NAMING
    The enum value is ``SMALL_VARIANT``, not ``SNV``. The value is not
    internal: it becomes a column in results.tsv, a cell in outcomes.tsv, a
    plot title and a line in a format spec, all of which get saved and shared.
    A row describing a 12 bp frameshift labelled ``SNV`` is wrong in the data,
    and nobody downstream can correct it. ``SNV`` is accepted as a CLI input
    alias and never emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VariantClass(str, Enum):
    """Classes of genomic variation, distinguished by how they are claimed."""

    CNV = "CNV"                        # abundance   (SVCLAIM=D analogue)
    SMALL_VARIANT = "SMALL_VARIANT"    # sequence alteration
    SV = "SV"                          # adjacency   (SVCLAIM=J analogue)
    REPEAT = "REPEAT"                  # tandem repeat length

    #: Produced ONLY by normalise/classify.py for a returned record whose class
    #: cannot be determined from its content. Never selectable, never a
    #: fan-out axis, never a plotting group. It exists so that an
    #: unclassifiable record is kept and labelled rather than dropped or
    #: guessed at.
    UNCLASSIFIED = "unclassified"

    @classmethod
    def selectable(cls) -> tuple["VariantClass", ...]:
        """Classes a user may choose. Excludes UNCLASSIFIED."""
        return (cls.CNV, cls.SMALL_VARIANT, cls.SV, cls.REPEAT)

    @classmethod
    def from_cli(cls, value: str) -> "VariantClass":
        """Parse a CLI value, accepting input aliases such as ``SNV``."""
        token = str(value).strip().upper().replace("-", "_")
        if token in CLI_ALIASES:
            return CLI_ALIASES[token]
        try:
            return cls(token)
        except ValueError as exc:
            raise ValueError(
                f"unknown variant class {value!r}; expected one of "
                + ", ".join(c.value for c in cls.selectable())
            ) from exc


#: Accepted on input, never written to any output.
CLI_ALIASES = {
    "SNV": VariantClass.SMALL_VARIANT,
    "INDEL": VariantClass.SMALL_VARIANT,
    "SMALLVARIANT": VariantClass.SMALL_VARIANT,
}


@dataclass(frozen=True)
class ClassProfile:
    """What one class legally looks like on the wire, and how it is analysed."""

    variant_class: VariantClass
    label: str                          # shown wherever a human reads it
    claim: str                          # abundance | sequence | adjacency | length
    legal_query_forms: tuple[str, ...]
    primary_query_form: str
    legal_parameters: tuple[str, ...]
    forbidden_parameters: tuple[str, ...]
    frequency_unit: str
    default_plots: tuple[str, ...]
    queryable_in: tuple[str, ...]       # spec versions that can express it


PROFILES: dict[VariantClass, ClassProfile] = {
    VariantClass.CNV: ClassProfile(
        variant_class=VariantClass.CNV,
        label="Copy number variant",
        claim="abundance",
        # geneId is legal: the specification's gene query takes an optional
        # variantType, and "deletions in TP53" is the canonical use.
        legal_query_forms=("bracket", "range", "geneId"),
        primary_query_form="bracket",
        legal_parameters=("variantType", "variantMinLength", "variantMaxLength"),
        forbidden_parameters=("referenceBases", "alternateBases", "aminoacidChange"),
        frequency_unit="fraction of samples per bin",
        default_plots=("genome_profile", "per_chromosome", "circos"),
        queryable_in=("v2.0", "v2.1"),
    ),
    VariantClass.SMALL_VARIANT: ClassProfile(
        variant_class=VariantClass.SMALL_VARIANT,
        label="SNV / small indel",
        claim="sequence",
        legal_query_forms=("sequence", "range", "geneId"),
        primary_query_form="sequence",
        legal_parameters=(
            "referenceBases", "alternateBases", "aminoacidChange", "geneId",
            "variantType",
        ),
        forbidden_parameters=(),
        frequency_unit="recurrence per gene, codon or bin",
        default_plots=("lollipop", "type_composition"),
        queryable_in=("v2.0", "v2.1"),
    ),
    VariantClass.SV: ClassProfile(
        variant_class=VariantClass.SV,
        label="Structural variant",
        claim="adjacency",
        legal_query_forms=("bracket", "range", "geneId"),
        primary_query_form="bracket",
        legal_parameters=("variantType", "variantMinLength", "variantMaxLength"),
        forbidden_parameters=("referenceBases", "alternateBases"),
        frequency_unit="breakpoint density per bin; adjacency counts",
        default_plots=("breakpoint_histogram", "circos_arcs"),
        queryable_in=("v2.0", "v2.1"),
    ),
    VariantClass.REPEAT: ClassProfile(
        variant_class=VariantClass.REPEAT,
        label="Tandem repeat expansion",
        claim="length",
        legal_query_forms=(),
        primary_query_form="",
        legal_parameters=("repeatSubunitLength", "sequenceLength"),
        forbidden_parameters=(),
        frequency_unit="allele-length distribution per locus",
        default_plots=("length_histogram",),
        queryable_in=("VQS",),
    ),
}
"""Populated at import. Declared here so the shape is reviewable:

    CNV             forms bracket (primary), range
                    params variantType(EFO), variantMinLength, variantMaxLength
                    forbids referenceBases, alternateBases, aminoacidChange
                    unit   fraction of samples per bin
                    plots  genome_profile, per_chromosome, circos
                    in     v2.0, v2.1

    SMALL_VARIANT   forms sequence (primary), range, geneId
                    params referenceBases, alternateBases, aminoacidChange,
                           geneId, variantType(SO consequence)
                    forbids copy-number EFO terms
                    unit   recurrence per gene / codon / bin
                    plots  lollipop, type_composition
                    in     v2.0, v2.1

    SV              forms bracket (primary), range
                    params variantType(BND/INV/TRA/...), length bounds,
                           adjacency parameters where VQS is available
                    forbids referenceBases, alternateBases
                    unit   breakpoint density per bin, adjacency counts
                    plots  breakpoint_histogram, circos_arcs
                    in     v2.0, v2.1 (adjacency parameters: VQS only)

    REPEAT          forms none expressible before VQS
                    params repeatSubunitLength, sequenceLength
                    unit   allele-length distribution per locus
                    plots  length_histogram
                    in     VQS only
"""


def profile(variant_class: VariantClass) -> ClassProfile:
    """Return the profile for a class."""
    try:
        return PROFILES[variant_class]
    except KeyError as exc:
        raise ValueError(f"no profile for {variant_class!r}") from exc


def legal_for(variant_class: VariantClass, query_form: str) -> bool:
    """Whether a class may be expressed through a query form."""
    return query_form in profile(variant_class).legal_query_forms


def incoherent_parameters(variant_class: VariantClass, supplied: dict) -> list[str]:
    """Return parameters that contradict the class.

    Caught here rather than by a remote server, so that a copy-number term
    combined with ``alternateBases`` is a clear local message instead of an
    opaque 400 from one beacon and silent acceptance from another.
    """
    forbidden = set(profile(variant_class).forbidden_parameters)
    return sorted(
        name for name, value in supplied.items()
        if name in forbidden and value not in (None, "", (), [])
    )


def is_queryable_today(variant_class: VariantClass, provider) -> bool:
    """Whether any spec version the provider speaks can express this class.

    ``REPEAT`` returns False for every v2.0/v2.1 provider. The user asked for
    something coherent that nothing reachable can answer, so the planner emits
    a SKIP, not a validation error.
    """
    versions = set(profile(variant_class).queryable_in)
    if versions == {"VQS"}:
        return bool(getattr(provider, "extensions", {}).get("vqs"))
    return True
