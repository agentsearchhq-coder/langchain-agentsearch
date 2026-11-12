from __future__ import annotations

from typing import Any, Literal, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, ValidationError, model_validator

from . import _client as c
from ._validate import InvalidInput, check_count, check_query, check_url


def _alias(data: Any, target: str, names: tuple[str, ...]) -> Any:
    """Map common LLM argument names onto the real field (in place, so every langchain-core version keeps it)."""
    if isinstance(data, dict) and data.get(target) is None:
        for n in names:
            if data.get(n) is not None:
                data[target] = data[n]
                break
    return data


def _on_validation_error(e: ValidationError) -> str:
    bits = []
    for err in e.errors()[:3]:
        loc = ".".join(str(x) for x in err.get("loc", ())) or "input"
        bits.append(f"{loc}: {err.get('msg')}")
    return "Error: invalid tool input (" + "; ".join(bits) + "). Nothing was sent or charged."


class _Filters(BaseModel):
    freshness: Optional[Literal["day", "week", "month", "year"]] = Field(default=None, description="Only results from the past day/week/month/year (paid direct route only)")
    date_from: Optional[str] = Field(default=None, description="Earliest publish date YYYY-MM-DD (paid direct route only)")
    date_to: Optional[str] = Field(default=None, description="Latest publish date YYYY-MM-DD (paid direct route only)")
    country: Optional[str] = Field(default=None, min_length=2, max_length=2, description="2-letter country code, e.g. us, gb (paid direct route only)")
    language: Optional[str] = Field(default=None, description="Language code, e.g. en, es, pt-BR (paid direct route only)")
    include_domains: Optional[list[str]] = Field(default=None, max_length=5, description="Only these domains, up to 5 (paid direct route only)")
    exclude_domains: Optional[list[str]] = Field(default=None, max_length=5, description="Never these domains, up to 5 (paid direct route only)")


def _filters(kw: dict[str, Any]) -> dict[str, Any]:
    return {k: kw[k] for k in c.FILTER_KEYS if kw.get(k) is not None}


class _SearchBase(BaseModel):
    query: str = Field(default="", description="Search query (non-empty)")
    max_results: Optional[int] = Field(default=None, description="1-5, default 5")

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        data = _alias(data, "query", ("q", "input", "search_query"))
        return _alias(data, "max_results", ("num_results", "k", "limit"))


class _UrlInput(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        return _alias(data, "url", ("link", "href", "page_url"))


class ExtractInput(_UrlInput):
    url: str = Field(default="", description="Full public http(s) URL to extract")
    formats: Optional[list[str]] = Field(default=None, description='e.g. ["markdown"]')
    max_chars: Optional[int] = Field(default=None, gt=0, description="Cut page text to at most this many characters (max 50000)")
    include_links: Optional[bool] = Field(default=None, description="Return the page's links (default true on the direct API); false saves tokens")
    render_fallback: Optional[bool] = Field(default=None, description="If extract returns thin content, retry with render (extra paid call: $0.010 direct, $0.005 via Pocket)")


class RenderInput(_UrlInput):
    url: str = Field(default="", description="Full public http(s) URL to render")
    formats: Optional[list[Literal["markdown", "text", "html", "links"]]] = None
    max_chars: Optional[int] = Field(default=None, gt=0)
    screenshot: Optional[bool] = None
    wait_until: Optional[Literal["domcontentloaded", "load", "networkidle"]] = None
    wait_for_selector: Optional[str] = None
    wait_ms: Optional[int] = Field(default=None, ge=0)


class _SARBase(BaseModel):
    query: str = Field(default="", description="Search query (non-empty)")
    num_results: Optional[int] = Field(default=None, description="How many top results to read, default 3, max 5")
    max_chars: Optional[int] = Field(default=None, gt=0, le=20000, description="Max characters of page text per result, default 8000, max 20000")
    render_fallback: Optional[bool] = Field(default=None, description="If extract is thin, render at most one page in the same $0.009 call")

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: Any) -> Any:
        data = _alias(data, "query", ("q", "input", "search_query"))
        return _alias(data, "num_results", ("max_results", "k", "limit"))


class ScreenshotViewport(BaseModel):
    width: int = Field(ge=320, le=1920)
    height: int = Field(ge=320, le=1920)


