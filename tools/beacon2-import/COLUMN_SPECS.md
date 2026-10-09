# Output column specifications

Version 3.0.0. Both files are tab-separated with a single header line. Every
query tool emits both, always, including when nothing was found and including
when every provider failed.

---

## `results.tsv`

One row per match. Provenance columns come first and are identical across every
tool; entity columns follow and vary by what was queried.

Because every row carries both `beacon_id` and `variant_class`, filtering
recovers any single-beacon or single-class view. One run answers the combined,
the per-beacon and the per-class question, which is why there is no separate
tool for any of them.

### Provenance columns (always present, always in this order)

| # | Column | Type | Values | Notes |
|---|---|---|---|---|
| 1 | `beacon_id` | string | registry id | Our stable id, not the beacon's self-reported one. |
| 2 | `beacon_name` | string | free text | Display name from the data table. |
| 3 | `access_tier` | enum | `public` `registered` `controlled` | As configured, not as claimed by the server. |
| 4 | `variant_class` | enum | `CNV` `SMALL_VARIANT` `SV` `REPEAT` `unclassified` | Never blank. Never `SNV` — see note below. |
| 5 | `classification_basis` | string | free text | How column 4 was decided. `pinned by query` when the class came from the request; otherwise the evidence used, e.g. `EFO:0030067 copy-number term`, `ref/alt length 1 <= 50 (convention)`. |
| 6 | `granularity_returned` | enum | `record` `count` `boolean` | From `meta.returnedGranularity`, which overrides anything the registry declares. |
| 7 | `count_precision` | enum | `exact` `imprecise` `rounded` | Defaults to `imprecise`, matching the specification's own default. |
| 8 | `count_precision_basis` | enum | `partial_retrieval` `failed_verification` `declared` `declared_adjustment` `inferred_from_complete_retrieval` `normative_default` | How column 7 was decided. See below. |
| 9 | `count_adjusted_to` | integer or empty | | Present only when the beacon declares rounding. |
| 10 | `query_degraded` | boolean | `true` `false` | True if the query was weakened for this beacon, or the rows are a random sample. |
| 11 | `degradation_notes` | string | free text | Semicolon-separated. Empty when column 10 is false. |
| 12 | `expansion_notes` | string | free text | Records client-side term expansion, and flags where an expansion crossed a locally inferred hierarchy edge. |

**On column 4.** The value is `SMALL_VARIANT`, never `SNV`, even though the tool
form labels it "SNV / small indel". This file gets saved, joined and cited; a
row describing a 12 bp frameshift labelled `SNV` would be wrong in the data with
no way for a downstream reader to correct it.

**On columns 7 and 8, partiality first.** `partial_retrieval` means the beacon
delivered fewer variant instances than the total it reported. It is OBSERVED in
each response, never taken from the registry or from the server's own
declarations, and it always overrides them: such rows are never `exact`. In
`outcomes.tsv` the note states how many of how many, for every request behind
that row.

`failed_verification` means the response held records outside the requested
region, or of a class the request itself excluded: the provider did not apply
what was sent, so its total no longer counts answers to the query. Such
records are excluded from the results and reported in `outcomes.tsv`; the rows
that remain carry this basis too.

bycon sends neither `countPrecision` nor
`countAdjustedTo`, so under the specification's default every bycon count would
be `imprecise`. Exactness is therefore inferred when, and only when, both
fields are absent, the response is at record granularity, and the
`caseLevelData` instance sum equals `numTotalResults`. An inferred `exact` reads
`inferred_from_complete_retrieval`, never `declared`, so a reader can always
tell an inference from a server's statement. An explicit `imprecise` or
`rounded`, or any declared adjustment, always wins.

**On column 5.** A reader must be able to tell a class that was *requested* from
one that was *inferred from a returned record*. Rows from a class-pinned query
read `pinned by query`; rows from a class-unknown or coalesced query carry the
actual evidence.

**Class is assigned by claim type, never by size.** A record carrying reference
and alternate bases makes a *sequence* claim and is `SMALL_VARIANT` at any
length, with the size disclosed in the basis — for example
`sequence-specified insertion; length 120 exceeds the 50 bp convention`. The 50
bp figure is a widely used convention rather than a specification value, and it
controls disclosure only. Filing a large sequence-specified indel as `SV` would
place a record with no breakpoint into a bucket whose frequency unit is
breakpoint density, where it could only contribute a silent undercount or a
fabricated junction.

The same record with no bases reported has neither a sequence nor a junction
claim, so it becomes `CNV` if a copy-number term is present and `unclassified`
otherwise. Identical size, different claim, different class.

### Entity columns

**Genomic variants**

`variant_internal_id`, `chromosome`, `start`, `end`, `variant_length`,
`reference_bases`, `alternate_bases`, `variant_type_raw`, `efo_id`,
`biosample_id`, `individual_id`, `analysis_id`, `run_id`, `dataset_id`

**`variant_length`** — size of the event in bases, independent of its class:

* interval-defined events: `end − start`
* sequence-specified indels: the absolute difference in allele lengths
* sequence-specified substitutions: the reference allele length
* empty where neither coordinates nor alleles are available

This column exists so that "is it structural?" is a column question. Filtering
`variant_length >= 50` returns every large event across all classes, which is
what makes it safe for `variant_class` to be decided strictly by claim type
with size never reassigning it.

Coordinates are **1-based inclusive** for display, converted once at the output
boundary from the 0-based half-open values used on the wire.

One row per **case-level observation**, not per variant. A variant seen in three
biosamples produces three rows. This is the normative `caseLevelData` shape and
it is exploded in the normaliser rather than the analysis layer, because it is
exactly the unit that "count distinct `biosample_id` per bin" requires.

