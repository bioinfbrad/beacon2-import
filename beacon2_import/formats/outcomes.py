"""outcomes.tsv -- one row per (provider, variant_class). SOLE minter of status.

A scientific requirement, not a log. Without it, "no rows from beacon X" is
ambiguous between "no matches", "never queried", and -- now that class is a
query axis -- "that beacon is not known to hold this kind of variant".

THE ROW-COUNT CONTRACT
    Selecting two classes across three beacons produces exactly six rows.
    Every pair the planner produced, planned or skipped, appears here once.
    Concentrating status creation in this module is what makes that structural
    rather than a matter of remembering.

For entity queries that retrieve no variants (a plain biosample lookup),
``variant_class`` is ``n/a`` and there is one row per provider, as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..query.classes import VariantClass


class Status(str, Enum):
    OK = "ok"
    SKIPPED = "skipped"
    AUTH_MISSING = "auth_missing"
    #: The provider's edge refused the request as automated traffic. Separate
    #: from ERROR because the remedy belongs to the Galaxy administrator
    #: (allow-listing the instance's egress addresses) rather than to the user,
    #: and separate from AUTH_MISSING because no credential would help.
    BLOCKED = "blocked"
    #: The provider is in maintenance, overloaded, or did not answer. Distinct
    #: from BLOCKED because it is TEMPORARY and retryable, and because the
    #: BLOCKED remedy -- ask the provider to allow-list this Galaxy instance --
    #: would be wrong and wasteful advice for an outage.
    UNAVAILABLE = "unavailable"
    ERROR = "error"


OUTCOME_COLUMNS = (
    "beacon_id",
    "beacon_name",
    "variant_class",          # the class queried, or n/a for entity queries
    "class_status",           # yes | unknown | no, as the registry declared it
    "status",                 # ok | skipped | auth_missing | error
    "row_count",
    "granularity_requested",
    "granularity_returned",
    "count_precision",
    "count_precision_basis",
    "query_degraded",
    "coalesced",              # yes | fallback | no
    "notes",
)


@dataclass(frozen=True)
class Outcome:
    """One (provider, class) pair's fate in this run."""

    beacon_id: str
    beacon_name: str
    variant_class: VariantClass | None      # None renders as n/a
    class_status: str
    status: Status
    row_count: int = 0
    granularity_requested: str = ""
    granularity_returned: str = ""
    count_precision: str = ""
    count_precision_basis: str = ""
    query_degraded: bool = False
    coalesced: str = "no"
    notes: str = ""


#: Note text is part of the contract, not decoration: these are the sentences
#: that turn an empty cell into a statement. Rendered by note_for().
NOTE_TEMPLATES = {
    "class_unverified_zero": (
        "No records returned. This beacon is not known to hold {klass} data "
        "(registry status: unknown), so this is not evidence that it holds none."
    ),
    "class_unverified_hit": (
        "Records returned for {klass}, which the registry lists as unknown for "
        "this beacon. The class can be upgraded to yes -- see the run log for a "
        "pasteable registry fragment."
    ),
    "class_declared_no": (
        "{name} does not serve {klass_plain} ({evidence})."
    ),
    "class_not_expressible": (
        "{klass_plain} cannot be expressed in the query standard this beacon "
        "speaks; no configured beacon supports these queries yet."
    ),
    "coalesced_complete": (
        "Answered from a single unconstrained query; complete for this region."
    ),
    "coalesced_fallback": (
        "A combined query was issued first but could not be shown complete "
        "({reason}), so each class was queried separately."
    ),
    "counts_imprecise": (
        "Counts from this beacon are {precision}; frequencies cannot be "
        "computed from them."
    ),
    "provider_blocked": (
        "{name} refused this request as automated traffic, so nothing was "
        "queried. This is not an authentication problem and no credential will "
        "help: the provider's edge is challenging requests from this Galaxy "
        "server's network. A Galaxy administrator may need to ask {name} to "
        "allow-list the instance's outbound addresses."
    ),
    "provider_unavailable": (
        "{name} did not answer this query: {detail}. This is a problem at the "
        "provider's end and is usually temporary, so it is worth retrying "
        "later. Nothing needs changing on this Galaxy server and no credential "
        "is involved."
    ),
    "entity_type_mismatch": (
        "{name} returned {returned} records for a {requested} query. The "
        "response was discarded rather than reported, because flattening it "
        "would have filed one kind of record under another kind's columns."
    ),
    "random_sample": (
        "These rows are a RANDOM SAMPLE of {retrieved} of {total} matching "
        "instances, retrieved because sampling was explicitly requested. This "
        "provider returns a different random subset on every request below the "
        "total, so a repeat run will return different rows."
    ),
    "retrieval_refused": "{reason}",
    "partial_retrieval": (
        "PARTIAL: retrieved {shortfall} instances, fewer than the provider reported. "
        "These rows are not the complete answer, and counts from them are not exact."
    ),
    "pagination_refused": "{reason}",
    "synthetic_data": (
        "This beacon serves synthetic data. Do not report findings from it."
    ),
}


def note_for(key: str, **kwargs) -> str:
    """Render a contract note. Unknown keys raise rather than emit an empty cell."""
    if key not in NOTE_TEMPLATES:
        raise KeyError(f"no note template {key!r}")
    return NOTE_TEMPLATES[key].format(**kwargs)


class OutcomeRecorder:
    """Accumulates outcomes; guarantees one row per planned pair."""

    def __init__(self, pairs: list[tuple[str, VariantClass | None]]) -> None:
        """Take every (provider_id, class) pair the planner produced."""
        self._order = list(dict.fromkeys(pairs))
        self._outcomes: dict[tuple[str, VariantClass | None], Outcome] = {}

    def record(self, outcome: Outcome) -> None:
        """Record one pair's outcome.

        A second record for the same pair is a programming error and raises: it
        would mean two parts of the code both believed they owned that cell.
        """
        key = (outcome.beacon_id, outcome.variant_class)
        if key not in self._order:
            raise KeyError(f"{key} was not planned; outcomes may only be recorded "
                           f"for pairs the planner produced")
        if key in self._outcomes:
            raise ValueError(f"outcome for {key} recorded twice")
        self._outcomes[key] = outcome

    def rows(self) -> list[Outcome]:
        """Every planned pair, in plan order, with unrecorded pairs as errors."""
        rows = []
        for beacon_id, klass in self._order:
            outcome = self._outcomes.get((beacon_id, klass))
            if outcome is None:
                outcome = Outcome(
                    beacon_id=beacon_id, beacon_name=beacon_id, variant_class=klass,
                    class_status="", status=Status.ERROR,
                    notes="no outcome was recorded for this pair; this is a bug, "
                          "reported rather than omitted",
                )
            rows.append(outcome)
        return rows

    def write(self, path: Path) -> None:
        """Write outcomes.tsv.

        Any planned pair without a recorded outcome is written as ``error``
        with an explanatory note. A missing row would be exactly the ambiguity
        this file exists to remove.
        """
        def cell(value) -> str:
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, Enum):
                return str(value.value)
            if value is None:
                return "n/a"
            return str(value).replace("\t", " ").replace("\n", " ")

        lines = ["\t".join(OUTCOME_COLUMNS)]
        for outcome in self.rows():
            lines.append("\t".join(cell(getattr(outcome, c)) for c in OUTCOME_COLUMNS))
        Path(path).write_text("\n".join(lines) + "\n")
