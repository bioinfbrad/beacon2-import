"""Flatten genomic variant records into the results.tsv column set.

Four location shapes, all seen in the wild:
  * ``definitions.Location.{chromosome,start,end}``
  * VRS-style ``variation.location.interval.{start,end}.value``
  * flat top-level ``start``/``end``/``referenceName``
  * FLAT VRS ``variation.location.{chromosome,start,end,sequence_id,
    sequenceReference.refgetAccession}`` with integers directly and NO
    ``interval`` nesting -- confirmed live on a bycon instance

The fourth shape carries the sequence identity twice: ``sequence_id`` in the
VRS 1.x style (``refseq:NC_000003.12``) and
``sequenceReference.refgetAccession`` in the VRS 2.0 style
(``SQ.Zu7h9AggXxhTaGVsy7h_EZSChSZGcmgX``), plus a convenience ``chromosome``.
Prefer ``refgetAccession`` where present: it is the forward direction, and a
refget accession is unambiguous where a chromosome name is not.

Three biosample shapes:
  * ``caseLevelData[]`` -- the NORMATIVE model. Each entry is one observation of
    the variant in one sample, carrying ``biosampleId``, ``individualId``,
    ``analysisId``, ``runId``.
  * a list of biosample ids
  * a comma-joined string of biosample ids

The ``caseLevelData`` explosion happens HERE, not in the analysis layer: one
row per case-level observation is exactly the unit that "count distinct
biosample_id per bin" needs, and doing it once keeps segments, frequency and
matrix consistent with each other.

``variation`` is ``oneOf`` VRS 1.3 MolecularVariation / SystemicVariation /
LegacyVariation, so ``variantType`` in a RESPONSE is descriptive, not the query
parameter echoed back.

Note also ``frequencyInPopulations``: provider-supplied population frequencies
are NOT our computed cohort frequencies and must never share a column name.
"""

from __future__ import annotations

from typing import Any

#: Entity columns for genomic variants, after the shared provenance columns.
#:
#: ``variant_length`` exists so that "is it structural?" is a COLUMN question.
#: Users reaching for that question want to filter large events regardless of
#: class, and giving them a column is what allows classify.py to file records
#: strictly by claim type without size ever bending the class.
VARIANT_COLUMNS = (
    "variant_internal_id",
    "chromosome",
    "start",
    "end",
    "variant_length",
    "reference_bases",
    "alternate_bases",
    "variant_type_raw",
    "efo_id",
    "biosample_id",
    "individual_id",
    "analysis_id",
    "run_id",
    "dataset_id",
)


