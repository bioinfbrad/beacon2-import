"""Static check of the Galaxy tool-test fixture tree.

The first real `planemo test` run failed five tests on fixtures the Python
suite never looked at: three of four provider directories were EMPTY, and the
existing check only asked whether each directory existed. This one reads them.

For every provider in test-data/beacon_providers.loc:
  * a fixture directory with a valid keyed manifest (beacon2-fixtures/2);
  * every entry's response file exists, and every file is referenced;
  * no directory is empty.
Providers not there yet are listed, with a reason, in galaxy_fixtures_awaiting.txt
-- enforced both ways, so the list can neither hide a gap nor go stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from beacon2_import.transport.http import FixtureMiss, load_manifest

ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DATA = ROOT / "tools" / "beacon2-import" / "test-data"
FIXTURES = TEST_DATA / "fixtures"
AWAITING = Path(__file__).resolve().parent / "galaxy_fixtures_awaiting.txt"
pytestmark = pytest.mark.skipif(not TEST_DATA.is_dir(), reason="tool test-data not present")


def _providers() -> list[str]:
    loc = TEST_DATA / "beacon_providers.loc"
    return [l.split("\t")[0] for l in loc.read_text().splitlines()
            if l.strip() and not l.startswith("#")] if loc.is_file() else []


def _awaiting() -> dict[str, str]:
    out = {}
    for line in AWAITING.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            provider, _, reason = line.partition("\t")
            out[provider.strip()] = reason.strip()
    return out


def _problems(provider: str) -> list[str]:
    directory = FIXTURES / provider
    if not directory.is_dir():
        return [f"no fixture directory {directory.relative_to(ROOT)}"]
    files = {p.name for p in directory.iterdir() if p.is_file()}
    if not files:
        return [f"{provider}: fixture directory is empty"]
    if "manifest.json" not in files:
        return [f"{provider}: no manifest.json"]
    try:
        entries = load_manifest(directory / "manifest.json")
    except FixtureMiss as exc:
        return [f"{provider}: {exc}"]
    problems = [] if entries else [f"{provider}: manifest has no entries"]
    referenced = {e["response"] for e in entries}
    problems += [f"{provider}: entry points at missing file {name}"
                 for name in sorted(referenced) if not (directory / name).is_file()]
    problems += [f"{provider}: {name} is referenced by no manifest entry"
                 for name in sorted(files - referenced - {"manifest.json"})]
    return problems


@pytest.mark.parametrize("provider", _providers())
def test_every_test_provider_has_complete_keyed_fixtures(provider):
    if provider in _awaiting():
        pytest.skip(f"listed as awaiting: {_awaiting()[provider]}")
    problems = _problems(provider)
    assert not problems, "\n".join(problems)


def test_the_awaiting_list_is_not_stale():
    providers = set(_providers())
    awaiting = _awaiting()
    unknown = sorted(set(awaiting) - providers)
    done = sorted(p for p in awaiting if p in providers and not _problems(p))
    assert not unknown, f"listed as awaiting but not in the test .loc: {unknown}"
    assert not done, f"listed as awaiting but already complete -- remove them: {done}"
    assert all(awaiting.values()), "every awaiting provider needs a reason"
