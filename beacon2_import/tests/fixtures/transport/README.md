# Transport failure fixtures

Three refusals that each arrive looking like something else. Consumed by
`tests/test_transport.py`.

## The refusal set

Four fixtures, because the discrimination is four-way and needs **status class
and body together**. Content type alone is not enough, and getting it wrong
fails in the worst direction.

| fixture | status | body | outcome | retryable |
|---|---|---|---|---|
| `provider_blocked.html` | 403 | HTML | `blocked` | no |
| `beacon_403_genuine.json` | 403 | JSON + error | `auth_missing` | no |
| `provider_unavailable_503.html` | 503 | HTML | `unavailable` | yes |
| `provider_timeout.json` | none | none | `unavailable` | yes |

Rows 1 and 3 are the load-bearing pair. **Both are a non-JSON body with no
Beacon envelope**, so any rule keying on content type alone assigns them the
same outcome — and would tell a user whose beacon is merely in maintenance that
their Galaxy instance may need allow-listing, sending them to their
administrator or to an unnecessary email to a partner. Status class must be
checked before the body: a 5xx is an outage whatever the body looks like.

The retry consequence runs the same way. A content-type-only rule backs off and
retries a bot challenge, which is futile and makes us look more like the
automated traffic being blocked, while retrying the 503 correctly but for the
wrong reason.

`provider_unavailable_503.html` and `provider_timeout.json` are records of a
**real EGA demo outage**, not synthetic constructions: every endpoint returned
that page, and a follow-up diagnostic timed out after 20002 ms with 0 bytes
received. The timeout has no status and no body, so nothing about a payload can
classify it — any rule that reaches for the body first has nothing to reach for.

Expectations for the two HTML artifacts live in `.expected.json` sidecars, so
the artifacts themselves stay faithful.

## The 403 pair

`provider_blocked.html` and `beacon_403_genuine.json` share a status code and
differ in body; `provider_blocked.html` and `provider_unavailable_503.html`
share a body shape and differ in status class. The two pairs cross, which is
what forces an implementation to consult both dimensions rather than either
one.

Remedies, which is why the distinction is worth the machinery:

| outcome | remedy |
|---|---|
| `blocked` | administrator asks the provider to allow-list the instance's outbound addresses |
| `auth_missing` | user sets the credential named in the note |
| `unavailable` | wait and retry; nothing to change locally |

`provider_blocked.html` is deliberately a **faithful artifact**: plausible block
markup with no explanatory comments and no vocabulary from this project. The
first version carried an HTML comment explaining its own purpose, which
mentioned the word `beaconError` — and the consumer test rejected it, correctly.
Any implementation that inspects the body for application markers would have
been misled by a fixture describing itself. Commentary belongs here, not in the
artifact.

## The silent one

`entity_type_mismatch.json` is HTTP 200, a well-formed envelope, no error field,
records present — and the wrong kind of record. At least one stack decides the
response entity type from `meta.requestedSchemas[0].entityType` rather than from
the endpoint path, so a variants query can be answered with biosamples and
nothing in the response says so. Without the `returnedSchemas` check, the
normaliser would flatten biosample records into variant columns.

The fixture must keep looking like a success. If it carried an error marker,
ordinary error handling would catch it and the check under test would never run.
