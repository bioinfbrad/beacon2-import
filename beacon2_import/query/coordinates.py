"""Chromosome naming and coordinate-base conversion.

Two conversions live here and nowhere else:

  1. Naming.  Users type ``17``, ``chr17`` or ``NC_000017.11``. The wire wants
     either a RefSeq accession or a bare name plus an assembly, depending on the
     provider's ``reference_style``.
  2. Base.  Users think 1-based inclusive (genome browsers, papers). The API is
     0-based, with ``start`` inclusive and ``end`` exclusive.

Keeping both in one module means the off-by-one lives in one tested place.
"""

from __future__ import annotations

import functools
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "refseq_accessions.tsv"


@functools.lru_cache(maxsize=1)
def _accession_tables() -> tuple[dict[tuple[str, str], str], dict[str, tuple[str, str]]]:
    """Load the packaged accession table in both directions."""
    forward: dict[tuple[str, str], str] = {}
    reverse: dict[str, tuple[str, str]] = {}
    for line in _DATA.read_text().splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("assembly\t"):
            continue
        assembly, chromosome, accession = line.split("\t")
        forward[(assembly, chromosome)] = accession
        reverse[accession] = (assembly, chromosome)
    return forward, reverse


def normalise_chromosome(user_value: str) -> str:
    """Reduce any accepted spelling to a bare chromosome name (``17``, ``X``)."""
    value = str(user_value).strip()
    if not value:
        raise ValueError("no chromosome given")
    if value.lower().startswith("refseq:"):
        value = value.split(":", 1)[1]
    if value.upper().startswith("NC_"):
        _, reverse = _accession_tables()
        if value in reverse:
            return reverse[value][1]
        for accession, (_, chromosome) in reverse.items():
            if accession.split(".")[0] == value.split(".")[0]:
                return chromosome
        raise ValueError(f"unrecognised RefSeq accession {user_value!r}")
    if value.lower().startswith("chr"):
        value = value[3:]
    value = value.upper() if value.upper() in ("X", "Y", "M", "MT") else value
    if value == "M":
        value = "MT"
    return value


def to_refseq_accession(chromosome: str, assembly: str) -> str:
    """Map a chromosome name plus assembly to ``refseq:NC_...``.

    Backed by data/refseq_accessions.tsv so an assembly addition is a data edit.
    """
    forward, _ = _accession_tables()
    key = (str(assembly), normalise_chromosome(chromosome))
    if key not in forward:
        raise ValueError(f"no RefSeq accession for {key[1]!r} on {key[0]!r}")
    return f"refseq:{forward[key]}"


def from_refseq_accession(accession: str) -> tuple[str, str]:
    """Inverse of :func:`to_refseq_accession`, for normalising responses."""
    value = str(accession)
    if value.lower().startswith("refseq:"):
        value = value.split(":", 1)[1]
    _, reverse = _accession_tables()
    if value not in reverse:
        raise ValueError(f"unrecognised RefSeq accession {accession!r}")
    return reverse[value]


def one_based_to_interbase(start: int, end: int | None = None) -> tuple[int, int | None]:
    """Convert 1-based inclusive user input to 0-based half-open wire values."""
    if start is None:
        raise ValueError("start is required")
    if int(start) < 1:
        raise ValueError("1-based positions start at 1")
    return int(start) - 1, (None if end is None else int(end))


def interbase_to_one_based(start: int, end: int | None = None) -> tuple[int, int | None]:
    """Convert wire coordinates back for display in results.tsv."""
    if start is None:
        return None, None
    return int(start) + 1, (None if end is None else int(end))


def bracket_precise_match(position: int) -> tuple[int, int]:
    """Build a one-sided precise bracket: ``(p, p + 1)``.

    The spec's documented idiom for pinning one side of a bracket query.
    """
    return int(position), int(position) + 1
