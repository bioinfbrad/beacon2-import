# Outstanding

The progress metric is the stub audit (`tests/test_stub_audit.py`), not the skip
count. **21 modules, 42 stub sites remain, all PR 2**: `analysis/`, `plotting/`,
their CLI modules, and the segments, frequency and matrix formats. The audit
enforces `tests/outstanding_stubs.txt` in both directions.

---

## Needs a ruling

### N2. The licence classifier

`License :: OSI Approved :: MIT License` is not in `pyproject.toml`.
setuptools 77 and later refuse to build with both a classifier and an SPDX
`license` expression:

    InvalidConfigError: License classifiers have been superseded by license
    expressions (see https://peps.python.org/pep-0639/). Please remove:
    License :: OSI Approved :: MIT License

The SPDX expression and `license-files` were kept. The alternative is the
pre-PEP 639 form, `license = {text = "MIT"}` plus the classifier, which
setuptools still accepts, though it warns that support will be removed.

---

## Lesson: how a 7% random sample passed as exact

Live against Progenetix, 297 rows from a random 100 of each of 4182, 2831 and
911 instances were reported `exact, inferred_from_complete_retrieval`. Two
faults combined: an unset `pagination_behaviour` DEFAULTED to "pages" (in the
schema and, separately, in the loader), so complete-or-refuse never ran; and
the outcome's precision was taken from the last query's envelope only, which
was 0 of 0 and so trivially complete.

The suite passed because the path was only ever exercised with providers
declared random-subset, or with totals under the page limit. Worse, three
tests used Progenetix as the example of a provider whose pages could be
trusted, so they REQUIRED the fault: one asserted "no pre-flight; the requested
page is sent". And every coalescence fixture delivered no records against
totals of up to 2591, which nothing compared.

The rules now enforced: partiality is OBSERVED in each response, never
declared; unknown pagination means complete-or-refuse; an outcome combines
every query's envelope. A test fixture must deliver what it reports, or say
why it does not.

---

## Required rules: `analysis/`, PR 2

- **R2. Frequency eligibility must verify full retrieval.** Refuse unless
  `normalise.envelope.is_complete_retrieval()` holds. Note: in the default
  model only **cohorts** carry a size (`cohortSize`); datasets have no size
  field, so the registry's `cohort_size_source: [cohorts, datasets]` overstates
  what a dataset can supply.
- **R3. Never use `info.counts.individuals`.** Derive from `caseLevelData`.

---

## Unverified

- **`planemo test`.** `planemo lint` passes on all 14 tools with zero warnings
  or errors, skipping only `BioToolsValid`, which cannot run here: bio.tools is
  unreachable from this environment (HTTP 403, `host_not_allowed`). The
  `ga4gh_beacon` xref is inherited from the published 2.2.x wrappers. The tool
  tests themselves have not been run under Galaxy.
- **The provider-table configfile in Galaxy.** It relies on
  `$connection.providers.fields.base_url` of a multiple select returning the
  comma-joined column. Without it, no tool passes base URLs to the CLI, and tool
  tests would reach the network. Needs a planemo run.
- **Tool fixture directories** for `org.progenetix.beacon`,
  `org.ega-archive.demo` and `test.fixture.bracketless` are empty. Every tool
  test uses `org.cancercelllines`, which now serves recorded responses for
  variants, all six entity types and the informational endpoints. The entity and
  informational ones are constructed, not captured.
- **The bioblend check is static.** All seven call sites bind against bioblend
  1.9.0's signatures; none was exercised against a live Galaxy server.
- **The recipe sha256 is for the shipped sdist only.** Two builds of an
  unchanged tree hash differently, with or without `SOURCE_DATE_EPOCH`. Upload
  that exact file, or re-hash from PyPI after uploading.


## Listed, not written

- A MongoDB integration test against `mongomock` or a server. The 3.0 filter was
  checked against `mongomock` outside the suite.
- A test checking `COLUMN_SPECS.md` against `PROVENANCE_COLUMNS`,
  `OUTCOME_COLUMNS` and `Status`. It passes when run by hand.

---

## Fixture sets and their consumers

Enforced by `tests/test_fixture_consumers.py`.

| fixture set | consumer |
|---|---|
| `fixtures/adapters/` | `test_adapters.py`, `test_retrieve.py`, `test_count_precision.py` |
| `fixtures/transport/` | `test_transport.py` |
| `fixtures/filtering_terms/` | `test_filtering_terms.py` |
| `fixtures/classify/` | `test_classify.py`, `test_normalise.py` |
| `fixtures/coalescence/` | `test_coalescence.py` |
| `fixtures/normalise/` | `test_normalise.py` |
