# Adapter and retrieval fixtures

Consumed by `tests/test_adapters.py`. These encode findings from three rounds of
live POST probes against cancercelllines (chr3:195,728,637-198,169,247,
EFO:0030070).

| fixture | finding | what it pins |
|---|---|---|
| `filtered_retrieval_shape.json` | 7 | `numTotalResults` counts caseLevelData **instances**, `limit` counts **records**. Completeness is the instance sum, not the record count. |
| `random_subset_pages.json` | 5 | Below the total, pages are independent random draws — paging is sampling with replacement. |
| `test_mode_echo_forms.json` | 10 | `testMode` echoes as `{}`, `false` or `true`. Truthiness works; type checks do not. |
| `fixture_provider/` | — | Manifest round-trip for `FixtureClient`, including that a miss raises. |

## On `filtered_retrieval_shape.json`

**Constructed, not verbatim.** The raw body was not available to me, so this
reproduces the shape and the arithmetic of the observed response (55 records,
60 instances, `numTotalResults` 60) at a readable size: 3 records, 4 instances,
`numTotalResults` 4. `_observed_original` records the real numbers.

The assertions are written against the *arithmetic* rather than the row count,
so dropping the raw response in its place will not break them. Worth doing —
a verbatim capture would also carry field spellings this reconstruction cannot
vouch for.

## Why the unit mismatch is only conservative

`verify_coalescence` compares `numTotalResults <= limit`, which compares
instances against records. Instances ≥ records always, so the comparison can
never call a truncated result complete — it can only refuse some results that
were in fact complete. Safe direction, and documented rather than fixed,
because the unit-correct test needs the records in hand:

```
sum(len(record.caseLevelData) for record in records) == numTotalResults
```
