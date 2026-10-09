"""Pagination arithmetic, isolated because it is so commonly got wrong.

NORMATIVE: ``skip`` counts PAGES, not records.

    "In the request: number of pages to skip"
    -- framework/src/common/beaconCommonComponents.yaml, Skip

so the record offset is ``skip * limit``. The framework documentation works the
example through: skip 2 with limit 8 returns records 17-24. A client that treats
``skip`` as a record offset silently returns the wrong window -- results that
look entirely plausible and are simply not the ones requested.

``limit: 0`` means "all results, or the server maximum".

This module is deliberately a separate, fully tested unit rather than inline
arithmetic in the fetch loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    """One page request."""

    skip: int
    limit: int

    @property
    def record_offset(self) -> int:
        """First record index covered by this page: ``skip * limit``."""
        return int(self.skip) * int(self.limit)


def page_for_record_offset(offset: int, limit: int) -> Page:
    """Return the page containing a given record offset.

    Raises when ``offset`` is not a whole multiple of ``limit``: the API cannot
    express an arbitrary record offset, and silently rounding would return a
    different window than the caller asked for.

    ``limit: 0`` is a single page holding everything, so only offset 0 exists.
    """
    offset, limit = int(offset), int(limit)
    if offset < 0 or limit < 0:
        raise ValueError("offset and limit must be non-negative")
    if limit == 0:
        if offset != 0:
            raise ValueError("limit 0 is a single page of everything; no offset "
                             "other than 0 exists")
        return Page(skip=0, limit=0)
    if offset % limit:
        raise ValueError(
            f"record offset {offset} is not a multiple of page size {limit}; skip "
            f"counts PAGES, so the API cannot start a page there"
        )
    return Page(skip=offset // limit, limit=limit)


def iter_pages(limit: int, max_pages: int, start_skip: int = 0):
    """Yield successive :class:`Page` values for a paged fetch.

    ``skip`` advances by ONE per page, never by ``limit``: it is a page index.
    ``limit: 0`` yields a single page, because one request returns everything.
    """
    if int(limit) == 0:
        yield Page(skip=0, limit=0)
        return
    for skip in range(int(start_skip), int(start_skip) + int(max_pages)):
        yield Page(skip=skip, limit=int(limit))


def is_exhausted(returned_count: int, limit: int, num_total_results: int | None,
                 records_so_far: int) -> bool:
    """Decide whether to stop paging.

    Stops on a short page, on reaching ``numTotalResults`` where the provider
    supplied it, or on ``max_pages``. ``numTotalResults`` is the total for the
    whole query, NOT the count in this batch.

    UNITS: ``records_so_far`` must be in the same unit as ``numTotalResults``.
    On a provider whose total counts caseLevelData instances, pass instances.
    Passing records against an instance total errs safe -- records <= instances,
    so it can only over-fetch, and the short-page check then stops it -- but it
    costs a request.
    """
    if int(limit) == 0:
        return True
    if int(returned_count) < int(limit):
        return True
    if num_total_results is not None and int(records_so_far) >= int(num_total_results):
        return True
    return False
