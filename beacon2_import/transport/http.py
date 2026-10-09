"""HTTP client: identity, politeness, retries, and error classification.

Politeness is not optional. These are shared academic services, so the client
rate-limits per provider, backs off on 429/5xx, sets an identifying
User-Agent with a contact URL, and never retries a 4xx other than 429.

Test transport: when a provider's ``base_url`` uses the ``file://`` scheme, the
request is served from a recorded fixture directory instead of the network.
That lets the standard test suite exercise the real URL-construction and
parsing paths with no network access and no monkeypatching -- the tool tests
point at a ``.test`` data table whose base URLs are file:// paths.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..auth.resolver import Secret


class BeaconHttpError(Exception):
    """Base for transport failures that become an ``error`` row, not a crash."""


class AuthRequired(BeaconHttpError):
    """401/403. Becomes ``auth_missing`` when we hold no credential."""


class RateLimited(BeaconHttpError):
    """429, after retries are exhausted."""


class ProviderUnavailable(BeaconHttpError):
    """The provider is up but cannot serve right now, or did not answer at all.

    Covers any 5xx and any connection-level failure including a bare timeout
    with zero bytes received. RETRYABLE -- this is what backoff exists for.

    Kept strictly apart from ProviderBlocked because the two demand opposite
    handling in both directions. Retrying an outage is correct; retrying a bot
    challenge is pointless and makes us look more like the automated traffic
    being challenged. And telling a user their instance may need allow-listing,
    when the beacon is simply in maintenance, sends them to their administrator
    or to an unnecessary email to a partner over something that will be fine in
    an hour.
    """


class ProviderBlocked(BeaconHttpError):
    """The provider's edge refused the request as automated traffic.

    Distinct from AuthRequired and from a generic error because the remedy is
    completely different and belongs to the Galaxy ADMIN, not the user: the
    instance's egress addresses need allow-listing by the provider.

    Detection needs BOTH the status class and the body. Content type alone is
    not sufficient and gets outages wrong: a 503 maintenance page is also HTML
    with no Beacon envelope, so a content-type-only rule reports a temporary
    outage as a permanent access problem. Only 403 and 429 are candidates for a
    challenge; a 5xx is an outage whatever the body looks like.

    Kept for the case where a provider's edge does challenge a Galaxy server.
    Progenetix's Cloudflare challenge was once taken for such a block, but it
    stops Linux curl, not Python clients from the same address: this tool
    reached it from an AWS container. So a curl failure is no evidence about the
    tool -- debug with the tool itself, or with Python. If a challenge does
    appear, lumping it into `error` would leave an admin with nothing to act on.
    """


class Unreachable(BeaconHttpError):
    """DNS failure, connection refused, or timeout."""


class MalformedResponse(BeaconHttpError):
    """Non-JSON body, or JSON that is not a Beacon response envelope."""


class FixtureMiss(BeaconHttpError):
    """No recorded fixture matched a request.

    Always a loud failure. Returning an empty result instead would be
    indistinguishable from "the beacon holds no matches", which is precisely
    the ambiguity this project exists to remove.
    """


class FixtureProviderEscaped(BeaconHttpError):
    """Raised when a request would be issued for a ``test_fixture`` provider.

    Redundant with registry/schema.py's validation that a fixture provider's
    base_url is a ``file://`` URL, and redundant on purpose. The check is
    nearly free, and it means a validation bypass -- a fork that skips
    validate(), a hand-built capability object in a test -- cannot put traffic
    on a partner's endpoint under a synthetic provider id.

    This is a bug, not a provider-level failure: it does not become an
    ``error`` row, it stops the run.
    """


class TransportFailure(str, Enum):
    """The four ways a request can fail below the Beacon application layer."""

    UNAVAILABLE = "unavailable"    # 5xx, timeout, connection refused
    BLOCKED = "blocked"            # edge challenge on a 403/429
    AUTH = "auth"                  # genuine Beacon authorisation refusal
    RATE_LIMITED = "rate_limited"  # 429 from the application


@dataclass
class Response:
    """A raw provider response plus what we needed to know to get it."""

    status: int
    body: dict[str, Any] | None
    url: str
    method: str
    elapsed_seconds: float
    raw_text: str | None = None


class RateLimiter:
    """Token-bucket limiter, one instance per provider.

    These are shared academic services; politeness is not optional.
    """

    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(1, int(per_minute))
        self._interval = 60.0 / self.per_minute
        self._last = 0.0

    def acquire(self) -> None:
        """Block until a request may be issued."""
        now = time.monotonic()
        wait = self._interval - (now - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()


class BeaconClient:
    """Per-provider HTTP session."""

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        rate_limit_per_minute: int = 30,
        credential: Secret | None = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 60.0,
        max_retries: int = 3,
        provider: Any = None,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self.user_agent = user_agent
        self.credential = credential
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max(0, int(max_retries))
        self.provider = provider
        self.limiter = RateLimiter(rate_limit_per_minute)
        self._session = None

    # -- session -----------------------------------------------------------

    def _ensure_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    @staticmethod
    def classify_transport_failure(
        status: int | None,
        content_type: str | None,
        body_text: str | None,
        bytes_received: int | None = None,
    ) -> "TransportFailure":
        """Classify a failed request into one of four outcomes.

        Replaces an earlier boolean helper. A boolean cannot express a four-way
        distinction, and the name invited exactly the collapse that produced the
        bug: treating any HTML-bodied refusal as a challenge, which reports a
        503 maintenance page as an access problem.

        =========================================  ==================  =========
        Condition                                  Outcome             Retryable
        =========================================  ==================  =========
        no status / 0 bytes received               UNAVAILABLE         yes
        5xx, any body                              UNAVAILABLE         yes
        403 or 429 + non-JSON body, no envelope    BLOCKED             no
        403 + JSON carrying error/beaconError      AUTH                no
        429 + JSON envelope                        RATE_LIMITED        yes
        =========================================  ==================  =========

        Status class is checked BEFORE the body, so no body inspection can
        promote a 5xx to BLOCKED. That ordering is the fix, not a detail.
        """
        if status is None or (bytes_received is not None and bytes_received == 0):
            return TransportFailure.UNAVAILABLE
        if 500 <= int(status) <= 599:
            return TransportFailure.UNAVAILABLE

        has_envelope = BeaconClient._is_beacon_envelope(content_type, body_text)
        if int(status) in (401, 403):
            return TransportFailure.AUTH if has_envelope else TransportFailure.BLOCKED
        if int(status) == 429:
            return (
                TransportFailure.RATE_LIMITED if has_envelope
                else TransportFailure.BLOCKED
            )
        return TransportFailure.AUTH if has_envelope else TransportFailure.BLOCKED

    @staticmethod
    def _is_beacon_envelope(content_type: str | None, body_text: str | None) -> bool:
        """Whether a refusal body came from the Beacon application.

        A genuine refusal is JSON carrying an error object. An edge challenge is
        HTML. Deciding on the body is correct ONLY once the status class has
        been checked -- which is why this is a private helper rather than the
        entry point it used to be.
        """
        if not body_text:
            return False
        if content_type and "json" not in content_type.lower():
            return False
        try:
            parsed = json.loads(body_text)
        except (ValueError, TypeError):
            return False
        if not isinstance(parsed, dict):
            return False
        return any(key in parsed for key in ("error", "beaconError", "meta"))

    @staticmethod
    def is_retryable(failure: "TransportFailure") -> bool:
        """Whether backoff should retry this failure.

        UNAVAILABLE and RATE_LIMITED yes; BLOCKED and AUTH no. Retrying a
        challenge is both futile and counterproductive -- it makes us look more
        like the automated traffic being blocked.
        """
        return failure in (TransportFailure.UNAVAILABLE, TransportFailure.RATE_LIMITED)

    def _assert_not_fixture(self) -> None:
        """Raise :class:`FixtureProviderEscaped` for a synthetic provider.

        Called before any socket is opened. Redundant with the registry's own
        validation, and redundant on purpose: a validation bypass must not be
        one mistake away from traffic at a partner endpoint.
        """
        if getattr(self.provider, "test_fixture", False):
            raise FixtureProviderEscaped(
                f"{getattr(self.provider, 'id', '?')} is a test fixture provider; "
                f"no request may be issued for it"
            )

    def get(self, path: str, params: dict[str, str] | None = None) -> Response:
        """Issue a GET. ``params`` values are already encoded by the adapter."""
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any]) -> Response:
        """Issue a POST with a JSON body."""
        return self._request("POST", path, body=body)

    def _auth_headers(self) -> dict[str, str]:
        """Build auth headers. The only place :meth:`Secret.reveal` is called."""
        if self.credential is None:
            return {}
        return {"Authorization": f"Bearer {self.credential.reveal()}"}

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        headers.update(self._auth_headers())
        return headers

    def _request(self, method: str, path: str, params=None, body=None) -> Response:
        """Issue one request with rate limiting, retries and failure mapping."""
        self._assert_not_fixture()
        url = self.base_url + "/" + str(path).lstrip("/")
        session = self._ensure_session()
        attempt = 0
        while True:
            self.limiter.acquire()
            started = time.monotonic()
            status = content_type = text = None
            bytes_received = None
            try:
                response = session.request(
                    method,
                    url,
                    params=params,
                    json=body,
                    headers=self._headers(),
                    timeout=(self.connect_timeout, self.read_timeout),
                )
                status = response.status_code
                content_type = response.headers.get("Content-Type")
                text = response.text
                bytes_received = len(response.content or b"")
                if 200 <= status < 300:
                    try:
                        parsed = response.json()
                    except ValueError as exc:
                        raise MalformedResponse(
                            f"{url} returned {status} with a body that is not JSON"
                        ) from exc
                    return Response(
                        status=status, body=parsed, url=url, method=method,
                        elapsed_seconds=time.monotonic() - started, raw_text=text,
                    )
            except Exception as exc:  # noqa: BLE001 - mapped below
                if isinstance(exc, (MalformedResponse,)):
                    raise
                status, content_type, text, bytes_received = None, None, None, 0

            failure = self.classify_transport_failure(
                status, content_type, text, bytes_received
            )
            attempt += 1
            if self.is_retryable(failure) and attempt <= self.max_retries:
                time.sleep(min(2.0 ** attempt, 30.0))
                continue
            raise self._as_exception(failure, url, status)

    @staticmethod
    def _as_exception(failure: "TransportFailure", url: str,
                      status: int | None) -> BeaconHttpError:
        """Map a classified failure onto the exception the caller expects."""
        detail = f"{url} returned {status}" if status else f"{url} did not respond"
        if failure is TransportFailure.UNAVAILABLE:
            return ProviderUnavailable(detail)
        if failure is TransportFailure.BLOCKED:
            return ProviderBlocked(detail)
        if failure is TransportFailure.RATE_LIMITED:
            return RateLimited(detail)
        return AuthRequired(detail)


class FixtureClient(BeaconClient):
    """Serves recorded responses from a directory for offline tests.

    Requests are matched via a ``manifest.json`` mapping a request signature to
    a response file, so a fixture MISS is a loud failure rather than a silent
    empty result -- an empty result would be indistinguishable from "no
    matches", which is the ambiguity this whole project exists to remove.

    Matching precedence: an exact key including the body digest wins. A
    path-only key (``"POST /g_variants"``) is a DELIBERATE WILDCARD the manifest
    author opts into, and matches any body. Use it for fixtures that test
    response handling; use digest keys where the test is about what was SENT,
    because a wildcard will not notice a changed request body.
    """

    def __init__(self, fixture_dir: str, **kwargs: Any) -> None:
        kwargs.setdefault("user_agent", "GalaxyBeacon2-fixture")
        super().__init__(base_url=f"file://{fixture_dir}", **kwargs)
        self.fixture_dir = Path(str(fixture_dir))

    def _assert_not_fixture(self) -> None:
        """Fixture providers are exactly what this client is for."""
        return None

    @staticmethod
    def signature(method: str, path: str, params=None, body=None) -> str:
        """Build the manifest key for a request."""
        key = f"{method.upper()} /{str(path).lstrip('/')}"
        if params:
            pairs = sorted((k, str(v)) for k, v in params.items())
            key += "?" + "&".join(f"{k}={v}" for k, v in pairs)
        if body is not None:
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()[:8]
            key += f" {digest}"
        return key

    def _manifest(self) -> dict[str, str]:
        path = self.fixture_dir / "manifest.json"
        if not path.is_file():
            raise FixtureMiss(f"no manifest.json in {self.fixture_dir}")
        return json.loads(path.read_text())

    def _request(self, method: str, path: str, params=None, body=None) -> Response:
        manifest = self._manifest()
        signature = self.signature(method, path, params, body)
        filename = manifest.get(signature)
        if filename is None:
            filename = manifest.get(f"{method.upper()} /{str(path).lstrip('/')}")
        if filename is None:
            raise FixtureMiss(
                f"no fixture for {signature!r} in {self.fixture_dir}. "
                f"Known: {sorted(manifest)}"
            )
        payload = json.loads((self.fixture_dir / filename).read_text())
        return Response(
            status=int(payload.get("_status", 200)),
            body=payload,
            url=f"{self.base_url}/{str(path).lstrip('/')}",
            method=method.upper(),
            elapsed_seconds=0.0,
        )
