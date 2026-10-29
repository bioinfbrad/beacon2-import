"""Assign a variant class to a returned record, from its own content.

Load-bearing: a class-``unknown`` query is issued anyway (see the planner), so
its records arrive unlabelled and must be classified here. The result appears
in results.tsv as ``variant_class`` plus ``classification_basis``, so a reader
can always see WHY a row was filed where it was.

CLASSIFICATION IS BY CLAIM TYPE, NEVER BY SIZE
    The taxonomy's organising principle is the kind of claim a record makes,
    following the abundance/junction distinction VCF 4.4 draws with SVCLAIM.
    Size is an ATTRIBUTE of an event, not a claim about it, so it may not
    reassign class -- the moment it can, the cut stops being the organising
    principle and becomes one input among several.

    This has a concrete consequence. A 120 bp insertion carrying
    referenceBases and alternateBases is precisely specified by sequence: we
    know exactly what was inserted and where. That is a sequence claim, fully
    determined and merely large, so it is a SMALL_VARIANT with its length
    disclosed in the basis string -- not an SV.

    Filing it as SV would hand the SV analysis path a record it cannot
    process. SV's frequency unit is breakpoint density and adjacency counts,
    and a record with no junction evidence has no breakpoint to count. It
    would either sit in the SV bucket contributing nothing to any SV
    computation -- present but structurally invisible, a silent undercount --
    or invite something downstream to synthesise breakpoints from the interval
    ends, which is a fabricated junction: the same category of error as
    inferring a denominator from the result set, a plausible number with
    nothing real underneath.

    Users who want to filter large events regardless of class use the
    ``variant_length`` column. That is a column problem, solved with a column,
    not by bending the class.

PRECEDENCE -- most specific claim first
  1. JUNCTION claim: adjacency evidence -- a mate or breakend field, a VRS
     Adjacency, breakend notation in the alternate allele, or variantType BND,
     INV or TRA                                                          -> SV
  2. ABUNDANCE claim: a copy-number term, from ANY of the places one appears
     -- see below                                                        -> CNV
  3. REPEAT claim: an explicit repeat expansion -- a VRS 1.x
     RepeatedSequenceExpression, i.e. a repeat unit with a copy count -> REPEAT
  4. SEQUENCE claim, AT ANY LENGTH                               -> SMALL_VARIANT
     * referenceBases and alternateBases, both plain base strings; or
     * a VRS Allele whose state determines the alternate sequence:
       a LiteralSequenceExpression (the sequence itself), or a
       ReferenceLengthExpression (reference plus length determine it).
  5. no claim of any kind                                        -> UNCLASSIFIED

  Junction precedes sequence because a breakend's alternate allele is bracket
  notation rather than a sequence, so rule 4 must not capture it. Repeat
  precedes sequence because a repeat expansion may also carry ref/alt.

  A ReferenceLengthExpression IS NOT A REPEAT CLAIM. VRS 2.0 defines it as a
  sequence "derived from repeating a subsequence of an associated
  SequenceLocation", and VRS normalisation produces one for an ordinary indel
  in repetitive sequence (vrs, docs/source/conventions/normalization.rst).
  Filing those as REPEAT -- as 3.0.0 first did -- would put every small indel a
  VRS-normalised beacon returns into a class no query asks for, and quietly
  shorten SMALL_VARIANT results and counts. Its `repeatSubunitLength` is part
  of the same encoding, so it is no repeat evidence either. VRS 2.0 has no
  repeat-state type at all: RepeatedSequenceExpression is VRS 1.x only.

  A record's type LABEL never decides this. Progenetix labels the 1-base
  deletion in fixtures/classify/progenetix_rle_deletion.json SO:0001483 (SNP);
  it is classified from what its state claims.

  The ordering does the work unaided on the adjacent hard case -- ref/alt
  absent, a large interval, no junction. That record makes no sequence claim
  and no junction claim, so it reaches rule 2 and becomes CNV if a copy-number
  term is present, or falls to rule 5 and becomes unclassified if not.

WHERE AN ABUNDANCE CLAIM ACTUALLY LIVES
    ``variantType`` is not one of the places, on at least one live provider.
    A real record from a bycon instance carries NO ``variantType`` key at all;
    the claim is evidenced by::

        variation.type            == "CopyNumberChange"
        variation.variantState.id == "EFO:0030070"

    An abundance rule reading only ``variantType`` would send every CNV that
    provider holds through to the sequence rule, find no bases, and file the
    resource's entire holdings as ``unclassified``. So rule 2 checks, in order:

        variation.variantState.id      (CURIE, preferred)
        variation.type                 ("CopyNumberChange", "CopyNumberCount")
        variation.copyChange           (see the warning below)
        variantType                    (legacy, and legacy DUP/DEL)

    THREE SPELLINGS OF ONE TERM, IN ONE RECORD
        ``variation.copyChange`` is the human LABEL, not a CURIE: the live
        record reads ``"copyChange": "gain"``. The CURIE lives in
        ``variation.variantState.id``. And ``variantInternalId`` renders the
        same term with an underscore, ``EFO_0030070``.

        So one record spells the term ``gain``, ``EFO:0030070`` and
        ``EFO_0030070``. Anything reading ``copyChange`` and expecting a CURIE
        gets a bare label, which will not match any term in
        data/efo_cnv_terms.tsv. :func:`normalise_efo_term` handles all three
        forms and is the only permitted route from a record to a term id.

An unclassifiable record is KEPT and labelled. Dropping it would manufacture
the ambiguous emptiness this project exists to remove, and guessing would put
an unfalsifiable claim in a column people will filter on. ``UNCLASSIFIED`` is
reserved for records we genuinely know nothing about -- never for records we
know a great deal about that happen to be large.
"""

