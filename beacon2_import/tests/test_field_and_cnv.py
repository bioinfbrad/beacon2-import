"""--field and --filter are different mechanisms, refused on opposite transports.

A filter is an ontology term a beacon SERVER maps onto its fields; a raw
collection has none, so filters are refused on MongoDB. A field is the field
itself, matched natively by MongoDB; Beacon v2 has no parameter for it, so
fields are refused on the API. Treating the two as one thing is how 3.0 first
dropped 56 entity fields on MongoDB.
"""

from __future__ import annotations

import pytest

from beacon2_import.cli.main import main
from beacon2_import.transport.mongo import cnv_filter_for, field_value, parse_fields


def _run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().err


def test_field_is_refused_on_the_api_and_points_to_filter(capsys):
    code, err = _run(capsys, "entity", "--entity", "run", "--providers", "org.cancercelllines",
                     "--field", "platform=Illumina")
    assert code == 2
    assert "no field-equality parameter" in err and "--filter" in err


def test_biosample_ids_is_refused_on_the_api_and_points_to_the_nested_lookup(capsys):
    code, err = _run(capsys, "sequence", "--providers", "org.cancercelllines",
                     "--reference-name", "17", "--start", "1", "--reference-bases", "G",
                     "--alternate-bases", "A", "--biosample-ids", "bs1")
    assert code == 2 and "--nested-entity genomicVariant" in err


def test_filter_and_field_refusals_are_distinct_messages(capsys):
    code, err = _run(capsys, "cnv", "--transport", "mongodb", "--collection", "cnv",
                     "--filter", "ontology:NCIT:C3058:descendants=true")
    assert code == 2 and "--field PATH=VALUE" in err and "no field-equality" not in err


def test_field_values_match_native_types():
    """The string "50" never equals the integer 50; 2.2.4's --cohortSize was an int."""
    assert parse_fields(["cohortSize=50"]) == {"cohortSize": {"$in": [50, "50"]}}
    assert parse_fields(["diseases.familyHistory=true"]) == {
        "diseases.familyHistory": {"$in": [True, "true"]}}
    assert parse_fields(["tumorGrade.label=G2"]) == {"tumorGrade.label": "G2"}
    assert field_value("2.5") == {"$in": [2.5, "2.5"]}


def test_a_malformed_field_is_a_clear_error():
    with pytest.raises(ValueError, match="PATH=VALUE"):
        parse_fields(["platform"])


def test_cnv_keeps_2_2_4_containment_on_mongodb():
    """The GTN CNV tutorial is built on these semantics, so they are unchanged."""
    clauses = cnv_filter_for("1", 243618689, 243620819, "DEL",
                             {"primarySite": "brain"})
    assert clauses == {
        "primarySite": "brain",
        "definitions.Location.chromosome": "1",
        "definitions.Location.start": {"$gte": 243618689},
        "definitions.Location.end": {"$lte": 243620819},
        "variantType": "DEL",
    }


def test_cnv_on_mongodb_needs_a_collection(capsys):
    code, err = _run(capsys, "cnv", "--transport", "mongodb", "--field", "gene=TP53")
    assert code == 2 and "--collection" in err


def test_an_unconstrained_mongodb_entity_query_is_refused(capsys):
    code, err = _run(capsys, "entity", "--entity", "run", "--transport", "mongodb")
    assert code == 2 and "whole collection" in err


def test_cnv_on_the_api_is_a_cnv_range_query(capsys):
    code, err = _run(capsys, "cnv", "--providers", "org.cancercelllines")
    assert code == 2 and "range query" in err