class ScreenshotInput(_UrlInput):
    url: str = Field(default="", description="Full public http(s) URL to capture")
    format: Optional[Literal["png", "jpeg"]] = Field(default=None, description="Image format, default png")
    full_page: Optional[bool] = Field(default=None, description="Capture the whole page (clipped at 4000 px tall) instead of the viewport")
    viewport: Optional[ScreenshotViewport] = Field(default=None, description="Viewport in CSS pixels, e.g. 390x844 for mobile; default 1280x800")


class SearchInput(_Filters, _SearchBase):
    """query and max_results come first (a plain string input maps to query); filters follow."""


class SearchAndReadInput(_Filters, _SARBase):
    pass


class NewsInput(SearchInput):
    max_results: Optional[int] = Field(default=None, description="1-10, default 5")


def _err(e: Exception) -> str:
    return f"Error: {e}"


__all__ = ["AgentSearchTool", "AgentSearchExtractTool", "AgentSearchRenderTool", "AgentSearchSearchAndReadTool",
           "AgentSearchNewsTool", "AgentSearchScreenshotTool", "InvalidInput"]


class AgentSearchTool(BaseTool):
    """Live web search. Free by default (up to 25/day per IP). Paid search (no daily cap) is opt-in:
    mode="paid", or mode="auto" with AGENTSEARCH_MODE=paid. A wallet key alone does not make search paid."""

    name: str = "agentsearch_search"
    description: str = "Live web search. Returns up to 5 ranked results (title, url, content). Use for current facts or finding URLs. Free by default (no key); paid mode is $0.008 per search and also honors freshness/date range, country, language and include/exclude domain filters. For recent news use agentsearch_news_search."
    args_schema: Type[BaseModel] = SearchInput
    mode: Literal["auto", "free", "paid"] = "auto"
    handle_validation_error: Any = _on_validation_error

    def _run(self, query: str = "", max_results: Optional[int] = None, run_manager: Any = None, **kw: Any) -> str:
        try:
            query = check_query(query)
            max_results = check_count(max_results, "max_results")
            if c.resolve_search_mode(self.mode) == "paid":
                body: dict[str, Any] = {"query": query, **_filters(kw)}
                if max_results:
                    body["max_results"] = max_results
                return c.dumps(c.call_portal("search", body))
            return c.dumps(c.free_search(query, max_results))
        except Exception as e:
            return _err(e)


class _PaidTool(BaseTool):
    op: str = ""
    handle_validation_error: Any = _on_validation_error

    def _run(self, run_manager: Any = None, **kwargs: Any) -> str:
        try:
            kwargs["url"] = check_url(kwargs.get("url"))
            fb = kwargs.pop("render_fallback", None)
            body = {k: v for k, v in kwargs.items() if v is not None}
            if not c.has_wallet_key():
                if not c.free_trial_enabled():
                    raise c.AgentSearchError(c.paid_only_message(self.name))
                try:
                    if self.op == "extract":
                        return c.dumps(c.free_extract_with_fallback(body, fb))
                    return c.dumps(c.free_trial(self.op, body))
                except c.FreeTrialUnavailable:
                    raise c.AgentSearchError(c.paid_only_message(self.name))
            if self.op == "extract":
                return c.dumps(c.extract_with_fallback(body, fb))
            return c.dumps(c.call_portal(self.op, body))
        except Exception as e:
            return _err(e)


class AgentSearchExtractTool(_PaidTool):
    name: str = "agentsearch_extract"
    description: str = "Fetch a URL and return its main content as clean text/markdown. Fast and best for articles, docs and static pages. If the result is empty or thin (JavaScript-heavy page, SPA, app shell), call agentsearch_render on the same URL, or pass render_fallback=true to do that automatically (a second paid call, $0.010). No wallet: free trial, 5 calls/day per IP. With a wallet: $0.004 per call (USDC on Base via x402 to AgentSearch's API)."
    args_schema: Type[BaseModel] = ExtractInput
    op: str = "extract"


class AgentSearchRenderTool(_PaidTool):
    name: str = "agentsearch_render"
    description: str = "Render a page in a real headless browser and return markdown/text/html/links. Use when agentsearch_extract returns empty or thin content, or for JavaScript-heavy pages (SPAs, dashboards, content loaded by scripts). No wallet: free trial, 3 calls/day per IP (no screenshots). With a wallet: $0.010 per call (USDC on Base via x402 to AgentSearch's API)."
    args_schema: Type[BaseModel] = RenderInput
    op: str = "render"


