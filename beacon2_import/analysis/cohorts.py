"""Denominator resolution -- the hard problem in frequency computation.

Frequency is ``samples_with_variant / total_samples_in_cohort``. A Beacon
returns the NUMERATOR only. Samples without the variant were never returned, so
dividing by the number of returned samples yields 100% everywhere: a
plausible-looking, completely wrong figure.

Denominators are therefore taken from ``/cohorts`` or ``/datasets``. Where
neither supplies one, the denominator is UNKNOWN and the frequency column is
left empty -- counts are emitted and labelled as counts. We never infer a
denominator from the result set.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CohortSize:
    """A denominator and where it came from."""

    provider_id: str
    cohort_id: str | None
    dataset_id: str | None
    size: int | None
    source: str  # cohorts | datasets | unknown

    @property
    def is_usable(self) -> bool:
        """Whether this may be used as a divisor."""
        raise NotImplementedError


def resolve_cohort_size(provider, cohort_id=None, dataset_id=None) -> CohortSize:
    """Fetch a cohort or dataset size from the provider's own metadata."""
    raise NotImplementedError


def denominators_for(providers: list, dataset_ids: tuple[str, ...]) -> dict[str, CohortSize]:
    """Resolve a denominator per provider. Missing ones return ``size=None``."""
    raise NotImplementedError
