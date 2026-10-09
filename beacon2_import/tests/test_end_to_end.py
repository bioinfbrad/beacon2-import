"""The milestone, pinned: a real command producing real output.

`beacon2-query range --providers org.cancercelllines --variant-class CNV ...`
-> results.tsv + outcomes.tsv, through the real planner, adapter, pre-flight,
complete-or-refuse retrieval, parser, classifier and writers. Only the socket
is replaced: the provider's base URL is a file:// fixture directory serving a
verbatim recorded response (55 records, 60 instances, total 60).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from beacon2_import.cli.main import main

PACKAGE = Path(__file__).resolve().parent.parent
TEST_DATA = PACKAGE.parent / "tools" / "beacon2-import" / "test-data"


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "end_to_end"


def _run(tmp_path, providers, classes):
    """Python-suite fixtures, keyed on the request. Progenetix and the bracketless
    provider point at directories with no manifest, so they fail loudly."""
    table = tmp_path / "providers.loc"
    table.write_text("".join(
        f"{pid}\t\tfile://{FIXTURES / pid}\t1\t\t\n"
        for pid in ("org.cancercelllines", "org.progenetix.beacon", "test.fixture.bracketless")))
    results, outcomes = tmp_path / "results.tsv", tmp_path / "outcomes.tsv"
    code = main(["range", "--providers", providers, "--variant-class", classes,
                 "--provider-table", str(table), "--reference-name", "3",
                 "--start", "195728638", "--end", "198169247",
                 "--filter", "ontology:NCIT:C3058:descendants=true:similarity=exact",
                 "--results", str(results), "--outcomes", str(outcomes)])
    read = lambda p: list(csv.DictReader(p.open(), delimiter="\t"))
    return code, read(results), read(outcomes)


def test_the_milestone_command(tmp_path):
    code, rows, outcomes = _run(tmp_path, "org.cancercelllines", "CNV")
    assert code == 0
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert (outcome["status"], outcome["row_count"], outcome["class_status"]) == ("ok", "60", "yes")
    assert outcome["count_precision"] == "exact"
    assert outcome["count_precision_basis"] == "inferred_from_complete_retrieval"
    assert len(rows) == 60, "one row per caseLevelData instance"
    assert len({r["biosample_id"] for r in rows}) == 44
    assert len({r["variant_internal_id"] for r in rows}) == 55


def test_coordinates_are_one_based_for_display(tmp_path):
    _, rows, _ = _run(tmp_path, "org.cancercelllines", "CNV")
    by_id = {r["variant_internal_id"]: r for r in rows}
    wire_start = int(next(iter(by_id)).split(":")[1].split("-")[0])
    first = next(iter(by_id.values()))
    assert int(first["start"]) == wire_start + 1


def test_the_two_axis_contract(tmp_path):
    """Three providers by two classes: six rows, each with a stated reason."""
    providers = "org.cancercelllines,org.progenetix.beacon,test.fixture.bracketless"
    code, _, outcomes = _run(tmp_path, providers, "CNV,SV")
    assert code == 0
    assert len(outcomes) == 6
    by_pair = {(o["beacon_id"], o["variant_class"]): o for o in outcomes}
    assert by_pair[("org.cancercelllines", "CNV")]["coalesced"] == "yes"
    sv = by_pair[("org.cancercelllines", "SV")]
    assert sv["status"] == "ok" and sv["row_count"] == "0"
    assert "not evidence" in sv["notes"]
    no = by_pair[("test.fixture.bracketless", "SV")]
    assert no["status"] == "skipped" and "does not serve" in no["notes"]
    assert all(o["notes"] for o in outcomes if o["row_count"] == "0"), \
        "every empty cell must state a reason"
