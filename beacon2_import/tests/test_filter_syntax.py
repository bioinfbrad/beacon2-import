"""--filter accepts a bare ontology id, the commonest filter there is.

`--filter NCIT:C3058` once failed with "unknown filter kind 'NCIT'".
"""

from __future__ import annotations

import pytest

from beacon2_import.cli.common import parse_filters
from beacon2_import.query.planner import QueryUsageError


def test_a_bare_ontology_id_is_an_ontology_filter():
    assert parse_filters(["NCIT:C3058"]) == parse_filters(["ontology:NCIT:C3058"])


def test_a_bare_ontology_id_takes_options():
    assert parse_filters(["NCIT:C3058:descendants=false"]) == \
        parse_filters(["ontology:NCIT:C3058:descendants=false"])


def test_explicit_kinds_are_unchanged():
    alphanumeric, custom = parse_filters(["alphanumeric:age:years:>=:40:age=true",
                                          "custom:myterm"])
    assert alphanumeric.operator == ">=" and custom.id == "myterm"


def test_a_spec_that_is_no_curie_suggests_the_fix():
    with pytest.raises(QueryUsageError, match=r"Did you mean something like ontology:NCIT:C3058"):
        parse_filters(["C3058"])


def test_a_spec_with_an_operator_suggests_alphanumeric():
    with pytest.raises(QueryUsageError, match=r"Did you mean alphanumeric:"):
        parse_filters(["age:years:>=:40"])


def test_the_live_command_accepts_a_bare_id(capsys):
    from beacon2_import.cli.main import build_parser

    args = build_parser().parse_args(["range", "--providers", "org.cancercelllines",
                                      "--reference-name", "9", "--start", "1", "--end", "2",
                                      "--filter", "NCIT:C3058"])
    assert parse_filters(args.filters)[0].id == "NCIT:C3058"
