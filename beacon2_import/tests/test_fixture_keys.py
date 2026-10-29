"""Fixtures are keyed on the request, and a miss is loud: no fallback answer."""

from __future__ import annotations

import json

import pytest

from beacon2_import.transport.http import (
    MANIFEST_FORMAT, FixtureClient, FixtureMiss, canonical_request,
)

BODY = {"meta": {"apiVersion": "2.0"}, "query": {
    "requestParameters": {"referenceName": "17", "start": [7572836], "end": [7578641],
                          "variantType": "EFO:0030067"},
    "filters": [{"id": "NCIT:C3058"}], "requestedGranularity": "record",
    "pagination": {"skip": 0, "limit": 1}}}


def _client(tmp_path, body=BODY):
    (tmp_path / "answer.json").write_text(json.dumps({"responseSummary": {"numTotalResults": 1}}))
    entry = {"request": canonical_request("POST", "/g_variants", None, body),
             "response": "answer.json", "origin": "constructed"}
    (tmp_path / "manifest.json").write_text(json.dumps({"format": MANIFEST_FORMAT, "entries": [entry]}))
    return FixtureClient(str(tmp_path))


def test_the_recorded_request_is_answered(tmp_path):
    assert _client(tmp_path).post("/g_variants", BODY).status == 200


@pytest.mark.parametrize("field, value", [
    ("referenceName", "3"), ("start", [1]), ("variantType", "EFO:0030070")])
def test_a_request_differing_in_one_field_misses_loudly(tmp_path, field, value):
    """The canned-response flaw: a chr3 answer to a chr17 question. Now a miss."""
    client = _client(tmp_path)
    other = json.loads(json.dumps(BODY))
    other["query"]["requestParameters"][field] = value
    with pytest.raises(FixtureMiss, match="no fixture"):
        client.post("/g_variants", other)


def test_filters_and_pagination_are_part_of_the_key(tmp_path):
    client = _client(tmp_path)
    for change in ({"filters": []}, {"pagination": {"skip": 0, "limit": 0}},
                   {"requestedGranularity": "count"}):
        other = json.loads(json.dumps(BODY))
        other["query"].update(change)
        with pytest.raises(FixtureMiss):
            client.post("/g_variants", other)


def test_layout_and_spelling_do_not_change_the_key():
    """Flat or nested parameters, list or comma string: the same request."""
    nested = json.loads(json.dumps(BODY))
    nested["query"]["requestParameters"] = {"g_variant": BODY["query"]["requestParameters"]}
    assert canonical_request("POST", "g_variants", None, nested) == \
        canonical_request("POST", "/g_variants", None, BODY)
    assert canonical_request("GET", "/g_variants", {"start": "1,2", "limit": "5"}) == \
        canonical_request("GET", "/g_variants", {"start": [1, 2], "limit": 5})


def test_a_miss_names_the_request_to_record(tmp_path):
    with pytest.raises(FixtureMiss) as caught:
        _client(tmp_path).get("/info")
    assert '"path": "/info"' in str(caught.value) and "record_fixtures.py" in str(caught.value)


def test_a_gzipped_recording_is_served_unchanged(tmp_path):
    """Large recordings are stored gzipped; the client serves them as recorded."""
    import gzip

    body = {"responseSummary": {"numTotalResults": 7}, "payload": "x" * 1000}
    (tmp_path / "big.json.gz").write_bytes(gzip.compress(json.dumps(body).encode(), mtime=0))
    entry = {"request": canonical_request("POST", "/g_variants", None, BODY),
             "response": "big.json.gz", "origin": "recorded"}
    (tmp_path / "manifest.json").write_text(json.dumps({"format": MANIFEST_FORMAT, "entries": [entry]}))
    assert FixtureClient(str(tmp_path)).post("/g_variants", BODY).body == body
