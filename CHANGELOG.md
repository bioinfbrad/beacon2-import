# Changelog

## 3.0.0

Breaking release. Version 2.x connected only to a MongoDB instance; 3.0.0 is a
client for the GA4GH Beacon v2 HTTP API, with MongoDB kept as a transport.

### Licence

- Relicensed from CC-BY-NC-4.0 to MIT. Releases up to and including 2.2.4 remain under CC-BY-NC-4.0.

### Security

- The import tool no longer falls back to hardcoded credentials. In 2.2.4, if
  any credential preference was empty, the tool authenticated as user `root`
  with password `example` against auth source `admin`. It now uses only what the
  user set; with no user set, `beacon2-import` connects without authentication
  and says so.
- The import tool's credential file is written with `json.dumps`. In 2.2.4 a
  password containing a double quote produced an unparseable file.
- Credentials are passed to the MongoDB driver as keyword arguments. In 2.2.4
  they were interpolated unescaped into a `mongodb://` URI, which failed on
  passwords containing `@`, `:`, `/` or `%` and placed the password in a string
  that driver errors can echo.

### Added

- `beacon2-query`, with subcommands `range`, `bracket`, `sequence`, `gene`,
  `entity`, `service-info` and `filtering-terms`.
- Both commands answer `--version`, and every Galaxy wrapper declares it as its
  `version_command`, so a job record names the version that actually ran. A
  stale install on `PATH` is the one failure a test suite cannot see in its own
  results: it reports failures that the working tree does not have.
- A recorded failure replays as a failure. `FixtureClient` classifies a
  recorded non-2xx response through the same status-and-content-type rules as
  the live client, and `scripts/record_fixtures.py` stores a failed request
  instead of leaving a gap. A provider outage is therefore testable, and is not
  replayed as a successful empty answer.
- Queries any number of Beacon v2 providers per run. Every result row carries
  its provider and variant class; `outcomes.tsv` reports one row per provider
  and variant class.
- A packaged provider registry recording each provider's request dialect and
  which variant classes it is known to serve, with the provenance of each claim.
- Complete-or-refuse retrieval for providers that return a random subset below
  the total, with an opt-in `--sample N`.
- `--field PATH=VALUE`, an exact match on a document field, for the MongoDB
  transport. It carries the per-field options of the 2.2.4 entity and `cnv`
  subcommands. It is distinct from `--filter`, which takes ontology terms and is
  refused on MongoDB; `--field` is refused on the API, which has no
  field-equality parameter.
- `beacon2-query cnv`, covering every 2.2.4 `cnv` option. On MongoDB its
  start/end keep 2.2.4's containment semantics; on the API it is a CNV range
  query, whose semantics are overlap.
- `--biosample-ids`, for the MongoDB transport, covering 2.2.4's
  `--collectionIds`.
- `--filter` accepts a bare ontology id, e.g. `--filter NCIT:C3058`.
- Partial results are detected in every response and labelled
  `partial_retrieval`, with how many of how many instances arrived; they are
  never reported as exact.
- VRS 2.0 Alleles are classified: a `ReferenceLengthExpression` or
  `LiteralSequenceExpression` state is a sequence claim (SNV / small indel).

### Changed

- Coordinates in results are 1-based inclusive; the wire format stays 0-based.
- The MongoDB transport passes credentials to the driver as keyword arguments
  instead of interpolating them into a `mongodb://` URI.
- `bioblend` is an optional extra, `galaxy`, used only to import from Galaxy
  histories.
- Requires Python 3.10 or later. The 2.2.4 upper bound of Python < 3.12 is gone.

### Removed

- **The `beacon2-search` command and the `beacon2_search` module.** Replaced by
  `beacon2-query`, which covers every 2.x subcommand and option; see
  "Migrating 2.x beacon2-search scripts" in the README, which maps each one.
  Nothing translates automatically, so two things need care. **Start
  positions: add 1. End positions: unchanged.** 2.2.4 passed coordinates to
  MongoDB as stored, and `beacon2-query` takes 1-based starts. And **`-vmin`
  and `-vmax`**: 2.2.4 attached `-vmax` to the minimum and `-vmin` to the
  maximum; `--variant-min-length` and `--variant-max-length` mean what they say,
  so a script that swapped the 2.x flags to compensate must swap them back.
  Scripts not worth migrating can pin `beacon2-import==2.2.4`, which stays on
  PyPI and Bioconda.
- The top-level `utils` module that 2.2.4 installed into site-packages. It was a
  namespace collision rather than a feature, there so that `from utils import *`
  worked; its contents are in `beacon2_import.importer.utils`.
- The `search` module, a duplicate of `beacon2_search` with no entry point,
  which took the database password on the command line. Covered by
  `beacon2-query`.
- Dependencies `dataclasses`, `cyvcf2` and `jsonschema`. None was imported by
  2.2.4 or by 3.0.0; `dataclasses` is part of the standard library.

### Fixed

- MongoDB range queries applied no positional constraint: the 2.2.4 filter set
  the start key twice, so the variant-length line replaced the position bound
  and every matching variant on the chromosome was returned. Range queries now
  match variants overlapping the region.
- MongoDB sequence queries matched any variant at or after the position instead
  of at it.
- The `-vmax` and `-vmin` options were attached to the opposite bounds.
- An invalid credential file raised `NameError` instead of exiting, because
  `sys` was not imported.
- The importer's `--database` option was declared as `"--database "`, with a
  trailing space, and worked only through argparse abbreviation.
- `--collectionIds` passed a single string to MongoDB's `$in`, which requires a
  list; it now takes a comma-separated list.
- `biosamples --diagnosticMarkers` was accepted and silently ignored: it was
  never added to the query. It now matches `diagnosticMarkers.label`.
- The Galaxy CNV tool's form did not offer `--variantStateId` or
  `--variantState`, though the 2.2.4 command accepted both. The 3.0 form offers
  all thirteen CNV fields.
