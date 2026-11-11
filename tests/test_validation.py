"""0.6.1: bad input returns an Error string before any HTTP request."""
import json

import httpx
import pytest

from langchain_agentsearch import AgentSearchExtractTool, AgentSearchRenderTool, AgentSearchSearchAndReadTool, AgentSearchTool
from langchain_agentsearch import _client
from langchain_agentsearch._validate import InvalidInput, check_count, check_url


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in _client.KEY_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    for k in ("AGENTSEARCH_MODE", "AGENTSEARCH_FREE_TRIAL", "AGENTSEARCH_X402_DIRECT", "AGENTSEARCH_PAYMENT_ROUTE"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def net(monkeypatch):
    calls = []

    def handler(req):
        calls.append({"url": str(req.url), "body": json.loads(req.content)})
        return httpx.Response(200, json={"results": [], "content": "x" * 600})

    real = httpx.Client
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    return calls


@pytest.mark.parametrize("q", ["", " ", "   \n\t "])
def test_empty_query_no_http(net, q):
    out = AgentSearchTool().invoke({"query": q})
    assert out.startswith("Error: ") and "empty" in out
    assert net == []


def test_missing_query_no_http(net):
    assert AgentSearchTool().invoke({}).startswith("Error: ")
    assert net == []


def test_too_long_query(net):
    assert AgentSearchTool().invoke({"query": "a" * 401}).startswith("Error: ")
    assert net == []


def test_query_is_stripped(net):
    AgentSearchTool().invoke({"query": "  langchain  "})
    assert net[0]["body"] == {"query": "langchain"}


def test_string_input(net):
    AgentSearchTool().invoke("langchain release")
    assert net[0]["body"] == {"query": "langchain release"}


def test_max_results_null_is_default(net):
    AgentSearchTool().invoke({"query": "x", "max_results": None})
    assert net[0]["body"] == {"query": "x"}


def test_max_results_clamped(net):
    AgentSearchTool().invoke({"query": "x", "max_results": 50})
    AgentSearchTool().invoke({"query": "x", "max_results": 0})
    assert [c["body"]["max_results"] for c in net] == [5, 1]


@pytest.mark.parametrize("args", [{"q": "x"}, {"input": "x"}, {"query": None, "q": "x"}])
def test_query_aliases(net, args):
    out = AgentSearchTool().invoke(args)
    assert not out.startswith("Error"), out
    assert net[0]["body"]["query"] == "x"


@pytest.mark.parametrize("k", ["num_results", "k"])
def test_count_aliases(net, k):
    AgentSearchTool().invoke({"query": "x", k: 2})
    assert net[0]["body"] == {"query": "x", "max_results": 2}


def test_bad_type_returns_error_string(net):
    out = AgentSearchTool().invoke({"query": "x", "max_results": "lots"})
    assert out.startswith("Error: ")
    assert net == []


BAD_URLS = [
    "", "   ", "example.com/page", "ftp://example.com/x", "javascript:alert(1)", "file:///etc/passwd",
    "https://user:pw@example.com/", "https://@example.com/x", "https:///path", "http://localhost:8080/",
    "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data",
    "http://[::1]/", "http://intranet/", "http://printer.local/", "http://svc.internal/", "https://exa mple.com/",
    "http://example.com:99999/",
]


@pytest.mark.parametrize("u", BAD_URLS)
@pytest.mark.parametrize("tool", [AgentSearchExtractTool, AgentSearchRenderTool])
def test_bad_urls_no_http(net, tool, u):
    out = tool().invoke({"url": u})
    assert out.startswith("Error: ") and "Nothing was sent" in out, out
    assert net == []


@pytest.mark.parametrize("u", ["https://example.com", "http://example.com/a?b=1", "https://docs.langchain.com/oss/python/", "https://8.8.8.8/"])
def test_good_urls(u):
    assert check_url(u) == u


def test_bare_domain_hint():
    with pytest.raises(InvalidInput, match="https://example.com"):
        check_url("example.com")


def test_url_alias_and_trial_call(net):
    out = AgentSearchExtractTool().invoke({"link": " https://example.com/a "})
    assert not out.startswith("Error"), out
    assert net[0]["body"]["url"] == "https://example.com/a"


def test_search_and_read_validates_before_signing(net, monkeypatch):
    called = []
    monkeypatch.setattr(_client, "call_portal", lambda op, body, client=None: called.append(body) or {"ok": True})
    assert AgentSearchSearchAndReadTool().invoke({"query": "  "}).startswith("Error: ")
    assert called == [] and net == []
    AgentSearchSearchAndReadTool().invoke({"q": "x", "max_results": 9})
    assert called == [{"query": "x", "num_results": 5}]


def test_check_count():
    assert check_count(None, "n") is None and check_count("", "n") is None
    assert check_count("3", "n") == 3 and check_count(7, "n") == 5
    with pytest.raises(InvalidInput):
        check_count("x", "n")


def test_descriptions_have_direct_prices():
    assert "$0.004" in AgentSearchExtractTool().description and "$0.005" not in AgentSearchExtractTool().description
    assert "$0.010" in AgentSearchRenderTool().description and "$0.005" not in AgentSearchRenderTool().description
    assert "$0.008" in AgentSearchTool().description and "Free" in AgentSearchTool().description
    assert "$0.009" in AgentSearchSearchAndReadTool().description
