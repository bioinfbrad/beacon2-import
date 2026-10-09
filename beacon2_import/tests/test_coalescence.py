"""Coalescence completeness logic, against synthetic responseSummary blocks.

Written now, against fixtures rather than a live beacon, because the real
values from a partner will CONFIRM the branch selection, not define it. The
four fixtures cover exactly the four conditions verify_coalescence() branches
on, so the logic is pinned before any implementation exists.

Until verify_coalescence() is implemented these SKIP with an explicit reason
rather than failing, so the suite stays green through the skeleton phase and
activates by itself the moment the function lands. The skip message names what
is missing -- a silent pass would be worse than a red build.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "coalescence"
CASES = sorted(p.name for p in FIXTURES.glob("*.json"))


@pytest.mark.parametrize("case", CASES)
def test_verdict_matches_fixture(case):
    """Each fixture declares its own expected verdict in ``_expected``."""
    from beacon2_import.normalise.envelope import parse
    from beacon2_import.query.planner import verify_coalescence

    payload = json.loads((FIXTURES / case).read_text())
    expected = payload["_expected"]
    try:
        envelope = parse(payload)
        verdict = verify_coalescence(envelope, payload["_requested_limit"])
    except NotImplementedError:  # skeleton phase only
        pytest.skip(
            "verify_coalescence()/envelope.parse() not yet implemented -- "
            "these fixtures are the specification for them"
        )

    assert verdict.holds is expected["holds"], case
    assert verdict.not_test_mode is expected["not_test_mode"], case
    assert verdict.has_total is expected["has_total"], case
    assert verdict.within_limit is expected["within_limit"], case
    assert verdict.count_exact is expected["count_exact"], case
    if "limit_source" in expected:
        assert verdict.limit_source == expected["limit_source"], case
    if not verdict.holds:
        assert verdict.reason.strip(), f"{case}: a rejection must state why"


def test_test_mode_is_never_coalescable():
    """A testMode response must be rejected even when every count agrees.

    Its fixture passes has_total, within_limit and count_exact, so an
    implementation checking only the three arithmetic conditions would coalesce
    it -- over a random sample of the collection.
    """
    payload = json.loads((FIXTURES / "rejects_test_mode.json").read_text())
    expected = payload["_expected"]
    assert expected["has_total"] and expected["within_limit"] and expected["count_exact"]
    assert expected["not_test_mode"] is False
    assert expected["holds"] is False
    assert payload["meta"]["receivedRequestSummary"]["testMode"] is True


def test_fixture_names_match_their_verdicts():
    """A `holds_` fixture must hold and a `rejects_` fixture must not.

    Name-based rather than a count, so adding a case cannot silently flip the
    guard -- which a hardcoded "exactly one holds" would have done the moment a
    second holding case arrived.
    """
    mismatched = []
    for case in CASES:
        expected = json.loads((FIXTURES / case).read_text())["_expected"]["holds"]
        if case.startswith("holds_") and not expected:
            mismatched.append(f"{case} is named holds_ but expects False")
        if case.startswith("rejects_") and expected:
            mismatched.append(f"{case} is named rejects_ but expects True")
    assert not mismatched, "; ".join(mismatched)
    assert any(c.startswith("holds_") for c in CASES)
    assert any(c.startswith("rejects_") for c in CASES)


def test_holding_cases_cover_more_than_one_page_size():
    """The permissive branch must be exercised at more than one page size.

    Provider page defaults differ by an order of magnitude, and a condition
    tested only at a small page could hide an assumption that a large page
    would expose.
    """
    limits = {
        json.loads((FIXTURES / c).read_text())["_expected"]["effective_limit"]
        for c in CASES
        if c.startswith("holds_")
    }
    assert len(limits) >= 2, f"holding cases all use the same page size: {limits}"
