"""CNV term vocabulary: EFO <-> VCF <-> SO, and hierarchical expansion.

Sources disagree, and the disagreement is bidirectional:

  * The VQS ``CopyChange`` component lists eight terms including
    ``EFO:0030064`` (regional base ploidy) and omits ``EFO:0030073``.
  * The CNV comparison table lists eight rows including ``EFO:0030073``
    (focal genome amplification) and omits ``EFO:0030064``.

We support the union of nine and treat the CopyChange hierarchy as
authoritative for expansion. ``EFO:0030064`` therefore has no VCF/SO/VRS
mapping: those cells are left empty rather than inferred.

``EFO:0030073`` is placed beneath ``EFO:0030072`` (high-level gain) as a LOCAL
INFERENCE -- the amplification note describes the same copy threshold as
high-level gain plus a size constraint, making it the more specific term. The
inference is recorded in data/efo_cnv_terms.tsv under a ``source`` column and
must be surfaced per row whenever expansion crosses that edge.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "efo_cnv_terms.tsv"


@dataclass(frozen=True)
class CnvTerm:
    """One row of data/efo_cnv_terms.tsv."""

    efo_id: str
    label: str
    parent: str | None
    vcf: str | None          # empty for EFO:0030064 -- absent from the table
    so: str | None
    vrs: str | None
    source: str              # copy_change_component | cnv_table | local_inference


@functools.lru_cache(maxsize=1)
def load_terms() -> dict[str, CnvTerm]:
    """Load the packaged term table.

    Width-checked: every row must have exactly as many fields as the header.
    A short row would shift `source` into the `vrs` column -- which is exactly
    what the EFO:0030064 row did until it was caught.
    """
    rows = [l for l in _DATA.read_text().splitlines() if l and not l.startswith("#")]
    header = rows[0].split("\t")
    terms: dict[str, CnvTerm] = {}
    for line in rows[1:]:
        fields = line.split("\t")
        if len(fields) != len(header):
            raise ValueError(
                f"{_DATA.name}: row has {len(fields)} fields, header has "
                f"{len(header)}: {line!r}"
            )
        row = dict(zip(header, fields))
        terms[row["efo_id"]] = CnvTerm(
            efo_id=row["efo_id"], label=row["label"],
            parent=row["parent"] or None, vcf=row["vcf"] or None,
            so=row["so"] or None, vrs=row["vrs"] or None, source=row["source"],
        )
    return terms


def expand(term_id: str, include_self: bool = True) -> list[str]:
    """Return a term and all its descendants, for client-side expansion."""
    terms = load_terms()
    if term_id not in terms:
        return [term_id] if include_self else []
    out = [term_id] if include_self else []
    frontier = [term_id]
    while frontier:
        parent = frontier.pop(0)
        children = sorted(t.efo_id for t in terms.values() if t.parent == parent)
        out.extend(children)
        frontier.extend(children)
    return out


def expansion_crosses_inference(term_id: str, expanded: list[str]) -> bool:
    """Whether an expansion used a locally inferred edge.

    Drives the per-row ``expansion_notes`` value, so a user can tell that a hit
    arrived through our inference rather than an authority's hierarchy.
    """
    terms = load_terms()
    return any(
        "local_inference" in terms[e].source
        for e in expanded if e in terms and e != term_id
    )


def legacy_to_efo(vcf_term: str) -> list[str]:
    """Map ``DEL``/``DUP`` to the EFO terms a provider might hold.

    "Legacy" is the Beacon specification's term for the variantType values DEL
    and DUP, which it marks LEGACY in favour of EFO terms.
    """
    wanted = str(vcf_term).upper()
    return [t.efo_id for t in load_terms().values() if t.vcf == wanted]


def efo_to_legacy(efo_id: str) -> str | None:
    """Map an EFO term down to ``DEL``/``DUP`` for a provider that needs it.

    Lossy by construction: this is a degradation and must be recorded as one.
    """
    term = load_terms().get(efo_id)
    return term.vcf if term else None


def help_table_rst() -> str:
    """Render the full mapping table for inclusion in tool help.

    Users think in DEL/DUP; the wire format should be EFO. Showing the mapping
    is what lets them check our translation rather than trust it.
    """
    lines = ["EFO term     Meaning                            VCF  SO"]
    for term in load_terms().values():
        lines.append(f"{term.efo_id:<12} {term.label:<34} {term.vcf or '-':<4} "
                     f"{term.so or '-'}")
    return "\n".join(lines)