def _variation(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("variation")
    return value if isinstance(value, dict) else {}


def _interval_value(endpoint: Any) -> int | None:
    """Read a coordinate that may be an int, a VRS Number, or a list."""
    if isinstance(endpoint, bool):
        return None
    if isinstance(endpoint, int):
        return endpoint
    if isinstance(endpoint, dict):
        value = endpoint.get("value")
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if isinstance(endpoint, list) and endpoint:
        return _interval_value(endpoint[0])
    return None


def flatten_variant(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one variant record into one row per case-level observation.

    Returns a single row with empty sample columns when no case-level data is
    present, rather than dropping the variant.
    """
    from .classify import normalise_efo_term, variant_length

    from ..query.coordinates import interbase_to_one_based

    location = extract_location(record)
    variation = _variation(record)
    raw_type, efo_id = extract_variant_type(record)
    length = variant_length(record)
    # THE output boundary for coordinates: the wire is 0-based half-open, and
    # results.tsv is 1-based inclusive, as COLUMN_SPECS.md promises. Converted
    # here, once. variant_length is computed from the wire values and is
    # unaffected.
    display_start, display_end = interbase_to_one_based(location.get("start"),
                                                        location.get("end"))
    from .verify import record_alleles

    alleles = record_alleles(record)
    base = {
        "variant_internal_id": str(record.get("variantInternalId") or ""),
        "chromosome": location.get("chromosome") or "",
        "start": "" if display_start is None else display_start,
        "end": "" if display_end is None else display_end,
        "variant_length": "" if length is None else length,
        # The sequence matcher's own derivation, so VRS-form records
        # (referenceSequence + state) carry their alleles too. Every bycon
        # small variant is VRS-form; these columns were blank on all of them.
        "reference_bases": alleles[0] or "",
        "alternate_bases": "" if alleles[1] is None else alleles[1],
        "variant_type_raw": raw_type or "",
        "efo_id": efo_id or normalise_efo_term(raw_type) or "",
    }
    cases = extract_case_level(record)
    if not cases:
        return [{**base, "biosample_id": "", "individual_id": "",
                 "analysis_id": "", "run_id": "", "dataset_id": ""}]
    return [{**base, **case} for case in cases]


def extract_location(record: dict[str, Any]) -> dict[str, Any]:
    """Pull chromosome, start and end from whichever of the four shapes is present.

    Returns the reference identity alongside the coordinates, preferring
    ``sequenceReference.refgetAccession`` over ``sequence_id`` over a bare
    ``chromosome``, and records which was used.
    """
    from ..query.coordinates import from_refseq_accession, normalise_chromosome

    variation = _variation(record)
    candidates = []
    if isinstance(variation.get("location"), dict):
        candidates.append(variation["location"])
    definitions = record.get("definitions")
    if isinstance(definitions, dict) and isinstance(definitions.get("Location"), dict):
        candidates.append(definitions["Location"])
    candidates.append(record)

    for location in candidates:
        interval = location.get("interval")
        if isinstance(interval, dict):
            start = _interval_value(interval.get("start"))
            end = _interval_value(interval.get("end"))
        else:
            start = _interval_value(location.get("start"))
            end = _interval_value(location.get("end"))
        if start is None and end is None:
            continue

        reference, source = None, None
        sequence_reference = location.get("sequenceReference")
        if isinstance(sequence_reference, dict) and sequence_reference.get("refgetAccession"):
            reference, source = sequence_reference["refgetAccession"], "refgetAccession"
        elif location.get("sequence_id"):
            reference, source = location["sequence_id"], "sequence_id"
        elif location.get("chromosome"):
            reference, source = str(location["chromosome"]), "chromosome"
        elif location.get("referenceName"):
            reference, source = str(location["referenceName"]), "referenceName"

        chromosome = location.get("chromosome")
        if not chromosome:
            for key in ("sequence_id", "referenceName"):
                value = location.get(key)
                if value:
                    try:
                        chromosome = (
                            from_refseq_accession(value)[1]
                            if "NC_" in str(value) else normalise_chromosome(value)
                        )
                    except ValueError:
                        chromosome = None
                    if chromosome:
                        break
        return {
            "chromosome": str(chromosome) if chromosome else None,
            "start": start, "end": end,
            "reference": reference, "reference_source": source,
        }
    return {"chromosome": None, "start": None, "end": None,
            "reference": None, "reference_source": None}


def extract_case_level(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise all three biosample-id shapes into a list of observations."""
    def case(biosample="", individual="", analysis="", run="", dataset="", instance=""):
        return {"biosample_id": str(biosample or ""),
                "individual_id": str(individual or ""),
                "analysis_id": str(analysis or ""),
                "run_id": str(run or ""), "dataset_id": str(dataset or ""),
                "instance_id": str(instance or "")}

    cases = record.get("caseLevelData")
    if isinstance(cases, list) and cases:
        return [
            case(c.get("biosampleId"), c.get("individualId"), c.get("analysisId"),
                 c.get("runId"), c.get("datasetId"), c.get("variantId"))
            for c in cases if isinstance(c, dict)
        ]
    ids = record.get("biosampleId") or record.get("biosampleIds")
    if isinstance(ids, str):
        ids = [i.strip() for i in ids.split(",") if i.strip()]
    if isinstance(ids, list):
        # The 2.2.4 cnv shape carries one observation's ids at top level.
        return [case(biosample=i, individual=record.get("individualId"),
                     analysis=record.get("analysisId")) for i in ids if i]
    return []


def extract_variant_type(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(raw_value, efo_id)``, mapping legacy DEL/DUP where possible.

    Reads every place a type appears. On at least one live provider there is no
    ``variantType`` field at all, and the term is in ``variantState.id``.
    """
    from .classify import normalise_efo_term

    variation = _variation(record)
    state = variation.get("variantState") or record.get("variantState")
    candidates = [
        state.get("id") if isinstance(state, dict) else None,
        variation.get("variantType"),
        record.get("variantType"),
        variation.get("copyChange"),
    ]
    raw = next((str(c) for c in candidates if c), None)
    efo = next((normalise_efo_term(str(c)) for c in candidates
                if c and normalise_efo_term(str(c))), None)
    return raw, efo


#: Columns identifying ONE observation. Wider than (variantInternalId,
#: biosampleId) on purpose: two analyses of the same biosample are distinct
#: observations and must both survive, while a double-expanded duplicate is
#: identical in every one of these fields.
#:
#: `run_id` is ALWAYS EMPTY on bycon -- caseLevelData carries no runId there.
#: That is fine in a tuple and the field must stay: dropping it as "unused"
#: would merge two runs of one analysis on any stack that does send it.
#:
#: Verified unique per instance against real data: 60/60 in a filtered
#: response and 2591/2591 unfiltered.
DEDUP_KEY = ("beacon_id", "variant_internal_id", "biosample_id",
             "analysis_id", "run_id")


def deduplicate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Remove repeated observations, returning ``(rows, removed)`` (R4).

    The case this exists for: one query per descendant term against a provider
    that ALSO expands server-side returns the descendant records twice.

    Precision on the exposure. Frequency counts DISTINCT biosample_id, so it is
    incidentally immune to a duplicated instance. results.tsv and the outcome
    row_count are not -- they inflate. Deduplicating here, once, gives every
    consumer the corrected rows.

    Two rules that keep it safe:
      * ``beacon_id`` is part of the key, so rows from different beacons can
        never be merged even if passed together.
      * a row with no ``variant_internal_id`` is NEVER treated as a duplicate.
        Identity cannot be shown without it, and dropping a distinct
        observation is worse than keeping a possible repeat.
    """
    seen: set[tuple[str, ...]] = set()
    kept: list[dict[str, Any]] = []
    removed = 0
    for row in rows:
        if not str(row.get("variant_internal_id") or ""):
            kept.append(row)
            continue
        key = tuple(str(row.get(column) or "") for column in DEDUP_KEY)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        kept.append(row)
    return kept, removed


def instance_id_anomalies(rows: list[dict[str, Any]]) -> list[str]:
    """Cross-check the composite key against a stack's own per-instance id.

    bycon's caseLevelData[].variantId is unique per instance (60/60 and
    2591/2591 in real responses). It is bycon-specific, so the stack-neutral
    composite key stays the deduplication key; variantId is a CONSISTENCY
    CHECK. Two rows sharing a variantId but differing in the composite key mean
    the server reported one instance as two different observations -- a data
    anomaly worth surfacing, not something to resolve silently either way.
    """
    by_instance: dict[tuple[str, str], set[tuple[str, ...]]] = {}
    for row in rows:
        instance = str(row.get("instance_id") or "")
        if not instance:
            continue
        key = tuple(str(row.get(column) or "") for column in DEDUP_KEY)
        by_instance.setdefault((str(row.get("beacon_id") or ""), instance), set()).add(key)
    return [
        f"{beacon or 'provider'} reports instance {instance} under "
        f"{len(keys)} different observation keys"
        for (beacon, instance), keys in sorted(by_instance.items()) if len(keys) > 1
    ]