from __future__ import annotations

from typing import Any

from ..query.classes import VariantClass

#: Length at or above which a sequence-specified event has its size called out
#: in ``classification_basis``. Fifty bases is the widely used convention, NOT
#: a value the Beacon specification defines.
#:
#: This threshold does NOT affect classification. It controls DISCLOSURE only:
#: a sequence claim is a sequence claim at any length.
LENGTH_DISCLOSURE_THRESHOLD = 50

#: An alternate allele containing any of these is breakend or symbolic
#: notation, not a sequence, and must not be read as a sequence claim.
BREAKEND_MARKERS = ("[", "]", "<", ">", ".")


#: Labels used in variation.copyChange and elsewhere, mapped to CURIEs.
_CNV_LABELS = {
    "regional base ploidy": "EFO:0030064",
    "loss": "EFO:0030067", "copy number loss": "EFO:0030067",
    "low-level loss": "EFO:0030068", "low-level copy number loss": "EFO:0030068",
    "high-level loss": "EFO:0020073", "high-level copy number loss": "EFO:0020073",
    "complete genomic loss": "EFO:0030069", "complete genomic deletion": "EFO:0030069",
    "gain": "EFO:0030070", "copy number gain": "EFO:0030070",
    "low-level gain": "EFO:0030071", "low-level copy number gain": "EFO:0030071",
    "high-level gain": "EFO:0030072", "high-level copy number gain": "EFO:0030072",
    "focal genome amplification": "EFO:0030073", "amplification": "EFO:0030073",
}
_CNV_TERMS = frozenset(_CNV_LABELS.values())
#: DEL and DUP as variantType values. "Legacy" here is the Beacon specification's
#: own term: it marks the VCF-derived variantType values LEGACY and prefers EFO.
_LEGACY_CNV = {"DEL": "EFO:0030067", "DUP": "EFO:0030070"}
_CNV_VRS_TYPES = ("CopyNumberChange", "CopyNumberCount")
_JUNCTION_TYPES = ("BND", "INV", "TRA", "CTX", "BREAKEND")
_ADJACENCY_KEYS = ("adjacency", "mate", "mateSequenceId", "matePosition",
                   "breakend", "breakends")
_PLAIN_BASES = frozenset("ACGTNacgtn")


