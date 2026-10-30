"""Transport-level failure discrimination, driven by tests/fixtures/transport/.

Four refusals and one silent success, each arriving looking like something
else:

  * an edge bot-block -- 403, HTML body, no credential would help, NOT retryable
  * a genuine Beacon authorisation refusal -- the same 403, JSON envelope
  * a provider outage -- 503, HTML body, retryable
  * a bare timeout -- no status, no body, 0 bytes, retryable
  * a wrong-entity response -- HTTP 200, well-formed, no error field at all

TWO CROSSING PAIRS, WHICH IS THE WHOLE POINT
    The 403 block and the 403 auth refusal share a STATUS and differ in BODY.
    The 403 block and the 503 outage share a BODY SHAPE and differ in STATUS
    CLASS. Because the pairs cross, no single-dimension rule can satisfy all
    four -- which is what forces status class and body to be consulted
    together.

    An earlier version of this file asserted that a 503 with an HTML body was a
    bot challenge. That was wrong in the worst direction: it would have told a
    user whose beacon was merely in maintenance that their Galaxy instance
    needed allow-listing, and it would have retried a bot challenge while
    correctly retrying the outage for the wrong reason. The 503 rows below now
    assert the opposite, and the retryability assertions exist so the same
    collapse cannot come back through a different door.

TWO LAYERS, DELIBERATELY
    The self-consistency tests below are body-complete and run TODAY, with no
    implementation. That matters because a fixture nothing reads is
    indistinguishable from a fixture that is wrong -- nothing had checked these
    `_expected` values were even internally coherent. Those tests check the
    fixtures against themselves.

    The behavioural tests skip loudly until the bodies land, in the same
    pattern as test_classify and test_coalescence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transport"

BLOCKED_HTML = FIXTURES / "provider_blocked.html"
BLOCKED_EXPECTED = FIXTURES / "provider_blocked.expected.json"
GENUINE_403 = FIXTURES / "beacon_403_genuine.json"
UNAVAILABLE_HTML = FIXTURES / "provider_unavailable_503.html"
UNAVAILABLE_EXPECTED = FIXTURES / "provider_unavailable_503.expected.json"
TIMEOUT = FIXTURES / "provider_timeout.json"
ENTITY_MISMATCH = FIXTURES / "entity_type_mismatch.json"
LIVE_CNV = FIXTURES.parent / "classify" / "bycon_cnv_live.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _expected(path: Path) -> dict:
    return _json(path)["_expected"]


# --------------------------------------------------------------------------
# Layer 1: the fixtures are coherent. Runs now, no implementation needed.
# --------------------------------------------------------------------------


def test_the_403_pair_differs_on_body_not_status():
    """Same status, different body: this pair isolates the body dimension."""
    html = BLOCKED_HTML.read_text()

    with pytest.raises(json.JSONDecodeError):
        json.loads(html)

    assert html.lstrip().lower().startswith("<!doctype html")
    genuine = _json(GENUINE_403)
    assert "error" in genuine, "a genuine Beacon refusal carries a beaconError"
    assert genuine["error"]["errorCode"] == 403
    assert _expected(BLOCKED_EXPECTED)["failure"] == "blocked"
    assert _json(GENUINE_403)["_expected"]["status"] == "auth_missing"


def test_the_html_pair_differs_on_status_class_not_body():
    """Same body shape, different status class: isolates the status dimension.

    Both are HTML with no Beacon envelope. If a rule could tell them apart from
    the body it would not need the status, and this is the pair that proves it
    cannot -- they are near-indistinguishable as payloads and have opposite
    outcomes.
    """
    for path in (BLOCKED_HTML, UNAVAILABLE_HTML):
        body = path.read_text()
        with pytest.raises(json.JSONDecodeError):
            json.loads(body)
        assert "<html" in body.lower()
        assert "responsesummary" not in body.lower()

    assert _expected(BLOCKED_EXPECTED)["failure"] == "blocked"
    assert _expected(UNAVAILABLE_EXPECTED)["failure"] == "unavailable"


def test_retryability_opposes_across_the_html_pair():
    """The two HTML cases must differ on retryability.

    Retrying an outage is what backoff is for. Retrying a challenge is futile
    and makes us look more like the automated traffic being blocked. A single
    flag keyed on "HTML body" would get one of the two backwards.
    """
    assert _expected(UNAVAILABLE_EXPECTED)["retryable"] is True
    assert _expected(BLOCKED_EXPECTED)["retryable"] is False


def test_timeout_fixture_has_nothing_to_discriminate_on():
    """A bare timeout has no status and no body, by construction.

    Recorded because any rule that inspects the payload first has nothing to
    inspect here, and must still reach `unavailable`.
    """
    payload = _json(TIMEOUT)["_transport"]
    assert payload["status"] is None
    assert payload["body"] is None
    assert payload["bytes_received"] == 0
    assert _json(TIMEOUT)["_expected"]["failure"] == "unavailable"
    assert _json(TIMEOUT)["_expected"]["retryable"] is True


def test_blocked_fixture_carries_no_beacon_envelope():
    """An edge block never reaches the Beacon application.

    If this body contained a `meta` or `responseSummary`, it would be modelling
    a Beacon response rather than an edge refusal.
    """
    html = BLOCKED_HTML.read_text().lower()
    for beacon_marker in ("responsesummary", "\"meta\"", "beaconerror", "apiversion"):
        assert beacon_marker not in html, f"unexpected Beacon marker: {beacon_marker}"


def test_genuine_403_expects_a_real_status_value():
    """The fixture's expected status must be a member of the Status enum."""
    from beacon2_import.formats.outcomes import Status

    expected = _json(GENUINE_403)["_expected"]["status"]
    assert expected in {member.value for member in Status}


