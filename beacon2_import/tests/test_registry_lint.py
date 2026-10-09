"""Registry lint. Runnable against the shipped YAML with no implementation.

Deliberately dependency-light and body-complete: this suite must pass from the
moment the registry exists, because it guards a class of error that produces no
exception and no visibly wrong output -- only every enum comparison quietly
failing. A comment in the YAML would not have caught the next hand-edit.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "beacon_registry.yaml"

#: YAML 1.1 coerces all of these to bool when unquoted.
YAML_BOOLEAN_TOKENS = {"yes", "no", "on", "off", "y", "n", "true", "false"}

#: Dotted paths, relative to a provider, whose values are string-typed enums.
#: `*` matches any single key.
STRING_ENUM_PATHS = (
    "stack",
    "tier",
    "request_layout",
    "filters_location",
    "get_list_style",
    "reference_style",
    "count_precision_declared",
    "copy_change_transport",
    "copy_change_expansion",
    "legacy_term_expansion",
    "granularity_ceiling.*",
    "variant_classes_served.*.status",
    "variant_classes_served.*.evidence_source",
)


def _load() -> dict:
    with REGISTRY.open() as handle:
        return yaml.safe_load(handle)


def _walk(container, path_parts: list[str]):
    """Yield (dotted_path, value) for every leaf matching a path pattern."""
    if not path_parts:
        yield "", container
        return
    head, rest = path_parts[0], path_parts[1:]
    if not isinstance(container, dict):
        return
    keys = container.keys() if head == "*" else ([head] if head in container else [])
    for key in keys:
        for sub_path, value in _walk(container[key], rest):
            yield (f"{key}.{sub_path}".rstrip("."), value)


def test_no_boolean_coercion_in_string_enums():
    """No string-typed enum field may have been coerced to a bool.

    The two values carrying the most weight in the design, `yes` and `no`, are
    exactly the two that YAML 1.1 eats.
    """
    registry = _load()
    offenders = []
    for provider_id, provider in registry["providers"].items():
        for pattern in STRING_ENUM_PATHS:
            for sub_path, value in _walk(provider, pattern.split(".")):
                if isinstance(value, bool):
                    offenders.append(f"{provider_id}.{sub_path} = {value!r}")
    assert not offenders, (
        "Boolean coercion detected. YAML 1.1 reads bare "
        + "/".join(sorted(YAML_BOOLEAN_TOKENS))
        + " as booleans -- quote the value, e.g. status: \"yes\".\nOffending: "
        + "; ".join(offenders)
    )


def test_class_statuses_are_known_strings():
    """Every declared class status is one of yes / no / unknown, as a string."""
    registry = _load()
    bad = []
    for provider_id, provider in registry["providers"].items():
        for klass, support in (provider.get("variant_classes_served") or {}).items():
            status = support.get("status")
            if not isinstance(status, str) or status not in {"yes", "no", "unknown"}:
                bad.append(f"{provider_id}.{klass}.status = {status!r}")
    assert not bad, "; ".join(bad)


def test_enabled_providers_declare_all_three_classes():
    """An omitted class is a gap in the contract, not an implicit unknown."""
    required = {"CNV", "SMALL_VARIANT", "SV"}
    registry = _load()
    gaps = []
    for provider_id, provider in registry["providers"].items():
        if not provider.get("enabled"):
            continue
        declared = set((provider.get("variant_classes_served") or {}).keys())
        missing = required - declared
        if missing:
            gaps.append(f"{provider_id} missing {sorted(missing)}")
    assert not gaps, "; ".join(gaps)


def test_declared_no_is_attributable():
    """A `no` requires an operator declaration with quotable evidence.

    Free prose in /info can support a human writing one by hand; it can never
    be parsed into one, and nothing automated may write one at all.
    """
    registry = _load()
    bad = []
    for provider_id, provider in registry["providers"].items():
        for klass, support in (provider.get("variant_classes_served") or {}).items():
            if support.get("status") != "no":
                continue
            if support.get("evidence_source") != "operator_declaration":
                bad.append(f"{provider_id}.{klass}: status no with evidence_source "
                           f"{support.get('evidence_source')!r}")
            if not (support.get("evidence") or "").strip():
                bad.append(f"{provider_id}.{klass}: status no with empty evidence")
    assert not bad, "; ".join(bad)


def test_fixture_providers_cannot_reach_the_network():
    """A test_fixture provider must have no base_url or a file:// one."""
    registry = _load()
    bad = []
    for provider_id, provider in registry["providers"].items():
        if not provider.get("test_fixture"):
            continue
        url = provider.get("base_url")
        if url is not None and not str(url).startswith("file://"):
            bad.append(f"{provider_id} base_url={url!r}")
    assert not bad, "; ".join(bad)


def test_pagination_limits_are_ints_or_null():
    """default_pagination_limit must be an int or explicitly null.

    Never a string, and never absent-by-accident: documented defaults span 200
    to 2000, and the value feeds the coalescing completeness condition.
    """
    registry = _load()
    bad = []
    for provider_id, provider in registry["providers"].items():
        if "default_pagination_limit" not in provider:
            continue
        value = provider["default_pagination_limit"]
        if value is not None and not isinstance(value, int):
            bad.append(f"{provider_id}.default_pagination_limit = {value!r}")
        if isinstance(value, bool):
            bad.append(f"{provider_id}.default_pagination_limit is a bool")
    assert not bad, "; ".join(bad)


def test_verification_tiers_are_disjoint():
    """A field cannot be both observed and documented.

    The tiers mean different things -- confirmed live versus published by the
    operator -- so a field in both is an unresolved claim about its provenance.
    """
    registry = _load()
    overlaps = []
    for provider_id, provider in registry["providers"].items():
        verification = provider.get("verification") or {}
        observed = set(verification.get("observed") or [])
        documented = set(verification.get("documented") or [])
        both = observed & documented
        if both:
            overlaps.append(f"{provider_id}: {sorted(both)}")
    assert not overlaps, "; ".join(overlaps)


def test_enabled_providers_have_no_unknown_dialect():
    """Dialect has no default: an enabled provider must state all four fields."""
    fields = ("request_layout", "filters_location", "get_list_style", "reference_style")
    registry = _load()
    bad = []
    for provider_id, provider in registry["providers"].items():
        if not provider.get("enabled"):
            continue
        for field in fields:
            if provider.get(field) in (None, "unknown"):
                bad.append(f"{provider_id}.{field} = {provider.get(field)!r}")
    assert not bad, "; ".join(bad)
