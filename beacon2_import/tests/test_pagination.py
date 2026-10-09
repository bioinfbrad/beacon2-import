"""Pagination arithmetic -- the isolated, tested unit it was always meant to be.

NORMATIVE: ``skip`` counts PAGES. Offset = skip * limit. The framework's own
worked example is skip 2, limit 8 -> records 17-24.
"""

from __future__ import annotations

import pytest

from beacon2_import.normalise.pagination import (
    Page, is_exhausted, iter_pages, page_for_record_offset,
)


def test_the_framework_worked_example():
    page = Page(skip=2, limit=8)
    assert page.record_offset == 16
    first, last = page.record_offset + 1, page.record_offset + page.limit
    assert (first, last) == (17, 24)


def test_treating_skip_as_a_record_offset_is_the_bug():
    """The commonest mis-implementation, pinned so it cannot creep back.

    A client wanting records 17-24 that sends skip=16 is asking for page 16,
    which starts at record 129.
    """
    assert Page(skip=16, limit=8).record_offset == 128
    assert page_for_record_offset(16, 8) == Page(skip=2, limit=8)


def test_an_offset_mid_page_cannot_be_expressed():
    with pytest.raises(ValueError, match="PAGES"):
        page_for_record_offset(17, 8)


def test_limit_zero_is_one_page_of_everything():
    assert page_for_record_offset(0, 0) == Page(skip=0, limit=0)
    with pytest.raises(ValueError):
        page_for_record_offset(5, 0)
    assert list(iter_pages(0, max_pages=10)) == [Page(skip=0, limit=0)]


def test_iteration_advances_skip_by_one_page():
    pages = list(iter_pages(limit=50, max_pages=3))
    assert [p.skip for p in pages] == [0, 1, 2]
    assert [p.record_offset for p in pages] == [0, 50, 100]


def test_iteration_resumes_from_a_page():
    assert [p.skip for p in iter_pages(10, 2, start_skip=4)] == [4, 5]


@pytest.mark.parametrize(
    "returned,limit,total,so_far,stop",
    [
        (50, 50, 200, 50, False),     # full page, more remain
        (50, 50, 200, 200, True),     # total reached
        (12, 50, None, 112, True),    # short page, no total reported
        (50, 50, None, 150, False),   # full page, no total: keep going
        (1713, 0, 2591, 1713, True),  # limit 0 is everything in one request
    ],
    ids=["more_remain", "total_reached", "short_page", "no_total", "limit_zero"],
)
def test_exhaustion(returned, limit, total, so_far, stop):
    assert is_exhausted(returned, limit, total, so_far) is stop
