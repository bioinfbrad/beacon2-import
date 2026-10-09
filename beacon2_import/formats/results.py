"""results.tsv -- combined rows from every provider, each carrying provenance.

One fixed column set per entity, whatever granularity each provider returned:
provenance first, then the entity's columns, then the two summary columns.
Mixed granularity across providers is normal -- one beacon returns records,
another only a count -- so a record row leaves the summary columns empty and a
summary row leaves the entity columns empty. The header never changes shape
between runs, which is what makes the file safe to concatenate and join.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..normalise.entities import ENTITY_COLUMNS
from ..normalise.provenance import PROVENANCE_COLUMNS
from ..normalise.variants import VARIANT_COLUMNS

SUMMARY_COLUMNS = ("exists", "num_total_results")


def columns_for(entity: str) -> tuple[str, ...]:
    """The full, ordered column set for an entity's results.tsv."""
    if entity == "genomicVariant":
        body = VARIANT_COLUMNS
    elif entity in ENTITY_COLUMNS:
        body = ENTITY_COLUMNS[entity]
    else:
        raise ValueError(f"no results columns defined for entity {entity!r}")
    return PROVENANCE_COLUMNS + body + SUMMARY_COLUMNS


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def write(rows: list[dict[str, Any]], path: Path, entity: str) -> None:
    """Write results.tsv with provenance columns first, then entity columns.

    Keys outside the column set are dropped deliberately -- internal keys such
    as `instance_id` are for cross-checks, not output -- and a missing key is an
    empty cell, never an error, because a row from a count response has no
    entity values at all.
    """
    columns = columns_for(entity)
    lines = ["\t".join(columns)]
    lines += ["\t".join(_cell(row.get(c)) for c in columns) for row in rows]
    Path(path).write_text("\n".join(lines) + "\n")
