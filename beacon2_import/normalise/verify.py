"""Verify every returned record against the query that produced it.

TRUST THE RESPONSE, NOT THE QUERY OR THE DECLARATION. Three instances of one
principle, each learned from a real failure:

  * PARTIALITY -- judged from the instances returned against numTotalResults
    (normalise/envelope.py), never from the registry's pagination claim.
  * CLASS -- judged from each record's own structure (normalise/classify.py),
    never from the class the query asked for. A record labelled by the query
    that requested it has not been observed as anything: sixty copy-number
    records once came back to a SMALL_VARIANT query, were stamped
    SMALL_VARIANT, and were offered as evidence to upgrade the registry.
  * REGION -- judged from each record's coordinates, with the semantics of the
    query form that was sent. Chromosome 3 records once came back to a
    chromosome 17 query. bycon has already been seen silently ignoring a
    misplaced filter, so a provider ignoring a parameter is a real risk.

Every consumer goes through :func:`verify_records`, so none can skip a check.
A record that fails is excluded from the results and the row counts, and
counted, with its reason, for the run report.

What is NOT checked: the exact term. Server-side expansion legitimately returns
descendants -- low-level loss for a loss query -- so the check is by class.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..query.classes import VariantClass
from ..query.coordinates import normalise_chromosome
from .classify import classify
from .variants import extract_location


@dataclass(frozen=True)
class Region:
    """The region a query asked for, in the 0-based coordinates sent.

    semantics:
      overlap      range query: the record overlaps [start, end)
      bracket      bracket query: start within [a, b] and end within [c, d]
      position     sequence query: the record starts at exactly `start`
      containment  the MongoDB cnv path: the record lies within [start, end],
                   in coordinates as stored -- 2.2.4's semantics, unchanged
    """

    chromosome: str | None
    semantics: str
    start: tuple[int | None, ...] = ()
    end: tuple[int | None, ...] = ()

    def describe(self) -> str:
        where = f"chromosome {self.chromosome}" if self.chromosome else "any chromosome"
        return f"{where}, {self.semantics} {self.start}-{self.end}"


def region_for(query) -> Region | None:
    """The region a Query asked for, or None where it has no coordinates.

    Gene and entity queries carry no coordinates: only their class is checked.
    """
    form = getattr(query.form, "value", query.form)
    chromosome = normalise_chromosome(query.reference_name) if query.reference_name else None
    starts = tuple(query.start.values) if query.start is not None else ()
    ends = tuple(query.end.values) if query.end is not None else ()
    if form == "range":
        return Region(chromosome, "overlap", starts, ends)
    if form == "bracket":
        return Region(chromosome, "bracket", starts, ends)
    if form == "sequence":
        return Region(chromosome, "position", starts)
    return None


def class_constrained(query) -> bool:
    """Whether the request itself constrained the class it would get back.

    A variant type, bases or an amino-acid change narrows the request. Without
    any of them -- a range query for CNV with no term, say -- a provider
    legitimately returns every variant in the region, so a record of another
    class answers nothing but signals nothing wrong either.
    """
    return any(value not in (None, "") for value in (
        query.variant_type, query.reference_bases, query.alternate_bases,
        query.aminoacid_change))


@dataclass(frozen=True)
class Checked:
    """A record that answers the query, with its class from its own structure."""

    record: dict[str, Any]
    variant_class: VariantClass
    basis: str


@dataclass
class Verification:
    """What a response held, sorted into answers and non-answers."""

    kept: list[Checked] = field(default_factory=list)
    other_class: Counter = field(default_factory=Counter)
    unclassified: int = 0
    outside_region: int = 0
    no_location: int = 0
    example: str = ""
    class_constrained: bool = False
    requested: tuple[VariantClass, ...] = ()

    @property
    def excluded(self) -> int:
        return (sum(self.other_class.values()) + self.unclassified
                + self.outside_region + self.no_location)

    @property
    def parameter_ignored(self) -> bool:
        """A sign the provider did not apply what was sent -- so its reported
        total no longer counts answers to this query, and cannot be exact."""
        return self.outside_region > 0 or (
            self.class_constrained and sum(self.other_class.values()) > 0)

    def notes(self) -> list[str]:
        out = []
        wanted = ", ".join(k.value for k in self.requested) or "the requested class"
        if self.other_class:
            got = ", ".join(k.value for k, _ in self.other_class.most_common())
            n = sum(self.other_class.values())
            if self.class_constrained:
                out.append(f"{n} records returned did not match the requested class "
                           f"(got {got}); the provider may have ignored a query parameter. "
                           f"They are excluded from the results")
            else:
                out.append(f"{n} records returned were of other classes (got {got}), as a "
                           f"request without a class constraint allows; they are excluded "
                           f"from the {wanted} results")
        if self.unclassified:
            out.append(f"{self.unclassified} records returned could not be classified from "
                       f"their own structure, so are not reported as {wanted}; they are "
                       f"excluded from the results")
        if self.outside_region:
            out.append(f"{self.outside_region} records returned lay outside the requested "
                       f"region ({self.example}); the provider may have ignored a query "
                       f"parameter. They are excluded from the results")
        if self.no_location:
            out.append(f"{self.no_location} records returned carried no coordinates to check "
                       f"against the requested region; they are excluded from the results")
        return out


def _record_chromosome(location: dict[str, Any]) -> str | None:
    for candidate in (location.get("chromosome"), location.get("reference")):
        if candidate:
            try:
                return normalise_chromosome(str(candidate))
            except (ValueError, KeyError):
                continue
    return None


def _is_reference_length_expression(record: dict[str, Any]) -> bool:
    variation = record.get("variation") if isinstance(record.get("variation"), dict) else record
    state = variation.get("state") if isinstance(variation, dict) else None
    return isinstance(state, dict) and state.get("type") == "ReferenceLengthExpression"


def _in_region(region: Region, start: int, end: int, record: dict[str, Any]) -> bool:
    if region.semantics == "overlap":
        return start < region.end[0] and end > region.start[0]
    if region.semantics == "bracket":
        start_min, start_max = region.start
        end_min, end_max = region.end
        return start_min <= start <= start_max and end_min <= end <= end_max
    if region.semantics == "position":
        position = region.start[0]
        if start == position:
            return True
        # VRS normalisation widens an indel in repetitive sequence over the whole
        # repeat (vrs docs/source/conventions/normalization.rst), so such a
        # ReferenceLengthExpression starts at the repeat, not at the queried base.
        return _is_reference_length_expression(record) and start <= position <= end
    if region.semantics == "containment":
        low = region.start[0] if region.start else None
        high = region.end[0] if region.end else None
        return (low is None or start >= low) and (high is None or end <= high)
    raise ValueError(f"unknown region semantics {region.semantics!r}")


def verify_records(records: Iterable[dict[str, Any]],
                   requested: Iterable[VariantClass] | None,
                   region: Region | None,
                   constrained: bool = False) -> Verification:
    """Classify every record from its own structure and check it answers the query.

    ``requested`` is the set of classes that would answer it, or None where any
    class does (an unfiltered nested lookup). ``region`` is from
    :func:`region_for`, or None where the query had no coordinates.
    """
    wanted = tuple(requested) if requested is not None else ()
    verification = Verification(class_constrained=constrained, requested=wanted)
    for record in records:
        klass, basis = classify(record)
        if requested is not None and klass not in wanted:
            if klass is VariantClass.UNCLASSIFIED:
                verification.unclassified += 1
            else:
                verification.other_class[klass] += 1
            continue
        if region is not None:
            location = extract_location(record)
            chromosome = _record_chromosome(location)
            start, end = location.get("start"), location.get("end")
            if chromosome is None or start is None or end is None:
                verification.no_location += 1
                continue
            if region.chromosome is not None and chromosome != region.chromosome:
                verification.outside_region += 1
                verification.example = verification.example or (
                    f"e.g. chromosome {chromosome} for a chromosome {region.chromosome} query")
                continue
            if not _in_region(region, int(start), int(end), record):
                verification.outside_region += 1
                verification.example = verification.example or (
                    f"e.g. {chromosome}:{int(start) + 1}-{end} for {region.describe()}")
                continue
        verification.kept.append(Checked(record, klass, basis))
    return verification
