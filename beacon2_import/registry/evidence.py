"""Registry evidence updates -- structurally incapable of writing ``no``.

There is no function in this module that produces ``ClassStatus.NO``, and there
must never be one. Writing ``no`` requires a human editing beacon_registry.yaml
with an attributable operator declaration in hand.

This is the same discipline that makes formats/outcomes.py the sole minter of
statuses: the rule is enforced by the shape of the code, so a reviewer checks
one small module rather than auditing every call site for a mistake that would
be invisible in a diff.

The upgrade path exists because ordinary use is a better evidence pipeline than
periodic sweeps. Every query against a class declared ``unknown`` is a free
experiment; when it returns records, that is positive evidence, and the tool
should say so rather than discard it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..query.classes import VariantClass
from .schema import ClassStatus, EvidenceSource, VariantClassSupport


@dataclass(frozen=True)
class UpgradeSuggestion:
    """A proposed registry edit, for a human to accept.

    Never applied automatically. The registry is a reviewed contract; a tool
    run may propose a change to it but may not perform one.
    """

    provider_id: str
    variant_class: VariantClass
    from_status: ClassStatus
    to_status: ClassStatus            # only ever YES
    evidence_source: EvidenceSource
    evidence: str
    observed: str

    def as_yaml_fragment(self) -> str:
        """Render the edit as a pasteable YAML block.

        The status is QUOTED: an unquoted yes is a YAML 1.1 boolean, and a
        fragment this tool emits must not reintroduce the trap the registry
        lint exists to catch.
        """
        evidence = self.evidence.replace('"', "'")
        return (
            f"  {self.provider_id}:\n"
            f"    variant_classes_served:\n"
            f"      {self.variant_class.value}:\n"
            f'        status: "{self.to_status.value}"\n'
            f"        evidence_source: {self.evidence_source.value}\n"
            f'        evidence: "{evidence}"\n'
            f'        observed: "{self.observed}"\n'
        )


def upgrade_to_yes(
    provider_id: str,
    variant_class: VariantClass,
    current: VariantClassSupport,
    evidence_source: EvidenceSource,
    evidence: str,
    observed: str,
) -> UpgradeSuggestion | None:
    """The ONLY status transition this module can express.

    Returns a suggestion when a class currently ``unknown`` has been shown to
    be served, and None when the class is already ``yes`` or is a declared
    ``no`` -- a declaration is not overturned by an observation without a human
    looking at the contradiction.
    """
    if current.status is not ClassStatus.UNKNOWN:
        return None
    if evidence_source in (EvidenceSource.OPERATOR_DECLARATION, EvidenceSource.NONE):
        return None
    return UpgradeSuggestion(
        provider_id=provider_id, variant_class=variant_class,
        from_status=current.status, to_status=ClassStatus.YES,
        evidence_source=evidence_source, evidence=evidence, observed=observed,
    )


def suggestion_from_run(provider_id: str, variant_class: VariantClass,
                        current: VariantClassSupport, row_count: int,
                        observed: str) -> UpgradeSuggestion | None:
    """Derive a suggestion from a completed query.

    Returns None when ``row_count`` is zero. A zero from an unverified class is
    reported honestly in outcomes.tsv, but it is not evidence of absence and
    must never move the registry in either direction.
    """
    if int(row_count) <= 0:
        return None
    return upgrade_to_yes(
        provider_id, variant_class, current, EvidenceSource.QUERY_OBSERVATION,
        f"{row_count} records classified as {variant_class.value} from their own "
        f"structure, returned on {observed}",
        observed,
    )
