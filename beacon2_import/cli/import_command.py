"""`beacon2-import` -- Load (write) Beacon JSON into a self-hosted beacon's MongoDB.

The WRITE job, and the only way to put data in. Searching is the other job,
done by `beacon2-query` (cli/main.py).

The command line and behaviour are those of 2.2.4; the code, ported from that
release, is in beacon2_import.importer. The 2.2.4 import path of this entry
point, `beacon2_import.beacon2_import:beacon2_import`, also still resolves --
see beacon2_import/beacon2_import.py.
"""

from __future__ import annotations


def _where(argv: list[str]) -> str:
    """HOST:PORT, read from the arguments the importer will parse."""
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-H", "--db-host", default="127.0.0.1")
    parser.add_argument("-P", "--db-port", default="27017")
    known, _ = parser.parse_known_args(argv)
    return f"{known.db_host}:{known.db_port}"


def _reason(exc: Exception) -> str:
    """The driver's reason, cut to one line: its own messages run to a page."""
    text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return text.split(", Timeout:")[0].split(" (configured timeouts")[0][:160]


def main(argv: list[str] | None = None) -> int:
    """Run the importer. It parses its own arguments, as it always has.

    An expected failure -- no database at that address, or credentials it
    refuses -- ends with ONE clear line on stderr and a non-zero exit, never a
    traceback. Anything else is a bug, and keeps its traceback.
    """
    import sys

    from pymongo.errors import ConnectionFailure, OperationFailure

    from ..importer.importer import beacon2_import

    if argv is not None:
        sys.argv = ["beacon2-import", *argv]
    where = _where(sys.argv[1:])
    try:
        beacon2_import()
    except ConnectionFailure as exc:
        print(f"Could not connect to MongoDB at {where}: {_reason(exc)} \u2014 check the host, "
              f"port and that the server is running.", file=sys.stderr)
        raise SystemExit(1)
    except OperationFailure as exc:
        if exc.code not in (13, 18):  # Unauthorized, AuthenticationFailed
            raise
        print(f"MongoDB at {where} refused the credentials: {_reason(exc)} \u2014 check the "
              f"beacon2_account preferences.", file=sys.stderr)
        raise SystemExit(1)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
