"""Entry point for the beacon2_variantplot Galaxy tool."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    """Build the parser."""
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """Render the beacon2_variantplot figures."""
    raise NotImplementedError


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
