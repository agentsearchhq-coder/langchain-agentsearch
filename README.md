# langchain-agentsearch

LangChain (Python) tools for [AgentSearch](https://agentsearchhq.com/?utm_source=langchain-agentsearch&utm_medium=package): live web search for agents.

| Tool | Name | Cost |
|---|---|---|
| `AgentSearchTool` | `agentsearch_search` | **Free** (up to 25 searches/day per IP, up to 5 results, no key). Paid search with no daily cap is opt-in (`mode="paid"` / `AGENTSEARCH_MODE=paid`). |
| `AgentSearchExtractTool` | `agentsearch_extract` | Free trial without a wallet (5/day per IP), then $0.005/call (USDC on Base via x402) |
| `AgentSearchRenderTool` | `agentsearch_render` | Free trial without a wallet (3/day per IP, no screenshots), then $0.005/call (headless browser for JS pages) |

## Install

```bash
pip install -U langchain-agentsearch          # free search
pip install -U "langchain-agentsearch[paid]"  # + x402 payments for extract/render
```

## Quick start (free, no key)

```python
from langchain_agentsearch import AgentSearchTool

search = AgentSearchTool()
print(search.invoke({"query": "latest LangChain release", "max_results": 3}))
# JSON string: {"query": ..., "results": [{"title", "url", "content"}, ...]}
```

With an agent:

```python
from langgraph.prebuilt import create_react_agent
from langchain_agentsearch import AgentSearchTool, AgentSearchExtractTool, AgentSearchRenderTool

agent = create_react_agent(llm, [AgentSearchTool(mode="free"), AgentSearchExtractTool(), AgentSearchRenderTool()])
```

## Search, then read the page

Snippets are often not enough to answer from. The usual loop: **search free → extract the 1–2 best URLs as markdown → render only pages extract couldn't read** (JavaScript apps).

```python
from langchain.agents import create_agent
from langchain_agentsearch import AgentSearchTool, AgentSearchExtractTool, AgentSearchRenderTool

SYSTEM = (
    "Search first. Extract at most 2 of the best results with max_chars=8000. "
    "If extract returns empty or very short content, render that URL once. Cite every URL you used."
)
agent = create_agent(
    model="openai:gpt-4.1-mini",
    tools=[AgentSearchTool(mode="free"), AgentSearchExtractTool(), AgentSearchRenderTool()],
    system_prompt=SYSTEM,
)
```

Without a wallet this already runs: search is free, and from 0.3.0 extract/render use a small free trial (5 extract and 3 render calls per IP per UTC day, shared daily capacity, no screenshots). Past the trial they return an `Error: ...` string with wallet setup steps (https://agentsearchhq.com/wallet-setup), so the agent answers from snippets. Set `AGENTSEARCH_FREE_TRIAL=0` to skip the trial (no request without a wallet). Add a wallet (below) and the same agent reads full pages at $0.005 per page; $1 covers 200 calls. Pass `render_fallback=True` to extract (or set `AGENTSEARCH_EXTRACT_RENDER_FALLBACK=1`) to retry thin pages with render automatically.

Full walkthrough: https://agentsearchhq.com/blog/langchain-agent-search-then-read-page?utm_source=langchain-agentsearch&utm_medium=package

## Paid mode

Install the `paid` extra and set `AGENTSEARCH_WALLET_PRIVATE_KEY` to the private key of a **new wallet made only for this**, funded with a little USDC on Base (e.g. $1; no ETH needed). Each call is paid over x402 through the Pocket Network Agentic Portal using the official x402 Python SDK. From 0.2.1 a wallet key alone keeps search free and only enables extract/render. Paid search (no daily cap, $0.005 per search) is opt-in: `AgentSearchTool(mode="paid")` or `AGENTSEARCH_MODE=paid`. (In 0.2.0 a key switched the default search tool to paid; `mode="free"` works in every version.)

| Env var | Default |
|---|---|
| `AGENTSEARCH_MAX_TOTAL_ATOMIC` | `1000000` ($1.00 per process) |
| `AGENTSEARCH_MAX_PER_CALL_ATOMIC` | `5000` ($0.005; can only be lowered) |
| `AGENTSEARCH_TIMEOUT_MS` | `30000` |

Limits are checked before anything is signed. The key is never logged or returned. Paid results include a `payment` object.

### Direct x402 (0.4.0, opt-in)

AgentSearch also runs its own x402 API on Base mainnet (`https://api.agentsearchhq.com`). With the `[paid]` extra and a wallet key, set `AGENTSEARCH_X402_DIRECT=1` and paid calls go straight to it instead of the Pocket portal: extract **$0.007**, render **$0.010**, search **$0.008** (search is still paid only with `mode="paid"` or `AGENTSEARCH_MODE=paid`).

```bash
pip install 'langchain-agentsearch[paid]'
export AGENTSEARCH_WALLET_PRIVATE_KEY=0x...   # a NEW wallet holding a little USDC on Base
export AGENTSEARCH_X402_DIRECT=1
```

Signs only the `exact` scheme, USDC on Base, to AgentSearch's payee `0xC49B157887e51c21CB655f39CF65D6a4c2a4C337`, at most $0.010 per call (lower with `AGENTSEARCH_MAX_PER_CALL_ATOMIC`) and `AGENTSEARCH_MAX_TOTAL_ATOMIC` per session (default $1.00). The API settles only after a successful answer. Direct extract/render take only `url` (other options are dropped and listed in `payment.droppedFields`). Without the variable nothing changes. Docs: https://agentsearchhq.com/docs/x402

## Errors

Tools return `"Error: ..."` strings rather than raising. A 429 from the free relay means the daily limit was hit; the message explains how to upgrade.

## Development

```bash
pip install -e ".[test,paid]" && pytest            # unit tests (mocked)
AGENTSEARCH_LIVE=1 pytest -k live                    # one real free search
```

Docs: https://agentsearchhq.com/agents.md?utm_source=langchain-agentsearch&utm_medium=package

MIT
