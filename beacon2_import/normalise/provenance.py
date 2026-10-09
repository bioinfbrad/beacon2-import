"""Provenance columns carried by EVERY row of results.tsv.

Because every row carries ``beacon_id`` AND ``variant_class``, filtering
recovers any single-beacon or single-class view. That is why one run serves the
combined, the per-beacon and the per-class question, and why no separate tools
are needed for any of them.

``variant_class`` is always a real class or ``unclassified`` -- never blank and
never a placeholder. ``classification_basis`` records how it was decided, so a
reader can tell a class pinned by the query from one inferred from a record's
content, and can see which convention was applied.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

PROVENANCE_COLUMNS = (
    "beacon_id",
    "beacon_name",
    "access_tier",
    "variant_class",
    "classification_basis",
    "granularity_returned",
    "count_precision",
    "count_precision_basis",
    "count_adjusted_to",
    "query_degraded",
    "degradation_notes",
    "expansion_notes",
)


@dataclass(frozen=True)
class Provenance:
    """Where a row came from and how much the query was weakened to get it."""

    beacon_id: str
    beacon_name: str
    access_tier: str
    variant_class: str
    classification_basis: str
    granularity_returned: str
    count_precision: str = "imprecise"
    #: declared | declared_adjustment | inferred_from_complete_retrieval |
    #: normative_default. An inferred `exact` must never read as a declared one.
    count_precision_basis: str = "normative_default"
    count_adjusted_to: str | None = None
    query_degraded: bool = False
    degradation_notes: str = ""
    expansion_notes: str = ""

    def as_columns(self) -> dict[str, str]:
        """Render as the fixed provenance column set."""
        values = {
            "beacon_id": self.beacon_id,
            "beacon_name": self.beacon_name,
            "access_tier": self.access_tier,
            "variant_class": self.variant_class,
            "classification_basis": self.classification_basis,
            "granularity_returned": self.granularity_returned,
            "count_precision": self.count_precision,
            "count_precision_basis": self.count_precision_basis,
            "count_adjusted_to": self.count_adjusted_to or "",
            "query_degraded": "true" if self.query_degraded else "false",
            "degradation_notes": self.degradation_notes,
            "expansion_notes": self.expansion_notes,
        }
        return {column: str(values[column]) for column in PROVENANCE_COLUMNS}


def random_sample_note(retrieved_instances: int, total: int | None) -> str:
    """The per-row label for a random sample (R1).

    Says what it is, how big it is relative to the whole, and that a repeat run
    differs -- the three facts a reader needs to not mistake it for a result.
    """
    of_total = f"of {total}" if total is not None else "of an unreported total"
    return (f"random sample: {retrieved_instances} {of_total} matching instances; "
            f"a repeat run returns different records")


def label_random_sample(provenance: Provenance, retrieved_instances: int,
                        total: int | None) -> Provenance:
    """Mark a row as part of a random sample, on top of any existing notes.

    Sets ``query_degraded``: a sample answers a narrower question than the one
    asked, which is exactly what that column exists to flag.
    """
    note = random_sample_note(retrieved_instances, total)
    notes = "; ".join(n for n in (provenance.degradation_notes, note) if n)
    return replace(provenance, query_degraded=True, degradation_notes=notes)