def _variation(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("variation")
    return value if isinstance(value, dict) else {}


def _plain(alleles: Any) -> bool:
    return isinstance(alleles, str) and bool(alleles) and set(alleles) <= _PLAIN_BASES


def classify(record: dict[str, Any]) -> tuple[VariantClass, str]:
    """Classify one normalised record by the claim it makes.

    Returns ``(variant_class, classification_basis)``. Precedence is junction,
    abundance, length, sequence -- most specific claim first -- and size never
    enters into it.
    """
    for detector, klass in (
        (_adjacency_evidence, VariantClass.SV),
        (_copy_number_evidence, VariantClass.CNV),
        (_repeat_evidence, VariantClass.REPEAT),
        (_sequence_evidence, VariantClass.SMALL_VARIANT),
    ):
        basis = detector(record)
        if basis:
            return klass, basis
    return VariantClass.UNCLASSIFIED, (
        "no claim evidence: no type term, no bases, no adjacency, no repeat fields"
    )


def classify_all(records: list[dict[str, Any]]) -> dict[VariantClass, int]:
    """Classify a batch and return counts per class.

    Used to populate the per-class outcome rows of a coalesced query.
    """
    counts: dict[VariantClass, int] = {}
    for record in records:
        klass, _ = classify(record)
        counts[klass] = counts.get(klass, 0) + 1
    return counts


def variant_length(record: dict[str, Any]) -> int | None:
    """Size of the event in bases, independent of its class.

    * sequence-specified events -- both alleles present as plain bases --
      take their size from the ALLELES: the absolute difference in lengths for
      an indel, the reference allele length for a substitution. The alleles
      win over an interval, because an insertion's interval is a single
      position however much was inserted.
    * interval-defined events: ``end - start``

    Returns None where neither alleles nor coordinates are available.

    This is the column to filter on for "is it big?", which exists precisely so
    that size never has to be smuggled into the class.
    """
    variation = _variation(record)
    ref = variation.get("referenceBases", record.get("referenceBases"))
    alt = variation.get("alternateBases", record.get("alternateBases"))
    if _plain(ref) and _plain(alt):
        if len(ref) == len(alt):
            return len(ref)
        return abs(len(alt) - len(ref))

    from .variants import extract_location

    location = extract_location(record)
    if location["start"] is not None and location["end"] is not None:
        return int(location["end"]) - int(location["start"])
    return None


def normalise_efo_term(value: str | None) -> str | None:
    """Coerce any spelling of a CNV term to a canonical CURIE.

    Accepts a CURIE (``EFO:0030070``), an underscore form (``EFO_0030070``) as
    used inside ``variantInternalId``, and a bare label (``gain``,
    ``high-level gain``) as used by ``variation.copyChange``. Returns None for
    anything it cannot map, rather than passing an unmatchable string onward.

    The single permitted route from a record's text to a term id. Reading a
    term field directly is how a bare label ends up compared against a CURIE
    and silently failing to match.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidate = text.replace("_", ":", 1) if text.upper().startswith("EFO_") else text
    if candidate.upper().startswith("EFO:"):
        candidate = "EFO:" + candidate[4:]
        return candidate if candidate in _CNV_TERMS else None
    return _CNV_LABELS.get(text.lower())


def _adjacency_evidence(record: dict[str, Any]) -> str | None:
    """Detect a junction claim.

    Checked first: mate or breakend fields, a VRS ``Adjacency``, variantType
    BND/INV/TRA, or an alternate allele containing breakend notation.
    """
    variation = _variation(record)
    for container in (variation, record):
        for key in _ADJACENCY_KEYS:
            value = container.get(key)
            if value:
                if isinstance(value, dict) and value.get("mateSequenceId"):
                    return (f"adjacency: mate at {value['mateSequenceId']}"
                            f":{value.get('matePosition', '?')}")
                return f"adjacency: {key} present"
    if str(variation.get("type", "")) == "Adjacency":
        return "adjacency: VRS Adjacency"
    for container in (variation, record):
        vt = str(container.get("variantType") or "").upper()
        if vt in _JUNCTION_TYPES:
            return f"adjacency: variantType {vt}"
    alt = variation.get("alternateBases", record.get("alternateBases"))
    if isinstance(alt, str) and any(m in alt for m in BREAKEND_MARKERS) \
            and not set(alt) <= _PLAIN_BASES:
        return "adjacency: breakend notation in alternate allele"
    return None


def _copy_number_evidence(record: dict[str, Any]) -> str | None:
    """Detect an abundance claim, checking every place a term appears.

    In priority order: ``variation.variantState.id``, ``variation.type``,
    ``variation.copyChange``, then legacy ``variantType``. Every candidate goes
    through :func:`normalise_efo_term`. Returns a basis naming the CURIE and
    the field it came from, so a reader can see which spelling was authoritative.
    """
    variation = _variation(record)
    for container, where in ((variation, "variation.variantState.id"),
                             (record, "variantState.id")):
        # The 2.2.4 cnv collection keeps variantState at TOP level.
        state = container.get("variantState")
        if isinstance(state, dict):
            term = normalise_efo_term(state.get("id"))
            if term:
                return f"{term} copy-number term ({where})"
    for container, label in ((variation, "variation.variantType"),
                             (record, "variantType")):
        raw = container.get("variantType")
        term = normalise_efo_term(raw)
        if term:
            return f"{term} copy-number term ({label})"
        if str(raw or "").upper() in _LEGACY_CNV:
            return (f"{str(raw).upper()} legacy copy-number term ({label}); "  # DEL/DUP: the spec's LEGACY values
                    f"maps to {_LEGACY_CNV[str(raw).upper()]}")
    copy_change = normalise_efo_term(variation.get("copyChange"))
    if copy_change:
        return (f"{copy_change} copy-number term (variation.copyChange label "
                f"{variation.get('copyChange')!r})")
    if str(variation.get("type", "")) in _CNV_VRS_TYPES:
        return f"copy-number claim (variation.type {variation['type']}); no term given"
    return None


def _repeat_evidence(record: dict[str, Any]) -> str | None:
    """Detect an explicit repeat-expansion claim: a VRS 1.x RepeatedSequenceExpression.

    Deliberately NOT a ReferenceLengthExpression or a bare repeatSubunitLength:
    those are VRS 2.0's normalised encoding of an ordinary indel in repetitive
    sequence, a sequence claim -- see the module docstring.
    """
    state = _variation(record).get("state")
    if isinstance(state, dict) and state.get("type") == "RepeatedSequenceExpression":
        count = state.get("count")
        return f"repeat: VRS RepeatedSequenceExpression (count {count})"
    return None


def _reference_length(variation: dict[str, Any]) -> int | None:
    """Length of the reference the state replaces: its sequence, else its location."""
    reference = variation.get("referenceSequence", variation.get("referenceBases"))
    if isinstance(reference, str) and set(reference) <= _PLAIN_BASES:
        return len(reference)
    location = variation.get("location") or {}
    start, end = location.get("start"), location.get("end")
    interval = location.get("interval") or {}
    if start is None and isinstance(interval, dict):
        start = (interval.get("start") or {}).get("value")
        end = (interval.get("end") or {}).get("value")
    if isinstance(start, int) and isinstance(end, int) and end >= start:
        return end - start
    return None


def _describe(kind: str, length: int, how: str) -> str:
    if length > LENGTH_DISCLOSURE_THRESHOLD:
        return (f"sequence-specified {kind}{how}; length {length} exceeds the "
                f"{LENGTH_DISCLOSURE_THRESHOLD} bp convention")
    return f"sequence-specified {kind}{how}; ref/alt length {length}"


def _kind(ref_length: int, alt_length: int) -> tuple[str, int]:
    if ref_length == alt_length:
        return "substitution", ref_length
    if alt_length > ref_length:
        return "insertion", alt_length - ref_length
    return "deletion", ref_length - alt_length


def _vrs_allele_evidence(variation: dict[str, Any]) -> str | None:
    """A VRS Allele whose state determines the alternate sequence."""
    state = variation.get("state")
    if not isinstance(state, dict):
        return None
    ref_length = _reference_length(variation)
    if ref_length is None:
        return None
    if state.get("type") == "ReferenceLengthExpression" and isinstance(state.get("length"), int):
        kind, length = _kind(ref_length, state["length"])
        return _describe(kind, length, f" (VRS ReferenceLengthExpression: length "
                                       f"{state['length']} over a reference of {ref_length})")
    if state.get("type") == "LiteralSequenceExpression":
        sequence = state.get("sequence")
        if isinstance(sequence, str) and set(sequence) <= _PLAIN_BASES:
            kind, length = _kind(ref_length, len(sequence))
            return _describe(kind, length, " (VRS LiteralSequenceExpression)")
    return None


def _sequence_evidence(record: dict[str, Any]) -> str | None:
    """Detect a sequence claim: both alleles present, both plain base strings.

    Applies at any length. The returned basis discloses the size when it
    exceeds :data:`LENGTH_DISCLOSURE_THRESHOLD`.
    """
    variation = _variation(record)
    ref = variation.get("referenceBases", record.get("referenceBases"))
    alt = variation.get("alternateBases", record.get("alternateBases"))
    if not (_plain(ref) and _plain(alt)):
        return _vrs_allele_evidence(variation)
    if len(ref) == len(alt):
        kind, length = "substitution", len(ref)
    elif len(alt) > len(ref):
        kind, length = "insertion", len(alt) - len(ref)
    else:
        kind, length = "deletion", len(ref) - len(alt)
    if length > LENGTH_DISCLOSURE_THRESHOLD:
        return (f"sequence-specified {kind}; length {length} exceeds the "
                f"{LENGTH_DISCLOSURE_THRESHOLD} bp convention")
    return f"sequence-specified {kind}; ref/alt length {length}"


#: Provider labels that claim a single-base substitution.
_SUBSTITUTION_LABELS = {"SO:0001483": "SNV", "SO:0000694": "SNP"}


def label_conflict(record: dict[str, Any]) -> str | None:
    """Name a provider label its own record's structure contradicts, or None.

    Classification is by structure and stays so; this only refuses to choose
    silently. Progenetix labels records SO:0001483 (SNV) that are structured as
    one-base deletions with no alternate allele.
    """
    from .verify import record_alleles

    variation = _variation(record)
    state = variation.get("variantState") or record.get("variantState")
    label = (state.get("id") if isinstance(state, dict) else None) or \
        variation.get("variantType") or record.get("variantType")
    if label not in _SUBSTITUTION_LABELS:
        return None
    reference, alternate = record_alleles(record)
    if not reference:
        return None
    if not alternate:
        structure = f"{len(reference)}-base deletion, no alternate allele"
    elif len(reference) == len(alternate):
        return None
    elif len(alternate) < len(reference):
        structure = f"{len(reference) - len(alternate)}-base deletion"
    else:
        structure = f"{len(alternate) - len(reference)}-base insertion"
    return (f"provider label {label} ({_SUBSTITUTION_LABELS[label]}) conflicts with "
            f"structure: {structure}")
