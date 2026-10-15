import json
import os

import httpx
import pytest

from langchain_agentsearch import AgentSearchExtractTool, AgentSearchRenderTool, AgentSearchTool, FREE_LIMIT_MESSAGE
from langchain_agentsearch import _client


@pytest.fixture(autouse=True)
def no_wallet(monkeypatch):
    for k in _client.KEY_ENV_VARS:
        monkeypatch.delenv(k, raising=False)


def mock(monkeypatch, status, body):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(status, json=body)

    real = httpx.Client
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    return seen


def test_names():
    assert [t().name for t in (AgentSearchTool, AgentSearchExtractTool, AgentSearchRenderTool)] == [
        "agentsearch_search", "agentsearch_extract", "agentsearch_render"]


def test_free_search_mocked(monkeypatch):
    seen = mock(monkeypatch, 200, {"provider": "p", "results": [{"title": "T", "url": "https://a"}]})
    out = json.loads(AgentSearchTool().invoke({"query": "x", "max_results": 1}))
    assert seen["url"] == "https://relay.agentsearchhq.com/v1/search"
    assert seen["body"] == {"query": "x", "max_results": 1}
    assert "provider" not in out and out["results"][0]["title"] == "T"


def test_429(monkeypatch):
    mock(monkeypatch, 429, {})
    assert AgentSearchTool().invoke({"query": "x"}) == f"Error: {FREE_LIMIT_MESSAGE}"


def test_paid_without_wallet():
    assert "No wallet" in AgentSearchExtractTool().invoke({"url": "https://example.com"})
    assert "No wallet" in AgentSearchRenderTool().invoke({"url": "https://example.com"})


def test_bad_key_not_leaked(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_WALLET_PRIVATE_KEY", "nothex-secret")
    out = AgentSearchExtractTool().invoke({"url": "https://example.com"})
    assert "not a private key" in out and "nothex-secret" not in out


def test_select_accept_caps():
    class A:
        scheme = "exact"; network = _client.BASE_NETWORK; asset = _client.USDC_BASE; pay_to = _client.PORTAL_PAYEE; amount = "6000"
    with pytest.raises(_client.AgentSearchError):
        _client.select_accept([A()], 5000)
    A.amount = "5000"
    assert _client.select_accept([A()], 5000).amount == "5000"


def test_tool_call_message(monkeypatch):
    mock(monkeypatch, 200, {"results": []})
    msg = AgentSearchTool().invoke({"type": "tool_call", "id": "1", "name": "agentsearch_search", "args": {"query": "x"}})
    assert msg.tool_call_id == "1"


@pytest.mark.skipif(not os.environ.get("AGENTSEARCH_LIVE"), reason="set AGENTSEARCH_LIVE=1")
def test_live_free_search():
    out = json.loads(AgentSearchTool(mode="free").invoke({"query": "LangChain python tools", "max_results": 2}))
    assert out["results"] and out["results"][0]["url"].startswith("http")


def test_paid_flow_signs_with_x402_sdk(monkeypatch):
    """Mocked portal: 402 -> SDK signs -> 200. Uses a throwaway random key; no network."""
    pytest.importorskip("x402")
    from eth_account import Account
    from x402.http.utils import encode_payment_required_header
    from x402.schemas import PaymentRequired, PaymentRequirements, ResourceInfo

    _client.reset_session_budget()
    monkeypatch.setenv("AGENTSEARCH_WALLET_PRIVATE_KEY", Account.create().key.hex())
    req = PaymentRequired(x402_version=2, resource=ResourceInfo(url="https://agent.pocket.network/v1/agentsearch-web-extract-v1"),
        accepts=[PaymentRequirements(scheme="exact", network=_client.BASE_NETWORK, asset=_client.USDC_BASE, amount="5000",
                                     pay_to=_client.PORTAL_PAYEE, max_timeout_seconds=60, extra={"name": "USD Coin", "version": "2"})])
    calls = []

    def handler(r):
        calls.append(r)
        if "payment-signature" not in r.headers:
            return httpx.Response(402, headers={"PAYMENT-REQUIRED": encode_payment_required_header(req)}, json={})
        return httpx.Response(200, json={"portal": {}, "data": {"url": "https://example.com", "content": "hi"}})

    real = httpx.Client
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    out = json.loads(AgentSearchExtractTool().invoke({"url": "https://example.com"}))
    assert out["content"] == "hi" and out["payment"]["amountAtomic"] == "5000"
    assert len(calls) == 2 and _client.session_spent_atomic() == 5000
    monkeypatch.setenv("AGENTSEARCH_MAX_TOTAL_ATOMIC", "5000")
    assert "cap reached" in AgentSearchExtractTool().invoke({"url": "https://example.com"})
