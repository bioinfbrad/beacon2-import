"""Direct MongoDB transport for a self-hosted beacon.

Retained deliberately: the read path for admins who run their own beacon, and
the counterpart of the import tool's write path. A transport CHOICE, never the
default.

WHAT WAS PORTED, AND WHAT WAS NOT
    The CONNECTION logic is ported from beacon2-import 2.2.4
    (2.2.4's connect_to_mongodb): unauthenticated `MongoClient(host,
    port)`, or an authenticated client against an auth source. One change:
    credentials go to MongoClient as keyword arguments instead of being
    interpolated into a mongodb:// URI. Interpolated, a password containing
    @ : / or % breaks the connection, and the password becomes part of a string
    that driver errors can echo -- against the rule that credentials never
    appear in stderr.

    The 2.2.4 FILTER BUILDERS were NOT ported, because they do not work.
    Evaluated against the release's own code, its range query sends no
    positional constraint at all: the dict literal sets the start key twice, so
    the variant-length line overwrites the position bound with None, which the
    truthiness filter then strips. A range query for chr17:7572837-7578641
    returned every matching variant on chromosome 17. Even when bounds survived,
    `start >= s AND end <= e` is containment, not the overlap the Beacon range
    query defines; the sequence query used `$gte` for a precise position; and
    the -vmax / -vmin short flags were wired to the opposite bounds.

    :func:`filter_for` builds the filter from the provider-agnostic Query with
    the specification's semantics instead.

Document shape assumed: the Beacon reference implementation's
genomicVariations collection, as 2.2.4 assumed -- VRS-nested
``variation.location.interval.{start,end}.value``, ``variation.location
.sequence_id`` as ``refseq:NC_...``, 0-based half-open coordinates.
"""

from __future__ import annotations

from typing import Any

from ..auth.resolver import Secret
from ..query.model import Query

#: Collections, keyed by entity, as the reference implementation names them.
COLLECTIONS = {
    "genomicVariant": "genomicVariations",
    "biosample": "biosamples",
    "individual": "individuals",
    "analysis": "analyses",
    "run": "runs",
    "cohort": "cohorts",
    "dataset": "datasets",
}

_START = "variation.location.interval.start.value"
_END = "variation.location.interval.end.value"


class MongoFiltersUnsupported(ValueError):
    """Ontology filters cannot be translated for a direct MongoDB query.

    A beacon server maps a filtering term onto document fields; a raw
    collection has no such mapping. Refused rather than dropped: a filter
    silently ignored returns the unfiltered set in a response that looks
    correct, which is exactly the root-placement failure seen live on bycon.
    """


def field_value(value: str) -> Any:
    """Exact-match value for a ``--field``, tolerant of the stored type.

    Command-line values are strings, but documents store numbers and booleans
    natively, and the string "50" never equals the integer 50 -- so a 2.2.4
    `--cohortSize 50` ported naively would match nothing. An integer or boolean
    literal therefore matches either the native value or the same string.
    """
    text = str(value)
    if text.lower() in ("true", "false"):
        return {"$in": [text.lower() == "true", text]}
    try:
        return {"$in": [int(text), text]}
    except ValueError:
        pass
    try:
        return {"$in": [float(text), text]}
    except ValueError:
        return text


def parse_fields(specs: list[str]) -> dict[str, Any]:
    """``--field PATH=VALUE`` (repeatable) into MongoDB equality clauses.

    PATH is a dotted document path, e.g. ``tumorGrade.label``. Exact match only.
    A different mechanism from ``--filter``: a filter is an ontology term a
    beacon server maps onto fields; a field is the field itself.
    """
    clauses: dict[str, Any] = {}
    for spec in specs:
        path, sep, value = str(spec).partition("=")
        if not sep or not path.strip():
            raise ValueError(f"--field must be PATH=VALUE, got {spec!r}")
        clauses[path.strip()] = field_value(value)
    return clauses


def cnv_filter_for(chromosome: str | None, start: int | None, end: int | None,
                   variant_type: str | None, fields: dict[str, Any]) -> dict[str, Any]:
    """Filter for the 2.2.4 `cnv` collection, whose document shape differs.

    Positions live under ``definitions.Location`` and the type at top level.
    The start/end semantics are 2.2.4's, kept deliberately: a CNV lies WITHIN
    [start, end] -- ``start >= s AND end <= e``. That is containment, not the
    Beacon range query's overlap, but unlike the 2.2.4 range query it was
    implemented correctly, and the GTN CNV tutorial is built on its results.
    """
    clauses: dict[str, Any] = dict(fields)
    if chromosome is not None:
        clauses["definitions.Location.chromosome"] = chromosome
    if start is not None:
        clauses["definitions.Location.start"] = {"$gte": int(start)}
    if end is not None:
        clauses["definitions.Location.end"] = {"$lte": int(end)}
    if variant_type:
        clauses["variantType"] = variant_type
    return clauses


