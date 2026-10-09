"""Security fixes to the import tool, tested against the REAL template and code.

The configfile macro is rendered with Cheetah, the engine Galaxy itself uses, so
these tests exercise the template that ships rather than a re-implementation.
"""

from __future__ import annotations

import json
import re
import types
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent.parent / "tools" / "beacon2-import"


def _template() -> str:
    macros = (TOOLS / "macros.xml").read_text()
    block = re.search(r'<xml name="configfile">.*?<!\[CDATA\[(.*?)\]\]>', macros, re.S)
    return block.group(1)


def _render(prefs: dict | None) -> str:
    Template = pytest.importorskip("Cheetah.Template").Template
    user = None if prefs is None else types.SimpleNamespace(extra_preferences=prefs)
    return str(Template(_template(), searchList=[{"__user__": user}]))


pytestmark = pytest.mark.skipif(not TOOLS.is_dir(), reason="tool XML not present")


def test_no_hardcoded_credentials_remain_in_the_macro():
    template = _template()
    assert '"root"' not in template and '"example"' not in template
    assert "'root'" not in template and "'example'" not in template


def test_empty_preferences_produce_empty_credentials_not_defaults():
    rendered = json.loads(_render({}))
    assert rendered == {"db_auth_source": "admin", "db_user": "", "db_password": ""}


def test_an_anonymous_user_renders_rather_than_crashing():
    assert json.loads(_render(None))["db_user"] == ""


def test_a_password_with_json_metacharacters_round_trips():
    password = 'pa"ss\\wo@rd:/%\n'
    rendered = json.loads(_render({
        "beacon2_account|db_auth_source": "admin",
        "beacon2_account|db_user": "beacon",
        "beacon2_account|db_password": password,
    }))
    assert rendered["db_password"] == password


class _Recorder:
    calls: list = []

    def __init__(self, *args, **kwargs):
        _Recorder.calls.append((args, kwargs))


def _connect(tmp_path, monkeypatch, config: dict):
    from beacon2_import.importer import importer

    path = tmp_path / "creds.json"
    path.write_text(json.dumps(config))
    _Recorder.calls = []
    monkeypatch.setattr(importer, "MongoClient", _Recorder)
    args = types.SimpleNamespace(advance=True, database_auth_config=str(path),
                                 database_host="db.example", database_port=27017,
                                 database="beacon", server_selection_timeout_ms=30000)
    importer.connect_to_mongodb(args, parser=None)
    return _Recorder.calls[0]


def test_credentials_go_to_the_driver_as_keywords_not_a_uri(tmp_path, monkeypatch):
    args, kwargs = _connect(tmp_path, monkeypatch, {
        "db_auth_source": "admin", "db_user": "beacon", "db_password": "p@ss:w/rd%"})
    assert args == ("db.example", 27017)
    assert kwargs == {"username": "beacon", "password": "p@ss:w/rd%", "authSource": "admin",
                      "serverSelectionTimeoutMS": 30000}
    assert not any("mongodb://" in str(a) for a in args)


def test_no_user_connects_unauthenticated_and_says_so(tmp_path, monkeypatch, capsys):
    args, kwargs = _connect(tmp_path, monkeypatch, {
        "db_auth_source": "admin", "db_user": "", "db_password": ""})
    assert args == ("db.example", 27017) and kwargs == {"serverSelectionTimeoutMS": 30000}
    assert "without authentication" in capsys.readouterr().err
