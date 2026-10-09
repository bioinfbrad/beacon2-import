"""Sole owner of credential material.

Design rule (§9): credentials never appear in stdout, stderr, dataset peek or
exception text. Errors name the *preference key to set*, never the value.

Confining secrets to one module makes that rule enforceable at review time --
a reviewer greps for imports of this module rather than auditing every log
statement in the package.

Transport note: the Galaxy wrapper writes credentials to a job-local configfile
and passes a PATH, never a value. Passing a token as a command-line argument
would place it in the job's recorded command line, which is visible in job
details and in some error reports.
"""

from __future__ import annotations

from pathlib import Path


class CredentialMissing(Exception):
    """Raised when an enabled provider needs a credential that is not set.

    The message names the preference key and nothing else. Callers convert this
    into an ``auth_missing`` row in outcomes.tsv.
    """

    def __init__(self, provider_id: str, credential_key: str) -> None:
        self.provider_id = provider_id
        self.credential_key = credential_key
        super().__init__(
            f"{provider_id} requires a credential. Set '{credential_key}' under "
            f"User > Preferences > Manage information."
        )


class Secret:
    """An opaque credential handle.

    ``__str__`` and ``__repr__`` return a redaction marker, so a stray f-string
    or traceback cannot leak the value. Only :meth:`reveal` returns the real
    token, and only transport/http.py calls it, immediately before setting a
    header.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "<Secret: redacted>"

    def __str__(self) -> str:
        return "<redacted>"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(("Secret", self._value))

    def reveal(self) -> str:
        """Return the raw token. Call sites must be auditable and few."""
        return self._value


def load_credentials(path: Path | str | None) -> dict[str, Secret]:
    """Read the job-local credentials file written by the Galaxy wrapper.

    Format is one ``key=value`` per line, chosen over JSON because it needs no
    escaping: Cheetah cannot safely JSON-escape an arbitrary token, and a
    password containing a quote would otherwise produce an unparseable file.
    Blank lines and ``#`` comments are ignored; the first ``=`` splits.
    """
    if path is None:
        return {}
    handle = Path(path)
    if not handle.is_file():
        return {}
    credentials: dict[str, Secret] = {}
    for line in handle.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            credentials[key] = Secret(value)
    return credentials


def credential_for(provider, credentials: dict[str, Secret]) -> Secret | None:
    """Return the credential for a provider, or None if it needs none.

    Raises :class:`CredentialMissing` when the provider declares a
    ``credential_key`` but the vault has no non-empty value for it. Public
    providers must work with a completely empty vault.
    """
    key = getattr(provider, "credential_key", None)
    if not key:
        return None
    secret = credentials.get(key)
    if secret is None or not secret:
        raise CredentialMissing(provider.id, key)
    return secret


def redact(text: str, credentials: dict[str, Secret]) -> str:
    """Scrub any known credential value out of arbitrary text.

    Last line of defence, applied to upstream error bodies before they are
    written to outcomes.tsv notes. Longest values first, so a token that
    contains another token's value cannot leave a fragment behind.
    """
    if not text:
        return text
    values = sorted(
        (secret.reveal() for secret in credentials.values() if secret),
        key=len,
        reverse=True,
    )
    for value in values:
        if value:
            text = text.replace(value, "<redacted>")
    return text
