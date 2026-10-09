# Recorded HTTP fixtures

The standard test suite never touches a partner service. Each provider
directory holds a `manifest.json` mapping a request signature to a response
file:

```json
{
  "POST /g_variants 8f3c1a2b": "range_query_record.json",
  "GET  /map":                 "map.json"
}
```

The signature is `METHOD path [body-digest]`. A request with no manifest entry
raises, so an unmatched request fails the test loudly instead of returning an
empty result that looks like "no matches".

Regenerate with `testMode=true`, which a beacon must answer with real or fake
content while skipping authentication — that is the mechanism the spec provides
for exactly this purpose, and it avoids replaying real queries at a partner.

Required coverage (§17):
all four query forms; EFO and legacy `variantType`; ontology filter with
`includeDescendantTerms` true and false; alphanumeric filter with an ISO 8601
period; boolean response; count response; empty `resultSets` with a valid
`responseSummary`; `resultSets[].results` layout; flat `response.results`
layout; nested path `/biosamples/{id}/g_variants`; 401; timeout; malformed
JSON; a multi-page response exercising `skip` as a page index; a 403 with an
HTML body (an edge bot-block, which must map to `blocked` rather than `error`);
a genuine Beacon 403 with a JSON error envelope, as the contrast case; and a
response whose `returnedSchemas[0].entityType` differs from the one requested.

The last three exist because each is a failure that arrives looking like a
success or like something else entirely: an HTML block that is not an
authentication problem, a JSON 403 that is, and a well-formed 200 carrying the
wrong kind of record. Unit-level copies live in
`beacon2_import/tests/fixtures/transport/`.