**Boolean and count granularity**

A single summary row per beacon, carrying `exists` and `num_total_results`, with
entity columns empty. Never an empty table — an empty table would be
indistinguishable from no matches.

**Entity queries** (biosamples, individuals, cohorts, datasets, runs, analyses)

Columns follow the corresponding default model schema. For a plain entity query
that retrieves no variants, `variant_class` is `n/a`.

---

## `outcomes.tsv`

**One row per (beacon, variant class) pair.** Two classes across three beacons
gives exactly six rows. Every pair the planner produced, queried or not, appears
here once.

This is a scientific requirement, not a log. Without it, "no rows from beacon X"
is ambiguous between no matches, never queried, and not known to hold that kind
of variant.

| # | Column | Type | Values | Notes |
|---|---|---|---|---|
| 1 | `beacon_id` | string | registry id | |
| 2 | `beacon_name` | string | free text | |
| 3 | `variant_class` | enum | `CNV` `SMALL_VARIANT` `SV` `REPEAT` `n/a` | `n/a` for entity queries that retrieve no variants. |
| 4 | `class_status` | enum | `yes` `unknown` `no` | What the registry declares for this beacon and class. |
| 5 | `status` | enum | `ok` `skipped` `auth_missing` `blocked` `unavailable` `error` | |
| 6 | `row_count` | integer | | Rows contributed to `results.tsv` by this pair. |
| 7 | `granularity_requested` | enum | `record` `count` `boolean` | |
| 8 | `granularity_returned` | enum | `record` `count` `boolean`, or empty | Empty when nothing was returned. |
| 9 | `count_precision` | enum | `exact` `imprecise` `rounded`, or empty | Surfaced here so a reader who never opens `results.tsv` still sees it. |
| 10 | `count_precision_basis` | enum | as in `results.tsv`, or empty | |
| 11 | `query_degraded` | boolean | `true` `false` | |
| 12 | `coalesced` | enum | `no` `yes` `fallback` | `yes`: answered from one combined request, verified complete. `fallback`: a combined request was tried and rejected, so classes were queried separately. |
| 13 | `notes` | string | free text | Rendered from fixed templates, never improvised. |

### Status semantics

| `status` | `class_status` | Meaning |
|---|---|---|
| `ok` | `yes` | Queried normally. `row_count` 0 means no matches. |
| `ok` | `unknown` | Queried anyway. **`row_count` 0 is not evidence of absence**, and the note says so explicitly. |
| `ok` | `unknown`, rows > 0 | Positive evidence the class is served. The note flags that the registry can be upgraded, and the run log carries a pasteable YAML fragment. |
| `skipped` | `no` | The only class-based skip, quoting the operator declaration. |
| `skipped` | any | Also used for: no registry entry, unsupported query form, unknown dialect, degradation refused, a class not expressible in the spec version the beacon speaks, a class incoherent with the query form, a refused later page from a random-subset provider, and a complete-or-refuse retrieval over the ceiling. |
| `auth_missing` | any | A credential is declared but not set. The note names the preference key, never the value. |
| `blocked` | any | The provider's bot-detection layer refused the request. Not retried. A Galaxy administrator may need the instance allow-listed. |
| `unavailable` | any | The provider did not answer, or answered 5xx. Retried with backoff; usually temporary. |
| `error` | any | Unreachable, timeout, malformed response, or an unrecorded pair. |

### Worked example

Two classes, three beacons, a copy-number bracket query:

```
beacon_id              variant_class   class_status  status   row_count  notes
org.progenetix.beacon  CNV             yes           ok       412
org.progenetix.beacon  SMALL_VARIANT   unknown       ok       0          No records returned. This beacon is not known to hold SMALL_VARIANT data (registry status: unknown), so this is not evidence that it holds none.
org.cancercelllines    CNV             yes           ok       37         bracket flattened to range query
org.cancercelllines    SMALL_VARIANT   unknown       ok       6          Records returned for SMALL_VARIANT, which the registry lists as unknown for this beacon. The class can be upgraded to yes.
org.ega-archive.demo   CNV             unknown       ok       0          No records returned. This beacon is not known to hold CNV data (registry status: unknown), so this is not evidence that it holds none.
org.ega-archive.demo   SMALL_VARIANT   yes           ok       88
```

Six rows, six stated reasons. The two zeroes are not silence: one says the class
is unverified here, the other says the same for a different beacon. Row four is
the evidence loop closing — an unverified class returned records, so the
registry can be corrected by someone who now has grounds to correct it.

---

## Invariants enforced in code

1. `formats/outcomes.py` is the **only** module that mints a status. Any planned
   pair with no recorded outcome is written as `error` rather than omitted.
2. `query/planner.py` is the **only** module that decides a degradation or a
   skip, so per-row notes in `results.tsv` cannot disagree with `outcomes.tsv`.
3. `registry/evidence.py` **cannot express** `class_status: no`. There is no
   function that produces it; a `no` requires a human editing the registry with
   an attributable operator declaration.
4. `frequency` output leaves the `frequency` column **empty** — not zero — when
   the denominator is unknown or `count_precision` is not `exact`.
5. No function in `analysis/` or `plotting/` accepts rows spanning more than one
   `(beacon_id, variant_class)` pair and returns a single series.
6. `transport/http.py` refuses to open a socket for a provider marked
   `test_fixture: true`, redundantly with `schema.validate()`. A validation
   bypass must not be one mistake away from traffic at a partner endpoint.
7. `tests/test_registry_lint.py` fails the build if any string-typed enum in the
   registry has been coerced to a bool by YAML 1.1. It is a test rather than a
   comment because the failure it guards produces no exception and no visibly
   wrong output.
