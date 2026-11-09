# Changelog

## 0.3.0 (2026-11-09)
- **No-wallet free trial for extract and render.** With no wallet key, `AgentSearchExtractTool` (5 calls/day per IP) and `AgentSearchRenderTool` (3 calls/day per IP, text output; screenshots are skipped with a note) call the AgentSearch free relay (`POST /v1/extract`, `/v1/render`) instead of returning a setup message. `render_fallback` uses the render trial allowance. Past the trial the tool returns the relay's reason plus wallet setup steps (https://agentsearchhq.com/wallet-setup). If the relay doesn't offer the trial (404/405), the old setup message is returned.
- `AGENTSEARCH_FREE_TRIAL=0` turns the trial off (no-wallet extract/render then make no network call, as in 0.2.x).
- Unchanged: free search, `mode`/`AGENTSEARCH_MODE`, the wallet paid path and its caps. Matches `@agentsearchhq/agentsearch-mcp` 1.4.0.

## 0.2.1 (2026-11-09)
- **Search stays free when a wallet key is set.** `AgentSearchTool()` (mode `auto`) now uses the free tier unless you opt in with `mode="paid"` or `AGENTSEARCH_MODE=paid`. A wallet key alone only enables `agentsearch_extract` / `agentsearch_render`. Matches `@agentsearchhq/langchain` 0.2.1, `crewai-agentsearch` 0.2.1 and the MCP server 1.3.5+. If you relied on a wallet key making search paid, set `AGENTSEARCH_MODE=paid`.
- `AGENTSEARCH_MODE=paid` without the `[paid]` extra falls back to free search with a warning.
- Free-tier 429 message now says pages you already found can still be read with extract ($0.005, $1 covers 200 calls) and links the search-then-read setup guide; per-IP wording.
- No-wallet extract/render message says nothing was charged, suggests answering from search results, and links the guide.

## 0.2.0
- Client tag, render guidance, repo metadata.
