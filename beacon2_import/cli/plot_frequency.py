"""Entry point for beacon2_freqplot: genome-wide, per-chromosome panels, circos.

The tool never offers a "combine beacons" option. Merging frequencies across
beacons must be impossible in the UI, not merely discouraged in help text.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build the parser."""
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """Render frequency plots, one panel or labelled series per beacon."""
    raise NotImplementedError


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
