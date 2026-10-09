"""Typed model of beacon_registry.yaml, with validation that fails loudly.

The registry is a contract, not configuration to be guessed at. Validation here
enforces the invariants agreed in design review:

  * Dialect fields have NO global default. An enabled provider that omits
    request_layout, filters_location, get_list_style or reference_style, or
    sets any of them to ``unknown``, is a hard configuration error.
  * ``unknown`` capability means SKIP, never probe. A provider may ship with
    unknown fields, but only while ``enabled: false``.
  * Anything not listed in ``verification.observed`` is an assumption. The
    planner is entitled to know the difference and to record it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..query.classes import VariantClass


class RequestLayout(str, Enum):
    """Where genomic request parameters sit inside the POST body."""

    NESTED_G_VARIANT = "nested_g_variant"  # spec: query.requestParameters.g_variant.*
    FLAT = "flat"                          # bycon and b2pi: query.requestParameters.*
    UNKNOWN = "unknown"


class FiltersLocation(str, Enum):
    """Where the ``filters`` array sits inside the POST body."""

    QUERY = "query"  # spec and b2pi: query.filters
    ROOT = "root"    # bycon: sibling of query
    UNKNOWN = "unknown"


class GetListStyle(str, Enum):
    """How multi-valued parameters are encoded in GET query strings."""

    COMMA = "comma"        # spec recommendation (still [Unreleased] in CHANGELOG)
    REPEATED = "repeated"  # used by Progenetix's own documented examples
    UNKNOWN = "unknown"


class ReferenceStyle(str, Enum):
    """How a chromosome is identified on the wire."""

    REFSEQ_ACCESSION = "refseq_accession"    # refseq:NC_000017.11
    NAME_PLUS_ASSEMBLY = "name_plus_assembly"  # referenceName=17 + assemblyId
    UNKNOWN = "unknown"


class Granularity(str, Enum):
    """Normative default is BOOLEAN -- always send this explicitly.

    ``AGGREGATED`` is a bycon extension, not a framework value: that stack's
    granularity enum is boolean/count/aggregated/record. It is recognised here
    precisely so it cannot be mistaken for record-level. An aggregated response
    is summarised, so analysis/frequency.py must refuse it exactly as it
    refuses a count -- and an unrecognised value silently treated as records is
    how aggregated data would end up under a per-sample denominator.
    """

    BOOLEAN = "boolean"
    COUNT = "count"
    AGGREGATED = "aggregated"   # non-standard; NOT record-level
    RECORD = "record"
    UNKNOWN = "unknown"


class CountPrecision(str, Enum):
    """Normative default is IMPRECISE, which is why frequency must check it."""

    EXACT = "exact"
    IMPRECISE = "imprecise"
    ROUNDED = "rounded"
    UNKNOWN = "unknown"


class ClassStatus(str, Enum):
    """Whether a provider serves a variant class.

    The asymmetry is deliberate and load-bearing:

      * ``YES`` may come from observation.
      * ``NO`` may come ONLY from an operator declaration.
      * everything else is ``UNKNOWN``.

    Absence in a sample proves nothing -- small sample, unknown sampling
    distribution -- so no observation may ever write ``NO``. Letting one do so
    would manufacture exactly the confident wrong assumption this field exists
    to prevent.
    """

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class EvidenceSource(str, Enum):
    """Where a class claim came from. Distinguishes what was observed.

    ``DOCUMENTATION`` is what most initial values honestly are, and it should
    look different at a glance from a live observation.
    """

    OPERATOR_DECLARATION = "operator_declaration"  # required for NO
    TEST_MODE_SAMPLE = "test_mode_sample"
    QUERY_OBSERVATION = "query_observation"        # records seen in normal use
    FILTERING_TERMS = "filtering_terms"            # suggestive, never conclusive
    DOCUMENTATION = "documentation"
    NONE = "none"


@dataclass(frozen=True)
class VariantClassSupport:
    """One provider's claim about one variant class."""

    status: ClassStatus = ClassStatus.UNKNOWN
    evidence_source: EvidenceSource = EvidenceSource.NONE
    evidence: str = ""       # quotable; a URL or a direct attributable statement
    observed: str | None = None   # date, null when not from a live check

    @property
    def queries_anyway(self) -> bool:
        """True for YES and UNKNOWN. Only a declared NO skips."""
        return self.status is not ClassStatus.NO


class Tier(str, Enum):
    PUBLIC = "public"
    REGISTERED = "registered"
    CONTROLLED = "controlled"


