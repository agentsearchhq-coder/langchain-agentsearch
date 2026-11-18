"""0.7.4: free_search / check_query / check_count tolerate tool-input dicts and other wrong-typed args."""
import json

import httpx
import pytest

from langchain_agentsearch import _client as c
from langchain_agentsearch._validate import InvalidInput, check_count, check_query, coerce_max_results


def _client():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"results": []})

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_query_dict_is_unwrapped():
    cl, seen = _client()
    c.free_search({"query": "langchain release", "max_results": 3}, None, client=cl)
    assert seen == [{"query": "langchain release"}]


def test_config_dict_in_max_results_slot_is_ignored():
    cl, seen = _client()
    c.free_search("hello world", {"callbacks": [], "tags": [], "configurable": {}}, client=cl)
    assert seen == [{"query": "hello world"}]


def test_max_results_variants():
    cl, seen = _client()
    for v in ({"max_results": 3}, {"value": {"max_results": "2"}}, "4", 99.7, "lots", 0, True, float("nan")):
        c.free_search("hello", v, client=cl)
    assert [b.get("max_results") for b in seen] == [3, 2, 4, 5, None, 1, None, None]


@pytest.mark.parametrize("q", [None, "", "   ", {}, {"query": ""}, {"max_results": 3}, [], True, "a"])
def test_bad_query_fails_locally(q):
    cl, seen = _client()
    with pytest.raises(InvalidInput) as e:
        c.free_search(q, None, client=cl)
    assert "query" in str(e.value) and "Nothing was sent or charged" in str(e.value)
    assert seen == []


def test_check_query_and_count():
    assert check_query({"query": " abc "}) == "abc"
    assert check_query({"input": {"q": "xyz"}}) == "xyz"
    assert check_query(2026) == "2026"
    assert check_count({"max_results": 3}, "n") == 3
    assert check_count({"foo": 1}, "n") is None
    assert check_count(" 7 ", "n") == 5
    with pytest.raises(InvalidInput):
        check_count("x", "n")
    assert coerce_max_results("x") is None
    assert coerce_max_results({"num_results": "12"}, 1, 10) == 10
