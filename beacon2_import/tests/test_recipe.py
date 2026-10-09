"""The Bioconda recipe must agree with pyproject.toml.

The failure this exists for lives in the RECIPE, where no test in the Python
package can see it: for a `noarch: python` recipe, a command exists after a
conda install only if `build: entry_points` declares it. A beacon2-query missing
there means every 3.0 Galaxy tool fails "command not found" on a server that
installs from Bioconda -- while every test here still passes.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
RECIPE = ROOT / "recipe" / "meta.yaml"
PYPROJECT = ROOT / "pyproject.toml"
pytestmark = pytest.mark.skipif(not RECIPE.is_file() or not PYPROJECT.is_file(),
                                reason="recipe or pyproject.toml not present")


def _recipe() -> str:
    return RECIPE.read_text()


def _section_list(section: str, key: str) -> list[str]:
    """The `- item` lines under `section:` -> `key:` in the recipe."""
    text = _recipe()
    block = re.search(rf"^{section}:\n(.*?)(?=^\S)", text + "\nEND:\n", re.S | re.M).group(1)
    items = re.search(rf"^  {key}:\n((?:    (?:- .*|#.*)\n)+)", block, re.M)
    assert items, f"no {section}.{key} in the recipe"
    return [l.strip()[2:].strip() for l in items.group(1).splitlines()
            if l.strip().startswith("- ")]


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


def _name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[]", requirement.strip(), maxsplit=1)[0].lower()


def test_entry_points_match_project_scripts_exactly():
    declared = {}
    for line in _section_list("build", "entry_points"):
        name, _, target = line.partition("=")
        declared[name.strip()] = target.strip()
    assert declared == _pyproject()["project"]["scripts"]


def test_every_entry_point_is_exercised_by_the_recipe_tests():
    commands = _section_list("test", "commands")
    for script in _pyproject()["project"]["scripts"]:
        assert f"{script} --help" in commands, f"recipe never runs {script}"


def test_every_shipped_package_is_imported_by_the_recipe_tests():
    include = _pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]
    packages = {p.rstrip("*") for p in include}
    assert packages <= set(_section_list("test", "imports"))


def test_version_matches_the_package():
    from beacon2_import import __version__

    assert re.search(r'{%\s*set version\s*=\s*"([^"]+)"', _recipe()).group(1) == __version__


def test_run_requirements_cover_every_dependency_and_the_galaxy_extra():
    run = {_name(r) for r in _section_list("requirements", "run")}
    project = _pyproject()["project"]
    wanted = {_name(d) for d in project["dependencies"]}
    wanted |= {_name(d) for d in project["optional-dependencies"]["galaxy"]}
    assert wanted <= run, f"missing from run: {sorted(wanted - run)}"
    assert not run & {"jsonschema", "dataclasses", "cyvcf2"}


def test_python_floor_matches():
    floor = _pyproject()["project"]["requires-python"]
    for section in ("host", "run"):
        pins = [r for r in _section_list("requirements", section) if _name(r) == "python"]
        assert pins == [f"python {floor}"], f"{section}: {pins}"


def test_host_provides_the_build_backend_pyproject_requires():
    """The recipe builds with --no-build-isolation, so build-system.requires is
    never installed: the backend must be in host, at a sufficient version."""
    assert "--no-build-isolation" in _recipe()
    required = _pyproject()["build-system"]["requires"]
    host = _section_list("requirements", "host")
    for requirement in required:
        name = _name(requirement)
        pinned = [h for h in host if _name(h) == name]
        assert pinned, f"host lacks {name}, which pyproject.toml's build-system requires"
        assert pinned[0].replace(" ", "") == requirement.replace(" ", ""), pinned[0]


def test_licence_matches():
    assert re.search(r"^  license: (\S+)$", _recipe(), re.M).group(1) == _pyproject()["project"]["license"]
