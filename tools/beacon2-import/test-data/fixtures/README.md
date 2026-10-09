# Galaxy tool-test fixtures

One directory per provider in `../beacon_providers.loc`, each with a
`manifest.json` in the keyed format `beacon2-fixtures/2`:

    {"format": "beacon2-fixtures/2",
     "entries": [{"request": {"method": ..., "path": ..., "query": {...}},
                  "response": "<file>.json",
                  "origin": "recorded" | "constructed",
                  "note": "..."}]}

A fixture is keyed on the REQUEST -- method, path, and the query-relevant
fields: reference name, coordinates, variant type, filters, granularity,
pagination, datasets, testMode -- never on the endpoint alone. A request with no
entry fails loudly (FixtureMiss); there is no fallback response. One canned
response per endpoint once answered a chromosome 17 query with chromosome 3
records, and the tests passed.

RECORD, DON'T CONSTRUCT. `scripts/record_fixtures.py` runs every Galaxy test's
query against the live providers and writes the request -> response pairs here.
Only `test.fixture.bracketless`, synthetic by definition, is constructed.

`beacon2_import/tests/test_galaxy_fixtures.py` checks this tree statically:
every provider in the test .loc has a directory with a valid manifest, every
entry's file exists, no file is unreferenced, and no directory is empty.
