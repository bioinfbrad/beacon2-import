"""Every bioblend call the importer makes binds against the installed bioblend.

The recipe drops 2.2.4's `bioblend =0.10.0` pin, dating from 2017. That is safe
only while this holds. A static check -- arguments are bound to signatures, no
Galaxy server is contacted -- so a renamed parameter or removed method fails
here rather than at a user's import.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

bioblend = pytest.importorskip("bioblend")
IMPORTER = Path(__file__).resolve().parent.parent / "importer"


def _targets():
    from bioblend.galaxy import GalaxyInstance
    from bioblend.galaxy.datasets import DatasetClient
    from bioblend.galaxy.histories import HistoryClient
    from bioblend.galaxy.users import UserClient

    return {"get_datasets": DatasetClient.get_datasets, "show_dataset": DatasetClient.show_dataset,
            "download_dataset": DatasetClient.download_dataset,
            "show_history": HistoryClient.show_history, "show_user": UserClient.show_user,
            "make_get_request": GalaxyInstance.make_get_request}


def _call_sites():
    for path in sorted(IMPORTER.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in _targets():
                yield path.name, node


SITES = list(_call_sites())


def test_there_are_call_sites_to_check():
    assert len(SITES) >= 6


@pytest.mark.parametrize("site", SITES, ids=lambda s: f"{s[0]}:{s[1].func.attr}:{s[1].lineno}")
def test_call_binds(site):
    _, node = site
    signature = inspect.signature(_targets()[node.func.attr])
    signature.bind("self", *node.args, **{k.arg: k.value for k in node.keywords})


def test_galaxy_instance_constructs_as_the_importer_calls_it():
    from bioblend.galaxy import GalaxyInstance

    gi = GalaxyInstance("http://galaxy.invalid", key="k")
    assert gi.base_url == "http://galaxy.invalid"
