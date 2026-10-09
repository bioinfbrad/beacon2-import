"""Filter construction, validation and value conversion.

Semantics are fixed by the spec: filters are joined by logical AND, always.
There is no OR and no NOT between filters, so no Boolean UI is offered. (The
``!`` operator negates a *value* within one alphanumeric filter; that is not
Boolean composition.)

Ages are transmitted as ISO 8601 periods, never numbers -- an explicit
implementer responsibility in the spec. Users type years; we convert.
"""

from __future__ import annotations

import re

from .model import AlphanumericFilter, CustomFilter, Filter, OntologyFilter

VALID_OPERATORS = ("=", "<", ">", "!", ">=", "<=")
VALID_SIMILARITY = ("exact", "high", "medium", "low")


def years_to_iso8601(years: float) -> str:
    """``70`` -> ``P70Y``."""
    value = float(years)
    if value.is_integer():
        return f"P{int(value)}Y"
    months = round((value - int(value)) * 12)
    return f"P{int(value)}Y{months}M"


def iso8601_to_years(period: str) -> float:
    """``P70Y`` -> ``70``, for display in results.tsv."""
    match = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?", str(period).strip())
    if not match:
        raise ValueError(f"not an ISO 8601 period: {period!r}")
    years, months, days = (int(g) if g else 0 for g in match.groups())
    return years + months / 12 + days / 365.25


def parse_curie(value: str) -> tuple[str, str]:
    """Split ``NCIT:C6975`` into prefix and local id, validating the shape."""
    text = str(value).strip()
    if ":" not in text:
        raise ValueError(f"not a CURIE: {value!r}")
    prefix, _, local = text.partition(":")
    if not prefix or not local:
        raise ValueError(f"not a CURIE: {value!r}")
    return prefix, local


def build_ontology_filter(
    term_id: str,
    include_descendant_terms: bool = True,
    similarity: str | None = None,
    scope: str | None = None,
) -> OntologyFilter:
    """Build an ontology filter, validating ``similarity`` and CURIE shape."""
    parse_curie(term_id)
    if similarity is not None and similarity not in VALID_SIMILARITY:
        raise ValueError(
            f"similarity {similarity!r} not one of {VALID_SIMILARITY}"
        )
    return OntologyFilter(
        id=str(term_id).strip(),
        include_descendant_terms=bool(include_descendant_terms),
        similarity=similarity,
        scope=scope or None,
    )


def build_alphanumeric_filter(
    field_id: str, operator: str, value: str, scope: str | None = None
) -> AlphanumericFilter:
    """Build an alphanumeric filter, validating the operator."""
    if operator not in VALID_OPERATORS:
        raise ValueError(f"operator {operator!r} not one of {VALID_OPERATORS}")
    return AlphanumericFilter(
        id=str(field_id).strip(), operator=operator, value=str(value),
        scope=scope or None,
    )


def requires_post(filters: tuple[Filter, ...]) -> bool:
    """Whether these filters force a POST request.

    Alphanumeric filters do. Their GET encoding puts the operator after a colon
    and therefore rewrites the CURIE with an underscore
    (``filters=PATO_0000011:>P70Y``); the spec also discourages non-CURIE filter
    ids in GET. Forcing POST avoids the whole trap.

    A ``scope`` or a non-default ``similarity`` also forces POST: neither has a
    GET encoding, and dropping one silently would change which records match.
    """
    for item in filters:
        if isinstance(item, AlphanumericFilter):
            return True
        if getattr(item, "scope", None):
            return True
        similarity = getattr(item, "similarity", None)
        if similarity and similarity != "exact":
            return True
    return False


def to_get_parameter(filters: tuple[Filter, ...]) -> str:
    """Encode ontology/custom filters as a comma-separated ``filters`` value."""
    return ",".join(
        item.id for item in filters if not isinstance(item, AlphanumericFilter)
    )


def filter_terms_by_prefix(terms: list[dict], prefixes: list[str]) -> list[dict]:
    """Select filtering terms by CURIE prefix, CLIENT-SIDE.

    Server-side prefix filtering does not exist on the bycon stack: passing
    ``?filters=EFO`` is interpreted as a filter term whose id is literally
    ``EFO``, matches nothing, and returns empty arrays without an error. So the
    full list is fetched and selected here.

    Matching is on the prefix before the colon, case-insensitively, because
    published prefixes are inconsistently cased (``icdom`` alongside ``NCIT``).
    """
    if not prefixes:
        return list(terms)
    wanted = {str(p).strip().lower() for p in prefixes if str(p).strip()}
    selected = []
    for term in terms:
        term_id = str(term.get("id", ""))
        prefix = term_id.split(":", 1)[0] if ":" in term_id else ""
        if prefix.lower() in wanted:
            selected.append(term)
    return selected


def validate_against_filtering_terms(
    filters: tuple[Filter, ...], known_terms: list[dict]
) -> list[str]:
    """Check user filters against a provider's /filtering_terms.

    Returns human-readable warnings rather than raising: an unrecognised term
    may still be valid, but a typo that silently matches nothing is the failure
    we are trying to make visible.
    """
    known = {str(term.get("id", "")) for term in known_terms}
    warnings = []
    for item in filters:
        if isinstance(item, AlphanumericFilter):
            continue
        if item.id not in known:
            warnings.append(
                f"{item.id} is not among this provider's filtering terms. It may "
                f"still be valid, but a filter that matches nothing returns an "
                f"empty result indistinguishable from no matches."
            )
    return warnings
