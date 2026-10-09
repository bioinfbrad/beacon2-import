"""Flatten biosample / individual / cohort / dataset / run / analysis records.

COLUMNS ARE DERIVED FROM THE DEFAULT MODEL SCHEMAS, not from memory. Each spec
below names the schema property it reads and its schema type, verified against
models/src/beacon-v2-default-model/*/defaultSchema.yaml and the shared
definitions in common/:

  term          an OntologyTerm {id, label}         -> <col>_id, <col>_label
  terms         array of OntologyTerm               -> <col>_ids, <col>_labels
  nested_term   object holding an OntologyTerm      -> <col>_id, <col>_label
  nested_terms  array of objects, each with one     -> <col>_ids, <col>_labels
  scalar        string / integer / timestamp        -> <col>

Cohorts and datasets are where a frequency DENOMINATOR would come from, and the
schema says something worth knowing: cohorts carry `cohortSize`, but datasets
have NO size field in the default model. Only cohorts can supply a denominator
without an implementation-specific extension.
"""

from __future__ import annotations

from typing import Any

# (column, schema property, kind, nested key or None)
_SPECS: dict[str, tuple[tuple[str, str, str, str | None], ...]] = {
    "biosample": (
        ("biosample_id", "id", "scalar", None),
        ("individual_id", "individualId", "scalar", None),
        ("biosample_status", "biosampleStatus", "term", None),
        ("sample_origin_type", "sampleOriginType", "term", None),
        ("sample_origin_detail", "sampleOriginDetail", "term", None),
        ("histological_diagnosis", "histologicalDiagnosis", "term", None),
        ("tumor_progression", "tumorProgression", "term", None),
        ("tumor_grade", "tumorGrade", "term", None),
        ("pathological_stage", "pathologicalStage", "term", None),
        ("pathological_tnm_finding", "pathologicalTnmFinding", "terms", None),
        ("diagnostic_markers", "diagnosticMarkers", "terms", None),
        ("phenotypic_features", "phenotypicFeatures", "nested_terms", "featureType"),
        ("obtention_procedure", "obtentionProcedure", "nested_term", "procedureCode"),
        ("sample_processing", "sampleProcessing", "term", None),
        ("sample_storage", "sampleStorage", "term", None),
        ("collection_date", "collectionDate", "scalar", None),
        ("collection_moment", "collectionMoment", "scalar", None),
        ("notes", "notes", "scalar", None),
    ),
    "individual": (
        ("individual_id", "id", "scalar", None),
        ("sex", "sex", "term", None),
        ("karyotypic_sex", "karyotypicSex", "scalar", None),
        ("ethnicity", "ethnicity", "term", None),
        ("geographic_origin", "geographicOrigin", "term", None),
        ("diseases", "diseases", "nested_terms", "diseaseCode"),
        ("phenotypic_features", "phenotypicFeatures", "nested_terms", "featureType"),
        ("treatments", "treatments", "nested_terms", "treatmentCode"),
        ("procedures", "interventionsOrProcedures", "nested_terms", "procedureCode"),
        ("exposures", "exposures", "nested_terms", "exposureCode"),
        ("measurements", "measurements", "nested_terms", "assayCode"),
    ),
    "analysis": (
        ("analysis_id", "id", "scalar", None),
        ("run_id", "runId", "scalar", None),
        ("biosample_id", "biosampleId", "scalar", None),
        ("individual_id", "individualId", "scalar", None),
        ("analysis_date", "analysisDate", "scalar", None),
        ("pipeline_name", "pipelineName", "scalar", None),
        ("pipeline_ref", "pipelineRef", "scalar", None),
        ("aligner", "aligner", "scalar", None),
        ("variant_caller", "variantCaller", "scalar", None),
    ),
    "run": (
        ("run_id", "id", "scalar", None),
        ("biosample_id", "biosampleId", "scalar", None),
        ("individual_id", "individualId", "scalar", None),
        ("run_date", "runDate", "scalar", None),
        ("library_source", "librarySource", "term", None),
        ("library_selection", "librarySelection", "scalar", None),
        ("library_strategy", "libraryStrategy", "scalar", None),
        ("library_layout", "libraryLayout", "scalar", None),
        ("platform", "platform", "scalar", None),
        ("platform_model", "platformModel", "term", None),
    ),
    "cohort": (
        ("cohort_id", "id", "scalar", None),
        ("name", "name", "scalar", None),
        ("cohort_type", "cohortType", "scalar", None),
        ("cohort_design", "cohortDesign", "term", None),
        ("cohort_size", "cohortSize", "scalar", None),
        ("cohort_data_types", "cohortDataTypes", "terms", None),
    ),
    "dataset": (
        ("dataset_id", "id", "scalar", None),
        ("name", "name", "scalar", None),
        ("description", "description", "scalar", None),
        ("create_date_time", "createDateTime", "scalar", None),
        ("update_date_time", "updateDateTime", "scalar", None),
        ("version", "version", "scalar", None),
        ("external_url", "externalUrl", "scalar", None),
    ),
}


def _columns(entity: str) -> tuple[str, ...]:
    out: list[str] = []
    for column, _, kind, _ in _SPECS[entity]:
        if kind in ("term", "nested_term"):
            out += [f"{column}_id", f"{column}_label"]
        elif kind in ("terms", "nested_terms"):
            out += [f"{column}_ids", f"{column}_labels"]
        else:
            out.append(column)
    return tuple(out)


#: Final column set per entity, in order. Consumed by formats/results.py.
ENTITY_COLUMNS: dict[str, tuple[str, ...]] = {e: _columns(e) for e in _SPECS}


def _term(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        return str(value.get("id") or ""), str(value.get("label") or "")
    return "", ""


def _scalar(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    return str(value)


def _flatten(entity: str, record: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column, prop, kind, nested in _SPECS[entity]:
        value = record.get(prop)
        if kind == "scalar":
            row[column] = _scalar(value)
        elif kind in ("term", "nested_term"):
            target = value.get(nested) if kind == "nested_term" and isinstance(value, dict) else value
            row[f"{column}_id"], row[f"{column}_label"] = _term(target)
        else:
            items = value if isinstance(value, list) else []
            terms = [_term(item.get(nested) if kind == "nested_terms" and isinstance(item, dict)
                           else item) for item in items]
            row[f"{column}_ids"] = ",".join(i for i, _ in terms if i)
            row[f"{column}_labels"] = ",".join(l for _, l in terms if l)
    return row


def flatten_biosample(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one biosample record."""
    return _flatten("biosample", record)


def flatten_individual(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one individual record."""
    return _flatten("individual", record)


def flatten_cohort(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one cohort record, including its declared cohortSize."""
    return _flatten("cohort", record)


def flatten_dataset(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one dataset record. The default schema has no size field."""
    return _flatten("dataset", record)


def flatten_run(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one run record."""
    return _flatten("run", record)


def flatten_analysis(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one analysis record."""
    return _flatten("analysis", record)


FLATTENERS = {
    "biosample": flatten_biosample,
    "individual": flatten_individual,
    "cohort": flatten_cohort,
    "dataset": flatten_dataset,
    "run": flatten_run,
    "analysis": flatten_analysis,
}
