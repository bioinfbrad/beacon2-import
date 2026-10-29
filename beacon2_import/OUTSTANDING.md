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

## Lesson: the recordings found what the constructed fixtures could not

Replaying the first real recordings failed cohorts and datasets. cancercelllines
answers both as a Beacon COLLECTIONS response (`response.collections`), and the
parser read only `resultSets`. The constructed fixtures had put cohorts and
datasets in `resultSets` -- agreeing with the code, not the specification -- so
every test passed on a path that never worked against a real beacon. The Galaxy
replay now runs in pytest, so this class of failure surfaces without planemo.

---

## The principle: trust the response, not the query or the declaration

Three instances, each learned from a real failure, all enforced:

- **Partiality**, judged from the instances returned against `numTotalResults`
  -- never from the registry's pagination claim (normalise/envelope.py).
- **Class**, judged from each record's own structure -- never from the class
  the query asked for. Sixty CNV records once came back to a SMALL_VARIANT
  query, were stamped SMALL_VARIANT ("pinned by query"), and were offered as
  evidence to upgrade the registry to `yes`.
- **Region**, judged from each record's coordinates, with the semantics of the
  form sent -- never assumed from the request. Chromosome 3 records once came
  back as answers to a chromosome 17 query.

Class and region are checked in ONE place, normalise/verify.py, which every
runner calls. A record that fails is excluded from results and counts and
reported, with its reason, in outcomes.tsv. No existing test noticed the
pinning, because every one sent queries whose answers already matched.

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

## Not a Galaxy tool test: a real insert

`import.xml`'s test is deliberately self-contained: it points at a closed port
on the loopback address and asserts the clean failure, exercising the wiring,
the credentials file and the error path without any database. A genuine insert
needs a MongoDB service, which a standard Galaxy tool test cannot provide, and a
test must never depend on an external server (the previous one connected to a
real database by hardcoded address). Inserts stay covered at the Python level.

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
- **Galaxy fixtures are recorded** from the live providers (cancercelllines 29
  requests, Progenetix 15, from AWS), plus the constructed bracketless provider.
  Every Galaxy test asserts the count the provider actually returned, and
  `tests/test_galaxy_replay.py` replays all of them in pytest with their own
  XML assertions. Three recordings over 256 kB are stored gzipped, byte for
  byte: the tree is 1.5 MB rather than 4.7 MB.
- **Verified before recording, so the AWS session is not wasted:** for all 24
  spec tests, Galaxy's rendered `<command>` sends exactly the requests the
  recorder records (`tests/test_galaxy_command_keys.py`, which renders each
  command with Galaxy's own macro loader and skips without galaxy-tool-util);
  and `--record` then `--check` completes against a stand-in network with no
  FixtureMiss on replay. The dry run also found, and fixed, the recorder
  leaving its client factory patched after `--record`.
- **Weak by the data, not the design:** four Galaxy tests assert a recorded
  zero. cancercelllines holds no CNV for the range #1, cnv #1 and gene #1 queries
  (each total 0, delivered 0), and neither provider holds TP53 R273H for the
  sequence tests. Zero is a specific, recorded fact, but a test that matches
  nothing cannot show matching works. Re-recording gene #1 with a gene
  cancercelllines does hold (CDKN2A, say) would make it prove something.
- **Individuals on cancercelllines is refused, correctly.** The server reports
  resultsCount 184 and delivers 180 at limit 0. A retrieval short of the
  provider's own total is never reported as complete; the Galaxy test asserts
  the refusal, with both numbers.
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
