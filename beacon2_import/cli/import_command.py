"""`beacon2-import` -- Load (write) Beacon JSON into a self-hosted beacon's MongoDB.

The WRITE job, and the only way to put data in. Searching is the other job,
done by `beacon2-query` (cli/main.py).

The command line and behaviour are those of 2.2.4; the code, ported from that
release, is in beacon2_import.importer. The 2.2.4 import path of this entry
point, `beacon2_import.beacon2_import:beacon2_import`, also still resolves --
see beacon2_import/beacon2_import.py.
"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    """Run the importer. It parses its own arguments, as it always has."""
    import sys

    from ..importer.importer import beacon2_import

    if argv is not None:
        sys.argv = ["beacon2-import", *argv]
    beacon2_import()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