@dataclass(frozen=True)
class Verification:
    """Provenance for a provider's capability claims."""

    last_checked: str | None = None
    checked_with: str | None = None
    #: Confirmed against a live server.
    observed: tuple[str, ...] = ()
    #: Taken from the operator's own published examples or configuration.
    #: Neither a live observation nor a guess, and it must not be collapsed
    #: into either -- otherwise a published value gets mistaken for a verified
    #: one, or discarded as an assumption.
    documented: tuple[str, ...] = ()
    notes: str | None = None

    def is_observed(self, dotted_field: str) -> bool:
        """Return True if ``dotted_field`` was confirmed against a live server."""
        return dotted_field in self.observed

    def provenance_of(self, dotted_field: str) -> str:
        """Return ``observed``, ``documented`` or ``assumed`` for a field."""
        if dotted_field in self.observed:
            return "observed"
        if dotted_field in self.documented:
            return "documented"
        return "assumed"


@dataclass(frozen=True)
class ProviderCapability:
    """Everything query/planner.py needs to decide how to talk to one beacon."""

    id: str
    name: str = ""
    base_url: str | None = None
    stack: str = "unknown"
    enabled: bool = False
    tier: Tier = Tier.PUBLIC
    credential_key: str | None = None

    beacon_id_reported: str | None = None
    api_version_reported: str | None = None  # verbatim; NEVER parsed as semver

    request_layout: RequestLayout = RequestLayout.UNKNOWN
    filters_location: FiltersLocation = FiltersLocation.UNKNOWN
    get_list_style: GetListStyle = GetListStyle.UNKNOWN
    reference_style: ReferenceStyle = ReferenceStyle.UNKNOWN
    assembly_param: str | None = None

    entity_paths: dict[str, str] = field(default_factory=dict)
    entity_path_aliases: dict[str, list[str]] = field(default_factory=dict)
    nested_paths: dict[str, str] = field(default_factory=dict)
    nested_paths_supported: bool = False
    map_endpoint: str = "/map"

    supported_query_forms: tuple[str, ...] = ()
    assemblies: tuple[str, ...] = ()

    copy_change_transport: str = "variant_type"
    copy_change_expansion: str = "unknown"
    #: Whether the server maps the variantType values DEL/DUP onto EFO terms.
    #: "Legacy" is the Beacon specification's own designation for DEL/DUP.
    legacy_term_expansion: str = "none"

    granularity_ceiling: dict[str, Granularity] = field(default_factory=dict)

    count_precision_declared: CountPrecision = CountPrecision.UNKNOWN
    count_rounding_configurable: bool = False
    cohort_size_source: tuple[str, ...] = ()

    filter_scope_supported: bool | None = None
    filter_similarity_supported: bool | None = None
    filter_operators: tuple[str, ...] = ()
    filtering_terms_prefix_filter: bool = False

    requires_user_agent: bool = False
    test_mode_supported: bool = False
    #: True for synthetic fixture providers. Guarded in TWO places: here by
    #: validate(), and again in transport/http.py, which refuses to issue a
    #: request for one. Deliberately redundant -- a validation bypass should
    #: not be one mistake away from traffic at a partner endpoint.
    test_fixture: bool = False
    default_dataset_ids: tuple[str, ...] = ()
    rate_limit_per_minute: int = 30
    #: The provider's own default page size, where known. Documented defaults
    #: range from 200 to 2000, which changes how often coalescing fires and the
    #: memory footprint of one page. None means unknown: read the applied limit
    #: from the response instead of assuming one.
    default_pagination_limit: int | None = None

    #: Keyed by VariantClass. CNV, SMALL_VARIANT and SV must all be present
    #: for an enabled provider, UNKNOWN included -- an omitted class is a gap
    #: in the contract, not an implicit unknown.
    variant_classes_served: dict[VariantClass, VariantClassSupport] = field(default_factory=dict)

    #: OBSERVED on cancercelllines: both nested_g_variant and flat were
    #: accepted and returned identical results. Layout is a PREFERENCE there,
    #: not a requirement -- which also gives the spec adapter a live validation
    #: target, the one the EGA outage took away.
    request_layouts_accepted: tuple[RequestLayout, ...] = ()
    #: OBSERVED: below the total, bycon returns a RANDOM SUBSET, so successive
    #: pages are independent draws. Paging gives a sample WITH REPLACEMENT --
    #: duplicates and gaps with no way to tell which. Never paginate; request
    #: everything and verify.
    #: unknown | pages | random_subset_below_total. DEFAULT UNKNOWN, and unknown
    #: means complete-or-refuse: "pages" must be declared, never assumed. This
    #: field chooses the REMEDY (page, or retrieve everything and verify). It
    #: never decides whether a short retrieval is REPORTED as partial -- that is
    #: observed in every response, whatever the registry says.
    pagination_behaviour: str = "unknown"
    #: OBSERVED: limit 0 is honoured as "all".
    full_retrieval: str = "unknown"            # limit_0_honoured | unknown
    #: OBSERVED: numTotalResults counts caseLevelData ENTRIES (per-sample
    #: variant instances), not records. Different unit from `limit`.
    total_counts_unit: str = "records"         # records | variant_instances
    #: OBSERVED: info.counts.individuals disagrees with caseLevelData in both
    #: directions, so it is not computed over the same set. Never use it.
    info_counts_individuals_reliable: bool = True
    #: Complete-or-refuse threshold, in INSTANCES, for random-subset providers.
    full_retrieval_ceiling: int = 10000
    granularity_values_extra: tuple[str, ...] = ()
    include_resultset_responses_default: str = "HIT"
    requested_granularity_default: str = "boolean"
    extensions: dict[str, bool] = field(default_factory=dict)
    verification: Verification = field(default_factory=Verification)
    data_notes: str | None = None

    def ceiling_for(self, entity: str) -> Granularity:
        """Declared granularity ceiling for one entity type.

        Per-entity, not per-provider: B2PI sets ceilings per dataset x entry
        type. This is only a declaration -- always prefer the observed
        ``meta.returnedGranularity`` from the actual response.
        """
        return self.granularity_ceiling.get(entity, Granularity.UNKNOWN)

    def supports(self, query_form: str) -> bool:
        """Whether this provider is declared to support a query form."""
        return query_form in self.supported_query_forms

    def class_support(self, variant_class: VariantClass) -> VariantClassSupport:
        """Return the declared support for a class, defaulting to UNKNOWN."""
        return self.variant_classes_served.get(
            variant_class,
            VariantClassSupport(ClassStatus.UNKNOWN, EvidenceSource.NONE),
        )

    def entity_path(self, entity: str) -> str:
        """Path segment for an entity on this provider."""
        return self.entity_paths.get(entity, entity)

    def accepts_layout(self, layout: "RequestLayout") -> bool:
        """Whether a layout is known to be accepted, beyond the declared one."""
        return layout is self.request_layout or layout in self.request_layouts_accepted


