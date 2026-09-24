import json
import random
import string

import pytest
import yaml

from libre_devops_helpers.core.yaml_text import dumps

TRICKY = [
    "",
    "plain",
    "Ana Analyst",
    "yes",
    "No",
    "ON",
    "off",
    "y",
    "n",
    "null",
    "Null",
    "~",
    "none",
    "true",
    "False",
    "0",
    "0123",
    "1.0",
    "-3",
    "1e3",
    "0x1F",
    ".inf",
    ".nan",
    "1_000",
    "2026-09-24",
    "12:30",
    "@odata.context",
    "#comment",
    "&anchor",
    "*alias",
    "!tag",
    "%directive",
    "`tick",
    "- dash",
    "? question",
    "[list]",
    "{map}",
    "a: b",
    "a:b",
    "x #y",
    "trailing ",
    " leading",
    "'single'",
    '"double"',
    "back\\slash",
    "tab\there",
    "Zürich",
    "emoji 🧰",
    "a|b",
    "a > b",
    "line one\nline two",
    "ends with newline\n",
    "keeps\n\n\n",
    "\nstarts with newline",
    " indented\nsecond",
    "trailing space \nline",
    "cr\r\nlf",
    "ctrl\x01char",
    "nel\u0085x",
    "https://graph.microsoft.com/v1.0/users?$filter=a eq 'b'",
]


@pytest.mark.parametrize("text", TRICKY)
def test_every_awkward_string_reads_back_as_itself(text):
    for document in (text, {"key": text}, [text], {text or "k": [text, {"n": text}]}):
        assert yaml.safe_load(dumps(document)) == document, dumps(document)


def test_a_graph_reply_reads_back_whole():
    reply = {
        "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#devices",
        "@odata.count": 2,
        "value": [
            {"id": "1", "displayName": "web01", "accountEnabled": True, "extensionAttributes": {}},
            {"id": "2", "displayName": "web02", "accountEnabled": False, "physicalIds": []},
        ],
        "nested": [[1, 2.5, None], [{"a": [{"b": {"c": "d"}}]}]],
    }
    assert yaml.safe_load(dumps(reply)) == reply


def test_it_reads_like_yaml_people_write():
    assert dumps({"name": "web01", "tags": ["linux", "prod"], "script": "a\nb\n", "count": 1}) == (
        "name: web01\ntags:\n  - linux\n  - prod\nscript: |\n  a\n  b\ncount: 1\n"
    )
    # Some readers take y and n for booleans, so even a key named n is quoted.
    assert dumps({"n": "y"}) == '"n": "y"\n'
    assert dumps([{"a": 1, "b": 2}]) == "- a: 1\n  b: 2\n"
    assert dumps({"a": {}}, indent=4) == "a: {}\n"
    assert dumps({"a": {"b": 1}}, indent=4) == "a:\n    b: 1\n"


def test_paint_sees_each_kind():
    seen = []
    dumps({"k": ["s", 1, True, None]}, paint=lambda kind, text: seen.append(kind) or text)
    assert {"key", "string", "number", "bool", "null", "punct"} <= set(seen)


def random_value(rng: random.Random, depth: int = 0):
    alphabet = string.printable + "éü🧰\u0085"
    kinds = ["str", "int", "float", "bool", "null"] + (["list", "dict"] if depth < 4 else [])
    kind = rng.choice(kinds)
    if kind == "str":
        return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
    if kind == "int":
        return rng.randint(-(10**12), 10**12)
    if kind == "float":
        return rng.choice([0.5, -1.25, 1e-7, 3.14159, 2.5e20])
    if kind == "bool":
        return rng.choice([True, False])
    if kind == "null":
        return None
    if kind == "list":
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {
        "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8))): random_value(
            rng, depth + 1
        )
        for _ in range(rng.randint(0, 4))
    }


def test_random_documents_read_back_as_themselves():
    rng = random.Random(20260924)
    for _ in range(500):
        document = json.loads(json.dumps(random_value(rng)))
        assert yaml.safe_load(dumps(document)) == document, dumps(document)
