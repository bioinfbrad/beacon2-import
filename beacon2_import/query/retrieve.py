"""Retrieval: complete-or-refuse for random-subset providers.

THE RULE
    Against a provider whose pages are random draws, a request below the total
    returns a random subset -- INCLUDING the first page. A default query that
    returns a random 100 of 2591, reports `ok / 100` and differs every run is
    the same failure as everything else this project guards against, reached
    through a default, which is the worst route because nobody chose it.

    So for those providers the default is COMPLETE OR REFUSE:

      1. Pre-flight a minimal request to read numTotalResults.
      2. Under the ceiling: retrieve with limit 0, then VERIFY the instance sum
         against the full response's own total. A shortfall means the server
         applied a maximum below the total -- refuse, never compute over the
         partial set.
      3. Over the ceiling: refuse, stating the total, the ceiling and the two
         remedies.

    Sampling is an explicit opt-in. When chosen, the result is labelled as a
    random sample on every row and in the run report. A sample is a legitimate
    exploratory choice; it is not a legitimate default.

    Providers with ordinary pagination keep the requested pagination.

WHY THE PRE-FLIGHT USES limit 1 AND NOT count GRANULARITY
    A count-granularity request would read the total more cheaply, but it may
    be served by a different code path, and its total is not guaranteed to be
    in the same unit as the record request it is standing in for. One record
    at the same granularity keeps the pre-flight the same query, smaller.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from ..normalise.envelope import Envelope, instance_count, is_complete_retrieval, parse
from .model import Pagination, Query


class RetrievalMode(str, Enum):
    PAGES = "pages"        # ordinary pagination, requested pagination honoured
    FULL = "full"          # complete retrieval, verified
    SAMPLE = "sample"      # explicit opt-in random sample, labelled
    REFUSE = "refuse"      # over the ceiling, or a full retrieval came back short
    EMPTY = "empty"        # pre-flight total was zero: complete without fetching


@dataclass(frozen=True)
class RetrievalDecision:
    """What to do for one query, given its pre-flight total."""

    mode: RetrievalMode
    total: int | None
    ceiling: int
    sample_size: int | None = None
    reason: str = ""


@dataclass
class RetrievalResult:
    """A retrieval and everything needed to label it honestly."""

    decision: RetrievalDecision
    envelope: Envelope | None
    records: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = False
    random_sample: bool = False
    preflight_total: int | None = None
    refusal: str | None = None
    requests_issued: int = 0


def refusal_message(provider_name: str, total: int, ceiling: int) -> str:
    """The over-ceiling refusal. Must state the total, the ceiling and both remedies."""
    return (
        f"{provider_name} holds {total} matching variant instances, above the "
        f"complete-retrieval ceiling of {ceiling}. A request smaller than the total "
        f"cannot be trusted to be the first part of it -- some providers return a "
        f"different random subset each time -- so a partial retrieval would not be "
        f"an answer. So narrow the query: an ontology filter usually brings the total "
        f"down furthest (for example --filter NCIT:C3058 for glioblastoma), as does a "
        f"smaller region or fewer variant classes. Or opt into sampling with "
        f"--sample N, in which case the results are labelled as a random sample."
    )


def short_retrieval_message(provider_name: str, retrieved: int, total: int) -> str:
    """A full retrieval that came back short. States what was OBSERVED only.

    The cause is not knowable from the response: a server may cap the request,
    or report a total it cannot fully deliver -- cancercelllines reported 184
    individuals and delivered 180 at limit 0. Either way it is not complete.
    """
    return (
        f"{provider_name} was asked for all {total} matching instances but returned "
        f"{retrieved}. A retrieval short of the provider's own total is not a "
        f"complete answer, so it was refused rather than reported as complete. "
        f"Narrow the query -- an ontology filter usually "
        f"brings the total down furthest, e.g. --filter NCIT:C3058 -- or opt into "
        f"sampling with --sample N."
    )


def decide_retrieval(provider, adapter, total: int | None,
                     sample_size: int | None = None) -> RetrievalDecision:
    """Choose a retrieval mode from the pre-flight total. Pure: no I/O."""
    ceiling = int(getattr(provider, "full_retrieval_ceiling", 10000))
    if adapter.may_paginate():
        return RetrievalDecision(RetrievalMode.PAGES, total, ceiling,
                                 reason="provider pages are contiguous")
    if sample_size is not None:
        return RetrievalDecision(RetrievalMode.SAMPLE, total, ceiling, int(sample_size),
                                 reason="random sample explicitly requested")
    if total is None:
        return RetrievalDecision(
            RetrievalMode.REFUSE, None, ceiling,
            reason=(f"{provider.name} did not report a total, so a complete "
                    f"retrieval cannot be verified"),
        )
    if total == 0:
        return RetrievalDecision(RetrievalMode.EMPTY, 0, ceiling,
                                 reason="no matches; complete without fetching")
    if total > ceiling:
        return RetrievalDecision(RetrievalMode.REFUSE, total, ceiling,
                                 reason=refusal_message(provider.name, total, ceiling))
    return RetrievalDecision(RetrievalMode.FULL, total, ceiling,
                             reason="under the ceiling; retrieving everything")


def _send(client, adapter, query: Query) -> Envelope:
    return parse(adapter.send(client, query).body)


def retrieve(query: Query, provider, adapter, client,
             sample_size: int | None = None) -> RetrievalResult:
    """Execute one query with the complete-or-refuse policy."""
    ceiling = int(getattr(provider, "full_retrieval_ceiling", 10000))

    if adapter.may_paginate():
        envelope = _send(client, adapter, query)
        decision = RetrievalDecision(RetrievalMode.PAGES, envelope.num_total_results,
                                     ceiling, reason="provider pages are contiguous")
        records = list(envelope.records)
        return RetrievalResult(
            decision, envelope, records,
            complete=is_complete_retrieval(records, envelope.num_total_results),
            random_sample=False, preflight_total=None, requests_issued=1,
        )

    # 1. Pre-flight: one record, same query, to read the total.
    preflight = _send(client, adapter,
                      replace(query, pagination=Pagination(skip=0, limit=1)))
    total = preflight.num_total_results
    decision = decide_retrieval(provider, adapter, total, sample_size)

    if decision.mode is RetrievalMode.EMPTY:
        return RetrievalResult(decision, preflight, [], complete=True,
                               preflight_total=total, requests_issued=1)
    if decision.mode is RetrievalMode.REFUSE:
        return RetrievalResult(decision, preflight, [], complete=False,
                               preflight_total=total, refusal=decision.reason,
                               requests_issued=1)

    if decision.mode is RetrievalMode.SAMPLE:
        envelope = _send(client, adapter,
                         replace(query, pagination=Pagination(0, decision.sample_size)))
        records = list(envelope.records)
        complete = is_complete_retrieval(records, envelope.num_total_results)
        return RetrievalResult(decision, envelope, records, complete=complete,
                               random_sample=not complete, preflight_total=total,
                               requests_issued=2)

    # 2. Full retrieval, then verify against the FULL response's own total --
    #    not the pre-flight's, which may have moved between the two requests.
    envelope = _send(client, adapter,
                     replace(query, pagination=adapter.full_retrieval_pagination(decision.total)))
    records = list(envelope.records)
    full_total = envelope.num_total_results
    if not is_complete_retrieval(records, full_total):
        message = short_retrieval_message(provider.name, instance_count(records),
                                          full_total if full_total is not None else -1)
        refused = replace(decision, mode=RetrievalMode.REFUSE, reason=message)
        return RetrievalResult(refused, envelope, [], complete=False,
                               preflight_total=total, refusal=message,
                               requests_issued=2)
    return RetrievalResult(decision, envelope, records, complete=True,
                           preflight_total=total, requests_issued=2)
