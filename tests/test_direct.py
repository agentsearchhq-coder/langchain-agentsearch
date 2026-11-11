"""0.4.0 direct x402 option. Unit tests use a mock transport; the e2e test needs the local mock direct API
(x402-direct/scripts/mock_mainnet_server.py, mainnet terms + MockFacilitator, no chain) and is skipped without it."""
import base64
import json
import os

import httpx
import pytest

from langchain_agentsearch import AgentSearchExtractTool, AgentSearchRenderTool, AgentSearchSearchAndReadTool, AgentSearchTool
from langchain_agentsearch import _client

pytest.importorskip("x402")
from eth_account import Account  # noqa: E402

PRICES = {"search": "8000", "extract": "4000", "render": "10000", "search_and_read": "9000"}
API = "https://api.agentsearchhq.com"
_REAL_CLIENT = httpx.Client


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in (*_client.KEY_ENV_VARS, "AGENTSEARCH_MODE", "AGENTSEARCH_FREE_TRIAL", "AGENTSEARCH_X402_DIRECT",
              "AGENTSEARCH_X402_DIRECT_URL", "AGENTSEARCH_PAYMENT_ROUTE", "AGENTSEARCH_MAX_PER_CALL_ATOMIC", "AGENTSEARCH_MAX_TOTAL_ATOMIC"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENTSEARCH_WALLET_PRIVATE_KEY", Account.create().key.hex())  # throwaway, unfunded
    _client.reset_session_budget()


def terms(op, **over):
    return {"x402Version": 2, "resource": {"url": f"{API}/x402/v1/{op}", "mimeType": "application/json"},
            "accepts": [{"scheme": "exact", "network": "eip155:8453", "amount": PRICES[op], "asset": _client.USDC_BASE,
                         "payTo": _client.DIRECT_PAYEE, "maxTimeoutSeconds": 300, "extra": {"name": "USD Coin", "version": "2"}, **over}]}


def mock_api(monkeypatch, op, over=None, paid_status=200):
    seen = {"calls": []}

    def handler(req):
        sig = req.headers.get("payment-signature")
        seen["calls"].append({"url": str(req.url), "body": json.loads(req.content), "sig": sig})
        if not sig:
            t = terms(op, **(over or {}))
            return httpx.Response(402, json=t, headers={"PAYMENT-REQUIRED": base64.b64encode(json.dumps(t).encode()).decode()})
        seen["signed"] = json.loads(base64.b64decode(sig))
        rcpt = base64.b64encode(json.dumps({"success": True, "transaction": "0x" + "cd" * 32, "network": "eip155:8453",
                                            "payer": seen["signed"]["payload"]["authorization"]["from"]}).encode()).decode()
        return httpx.Response(paid_status, json={"markdown": "x" * 300, "ok": op}, headers={"PAYMENT-RESPONSE": rcpt})

    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)))
    return seen


def test_default_rail_is_direct_pocket_opt_in(monkeypatch):
    """0.5.0: with a wallet key, paid calls go to AgentSearch's own x402 API; Pocket is opt-in."""
    assert _client.direct_enabled()
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    assert not _client.direct_enabled()
    monkeypatch.delenv("AGENTSEARCH_PAYMENT_ROUTE")
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT", "0")  # 0.4.0 switch still selects Pocket
    assert not _client.direct_enabled()
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "direct")
    assert _client.direct_enabled()
    monkeypatch.delenv("AGENTSEARCH_X402_DIRECT")
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(500, text="stop")

    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler)))
    AgentSearchExtractTool().invoke({"url": "https://example.com"})
    assert seen["url"].startswith("https://agent.pocket.network/v1/agentsearch-web-extract-v1")


def test_default_extract_reaches_direct_api(monkeypatch):
    seen = mock_api(monkeypatch, "extract")
    out = json.loads(AgentSearchExtractTool().invoke({"url": "https://example.com"}))
    assert seen["calls"][0]["url"] == f"{API}/x402/v1/extract"
    assert out["payment"]["payTo"] == _client.DIRECT_PAYEE and out["payment"]["amountAtomic"] == "4000"


def test_invalid_route_refuses(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "bogus")
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: pytest.fail("no network call expected"))
    out = AgentSearchExtractTool().invoke({"url": "https://example.com"})
    assert "AGENTSEARCH_PAYMENT_ROUTE must be" in out


def test_old_pocket_per_call_cap_gets_hint(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "5000")
    seen = mock_api(monkeypatch, "render")
    out = AgentSearchRenderTool().invoke({"url": "https://example.com"})
    assert "AGENTSEARCH_PAYMENT_ROUTE=pocket" in out
    assert all(c["sig"] is None for c in seen["calls"])