class RegistryValidationError(ValueError):
    """Raised for a structurally invalid or unsafely-enabled registry entry."""


#: Every registry field whose value is a string-typed enum, and which YAML 1.1
#: would therefore silently coerce if left unquoted.
#:
#: The trap is not confined to `yes` and `no`. YAML 1.1 also reads `on`, `off`,
#: `y`, `n`, `true` and `false` as booleans, so a class status, a granularity
#: or a precision written bare becomes True/False with no error, no visibly
#: wrong output, and every comparison against the enum quietly failing. That is
#: the failure class that survives code review, which is why it is checked
#: rather than commented on.
STRING_ENUM_FIELDS = (
    "request_layout",
    "filters_location",
    "get_list_style",
    "reference_style",
    "stack",
    "tier",
    "count_precision_declared",
    "copy_change_transport",
    "copy_change_expansion",
    "legacy_term_expansion",
    "granularity_ceiling.*",
    "variant_classes_served.*.status",
    "variant_classes_served.*.evidence_source",
)

#: The YAML 1.1 tokens that coerce to bool. Any of these appearing unquoted in
#: a STRING_ENUM_FIELDS position is a hard error.
YAML_BOOLEAN_TOKENS = (
    "yes", "no", "on", "off", "y", "n", "true", "false",
)


def _walk_enum_paths(provider: dict, pattern: str):
    """Yield (dotted_path, value) for a STRING_ENUM_FIELDS pattern."""
    parts = pattern.split(".")

    def walk(node, remaining, trail):
        if not remaining:
            yield ".".join(trail), node
            return
        head, rest = remaining[0], remaining[1:]
        if not isinstance(node, dict):
            return
        keys = list(node.keys()) if head == "*" else ([head] if head in node else [])
        for key in keys:
            yield from walk(node[key], rest, trail + [str(key)])

    yield from walk(provider, parts, [])


