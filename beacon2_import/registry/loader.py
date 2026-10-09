"""Merge the admin's .loc rows with the packaged capability contract.

Precedence, and the reasoning for it:

  * ``enabled`` and ``base_url`` come from the .loc file when present. The admin
    owns availability and can point at a local mirror without a pull request.
  * Every capability field comes from the YAML. An admin cannot invent a dialect.
  * A .loc row with no YAML entry yields a provider that is *listed but not
    queryable*: selecting it produces one ``skipped`` row in outcomes.tsv
    naming the missing registry entry. Silence here would be indistinguishable
    from "no matches".
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from ..query.classes import VariantClass
from .schema import (
    ClassStatus,
    CountPrecision,
    EvidenceSource,
    FiltersLocation,
    GetListStyle,
    Granularity,
    ProviderCapability,
    ReferenceStyle,
    RequestLayout,
    Tier,
    Verification,
    VariantClassSupport,
    validate,
)

DEFAULT_REGISTRY = Path(__file__).resolve().parent / "beacon_registry.yaml"

LOC_COLUMNS = ("id", "name", "base_url", "enabled", "tier", "credential_key")


def _enum(cls, value, fallback):
    if value is None:
        return fallback
    try:
        return cls(str(value))
    except ValueError:
        return fallback


def _capability(provider_id: str, raw: dict[str, Any],
                defaults: dict[str, Any]) -> ProviderCapability:
    """Build one typed capability from its YAML mapping."""
    pagination = raw.get("pagination") or {}
    default_limit = raw.get("default_pagination_limit")
    if default_limit is None:
        default_limit = pagination.get("default_limit")

    classes: dict[VariantClass, VariantClassSupport] = {}
    for name, support in (raw.get("variant_classes_served") or {}).items():
        try:
            klass = VariantClass(str(name))
        except ValueError:
            continue
        support = support or {}
        classes[klass] = VariantClassSupport(
            status=_enum(ClassStatus, support.get("status"), ClassStatus.UNKNOWN),
            evidence_source=_enum(
                EvidenceSource, support.get("evidence_source"), EvidenceSource.NONE
            ),
            evidence=str(support.get("evidence") or ""),
            observed=support.get("observed"),
        )

    ceilings = {
        entity: _enum(Granularity, value, Granularity.UNKNOWN)
        for entity, value in (raw.get("granularity_ceiling") or {}).items()
    }

    verification = raw.get("verification") or {}

    return ProviderCapability(
        id=provider_id,
        name=str(raw.get("name") or provider_id),
        base_url=raw.get("base_url"),
        stack=str(raw.get("stack") or "unknown"),
        enabled=bool(raw.get("enabled")),
        tier=_enum(Tier, raw.get("tier"), Tier.PUBLIC),
        credential_key=raw.get("credential_key"),
        beacon_id_reported=raw.get("beacon_id_reported"),
        api_version_reported=raw.get("api_version_reported"),
        request_layout=_enum(RequestLayout, raw.get("request_layout"),
                             RequestLayout.UNKNOWN),
        filters_location=_enum(FiltersLocation, raw.get("filters_location"),
                               FiltersLocation.UNKNOWN),
        get_list_style=_enum(GetListStyle, raw.get("get_list_style"),
                             GetListStyle.UNKNOWN),
        reference_style=_enum(ReferenceStyle, raw.get("reference_style"),
                              ReferenceStyle.UNKNOWN),
        assembly_param=raw.get("assembly_param"),
        entity_paths=dict(raw.get("entity_paths") or {}),
        entity_path_aliases=dict(raw.get("entity_path_aliases") or {}),
        nested_paths=dict(raw.get("nested_paths") or {}),
        nested_paths_supported=bool(raw.get("nested_paths_supported")),
        map_endpoint=str(raw.get("map_endpoint") or "/map"),
        supported_query_forms=tuple(raw.get("supported_query_forms") or ()),
        assemblies=tuple(raw.get("assemblies") or ()),
        copy_change_transport=str(raw.get("copy_change_transport") or "variant_type"),
        copy_change_expansion=str(raw.get("copy_change_expansion") or "unknown"),
        legacy_term_expansion=str(raw.get("legacy_term_expansion") or "none"),
        granularity_ceiling=ceilings,
        count_precision_declared=_enum(
            CountPrecision, raw.get("count_precision_declared"), CountPrecision.UNKNOWN
        ),
        count_rounding_configurable=bool(raw.get("count_rounding_configurable")),
        cohort_size_source=tuple(raw.get("cohort_size_source") or ()),
        filter_scope_supported=raw.get("filter_scope_supported")
        if isinstance(raw.get("filter_scope_supported"), bool) else None,
        filter_similarity_supported=raw.get("filter_similarity_supported")
        if isinstance(raw.get("filter_similarity_supported"), bool) else None,
        filter_operators=tuple(raw.get("filter_operators") or ()),
        filtering_terms_prefix_filter=bool(raw.get("filtering_terms_prefix_filter")),
        requires_user_agent=bool(raw.get("requires_user_agent")),
        test_mode_supported=bool(raw.get("test_mode_supported")),
        test_fixture=bool(raw.get("test_fixture")),
        default_dataset_ids=tuple(raw.get("default_dataset_ids") or ()),
        rate_limit_per_minute=int(
            raw.get("rate_limit_per_minute")
            or defaults.get("rate_limit_per_minute", 30)
        ),
        default_pagination_limit=default_limit,
        request_layouts_accepted=tuple(
            _enum(RequestLayout, v, RequestLayout.UNKNOWN)
            for v in (raw.get("request_layouts_accepted") or ())
        ),
        # Unset means UNKNOWN, never "pages": an undeclared provider is not
        # trusted to page contiguously. See schema.pagination_behaviour.
        pagination_behaviour=str(raw.get("pagination_behaviour") or "unknown"),
        full_retrieval=str(raw.get("full_retrieval") or "unknown"),
        total_counts_unit=str(raw.get("total_counts_unit") or "records"),
        info_counts_individuals_reliable=bool(
            raw.get("info_counts_individuals_reliable", True)
        ),
        full_retrieval_ceiling=int(
            raw.get("full_retrieval_ceiling")
            or defaults.get("full_retrieval_ceiling", 10000)
        ),
        granularity_values_extra=tuple(raw.get("granularity_values_extra") or ()),
        include_resultset_responses_default=str(
            raw.get("include_resultset_responses_default") or "HIT"
        ),
        requested_granularity_default=str(
            raw.get("requested_granularity_default") or "boolean"
        ),
        variant_classes_served=classes,
        extensions=dict(raw.get("extensions") or {}),
        verification=Verification(
            last_checked=verification.get("last_checked"),
            checked_with=verification.get("checked_with"),
            observed=tuple(verification.get("observed") or ()),
            documented=tuple(verification.get("documented") or ()),
            notes=verification.get("notes"),
        ),
        data_notes=raw.get("data_notes"),
    )


def load_registry(path: Path | None = None) -> dict[str, ProviderCapability]:
    """Load and validate the packaged beacon_registry.yaml."""
    handle = Path(path) if path else DEFAULT_REGISTRY
    raw = yaml.safe_load(handle.read_text()) or {}
    validate(raw)
    defaults = raw.get("defaults") or {}
    return {
        provider_id: _capability(provider_id, provider or {}, defaults)
        for provider_id, provider in (raw.get("providers") or {}).items()
    }


def load_loc_table(path: Path) -> list[dict[str, str]]:
    """Parse beacon_providers.loc.

    Columns: id, name, base_url, enabled, tier, credential_key.
    Lines beginning with ``#`` are comments; blank lines are ignored.
    """
    rows: list[dict[str, str]] = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        fields += [""] * (len(LOC_COLUMNS) - len(fields))
        rows.append(dict(zip(LOC_COLUMNS, (f.strip() for f in fields))))
    return rows


def resolve(
    selected_ids: list[str],
    loc_path: Path | None = None,
    registry_path: Path | None = None,
) -> tuple[list[ProviderCapability], list[tuple[str, str]]]:
    """Resolve user-selected provider ids into capabilities.

    Returns ``(resolvable, unresolvable)`` where each unresolvable entry is
    ``(provider_id, reason)`` destined for outcomes.tsv with status ``skipped``.
    Never raises for a single bad provider: partial failure is normal.
    """
    registry = load_registry(registry_path)
    overrides = {}
    if loc_path is not None and Path(loc_path).is_file():
        overrides = {row["id"]: row for row in load_loc_table(loc_path)}

    resolvable: list[ProviderCapability] = []
    unresolvable: list[tuple[str, str]] = []

    for provider_id in selected_ids:
        capability = registry.get(provider_id)
        if capability is None:
            unresolvable.append((
                provider_id,
                "no entry in beacon_registry.yaml, so no dialect is known for it; "
                "it was listed but could not be queried",
            ))
            continue
        row = overrides.get(provider_id)
        if row:
            replacements: dict[str, Any] = {}
            if row.get("base_url"):
                replacements["base_url"] = row["base_url"]
            if row.get("enabled") != "":
                replacements["enabled"] = row["enabled"] in ("1", "true", "True")
            if replacements:
                capability = replace(capability, **replacements)
        resolvable.append(capability)

    return resolvable, unresolvable
