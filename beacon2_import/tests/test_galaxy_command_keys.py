"""Galaxy's rendered command and the fixture recorder send the SAME requests.

Fixtures are keyed on the request. scripts/record_fixtures.py records each
Galaxy test's query from the argv in scripts/galaxy_tests.py; `planemo test`
then sends whatever the tool's Cheetah <command> renders. If those two ever
differed, every recording would silently stop matching, and nothing would say
so until planemo failed with FixtureMiss.

So this renders each tool's real command, with Galaxy's own macro loader and
Galaxy-style parameter wrappers built from the tool's inputs and the test's
values, and runs both argument lists through the real CLI against one stand-in
network, comparing the canonical request of everything each sends.

Needs galaxy-tool-util (installed wherever planemo is) and Cheetah; skips
cleanly without them.
"""

from __future__ import annotations

import json
import shlex
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

xml_macros = pytest.importorskip("galaxy.util.xml_macros")
Template = pytest.importorskip("Cheetah.Template").Template
etree = pytest.importorskip("lxml.etree")

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = ROOT / "tools" / "beacon2-import"
SCRIPTS = ROOT / "scripts"
pytestmark = pytest.mark.skipif(not (SCRIPTS / "galaxy_tests.py").is_file() or not TOOLS.is_dir(),
                                reason="scripts or tool XML not present")
if (SCRIPTS / "galaxy_tests.py").is_file():
    sys.path.insert(0, str(SCRIPTS))
    import galaxy_tests as spec

    TESTS = spec.TESTS
else:  # pragma: no cover
    TESTS = []

from beacon2_import.cli import common  # noqa: E402
from beacon2_import.cli.main import main  # noqa: E402
from beacon2_import.transport.http import Response, canonical_request  # noqa: E402

_CACHE: dict = {}


def _expanded(tool):
    """The tool's XML with every macro expanded, by Galaxy's own loader."""
    if tool not in _CACHE:
        tree = xml_macros.load(str(TOOLS / f"{tool}.xml"))
        root = tree.getroot() if hasattr(tree, "getroot") else tree
        _CACHE[tool] = ET.fromstring(etree.tostring(root))
    return _CACHE[tool]


class Leaf:
    def __init__(self, value): self.value = "" if value is None else str(value)
    def __str__(self): return self.value
    def __eq__(self, other): return str(self) == str(other)
    def __hash__(self): return hash(self.value)


def default_of(param):
    kind = param.get("type")
    if kind == "boolean":
        return (param.get("truevalue", "true") if param.get("checked", "false") == "true"
                else param.get("falsevalue", "false"))
    if kind == "select":
        options = param.findall("option")
        chosen = [o.get("value") for o in options if o.get("selected") == "true"]
        if param.get("multiple") == "true":
            return ",".join(chosen) if chosen else "None"
        return chosen[0] if chosen else (options[0].get("value") if options else "")
    return param.get("value", "")


def pname(param):
    return param.get("name") or param.get("argument", "").lstrip("-").replace("-", "_")


def build(inputs, values):
    """values: nested dict from the test (names -> str | dict | list)."""
    ns = types.SimpleNamespace()
    for el in inputs:
        tag = el.tag
        if tag == "param":
            name = pname(el)
            value = values.get(name, default_of(el))
            if el.get("type") == "boolean" and name in values:
                value = el.get("truevalue", "true") if str(value).lower() == "true" else el.get("falsevalue", "false")
            setattr(ns, name, Leaf(value))
        elif tag == "conditional":
            name, sub = el.get("name"), values.get(el.get("name"), {})
            test = el.find("param")
            test_value = sub.get(pname(test), default_of(test))
            group = build([test], {pname(test): test_value})
            when = next((w for w in el.findall("when") if w.get("value") == str(test_value)), None)
            if when is not None:
                for k, v in vars(build(list(when), sub)).items():
                    setattr(group, k, v)
            setattr(ns, name, group)
        elif tag == "section":
            setattr(ns, el.get("name"), build(list(el), values.get(el.get("name"), {})))
        elif tag == "repeat":
            setattr(ns, el.get("name"), [build(list(el), inst) for inst in values.get(el.get("name"), [])])
    return ns


def _form_values(element):
    out = {}
    for child in element:
        if child.tag == "param":
            out[child.get("name")] = child.get("value")
        elif child.tag in ("conditional", "section"):
            out.setdefault(child.get("name"), {}).update(_form_values(child))
        elif child.tag == "repeat":
            out.setdefault(child.get("name"), []).append(_form_values(child))
    return out


