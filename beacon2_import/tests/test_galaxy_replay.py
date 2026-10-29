"""Every Galaxy test, replayed from the recorded fixtures, with its own assertions.

Runs each test's query through the real CLI against the fixture tree, exactly
as `planemo test` would through the test .loc, and evaluates the test's XML
assertions with Galaxy's semantics. So a Galaxy test that would fail fails
HERE, in pytest, without a Galaxy server.

Written after the first replay of real recordings found a bug no test had:
cohorts and datasets come back as a Beacon COLLECTIONS response
(`response.collections`), which the parser did not read -- the constructed
fixtures had put them in resultSets, agreeing with the code instead of the
specification.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
TEST_DATA = ROOT / "tools" / "beacon2-import" / "test-data"
pytestmark = pytest.mark.skipif(not (SCRIPTS / "record_fixtures.py").is_file()
                                or not TEST_DATA.is_dir(), reason="scripts or tool test-data not present")
if (SCRIPTS / "record_fixtures.py").is_file():
    sys.path.insert(0, str(SCRIPTS))
    import galaxy_tests as spec
    import record_fixtures as recorder

    TESTS = spec.TESTS
else:  # pragma: no cover
    TESTS = []

AWAITING = Path(__file__).resolve().parent / "galaxy_fixtures_awaiting.txt"


def _awaiting() -> set[str]:
    return {l.split("\t")[0] for l in AWAITING.read_text().splitlines()
            if l.strip() and not l.startswith("#")}


@pytest.fixture(scope="module")
def table(tmp_path_factory):
    path = tmp_path_factory.mktemp("loc") / "providers.loc"
    path.write_text((TEST_DATA / "beacon_providers.loc").read_text()
                    .replace("${__HERE__}", str(TEST_DATA)))
    return path


TESTS_AWAITING = Path(__file__).resolve().parent / "galaxy_tests_awaiting.txt"


def _tests_awaiting() -> dict[str, str]:
    return {l.split("\t")[0]: l.split("\t")[1] for l in TESTS_AWAITING.read_text().splitlines()
            if l.strip() and not l.startswith("#")}


def _replay(test, table) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        first, second, _ = recorder._run(test, Path(tmp), ["--provider-table", str(table)])
        return {test.output_names[0]: first.read_text() if first.exists() else "",
                test.output_names[1]: second.read_text() if second.exists() else ""}


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_the_galaxy_test_passes_on_the_recorded_fixtures(test, table):
    waiting = set(test.requests_to) & _awaiting()
    if waiting:
        pytest.skip(f"fixtures awaiting recording for {sorted(waiting)}")
    files = _replay(test, table)
    if test.id in _tests_awaiting():
        # Listed as awaiting a re-recording: it must still be missing its
        # fixtures, or the list has gone stale.
        assert "no fixture" in files[test.output_names[1]], (
            f"{test.id} is listed as awaiting re-recording but its fixtures are present: "
            f"remove it from galaxy_tests_awaiting.txt")
        pytest.skip(f"awaiting re-recording: {_tests_awaiting()[test.id]}")
    failures = recorder._assertion_failures(test, files)
    assert not failures, "\n".join(failures)


def _counts(test, table) -> dict[str, str]:
    lines = _replay(test, table)["outcomes"].splitlines()[1:]
    return {l.split("\t")[0]: l.split("\t")[5] for l in lines}


def test_a_gene_query_counts_what_its_positional_twin_counts(table):
    """bycon's GET geneId is applied positionally, so for the same class and
    filters the gene query must count exactly what a range over the gene does."""
    gene = next(t for t in TESTS if t.id == "beacon2_gene#1")
    twin = next(t for t in TESTS if t.id == "beacon2_range#5")
    if {gene.id, twin.id} & set(_tests_awaiting()):
        pytest.skip("awaiting re-recording")
    assert _counts(gene, table) == _counts(twin, table)


def test_a_recorded_collections_response_is_parsed():
    """cancercelllines answers /cohorts with response.collections: 6 of them."""
    import json

    from beacon2_import.normalise.envelope import instance_count, parse
    from beacon2_import.transport.http import canonical_request, load_manifest

    directory = TEST_DATA / "fixtures" / "org.cancercelllines"
    if not (directory / "manifest.json").is_file():
        pytest.skip("cancercelllines fixtures not present")
    entry = next(e for e in load_manifest(directory / "manifest.json")
                 if e["request"]["path"] == "/cohorts" and e["request"]["query"].get(
                     "pagination", {}).get("limit") == 0)
    body = json.loads((directory / entry["response"]).read_text())
    assert "collections" in body["response"] and "resultSets" not in body["response"]
    envelope = parse(body)
    assert len(envelope.records) == 6 == envelope.num_total_results
    assert instance_count(list(envelope.records)) == 6