class AgentSearchSearchAndReadTool(BaseTool):
    """Search the live web and read the top pages in one paid call on AgentSearch's direct x402 API ($0.009 when at least one page returns text). Direct only — not on Pocket, not on the free relay."""

    name: str = "agentsearch_search_and_read"
    description: str = (
        "Search the live web and return the top results with each page's main text in one paid call ($0.009 USDC on Base, charged only when at least one page returns text). "
        "Cheaper than a $0.008 search plus three $0.004 extracts ($0.020) and one payment instead of four. Default 3 results (max 5), default 8000 characters per page (max 20000). "
        "Pass render_fallback=true to render at most one thin page in the same call. Direct x402 only — not available on Pocket or the free relay. Search itself stays free by default."
    )
    args_schema: Type[BaseModel] = SearchAndReadInput
    handle_validation_error: Any = _on_validation_error

    def _run(self, query: str = "", num_results: Optional[int] = None, max_chars: Optional[int] = None,
             render_fallback: Optional[bool] = None, run_manager: Any = None, **kw: Any) -> str:
        try:
            query = check_query(query)
            num_results = check_count(num_results, "num_results")
            body: dict[str, Any] = {"query": query, **_filters(kw)}
            if num_results is not None:
                body["num_results"] = num_results
            if max_chars is not None:
                body["max_chars"] = max_chars
            if render_fallback is not None:
                body["render_fallback"] = render_fallback
            return c.dumps(c.call_portal("search_and_read", body))
        except Exception as e:
            return _err(e)


class AgentSearchNewsTool(BaseTool):
    """Recent news articles in one paid call on AgentSearch's direct x402 API ($0.008; no results, no charge). Direct only."""

    name: str = "agentsearch_news_search"
    description: str = (
        "Search recent news articles and return title, URL, snippet, source domain and publish date for each (1-10, default 5). "
        "Use for current events, company or product news, and anything where recency matters; optional freshness (day/week/month/year) "
        "or date_from/date_to, country, language, include/exclude domains. To read an article in full, pass its URL to agentsearch_extract. "
        "Paid: $0.008 per call (USDC on Base via x402 to AgentSearch's own API; calls with no results are not charged). Needs a wallet; not on Pocket or the free relay."
    )
    args_schema: Type[BaseModel] = NewsInput
    handle_validation_error: Any = _on_validation_error

    def _run(self, query: str = "", max_results: Optional[int] = None, run_manager: Any = None, **kw: Any) -> str:
        try:
            query = check_query(query)
            max_results = check_count(max_results, "max_results", hi=10)
            body: dict[str, Any] = {"query": query, **_filters(kw)}
            if max_results is not None:
                body["max_results"] = max_results
            return c.dumps(c.call_portal("news", body))
        except Exception as e:
            return _err(e)


class AgentSearchScreenshotTool(BaseTool):
    """Website screenshot in one paid call on AgentSearch's direct x402 API ($0.010). Direct only.

    Returns (content, artifact): the content string the model sees has the image metadata but not the base64
    bytes (to save tokens); the artifact is the full result including ``screenshot.base64``."""

    name: str = "agentsearch_screenshot"
    description: str = (
        "Load a public URL in a real headless browser and capture a PNG or JPEG screenshot of the viewport or the full page "
        "(up to 4000 px tall), plus title, final URL and HTTP status. Use for visual checks, layout or UI questions, and pages "
        "where the look matters; for page text use agentsearch_extract. Set viewport (e.g. 390x844) for mobile. "
        "Paid: $0.010 per call (USDC on Base via x402 to AgentSearch's own API). Needs a wallet; not on Pocket or the free relay. "
        "The image bytes go to the tool artifact, not into this text."
    )
    args_schema: Type[BaseModel] = ScreenshotInput
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"
    handle_validation_error: Any = _on_validation_error

    def _run(self, url: str = "", format: Optional[str] = None, full_page: Optional[bool] = None,
             viewport: Any = None, run_manager: Any = None) -> Any:
        try:
            body: dict[str, Any] = {"url": check_url(url)}
            if format is not None:
                body["format"] = format
            if full_page is not None:
                body["full_page"] = full_page
            if viewport is not None:
                body["viewport"] = viewport.model_dump() if hasattr(viewport, "model_dump") else dict(viewport)
            out = c.call_portal("screenshot", body)
        except Exception as e:
            return _err(e), None
        shown = dict(out)
        shot = shown.get("screenshot")
        if isinstance(shot, dict) and "base64" in shot:
            shown["screenshot"] = {**{k: v for k, v in shot.items() if k != "base64"}, "base64": "(omitted from text; see the tool artifact)"}
        return c.dumps(shown), out
