# Normaliser fixtures

Consumed by `tests/test_normalise.py`.

`double_expansion_responses.json` holds two responses for one (provider, class)
pair. It is what client-side expansion produces against a provider that also
expands server-side: the descendant record comes back once in each response.

The expectations encode a precision about the exposure. Rows go from 6 to 4,
but distinct biosamples stay at 4 either way. Frequency counts distinct
biosamples and is therefore incidentally immune; `results.tsv` and the outcome
`row_count` are not, which is why deduplication lives in the normaliser rather
than in any one consumer.

The deduplication key is wider than `(variantInternalId, biosampleId)`: it is
`(beacon_id, variant_internal_id, biosample_id, analysis_id, run_id)`. Two
analyses of one biosample are distinct observations and must both survive; a
double-expanded duplicate matches in every field.
