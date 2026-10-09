"""Every Galaxy tool test, defined once.

Each test carries BOTH encodings of one query:
  * `params` -- the Galaxy form values, written into the tool XML's <tests>;
  * `argv`   -- the same query as beacon2-query arguments, which
                scripts/record_fixtures.py runs against the live providers.
Fixtures are keyed on the request, so the two must produce the same request.
tests/test_galaxy_tests_spec.py checks that the XML holds exactly what this
file renders, and that each test's argv agrees with its params.

Assertions are SPECIFIC. Every test checks, on one line of outcomes.tsv, the
beacon, the class and the status together -- not three loose has_text checks
that could each be satisfied by a different row. Where rows are expected,
results.tsv must hold one with the right beacon, class and chromosome.

    python3 scripts/galaxy_tests.py      rewrite the <tests> of every tool XML
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools" / "beacon2-import"

PGX, CCL, BRK = "org.progenetix.beacon", "org.cancercelllines", "test.fixture.bracketless"
GBM = "NCIT:C3058"  # glioblastoma: keeps CNV totals small enough to record


# ---------------- assertion builders ----------------

def outcome(beacon: str, klass: str, status: str) -> str:
    """beacon, class and status on ONE outcomes.tsv line (columns 0, 2 and 4)."""
    expr = rf"^{re.escape(beacon)}\t[^\t]*\t{re.escape(klass)}\t[^\t]*\t{status}\t.*"
    return f'<has_line_matching expression={quoteattr(expr)}/>'


def row(beacon: str, klass: str, chromosome: str | None = None) -> str:
    """A results.tsv row with this beacon (col 0), class (col 3), chromosome (col 13)."""
    expr = rf"^{re.escape(beacon)}\t(?:[^\t]*\t){{2}}{re.escape(klass)}\t"
    if chromosome is not None:
        expr += rf"(?:[^\t]*\t){{9}}{re.escape(chromosome)}\t"
    return f'<has_line_matching expression={quoteattr(expr + ".*")}/>'


def text(value: str) -> str:
    return f"<has_text text={quoteattr(value)}/>"


def lines(n: int) -> str:
    return f'<has_n_lines n="{n}"/>'


# ---------------- form parameter builders ----------------

def connection(providers: list[str], *inner: str) -> str:
    """The connection conditional. `inner` holds parameters that live INSIDE its
    API branch -- as in the generated entity and cnv tools, where a parameter
    placed at top level would simply be ignored."""
    nested = "".join("\n" + "\n".join("    " + l for l in block.splitlines()) for block in inner)
    return ('<conditional name="connection">\n'
            '    <param name="transport" value="api"/>\n'
            f'    <param name="providers" value="{",".join(providers)}"/>'
            f'{nested}\n</conditional>')


def api_only(providers: list[str]) -> str:
    return ('<conditional name="connection">\n'
            f'    <param name="providers" value="{",".join(providers)}"/>\n'
            '</conditional>')


def p(name: str, value) -> str:
    return f'<param name="{name}" value="{value}"/>'


def cnv_term(term: str, expand: str = "auto") -> str:
    return ('<section name="cnv_terms">\n    <conditional name="variant_type">\n'
            f'        <param name="mode" value="efo"/>\n        <param name="term" value="{term}"/>\n'
            f'        <param name="expand_hierarchy" value="{expand}"/>\n'
            '    </conditional>\n</section>')


def vcf_term(term: str) -> str:
    """A DEL/DUP variantType value, which the specification marks LEGACY."""
    return ('<section name="cnv_terms">\n    <conditional name="variant_type">\n'
            f'        <param name="mode" value="legacy"/>\n        <param name="term" value="{term}"/>\n'
            '    </conditional>\n</section>')


def ontology_filter(term: str, descendants: bool = True) -> str:
    return ('<repeat name="filters">\n    <conditional name="filter_type">\n'
            f'        <param name="kind" value="ontology"/>\n        <param name="term" value="{term}"/>\n'
            f'        <param name="include_descendant_terms" value="{str(descendants).lower()}"/>\n'
            '    </conditional>\n</repeat>')


def arg_filter(term: str, descendants: bool = True) -> list[str]:
    return ["--filter", f"ontology:{term}:descendants={str(descendants).lower()}:similarity=exact"]


@dataclass
class GalaxyTest:
    tool: str
    index: int
    purpose: str
    params: list[str]
    argv: list[str]
    outcomes: list[str]
    results: list[str] = field(default_factory=list)
    #: Providers that receive requests. Empty where the planner skips before
    #: any request, which needs no fixture at all.
    requests_to: list[str] = field(default_factory=list)
    #: (beacon, class, chromosome) rows the test expects; checked after
    #: recording, before the XML can be trusted to pass.
    expects_rows: list[tuple] = field(default_factory=list)
    output_names: tuple[str, str] = ("results", "outcomes")
    attributes: str = 'expect_num_outputs="2"'

    @property
    def id(self) -> str:
        return f"{self.tool}#{self.index}"

    def render(self) -> str:
        body = "\n".join(self.params)
        first, second = self.output_names
        for name, checks in ((first, self.results), (second, self.outcomes)):
            if checks:
                body += (f'\n<output name="{name}">\n    <assert_contents>\n'
                         + "\n".join("        " + c for c in checks)
                         + "\n    </assert_contents>\n</output>")
        inner = "\n".join("    " + l for l in body.splitlines())
        return f"<!-- {self.purpose} -->\n<test {self.attributes}>\n{inner}\n</test>"


TP53 = ["--reference-name", "17", "--assembly", "GRCh38"]
#: TP53 R273H (rs28934576) in GRCh38, on the genomic plus strand: 17:7673802 C>T.
#: These tests once asked for 17:7577120 G>A under GRCh38 -- the GRCh37 position,
#: and the coding-strand change of a minus-strand gene -- so they could only ever
#: return nothing.
TESTS: list[GalaxyTest] = [
    # ---------------- beacon2_range ----------------
    GalaxyTest("beacon2_range", 1, "Two live providers; rows from each on the requested chromosome.",
               [connection([PGX, CCL]), p("variant_classes", "CNV"), p("reference_name", "17"),
                p("assembly", "GRCh38"), p("start", 7572837), p("end", 7578641),
                p("granularity", "record"), cnv_term("EFO:0020073"), ontology_filter(GBM)],
               ["range", "--providers", f"{PGX},{CCL}", "--variant-classes", "CNV", *TP53,
                "--start", "7572837", "--end", "7578641", "--granularity", "record",
                "--class-term", "CNV=EFO:0020073", "--expand-hierarchy", "auto", *arg_filter(GBM)],
               [outcome(PGX, "CNV", "ok"), outcome(CCL, "CNV", "ok"), lines(3)],
               [row(PGX, "CNV", "17"), row(CCL, "CNV", "17")],
               requests_to=[PGX, CCL], expects_rows=[(PGX, "CNV", "17"), (CCL, "CNV", "17")]),
    GalaxyTest("beacon2_range", 2, "An unfiltered common region exceeds the ceiling: refused, with a filter suggested.",
               [connection([PGX]), p("variant_classes", "CNV"), p("reference_name", "17"),
                p("start", 7572837), p("end", 7578641)],
               ["range", "--providers", PGX, "--variant-classes", "CNV", "--reference-name", "17",
                "--start", "7572837", "--end", "7578641"],
               [outcome(PGX, "CNV", "skipped"), text("ceiling"), text("--filter")],
               requests_to=[PGX]),
    GalaxyTest("beacon2_range", 3, "Count granularity: one summary row, no records.",
               [connection([CCL]), p("variant_classes", "CNV"), p("reference_name", "17"),
                p("start", 7572837), p("end", 7578641), p("granularity", "count")],
               ["range", "--providers", CCL, "--variant-classes", "CNV", "--reference-name", "17",
                "--start", "7572837", "--end", "7578641", "--granularity", "count"],
               [outcome(CCL, "CNV", "ok")],
               [rf'<has_line_matching expression={quoteattr(chr(94) + re.escape(CCL) + r"\t(?:[^\t]*\t){2}CNV\t[^\t]*\tcount\t.*")}/>',
                lines(2)],
               requests_to=[CCL]),
    GalaxyTest("beacon2_range", 4, "An ontology filter without descendants.",
               [connection([PGX]), p("variant_classes", "CNV"), p("reference_name", "17"),
                p("start", 7572837), p("end", 7578641), cnv_term("EFO:0020073"),
                ontology_filter(GBM, descendants=False)],
               ["range", "--providers", PGX, "--variant-classes", "CNV", "--reference-name", "17",
                "--start", "7572837", "--end", "7578641", "--class-term", "CNV=EFO:0020073",
                "--expand-hierarchy", "auto", *arg_filter(GBM, descendants=False)],
               [outcome(PGX, "CNV", "ok")], [row(PGX, "CNV", "17")],
               requests_to=[PGX], expects_rows=[(PGX, "CNV", "17")]),
    # ---------------- beacon2_bracket ----------------
    GalaxyTest("beacon2_bracket", 1, "Bracket query on two live providers, with client- or server-side expansion.",
               [connection([PGX, CCL]), p("variant_classes", "CNV"), p("reference_name", "17"),
                p("assembly", "GRCh38"), p("start_min", 5000000), p("start_max", 7676592),
                p("end_min", 7669607), p("end_max", 10000000), cnv_term("EFO:0030067", "always"),
                ontology_filter(GBM)],
               ["bracket", "--providers", f"{PGX},{CCL}", "--variant-classes", "CNV", *TP53,
                "--start-min", "5000000", "--start-max", "7676592", "--end-min", "7669607",
                "--end-max", "10000000", "--class-term", "CNV=EFO:0030067",
                "--expand-hierarchy", "always", *arg_filter(GBM)],
               [outcome(PGX, "CNV", "ok"), outcome(CCL, "CNV", "ok"), lines(3)],
               [row(PGX, "CNV", "17"), row(CCL, "CNV", "17")],
               requests_to=[PGX, CCL], expects_rows=[(PGX, "CNV", "17"), (CCL, "CNV", "17")]),
    GalaxyTest("beacon2_bracket", 2, "No bracket support: degraded to a range query, and labelled so.",
               [connection([BRK]), p("variant_classes", "CNV"), p("reference_name", "17"),
                p("start_min", 5000000), p("start_max", 7676592), p("end_min", 7669607),
                p("end_max", 10000000)],
               ["bracket", "--providers", BRK, "--variant-classes", "CNV", "--reference-name", "17",
                "--start-min", "5000000", "--start-max", "7676592", "--end-min", "7669607",
                "--end-max", "10000000"],
               [outcome(BRK, "CNV", "ok"), text("bracket"), text("range")],
               [row(BRK, "CNV", "17")],
               requests_to=[BRK], expects_rows=[(BRK, "CNV", "17")]),
    GalaxyTest("beacon2_bracket", 3, "Degradation refused: skipped before any request.",
               [connection([BRK]), p("variant_classes", "CNV"), p("reference_name", "17"),
                p("start_min", 5000000), p("start_max", 7676592), p("end_min", 7669607),
                p("end_max", 10000000),
                # inside the `advanced` section: at top level Galaxy would ignore it,
                # and the test would quietly run WITH degradation
                '<section name="advanced">\n    <param name="allow_degradation" value="false"/>\n</section>'],
               ["bracket", "--providers", BRK, "--variant-classes", "CNV", "--reference-name", "17",
                "--start-min", "5000000", "--start-max", "7676592", "--end-min", "7669607",
                "--end-max", "10000000", "--no-degradation"],
               [outcome(BRK, "CNV", "skipped")]),
    GalaxyTest("beacon2_bracket", 4, "A DEL/DUP variant type, which the specification marks LEGACY.",
               [connection([CCL]), p("variant_classes", "CNV"), p("reference_name", "9"),
                p("start_min", 21500001), p("start_max", 21975098), p("end_min", 21967753),
                p("end_max", 22500000), vcf_term("DEL")],
               ["bracket", "--providers", CCL, "--variant-classes", "CNV", "--reference-name", "9",
                "--start-min", "21500001", "--start-max", "21975098", "--end-min", "21967753",
                "--end-max", "22500000", "--class-term", "CNV=DEL"],
               [outcome(CCL, "CNV", "ok")], [row(CCL, "CNV", "9")],
               requests_to=[CCL], expects_rows=[(CCL, "CNV", "9")]),
    # ---------------- beacon2_sequence ----------------
    GalaxyTest("beacon2_sequence", 1, "A sequence query on a provider holding small variants.",
               [connection([PGX]), p("variant_classes", "SMALL_VARIANT"), p("reference_name", "17"),
                p("assembly", "GRCh38"), p("start", 7673802), p("reference_bases", "C"),
                p("alternate_bases", "T")],
               ["sequence", "--providers", PGX, "--variant-classes", "SMALL_VARIANT", *TP53,
                "--start", "7673802", "--reference-bases", "C", "--alternate-bases", "T"],
               [outcome(PGX, "SMALL_VARIANT", "ok")], requests_to=[PGX]),
    GalaxyTest("beacon2_sequence", 2, "A class of unknown status: queried, and zero is not evidence of absence.",
               [connection([CCL]), p("variant_classes", "SMALL_VARIANT"), p("reference_name", "17"),
                p("start", 7673802), p("reference_bases", "C"), p("alternate_bases", "T")],
               ["sequence", "--providers", CCL, "--variant-classes", "SMALL_VARIANT",
                "--reference-name", "17", "--start", "7673802", "--reference-bases", "C",
                "--alternate-bases", "T"],
               [outcome(CCL, "SMALL_VARIANT", "ok"), text("unknown")], requests_to=[CCL]),
    GalaxyTest("beacon2_sequence", 3, "A copy-number class is incoherent with a sequence query: skipped.",
               [connection([PGX]), p("variant_classes", "SMALL_VARIANT,CNV"), p("reference_name", "17"),
                p("start", 7673802), p("reference_bases", "C"), p("alternate_bases", "T")],
               ["sequence", "--providers", PGX, "--variant-classes", "SMALL_VARIANT,CNV",
                "--reference-name", "17", "--start", "7673802", "--reference-bases", "C",
                "--alternate-bases", "T"],
               [outcome(PGX, "SMALL_VARIANT", "ok"), outcome(PGX, "CNV", "skipped"), lines(3)],
               requests_to=[PGX]),
    GalaxyTest("beacon2_sequence", 4, "A class the provider declares it does not serve: skipped before any request.",
               [connection([BRK]), p("variant_classes", "SV"), p("reference_name", "17"),
                p("start", 7673802), p("reference_bases", "C"), p("alternate_bases", "T")],
               ["sequence", "--providers", BRK, "--variant-classes", "SV", "--reference-name", "17",
                "--start", "7673802", "--reference-bases", "C", "--alternate-bases", "T"],
               [outcome(BRK, "SV", "skipped"), text("does not serve")]),
    GalaxyTest("beacon2_sequence", 5, "A class Beacon v2 cannot express: skipped before any request.",
               [connection([PGX]), p("variant_classes", "REPEAT"), p("reference_name", "17"),
                p("start", 7673802), p("reference_bases", "C"), p("alternate_bases", "T")],
               ["sequence", "--providers", PGX, "--variant-classes", "REPEAT", "--reference-name", "17",
                "--start", "7673802", "--reference-bases", "C", "--alternate-bases", "T"],
               [outcome(PGX, "REPEAT", "skipped")]),
    # ---------------- beacon2_gene ----------------
    GalaxyTest("beacon2_gene", 1, "A gene query: no coordinates, so the class is what is checked.",
               [connection([CCL]), p("variant_classes", "CNV"), p("gene_id", "TP53")],
               ["gene", "--providers", CCL, "--variant-classes", "CNV", "--gene-id", "TP53"],
               [outcome(CCL, "CNV", "ok")], [row(CCL, "CNV")],
               requests_to=[CCL], expects_rows=[(CCL, "CNV", None)]),
    # ---------------- beacon2_cnv ----------------
    GalaxyTest("beacon2_cnv", 1, "CNVs from two live providers in one region.",
               [connection([PGX, CCL], p("reference_name", "3"), p("start", 195728638),
                           p("end", 198169247), cnv_term("EFO:0030072"), ontology_filter(GBM))],
               ["cnv", "--providers", f"{PGX},{CCL}", "--reference-name", "3", "--assembly", "GRCh38",
                "--start", "195728638", "--end", "198169247", "--granularity", "record",
                "--limit", "100", "--skip", "0", "--class-term", "CNV=EFO:0030072",
                "--expand-hierarchy", "auto", *arg_filter(GBM)],
               [outcome(PGX, "CNV", "ok"), outcome(CCL, "CNV", "ok"), lines(3)],
               [row(PGX, "CNV", "3"), row(CCL, "CNV", "3")],
               requests_to=[PGX, CCL], expects_rows=[(PGX, "CNV", "3"), (CCL, "CNV", "3")]),
    # ---------------- informational ----------------
    GalaxyTest("beacon2_filtering_terms", 1, "Every term, from a live provider.",
               [api_only([CCL])],
               ["filtering-terms", "--providers", CCL],
               [outcome(CCL, "n/a", "ok")], [text("shared_with"), text("NCIT:")],
               requests_to=[CCL], output_names=("terms", "outcomes")),
    GalaxyTest("beacon2_filtering_terms", 2, "A prefix is applied client-side, and the report says so.",
               [api_only([CCL]), p("prefixes", "EFO")],
               ["filtering-terms", "--providers", CCL, "--prefix", "EFO"],
               [outcome(CCL, "n/a", "ok"), text("selected client-side")],
               requests_to=[CCL], output_names=("terms", "outcomes")),
    GalaxyTest("beacon2_service_info", 1, "What a live provider reports about itself, against the registry.",
               [api_only([CCL])],
               ["service-info", "--providers", CCL],
               [outcome(CCL, "n/a", "ok")],
               # an OBSERVED value, not merely the row: the row is written either way
               [rf'<has_line_matching expression={quoteattr(chr(94) + re.escape(CCL) + r"\tbeacon_id_reported\t[^\t]*\t[^\t]+\t.*")}/>',
                text("production_status")],
               requests_to=[CCL], output_names=("report", "outcomes")),
]

for entity, plural, column, filtered in (
        ("biosample", "biosamples", "biosample_id", True),
        ("individual", "individuals", "individual_id", True),
        ("analysis", "analyses", "analysis_id", True), ("run", "runs", "run_id", True),
        # Small collections, which may not apply a disease filter at all.
        ("cohort", "cohorts", "cohort_id", False), ("dataset", "datasets", "dataset_id", False)):
    inner = [ontology_filter(GBM)] if filtered else []
    TESTS.append(GalaxyTest(
        f"beacon2_{plural}", 1,
        f"{plural.capitalize()}{' matching a filter' if filtered else ''}, from a live provider.",
        [connection([CCL], *inner)],
        ["entity", "--entity", entity, "--providers", CCL, "--granularity", "record",
         "--limit", "100", "--skip", "0", *(arg_filter(GBM) if filtered else [])],
        [outcome(CCL, "n/a", "ok"), lines(2)],
        [rf'<has_line_matching expression={quoteattr(chr(94) + re.escape(CCL) + r"\t.*")}/>',
         text(column)],
        requests_to=[CCL]))


def tests_for(tool: str) -> list[GalaxyTest]:
    return sorted((t for t in TESTS if t.tool == tool), key=lambda t: t.index)


def render_tests(tool: str, indent: str = "    ") -> str:
    """The complete <tests> block for a tool, as it must appear in its XML."""
    blocks = "\n".join(t.render() for t in tests_for(tool))
    inner = "\n".join((indent * 2 + l) if l else l for l in blocks.splitlines())
    return f"{indent}<tests>\n{inner}\n{indent}</tests>"


def write_all() -> list[str]:
    written = []
    for tool in sorted({t.tool for t in TESTS}):
        path = TOOLS / f"{tool}.xml"
        text_ = path.read_text()
        new = re.sub(r"    <tests>.*?</tests>", lambda _: render_tests(tool), text_, count=1, flags=re.S)
        if new != text_:
            path.write_text(new)
        written.append(path.name)
    return written


if __name__ == "__main__":
    print("rewrote:", write_all())
    sys.exit(0)
