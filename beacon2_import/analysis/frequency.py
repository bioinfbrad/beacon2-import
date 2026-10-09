"""Cohort-level frequency per genomic interval.

THREE RULES, ENFORCED IN CODE -- not documented in help text and hoped for.

1. RECORD GRANULARITY IS REQUIRED -- and only `record` counts as record.
   A provider capped at count or boolean cannot feed a frequency computation.
   Nor can one returning bycon's non-standard `aggregated`, which is a
   summarised response wearing an unfamiliar name: treating an unrecognised
   granularity as records is how aggregated data ends up divided by a
   per-sample denominator. The check is an equality test against `record`, not
   an exclusion list, so a new value defaults to refusal rather than to trust.
   Refuse BY NAME in outcomes.tsv. Never silently compute over the subset of
   providers that happened to return records.

2. THE DENOMINATOR MUST BE KNOWN AND THE NUMERATOR MUST BE EXACT.
   Denominator comes from /cohorts or /datasets (see cohorts.py); where it is
   unknown, emit counts and leave ``frequency`` empty.
   Additionally the numerator must be exact: ``countPrecision`` is normatively
   ``imprecise`` by default, and at least one implementation ships configurable
   rounding. A rounded numerator over a real denominator is the same failure as
   a fabricated denominator -- a plausible figure that is wrong -- so it gets
   the same treatment.

3. NEVER MERGE ACROSS BEACONS *OR* ACROSS VARIANT CLASSES.
   Across beacons: different cohorts, assays and ascertainment.
   Across classes: different UNITS. CNV frequency is fraction-of-samples per
   bin; small-variant recurrence is count per gene or codon; SV is breakpoint
   density. A series combining them is not merely misleading, it is
   dimensionless nonsense.
   The API makes both merges IMPOSSIBLE rather than discouraged: there is no
   function that accepts rows spanning more than one (beacon, class) pair and
   returns a single series. The grouping key is the pair, throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..query.classes import VariantClass
from .binning import Scale
from .cohorts import CohortSize


class FrequencyRefused(Exception):
    """Raised when a provider cannot support a frequency computation.

    Carries the provider id and a reason destined for outcomes.tsv.
    """


@dataclass(frozen=True)
class FrequencyRow:
    """One bin x category result for ONE provider.

    numerator, denominator and frequency are carried as three separate columns.
    That is what makes the counts-versus-frequency distinction auditable
    downstream, instead of a claim buried in an axis label.
    """

    beacon_id: str
    variant_class: str
    bin_id: str
    chromosome: str
    start: int
    end: int
    category: str
    numerator: int
    denominator: int | None
    frequency: float | None       # empty when denominator unknown or count inexact
    count_precision: str
    denominator_source: str


def compute(
    segments: list[dict[str, Any]],
    provider_id: str,
    variant_class: VariantClass,
    cohort_size: CohortSize,
    scale: Scale,
    assembly: str,
    width: int = 1_000_000,
    count_precision: str = "imprecise",
) -> list[FrequencyRow]:
    """Compute frequencies for a SINGLE (provider, class) pair.

    Deliberately single-pair: the signature is the enforcement mechanism for
    rule 3. Raises if ``segments`` contains rows of any other class.

    Pipeline: record-level rows -> bin the genome -> per bin, per category,
    count DISTINCT biosample_id -> divide by cohort size.
    """
    raise NotImplementedError


def check_eligibility(provider, returned_granularity: str, cohort_size: CohortSize,
                      count_precision: str) -> None:
    """Raise :class:`FrequencyRefused` unless all three rules are satisfied."""
    raise NotImplementedError
