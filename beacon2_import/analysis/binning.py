"""Genome binning at four scales: 1 Mb bins, arms, chromosomes, whole genome.

Cytoband and arm boundaries are packaged data (data/cytobands/), so supporting
a new assembly is a data edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Scale(str, Enum):
    BIN = "bin"                # fixed width, 1 Mb default
    ARM = "arm"
    CHROMOSOME = "chromosome"
    GENOME = "genome"


@dataclass(frozen=True)
class Bin:
    """One genomic interval in a binning scheme."""

    id: str
    chromosome: str
    start: int
    end: int
    arm: str | None = None


def build_bins(assembly: str, scale: Scale, width: int = 1_000_000) -> list[Bin]:
    """Construct the bin set for an assembly and scale."""
    raise NotImplementedError


def assign(chromosome: str, start: int, end: int, bins: list[Bin]) -> list[str]:
    """Return the ids of all bins a segment overlaps.

    A segment spanning several bins counts in each: a sample carrying a 5 Mb
    deletion is affected in all five 1 Mb bins.
    """
    raise NotImplementedError