@pytest.mark.parametrize("op", ["search", "extract", "render", "search_and_read"])
def test_direct_signs_for_agentsearch_payee(monkeypatch, op):
    # 0.5.0: no env needed, direct is the default paid route.
    seen = mock_api(monkeypatch, op)
    if op == "search":
        out = json.loads(AgentSearchTool(mode="paid").invoke({"query": "q", "max_results": 3}))
    elif op == "extract":
        out = json.loads(AgentSearchExtractTool().invoke({"url": "https://example.com"}))
    elif op == "search_and_read":
        out = json.loads(AgentSearchSearchAndReadTool().invoke({"query": "q", "num_results": 3}))
    else:
        out = json.loads(AgentSearchRenderTool().invoke({"url": "https://example.com", "formats": ["markdown"]}))
    assert seen["calls"][0]["url"] == f"{API}/x402/v1/{op}"
    assert set(seen["calls"][1]["body"]) <= set(_client.DIRECT_FIELDS[op])
    a = seen["signed"]["payload"]["authorization"]
    assert a["to"].lower() == _client.DIRECT_PAYEE.lower() and a["value"] == PRICES[op]
    assert out["payment"]["payTo"] == _client.DIRECT_PAYEE and out["payment"]["rail"] == "agentsearch-x402-direct"
    assert out["payment"]["settled"] is True


@pytest.mark.parametrize("over", [{"payTo": _client.PORTAL_PAYEE}, {"amount": "20001"}, {"network": "eip155:84532"},
                                  {"asset": "0x" + "11" * 20}])
def test_direct_refuses_bad_terms(monkeypatch, over):
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT", "1")
    seen = mock_api(monkeypatch, "extract", over)
    out = AgentSearchExtractTool().invoke({"url": "https://example.com"})
    assert "Nothing was signed" in out and len(seen["calls"]) == 1


def test_direct_per_call_cap_can_only_lower(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT", "1")
    monkeypatch.setenv("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "999999")
    seen = mock_api(monkeypatch, "render", {"amount": "20001"})
    assert "Nothing was signed" in AgentSearchRenderTool().invoke({"url": "https://example.com"})
    monkeypatch.setenv("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "4000")
    seen = mock_api(monkeypatch, "render")
    assert "Nothing was signed" in AgentSearchRenderTool().invoke({"url": "https://example.com"})
    assert len(seen["calls"]) == 1


def test_direct_url_must_be_https(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT", "1")
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT_URL", "http://evil.example")
    assert "must be https" in AgentSearchExtractTool().invoke({"url": "https://example.com"})


MOCK = os.environ.get("AGENTSEARCH_TEST_DIRECT_MOCK")  # e.g. http://127.0.0.1:8397


@pytest.mark.skipif(not MOCK, reason="local mock direct API not running")
def test_e2e_against_local_mock(monkeypatch):
    # 0.5.0: default route, no switch needed
    monkeypatch.setenv("AGENTSEARCH_X402_DIRECT_URL", MOCK)
    s = json.loads(AgentSearchTool(mode="paid").invoke({"query": "x402"}))
    e = json.loads(AgentSearchExtractTool().invoke({"url": "https://example.com"}))
    r = json.loads(AgentSearchRenderTool().invoke({"url": "https://example.com"}))
    assert [x["payment"]["amountAtomic"] for x in (s, e, r)] == ["8000", "4000", "10000"]
    assert all(x["payment"]["settled"] for x in (s, e, r))


def test_search_and_read_is_direct_only(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_PAYMENT_ROUTE", "pocket")
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: pytest.fail("no network call expected"))
    out = AgentSearchSearchAndReadTool().invoke({"query": "q"})
    assert "own x402 API" in out and "Nothing was signed" in out and "Pocket" in out


def test_search_and_read_old_cap_needs_20000(monkeypatch):
    monkeypatch.setenv("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "8000")
    seen = mock_api(monkeypatch, "search_and_read")
    out = AgentSearchSearchAndReadTool().invoke({"query": "q"})
    assert "to 20000" in out and "Nothing was signed" in out
    assert all(c["sig"] is None for c in seen["calls"])


def test_search_and_read_no_key_is_not_on_free_relay(monkeypatch):
    for k in _client.KEY_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(_client.httpx, "Client", lambda **kw: pytest.fail("no network call expected"))
    out = AgentSearchSearchAndReadTool().invoke({"query": "q"})
    assert "No wallet is configured" in out or "no wallet" in out.lower()
    assert "Nothing was signed" in out or "no call was made" in out.lower()