def test_all_four_outcomes_are_separately_representable():
    """Without distinct members, an alias would satisfy the behavioural tests.

    `blocked` quietly aliased to `error`, or `unavailable` to `blocked`, would
    pass every behavioural assertion while destroying the distinction the
    statuses exist for.
    """
    from beacon2_import.formats.outcomes import Status

    distinct = {Status.BLOCKED, Status.UNAVAILABLE, Status.ERROR, Status.AUTH_MISSING}
    assert len(distinct) == 4
    assert Status.BLOCKED.value == "blocked"
    assert Status.UNAVAILABLE.value == "unavailable"


def test_unavailable_note_does_not_send_the_user_to_an_administrator():
    """An outage note must not carry the allow-listing remedy.

    This is the user-visible half of the bug: the two notes are actionable in
    completely different directions, and the wrong one wastes an
    administrator's time or a partner's.
    """
    from beacon2_import.formats.outcomes import NOTE_TEMPLATES

    unavailable = NOTE_TEMPLATES["provider_unavailable"].lower()
    assert "allow-list" not in unavailable
    assert "retry" in unavailable or "retrying" in unavailable
    assert "allow-list" in NOTE_TEMPLATES["provider_blocked"].lower()


def test_blocked_has_an_actionable_note_template():
    """The note must tell an administrator what to do, and rule out a credential.

    A `blocked` row that read like an error would defeat the point of the
    separate status.
    """
    from beacon2_import.formats.outcomes import NOTE_TEMPLATES

    template = NOTE_TEMPLATES["provider_blocked"].lower()
    assert "allow-list" in template
    assert "credential" in template
    assert "administrator" in template


def test_entity_mismatch_fixture_actually_mismatches():
    """The requested and returned entity types must genuinely differ.

    Self-consistency: `_expected.returned_entity_type` has to agree with what
    `meta.returnedSchemas` actually says, or the fixture asserts one thing and
    contains another.
    """
    payload = _json(ENTITY_MISMATCH)
    requested = payload["_requested_entity_type"]
    returned = payload["meta"]["returnedSchemas"][0]["entityType"]

    assert requested != returned
    assert payload["_expected"]["returned_entity_type"] == returned
    assert payload["_expected"]["raises"] == "EntityTypeMismatch"


def test_entity_mismatch_looks_like_success():
    """The fixture must be a well-formed success, or it proves nothing.

    The failure this guards is silent: HTTP 200, a valid envelope, no error
    field, records present. A fixture carrying an error marker would be caught
    by ordinary error handling and would not exercise the check at all.
    """
    payload = _json(ENTITY_MISMATCH)
    assert "error" not in payload
    assert payload["responseSummary"]["exists"] is True
    assert payload["responseSummary"]["numTotalResults"] > 0
    results = payload["response"]["resultSets"][0]["results"]
    assert results, "a mismatch with no records could not be misfiled"


# --------------------------------------------------------------------------
# Layer 2: behaviour. Skips until the bodies land.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,content_type,body_path,expected,retryable",
    [
        (403, "text/html; charset=utf-8", BLOCKED_HTML, "blocked", False),
        (429, "text/html", BLOCKED_HTML, "blocked", False),
        (403, "application/json", GENUINE_403, "auth", False),
        # A 5xx is an outage WHATEVER the body looks like. These two rows are
        # the regression test for the content-type-only rule.
        (503, "text/html", UNAVAILABLE_HTML, "unavailable", True),
        (503, "text/html", BLOCKED_HTML, "unavailable", True),
        (500, "application/json", GENUINE_403, "unavailable", True),
        (502, None, None, "unavailable", True),
    ],
    ids=[
        "html_403_blocked",
        "html_429_blocked",
        "json_403_auth",
        "html_503_outage",
        "challenge_body_on_503_is_still_an_outage",
        "json_500_outage",
        "bodyless_502_outage",
    ],
)
def test_transport_failure_classification(status, content_type, body_path,
                                          expected, retryable):
    """Status class is consulted before the body, and never overridden by it.

    ``challenge_body_on_503_is_still_an_outage`` is the sharpest row: it feeds
    the bot-challenge body in on a 503 and requires `unavailable` anyway. An
    implementation that inspects the body first cannot pass it.
    """
    from beacon2_import.transport.http import BeaconClient, TransportFailure

    body = body_path.read_text() if body_path is not None else None
    try:
        failure = BeaconClient.classify_transport_failure(status, content_type, body)
        assert BeaconClient.is_retryable(failure) is retryable
    except NotImplementedError:
        pytest.skip(
            "classify_transport_failure()/is_retryable() not yet implemented -- "
            "these fixtures are their spec"
        )

    assert failure is TransportFailure(expected)


