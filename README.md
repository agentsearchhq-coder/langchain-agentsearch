# langchain-agentsearch

LangChain (Python) tools for [AgentSearch](https://agentsearchhq.com/?utm_source=langchain-agentsearch&utm_medium=package): live web search for agents.

| Tool | Name | Cost |
|---|---|---|
| `AgentSearchTool` | `agentsearch_search` | **Free** (25 searches/day per user, up to 5 results, no key). Paid & unlimited if a wallet is set. |
| `AgentSearchExtractTool` | `agentsearch_extract` | $0.005/call (USDC on Base via x402) |
| `AgentSearchRenderTool` | `agentsearch_render` | $0.005/call (headless browser for JS pages) |

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

agent = create_react_agent(llm, [AgentSearchTool(), AgentSearchExtractTool(), AgentSearchRenderTool()])
```

## Paid mode

Install the `paid` extra and set `AGENTSEARCH_WALLET_PRIVATE_KEY` to the private key of a **new wallet made only for this**, funded with a little USDC on Base (e.g. $1; no ETH needed). Each call is paid over x402 through the Pocket Network Agentic Portal using the official x402 Python SDK. With a key set, `AgentSearchTool` also goes paid; force free with `AgentSearchTool(mode="free")`.

| Env var | Default |
|---|---|
| `AGENTSEARCH_MAX_TOTAL_ATOMIC` | `1000000` ($1.00 per process) |
| `AGENTSEARCH_MAX_PER_CALL_ATOMIC` | `5000` ($0.005; can only be lowered) |
| `AGENTSEARCH_TIMEOUT_MS` | `30000` |

Limits are checked before anything is signed. The key is never logged or returned. Paid results include a `payment` object.

## Errors

Tools return `"Error: ..."` strings rather than raising. A 429 from the free relay means the daily limit was hit; the message explains how to upgrade.

## Development

```bash
pip install -e ".[test,paid]" && pytest            # unit tests (mocked)
AGENTSEARCH_LIVE=1 pytest -k live                    # one real free search
```

Docs: https://agentsearchhq.com/agents.md?utm_source=langchain-agentsearch&utm_medium=package

MIT
