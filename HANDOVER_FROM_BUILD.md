# Handover: beacon2-import 3.0.0 build

Read with the repository. Branch `release/3.0.0` on github.com/bioinfbrad/beacon2-import.

## 1. Code state

| Item | State |
|---|---|
| Branch / commit | `release/3.0.0` at `4970d0a` ("Re-record fixtures") **plus 24 uncommitted files** delivered as `beacon2-import-3.0.0.zip` (filter efficacy, allele columns, --check decoding, partial re-record, spec counts) |
| pytest | 667 passed, 4 skipped. Skips: `range#5`, `gene#1`, `datasets#1` await recording; the gene-equals-twin check waits on two of them |
| Stub audit | 21 modules, 42 stub sites (PR 2: analysis/, plotting/) |
| planemo lint | Clean on the last run (14 tools); **not re-run since this step's XML regeneration** |
| Release files | **Not built.** sdist, wheel and recipe sha256 are built once, after `planemo test` passes |

## 2. Architecture map

| Directory | Role |
|---|---|
| `cli/` | `beacon2-query` (`main.py`, `query_*.py`), `beacon2-import` (`import_command.py`); `common.py` runs every provider x class pair |
| `adapters/` | Per stack (`spec`, `bycon`, `b2pi`). `base.wire_query` = what is SENT, which may differ from what was ASKED; `send` picks GET or POST |
| `transport/` | `http.py`: `BeaconClient`, `FixtureClient` (request-keyed, `.json.gz` ok), failure classifier; `mongo.py` |
| `normalise/` | `envelope`, `classify` (+ `label_conflict`), `variants` (flatten), `verify` (class, region, alleles) |
| `query/` | `planner` (skips, degradations), `retrieve` (complete-or-refuse), `model`, `classes`, `filters`, `terms` |
| `registry/` | `beacon_registry.yaml` (observed facts), `schema`, `loader`, `evidence` |
| `formats/` | `outcomes.tsv`, `results.tsv` |
| `importer/` | The write path into MongoDB, ported from 2.2.4. Test against local MongoDB only; never a provider API |

| Principle | Enforced in |
|---|---|
| Partiality, observed per response | `retrieve.py` (`is_complete_retrieval`), `cli/common.combined_precision` (across all envelopes) |
| Class, observed from structure | `normalise/verify.verify_records` via `classify` |
| Region and alleles, observed from coordinates | `verify.region_for`, `_in_region`, `record_alleles`, `_indel_matches` |
| Filter efficacy | Registry `filters_effective` (refused in `planner.plan_pair`, and in `common.filter_efficacy` for entity queries); runtime filtered-vs-unfiltered count in `common.filter_efficacy` |
| Complete-or-refuse | `query/retrieve.retrieve`: unknown pagination means complete or refuse; a shortfall against the provider's own total is refused |
| Dedup | `cli/common` `deduplicate` (variant instances), notes "N duplicate observations removed" |

## 3. Provider dialect facts (both bycon providers unless noted)

| Fact | Status | Evidence |
|---|---|---|
| Filters received but NOT applied | **observed 2026-10-26** | Glioblastoma 2,934 vs breast 2,772 vs none 3,401; cnv #1 60 on 9 Oct, 2,938 now |
| `geneId` resolved only over GET | observed | TP53 69,662 (Progenetix) / 2,487 (cancercelllines) by GET; 0 by every POST form; 422 for unknown symbols |
| Sequence queries miss stored alleles | observed | R273H stored at 7673801 C>T; every sequence form returns 0 |
| Small-variant SO filter | observed | Progenetix `SO:0001059` (expands to children); cancercelllines unsupported (0) |
| Progenetix small variants lack alternates | observed | All 277 TP53 `SO:0001483` records are 1-base deletions with empty alternates |
| Filters belong in the body's `query`, not the root | observed | Root placement silently ignored (60 vs 2,591) |
| Pagination is a random subset below the total | observed | `pagination_behaviour: random_subset_below_total` |
| Copy-change expansion is server-side (Progenetix) | observed | 4,182 = 440 + 2,831 + 911 + 0 |
| Lowercase `assemblyid` in POST | documented | bycon POST example |
| Collections responses for cohorts and datasets | observed | `response.collections`, not `resultSets` |
| GET filters work where POST doesn't | **refuted** | GET 2,923 vs POST 2,934 |
| `includeDescendantTerms` widened | **refuted** | false 2,915 vs true 2,933 |

## 4. Open items, ranked

1. **Record** `range#5`, `gene#1` and `datasets#1`, then `--check` and `planemo test`. Files: `tests/galaxy_tests_awaiting.txt` (remove the three lines), and `scripts/galaxy_tests.py` (add their counts).
2. **Re-probe filters** (`probe_filters.py`) periodically. When glioblastoma no longer equals breast, set `filters_effective: "yes"` with evidence in `registry/beacon_registry.yaml`; the filtered tests' queries are intact.
3. **Build once:** sdist, wheel, recipe sha256 (`recipe/meta.yaml`). Upload exactly that sdist.
4. **Runtime check limit:** a filtered total merely smaller passes (`common.filter_efficacy`); the registry observation is the guard. Consider a control-term probe for 3.1.
5. **3.1:** a packaged gene-span table, so gene queries resolve client-side and are region-verified (`query/`, `normalise/verify.py`).
6. **PR 2:** `analysis/`, `plotting/` (42 stub sites).

## 5. Known traps, and the test guarding each

| Trap (it broke silently before) | Guard |
|---|---|
| A 7% random sample reported as exact | `test_partial_retrieval.py` |
| Precision taken from the last envelope only | `test_partial_retrieval.py` |
| Fixtures keyed by endpoint answered the wrong query | `test_fixture_keys.py` |
| chr3 records answered a chr17 query | `test_verification.py` |
| Cohorts and datasets parsed as zero (collections) | `test_galaxy_replay.py::test_a_recorded_collections_response_is_parsed` |
| Gene queries by POST returned 0 | `test_gene_and_sequence.py` |
| Sequence queries returned 0; neighbouring alleles accepted | `test_gene_and_sequence.py` |
| A 422 reported as an authentication failure | `test_gene_and_sequence.py::test_a_422_is_a_rejection_never_an_auth_failure` |
| Filters ignored: every cancer returned as glioblastoma | `test_filter_efficacy.py` |
| Blank allele columns on VRS rows | `test_gene_and_sequence.py::test_a_vrs_form_row_carries_its_alleles` |
| `--check` and Galaxy decoding assertions differently | `test_galaxy_replay.py::test_check_reads_assertions_as_galaxy_does` |
| `--only` deleted other tests' fixtures | `test_galaxy_replay.py::test_recording_one_test_keeps_the_others_fixtures` |
| Galaxy's command sending different requests from the recorder | `test_galaxy_command_keys.py` |
| Recording in one tree, testing in another | Process: record, check, test and commit in one tree |

## 6. Commands (repository root, in the Codespace, which reaches both providers)

```
pip install -e .
python3 scripts/record_fixtures.py --record                       # all tests; rewrites each provider
python3 scripts/record_fixtures.py --record --only beacon2_gene#1  # one test; merges, keeps the rest
python3 scripts/record_fixtures.py --check                         # replay with Galaxy's semantics
python3 -m pytest -q
planemo test tools/beacon2-import
python3 -m build --sdist --wheel --outdir dist . && sha256sum dist/beacon2_import-3.0.0.tar.gz
```
Paste the sha256 into `recipe/meta.yaml`, rerun `pytest`, and never rebuild after hashing.