def assert_no_boolean_coercion(raw: dict) -> None:
    """Reject a bool anywhere a string-typed enum is expected.

    Raises :class:`RegistryValidationError` naming the offending path AND the
    fix, so someone who hits this in a fork gets the answer rather than a type
    error thrown from somewhere unrelated three layers down.
    """
    offenders = []
    for provider_id, provider in (raw.get("providers") or {}).items():
        if not isinstance(provider, dict):
            continue
        for pattern in STRING_ENUM_FIELDS:
            for path, value in _walk_enum_paths(provider, pattern):
                if isinstance(value, bool):
                    offenders.append(f"{provider_id}.{path} is a boolean ({value})")
    if offenders:
        raise RegistryValidationError(
            "; ".join(offenders)
            + ". YAML 1.1 coerces bare "
            + "/".join(YAML_BOOLEAN_TOKENS)
            + ' to booleans -- quote the value, e.g. status: "yes".'
        )


def validate(raw: dict[str, Any]) -> None:
    """Validate a parsed registry document, raising on the first hard error.

    Hard errors:
      * an enabled provider with any dialect field missing or ``unknown``
      * an enabled provider with no ``base_url``
      * an unknown key anywhere (typos in a contract are silent misconfiguration)
      * a credentialed provider whose ``credential_key`` is not ``section|input``
      * an enabled provider not declaring all of CNV, SMALL_VARIANT and SV
      * a class with ``status: no`` whose ``evidence_source`` is anything other
        than ``operator_declaration``, or whose ``evidence`` is empty. A ``no``
        must be attributable to a quotable source: free prose in ``/info`` can
        support a human writing one by hand, but can never be parsed into one.
      * a provider marked ``test_fixture: true`` whose ``base_url`` is not a
        ``file://`` URL, so a test provider can never reach the network
      * an enabled provider declaring ``filters_location: root`` without having
        live-verified it, because root placement is silently ignored on at
        least one bycon instance and the wrong answer looks correct
      * a boolean anywhere a string-typed enum belongs -- see
        :func:`assert_no_boolean_coercion`, which validate() calls first,
        because a coerced status makes every later check meaningless
    """
    assert_no_boolean_coercion(raw)

    problems: list[str] = []
    dialect_fields = (
        "request_layout", "filters_location", "get_list_style", "reference_style",
    )
    required_classes = (
        VariantClass.CNV, VariantClass.SMALL_VARIANT, VariantClass.SV,
    )

    for provider_id, provider in (raw.get("providers") or {}).items():
        if not isinstance(provider, dict):
            problems.append(f"{provider_id}: not a mapping")
            continue

        if provider.get("test_fixture"):
            url = provider.get("base_url")
            if url is not None and not str(url).startswith("file://"):
                problems.append(
                    f"{provider_id}: test_fixture providers must have a file:// "
                    f"base_url or none, got {url!r}"
                )

        for klass, support in (provider.get("variant_classes_served") or {}).items():
            if not isinstance(support, dict):
                continue
            if support.get("status") == "no":
                if support.get("evidence_source") != "operator_declaration":
                    problems.append(
                        f"{provider_id}.{klass}: status 'no' requires "
                        f"evidence_source 'operator_declaration'"
                    )
                if not str(support.get("evidence") or "").strip():
                    problems.append(
                        f"{provider_id}.{klass}: status 'no' requires attributable "
                        f"evidence"
                    )

        if not provider.get("enabled"):
            continue

        if not provider.get("base_url"):
            problems.append(f"{provider_id}: enabled with no base_url")
        for field_name in dialect_fields:
            value = provider.get(field_name)
            if value in (None, "unknown"):
                problems.append(
                    f"{provider_id}.{field_name} is {value!r}; dialect has no "
                    f"default and must be stated for an enabled provider"
                )
        declared = set((provider.get("variant_classes_served") or {}).keys())
        missing = [k.value for k in required_classes if k.value not in declared]
        if missing:
            problems.append(
                f"{provider_id}: enabled without declaring {missing} -- an "
                f"omitted class is a gap in the contract, not an implicit unknown"
            )
        if provider.get("filters_location") == "root":
            observed = set((provider.get("verification") or {}).get("observed") or ())
            if "filters_location" not in observed:
                problems.append(
                    f"{provider_id}: filters_location 'root' must be live-verified "
                    f"(listed in verification.observed) before use. On at least one "
                    f"bycon instance, root-placed filters are silently ignored and "
                    f"the response is indistinguishable from a correct one"
                )

        key = provider.get("credential_key")
        if key and "|" not in str(key):
            problems.append(
                f"{provider_id}.credential_key {key!r} is not 'section|input'"
            )

    if problems:
        raise RegistryValidationError("; ".join(problems))
