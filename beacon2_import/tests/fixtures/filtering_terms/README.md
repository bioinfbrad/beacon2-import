# Filtering terms fixtures

These two record a **negative finding** and its contrast, both live from
cancercelllines.org. Consumed by `tests/test_filtering_terms.py`.

## Server-side prefix filtering does not exist on this stack

`/filtering_terms?filters=EFO` and `?filters=SO` both return
`{"filteringTerms": [], "resources": []}`. The request echo shows why:
`filters: [{"id": "EFO"}]`. The bare prefix was accepted and interpreted as a
filter term whose id is literally `EFO`, which matches nothing. It is not a
prefix query and it does not error — it silently returns nothing.

That silence is what makes it worth a fixture. Shipping prefix filtering as a
server-side parameter would give users an empty result for a perfectly good
prefix and no indication that the parameter was misunderstood. So
`beacon2_filtering_terms` fetches the term list and filters on the CURIE prefix
**client-side**, and the registry records
`filtering_terms_prefix_filter: false`.

## What this kills

Filtering terms had been assessed as the one informational endpoint with
genuine signal for evidencing `variant_classes_served`. The prefix route to
that signal is now closed.

A full-list route may survive: `?limit=5` returns real terms carrying a `count`
field, so fetching the whole list and looking for SO or EFO copy-number terms
would give both presence and holdings volume. But it is a large unpaginated
fetch, and it is now the only remaining non-`testMode` route.

`testMode` sampling therefore stands as the practical evidence mechanism — with
the caveat that it returns *random* documents, so it can only ever write `yes`,
never `no`.