def rendered_argv(tool, index):
    root = _expanded(tool)
    test = root.find("tests").findall("test")[index - 1]
    ns = build(list(root.find("inputs")), _form_values(test))
    ns.credentials = Leaf("/tmp/credentials.txt"); ns.provider_table = Leaf("/tmp/provider_table.loc")
    command = str(Template(root.find("command").text, searchList=[vars(ns)]))
    tokens = shlex.split(command)
    argv = tokens[tokens.index("beacon2-query") + 1:]
    # Galaxy's file arguments are not part of any request
    drop = {"--provider-table", "--credentials-file", "--results", "--outcomes", "--terms", "--report"}
    out, skip = [], False
    for token in argv:
        if skip: skip = False; continue
        if token in drop: skip = True; continue
        out.append(token)
    return out


class Network:
    """One stand-in network for both runs: answers every request plausibly."""

    def __init__(self): self.keys = []

    def _answer(self, method, path, params=None, body=None):
        self.keys.append(json.dumps(canonical_request(method, path, params, body), sort_keys=True))
        q = canonical_request(method, path, params, body)["query"]
        entity = {"g_variants": "genomicVariant", "genomicVariations": "genomicVariant"}.get(
            path.strip("/").split("/")[-1], path.strip("/").rstrip("s"))
        start, end = (q.get("start") or [100])[0], (q.get("end") or [1000])[-1]
        records = [{"id": f"x{i}", "variantInternalId": f"x{i}",
                    "variation": {"variantState": {"id": "EFO:0030067"},
                                  "location": {"chromosome": q.get("referenceName", "17"),
                                               "start": start, "end": start + 1}},
                    "caseLevelData": [{"biosampleId": f"b{i}"}]} for i in range(2)]
        body = {"meta": {"returnedGranularity": q.get("requestedGranularity", "record"),
                         "returnedSchemas": [{"entityType": entity}],
                         "receivedRequestSummary": {"pagination": {"limit": 0}, "testMode": False}},
                "responseSummary": {"exists": True, "numTotalResults": 2},
                "response": {"resultSets": [{"id": "s", "exists": True, "resultsCount": 2,
                                             "results": records}], "filteringTerms": [{"id": "NCIT:C1"}]}}
        return Response(200, body, path, method, 0.0)

    def post(self, path, body): return self._answer("POST", path, None, body)
    def get(self, path, params=None): return self._answer("GET", path, params, None)


def keys_for(argv, output_names):
    net = Network()
    common.make_client = lambda provider, credentials: net
    tmp = Path(tempfile.mkdtemp())
    table = tmp / "providers.loc"
    table.write_text((TOOLS / "test-data/beacon_providers.loc").read_text()
                     .replace("${__HERE__}", str(TOOLS / "test-data")))
    flags = {"results": "--results", "outcomes": "--outcomes", "terms": "--terms", "report": "--report"}
    try:
        main([*argv, "--provider-table", str(table),
              flags[output_names[0]], str(tmp / "a.tsv"), flags[output_names[1]], str(tmp / "b.tsv")])
    except SystemExit as exc:
        return None, f"exit {exc.code}"
    return sorted(set(net.keys)), None




@pytest.fixture(autouse=True)
def _restore_factory():
    original = common.make_client
    yield
    common.make_client = original


@pytest.mark.parametrize("test", TESTS, ids=lambda t: t.id)
def test_galaxy_sends_what_the_recorder_records(test):
    recorded, error = keys_for(test.argv, test.output_names)
    rendered, error2 = keys_for(rendered_argv(test.tool, test.index), test.output_names)
    assert not error and not error2, (error, error2)
    assert recorded == rendered, "\n".join(sorted(set(recorded) ^ set(rendered)))


def test_the_renderer_notices_a_changed_value():
    """Guards the guard: a renderer that dropped parameters would agree trivially."""
    tool, index = "beacon2_range", 1
    root = _expanded(tool)
    param = next(p for p in root.find("tests").findall("test")[index - 1].iter("param")
                 if p.get("name") == "reference_name")
    original = param.get("value")
    try:
        param.set("value", "18")
        changed, _ = keys_for(rendered_argv(tool, index), ("results", "outcomes"))
    finally:
        param.set("value", original)
    recorded, _ = keys_for(spec.tests_for(tool)[index - 1].argv, ("results", "outcomes"))
    assert changed != recorded and any('"referenceName": "18"' in k for k in changed)