def filter_for(query: Query, reference: str | None,
               fields: dict[str, Any] | None = None,
               biosample_ids: list[str] | None = None) -> dict[str, Any]:
    """Translate a Query into a MongoDB filter with the specification's semantics.

    ``reference`` is the already-normalised sequence id (``refseq:NC_...``).
    Coordinates are taken as the 0-based half-open values the Query carries.

    * sequence -- variant starts at exactly ``start``, with matching bases
    * range    -- OVERLAP: variant start < query end AND variant end > query start
    * bracket  -- start in [start_min, start_max] AND end in [end_min, end_max]
    * geneId   -- a gene identifier match

    Unset parameters are omitted by ``is None`` tests, never by truthiness, so a
    legitimate 0 is kept -- the truthiness strip in 2.2.4 would drop it.
    """
    if query.filters:
        raise MongoFiltersUnsupported(
            "ontology, alphanumeric and custom filters are not supported on the "
            "direct MongoDB transport: a raw collection has no filtering-term "
            "mapping, and a dropped filter would return unfiltered results"
        )
    clauses: dict[str, Any] = {}
    form = getattr(query.form, "value", query.form)

    if reference is not None:
        clauses["variation.location.sequence_id"] = reference

    if form == "sequence":
        clauses[_START] = query.start.values[0]
    elif form == "range":
        clauses[_START] = {"$lt": query.end.values[0]}
        clauses[_END] = {"$gt": query.start.values[0]}
    elif form == "bracket":
        smin, smax = query.start.values
        emin, emax = query.end.values
        clauses[_START] = {"$gte": smin, "$lte": smax}
        clauses[_END] = {"$gte": emin, "$lte": emax}
    elif form == "geneId":
        clauses["molecularAttributes.geneIds"] = query.gene_id

    for field, value in (
        ("variation.referenceBases", query.reference_bases),
        ("variation.alternateBases", query.alternate_bases),
        ("variation.variantType", query.variant_type),
        ("molecularAttributes.aminoacidChanges", query.aminoacid_change),
    ):
        if value is not None and value != "":
            clauses[field] = value

    length_bounds = []
    if query.variant_min_length is not None:
        length_bounds.append({"$gte": [{"$subtract": [f"${_END}", f"${_START}"]},
                                       int(query.variant_min_length)]})
    if query.variant_max_length is not None:
        length_bounds.append({"$lte": [{"$subtract": [f"${_END}", f"${_START}"]},
                                       int(query.variant_max_length)]})
    if length_bounds:
        clauses["$expr"] = (length_bounds[0] if len(length_bounds) == 1
                            else {"$and": length_bounds})
    if biosample_ids:
        clauses["caseLevelData.biosampleId"] = {"$in": list(biosample_ids)}
    clauses.update(fields or {})
    return clauses


class MongoTransport:
    """Connection to a self-hosted beacon database."""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        collection: str,
        auth_source: str | None = None,
        username: str | None = None,
        password: Any = None,
        client: Any = None,
    ) -> None:
        """Connect as 2.2.4 did, with credentials passed as keyword arguments.

        ``client`` lets a caller supply an existing client. ``password`` may be
        a :class:`Secret`; it is revealed only here, at the call into the driver.
        """
        self.database = database
        self.collection = collection
        if client is not None:
            self._client = client
            return
        from pymongo import MongoClient

        if username:
            secret = password.reveal() if isinstance(password, Secret) else password
            self._client = MongoClient(
                host, int(port), username=username, password=secret,
                authSource=auth_source or "admin",
            )
        else:
            self._client = MongoClient(host, int(port))

    @classmethod
    def from_credentials(cls, host: str, port: int, database: str, collection: str,
                         credentials: dict[str, Secret], client: Any = None):
        """Build from the job-local credentials file's ``db_*`` keys."""
        def plain(key: str) -> str | None:
            value = credentials.get(key)
            return value.reveal() if value else None

        return cls(host, port, database, collection,
                   auth_source=plain("db_auth_source"), username=plain("db_user"),
                   password=credentials.get("db_password"), client=client)

    def find(self, query: dict[str, Any], limit: int = 0) -> list[dict[str, Any]]:
        """Run a filter against the configured collection.

        ``limit`` 0 means all, matching both the Beacon convention and
        pymongo's. The ``_id`` ObjectId is dropped: it is not JSON-serialisable
        and is not a Beacon field.
        """
        cursor = self._client[self.database][self.collection].find(
            query, projection={"_id": False})
        if int(limit) > 0:
            cursor = cursor.limit(int(limit))
        return list(cursor)