def test_timeout_classifies_without_a_body():
    """No status, no body, zero bytes: still `unavailable`, still retryable."""
    from beacon2_import.transport.http import BeaconClient, TransportFailure

    transport = _json(TIMEOUT)["_transport"]
    try:
        failure = BeaconClient.classify_transport_failure(
            transport["status"], transport["content_type"], transport["body"],
            bytes_received=transport["bytes_received"],
        )
        assert BeaconClient.is_retryable(failure) is True
    except NotImplementedError:
        pytest.skip("classify_transport_failure() not yet implemented")

    assert failure is TransportFailure.UNAVAILABLE


def test_entity_type_mismatch_raises():
    """A wrong-entity response is an error, never a warning."""
    from beacon2_import.normalise.envelope import (
        EntityTypeMismatch,
        assert_entity_type,
        parse,
    )

    payload = _json(ENTITY_MISMATCH)
    try:
        envelope = parse(payload)
    except NotImplementedError:
        pytest.skip("envelope.parse() not yet implemented")

    with pytest.raises(EntityTypeMismatch):
        assert_entity_type(envelope, payload["_requested_entity_type"])


def test_matching_entity_type_passes():
    """The contrast case: a correct entity type must not raise.

    Borrowed from the coalescence fixtures, which declare
    `returnedSchemas[0].entityType` as genomicVariant. Without this, an
    implementation that raised unconditionally would pass the test above.
    """
    from beacon2_import.normalise.envelope import assert_entity_type, parse

    coalescence = FIXTURES.parent / "coalescence" / "holds_complete_exact_large_page.json"
    payload = json.loads(coalescence.read_text())
    try:
        envelope = parse(payload)
    except NotImplementedError:
        pytest.skip("envelope.parse() not yet implemented")

    assert_entity_type(envelope, "genomicVariant")


def test_effective_limit_prefers_the_response():
    """The applied limit wins over the requested one.

    The large-page fixture requests 100 and is answered with 2000, so an
    implementation reading the request fails here specifically.
    """
    from beacon2_import.normalise.envelope import effective_limit, parse

    coalescence = FIXTURES.parent / "coalescence" / "holds_complete_exact_large_page.json"
    payload = json.loads(coalescence.read_text())
    try:
        envelope = parse(payload)
        limit, source = effective_limit(envelope, payload["_requested_limit"])
    except NotImplementedError:
        pytest.skip("envelope.parse()/effective_limit() not yet implemented")

    assert limit == 2000
    assert source == "response"

# ---------------------------------------------------------------------------
# A RECORDED FAILURE REPLAYS AS A FAILURE
#
# The trap this guards: FixtureClient overrides _request, so it bypassed the
# live client's status classification entirely. A recorded 500 came back as a
# Response with an empty body -- indistinguishable, to every caller above it,
# from a provider that answered "nothing found". An outage cannot be tested at
# all if replaying it produces a plausible success.
# ---------------------------------------------------------------------------

def _recorded(tmp_path, payload):
    """A one-entry fixture directory keyed on POST /datasets."""
    from beacon2_import.transport.http import MANIFEST_FORMAT

    request = {"method": "POST", "path": "/datasets", "query": {}}
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"format": MANIFEST_FORMAT,
         "entries": [{"request": request, "response": "r-recorded.json",
                      "origin": "recorded", "note": "a recorded failure"}]}))
    (tmp_path / "r-recorded.json").write_text(json.dumps(payload))
    return tmp_path


@pytest.mark.parametrize("status,content_type,expected_name", [
    (500, "text/html; charset=iso-8859-1", "ProviderUnavailable"),
    (503, "text/html", "ProviderUnavailable"),
    (403, "text/html", "ProviderBlocked"),
    (422, "application/json", "RequestRejected"),
])
def test_a_recorded_failure_replays_as_the_same_failure(
        tmp_path, status, content_type, expected_name):
    """Replay classifies on the status and content type that were recorded."""
    from beacon2_import.transport import http

    directory = _recorded(tmp_path, {"_status": status,
                                     "_content_type": content_type,
                                     "_body_excerpt": "a provider error page"})
    client = http.FixtureClient(str(directory))
    with pytest.raises(getattr(http, expected_name)):
        client.post("/datasets", {})


def test_a_recorded_success_is_still_served(tmp_path):
    """The failure branch must not swallow ordinary recordings."""
    from beacon2_import.transport.http import FixtureClient

    directory = _recorded(tmp_path, {"meta": {}, "response": {}})
    response = FixtureClient(str(directory)).post("/datasets", {})
    assert response.status == 200
    assert response.body["meta"] == {}
