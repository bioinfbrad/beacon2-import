# Informational-endpoint fixtures

Consumed by `tests/test_informational.py`. `agrees/filtering_terms.json` is the
real cancercelllines response; every other file here is CONSTRUCTED from the
framework schemas, because no verbatim `/info`, `/configuration`,
`/entry_types` or `/map` body was available. Each says so in its `_note`.

- `agrees/` identifiers match the registry entry for `org.cancercelllines`.
- `drifted/` disagrees on `beaconId` and `apiVersion`, and serves its map only
  at the non-normative `/beaconMap`, so the `/map`-first fallback is exercised.
- `second/` shares one filtering term with `agrees/`, for the merged view.
