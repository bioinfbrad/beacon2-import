"""beacon2-query service-info and filtering-terms, end to end against fixtures."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from beacon2_import.cli.main import main

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "informational"
REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "beacon_registry.yaml"


def _table(tmp_path, rows: dict[str, str]) -> Path:
    path = tmp_path / "providers.loc"
    path.write_text("".join(f"{pid}\t\tfile://{FIXTURES / d}\t1\t\t\n" for pid, d in rows.items()))
    return path


def _read(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(), delimiter="\t"))


def _service_info(tmp_path, directory):
    table = _table(tmp_path, {"org.cancercelllines": directory})
    report, outcomes = tmp_path / "report.tsv", tmp_path / "outcomes.tsv"
    code = main(["service-info", "--providers", "org.cancercelllines",
                 "--provider-table", str(table), "--report", str(report),
                 "--outcomes", str(outcomes)])
    return code, {r["field"]: r for r in _read(report)}, _read(outcomes)


# ---------------- service-info ----------------

def test_agreeing_provider_reports_no_drift(tmp_path):
    code, fields, outcomes = _service_info(tmp_path, "agrees")
    assert code == 0
    assert fields["beacon_id_reported"]["agrees"] == "true"
    assert fields["api_version_reported"]["agrees"] == "true"
    assert fields["production_status"]["observed"] == "PROD"
    assert outcomes[0]["status"] == "ok" and "drift" not in outcomes[0]["notes"]


def test_drift_is_reported_as_data(tmp_path):
    _, fields, outcomes = _service_info(tmp_path, "drifted")
    assert fields["beacon_id_reported"]["agrees"] == "false"
    assert fields["beacon_id_reported"]["observed"] == "org.cancercelllines.renamed"
    assert fields["api_version_reported"]["agrees"] == "false"
    assert "drift in" in outcomes[0]["notes"]
    assert "beacon_id_reported" in outcomes[0]["notes"]


def test_map_is_tried_first_and_beacon_map_is_the_fallback(tmp_path):
    _, agrees, _ = _service_info(tmp_path, "agrees")
    assert agrees["map_endpoint_sets"]["endpoint"] == "/map"
    _, drifted, _ = _service_info(tmp_path, "drifted")
    assert drifted["map_endpoint_sets"]["endpoint"] == "/beaconMap"
    assert drifted["map_endpoint_sets"]["observed"] == "genomicVariant"


def test_service_info_never_writes_the_registry(tmp_path):
    before = hashlib.sha256(REGISTRY.read_bytes()).hexdigest()
    _service_info(tmp_path, "drifted")
    assert hashlib.sha256(REGISTRY.read_bytes()).hexdigest() == before


def test_entry_types_are_flagged_as_saying_nothing_about_classes(tmp_path):
    _, fields, _ = _service_info(tmp_path, "agrees")
    assert "variant classes" in fields["entry_types"]["note"]


# ---------------- filtering-terms ----------------

def _terms(tmp_path, *prefixes, providers=("org.cancercelllines",)):
    dirs = {"org.cancercelllines": "agrees", "org.progenetix.beacon": "second"}
    table = _table(tmp_path, {p: dirs[p] for p in providers})
    terms, outcomes = tmp_path / "terms.tsv", tmp_path / "outcomes.tsv"
    argv = ["filtering-terms", "--providers", ",".join(providers),
            "--provider-table", str(table), "--terms", str(terms), "--outcomes", str(outcomes)]
    for prefix in prefixes:
        argv += ["--prefix", prefix]
    assert main(argv) == 0
    return _read(terms), _read(outcomes)


def test_all_terms_without_a_prefix(tmp_path):
    rows, outcomes = _terms(tmp_path)
    assert len(rows) == 2 and outcomes[0]["row_count"] == "2"


def test_prefix_selection_is_client_side_and_says_so(tmp_path):
    rows, outcomes = _terms(tmp_path, "EFO")
    assert rows == []
    assert "0 of 2 terms match prefix EFO (selected client-side)" in outcomes[0]["notes"]


def test_prefix_matching_ignores_case(tmp_path):
    rows, _ = _terms(tmp_path, "edam")
    assert {r["prefix"] for r in rows} == {"EDAM"}


def test_merged_view_names_the_other_holders(tmp_path):
    rows, outcomes = _terms(tmp_path, providers=("org.cancercelllines", "org.progenetix.beacon"))
    shared = [r for r in rows if r["term_id"] == "EDAM:operation_3961"]
    assert {r["shared_with"] for r in shared} == {"org.progenetix.beacon", "org.cancercelllines"}
    only_one = [r for r in rows if r["term_id"] == "NCIT:C3058"]
    assert only_one and only_one[0]["shared_with"] == ""
    assert {o["status"] for o in outcomes} == {"ok"}


def test_a_failing_provider_is_a_row_not_a_crash(tmp_path):
    table = tmp_path / "providers.loc"
    table.write_text(f"org.cancercelllines\t\tfile://{FIXTURES / 'agrees'}\t1\t\t\n"
                     f"org.progenetix.beacon\t\tfile://{tmp_path / 'nothing'}\t1\t\t\n")
    terms, outcomes = tmp_path / "t.tsv", tmp_path / "o.tsv"
    assert main(["filtering-terms", "--providers", "org.cancercelllines,org.progenetix.beacon",
                 "--provider-table", str(table), "--terms", str(terms),
                 "--outcomes", str(outcomes)]) == 0
    by_id = {o["beacon_id"]: o for o in _read(outcomes)}
    assert by_id["org.cancercelllines"]["status"] == "ok"
    assert by_id["org.progenetix.beacon"]["status"] == "error"


def test_a_provider_where_nothing_answers_is_not_reported_healthy(tmp_path):
    """Found by replaying the Galaxy tests with no fixtures: service-info wrote
    its rows with empty observed values and reported the provider `ok`."""
    table = tmp_path / "providers.loc"
    table.write_text(f"org.cancercelllines\t\tfile://{tmp_path / 'nothing'}\t1\t\t\n")
    report, outcomes = tmp_path / "report.tsv", tmp_path / "outcomes.tsv"
    assert main(["service-info", "--providers", "org.cancercelllines", "--provider-table", str(table),
                 "--report", str(report), "--outcomes", str(outcomes)]) == 0
    outcome = _read(outcomes)[0]
    assert outcome["status"] == "error" and "no manifest" in outcome["notes"]
