"""beacon2-import fails cleanly when the database is not there.

The Galaxy test once connected to a real external database by hardcoded
address, and a connection timeout ended in a raw PyMongo traceback. Now an
expected failure is one clear line and a non-zero exit, tested here against a
closed port on the loopback address -- no database, nothing external.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from beacon2_import.cli.import_command import main

INPUT = (Path(__file__).resolve().parent.parent.parent / "tools" / "beacon2-import"
         / "test-data" / "HG00096.json")
CLOSED = ["--db-host", "127.0.0.1", "--db-port", "9", "--server-selection-timeout-ms", "500",
          "--database", "beacon", "--collection", "genomicVariations"]


@pytest.mark.skipif(not INPUT.is_file(), reason="tool test-data not present")
def test_a_closed_port_is_one_clear_line_and_exit_1(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--input_json_file", str(INPUT), *CLOSED])
    err = capsys.readouterr().err
    assert caught.value.code == 1
    assert err.startswith("Could not connect to MongoDB at 127.0.0.1:9: ")
    assert "\u2014 check the host, port and that the server is running." in err
    assert len(err.strip().splitlines()) == 1 and "Traceback" not in err


def test_refused_credentials_are_one_clear_line(monkeypatch, capsys):
    from pymongo.errors import OperationFailure

    from beacon2_import.importer import importer

    def refuse():
        raise OperationFailure("Authentication failed.", code=18)

    monkeypatch.setattr(importer, "beacon2_import", refuse)
    with pytest.raises(SystemExit) as caught:
        main(CLOSED)
    err = capsys.readouterr().err
    assert caught.value.code == 1 and "refused the credentials" in err
    assert len(err.strip().splitlines()) == 1


def test_an_unexpected_error_keeps_its_traceback(monkeypatch):
    """Only EXPECTED failures are made clean; a bug must stay loud."""
    from beacon2_import.importer import importer

    def broken():
        raise ValueError("a bug")

    monkeypatch.setattr(importer, "beacon2_import", broken)
    with pytest.raises(ValueError, match="a bug"):
        main(CLOSED)
