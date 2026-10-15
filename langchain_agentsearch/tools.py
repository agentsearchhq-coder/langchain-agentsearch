from __future__ import annotations

from typing import Any, Literal, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from . import _client as c


class SearchInput(BaseModel):
    query: str = Field(description="Search query", min_length=1)
    max_results: Optional[int] = Field(default=None, ge=1, le=5, description="1-5, default 5")


class ExtractInput(BaseModel):
    url: str = Field(description="http(s) URL to extract")
    formats: Optional[list[str]] = Field(default=None, description='e.g. ["markdown"]')
    max_chars: Optional[int] = Field(default=None, gt=0)


class RenderInput(BaseModel):
    url: str = Field(description="http(s) URL to render")
    formats: Optional[list[Literal["markdown", "text", "html", "links"]]] = None
    max_chars: Optional[int] = Field(default=None, gt=0)
    screenshot: Optional[bool] = None
    wait_until: Optional[Literal["domcontentloaded", "load", "networkidle"]] = None
    wait_for_selector: Optional[str] = None
    wait_ms: Optional[int] = Field(default=None, ge=0)


def _err(e: Exception) -> str:
    return f"Error: {e}"


class AgentSearchTool(BaseTool):
    """Live web search. Free by default (25/day per user); paid & unlimited when a wallet key is set."""

    name: str = "agentsearch_search"
    description: str = "Live web search. Returns up to 5 ranked results (title, url, content). Use for current facts or finding URLs."
    args_schema: Type[BaseModel] = SearchInput
    mode: Literal["auto", "free", "paid"] = "auto"

    def _run(self, query: str, max_results: Optional[int] = None, run_manager: Any = None) -> str:
        try:
            paid = self.mode == "paid" or (self.mode == "auto" and c.has_wallet_key())
            if paid:
                body: dict[str, Any] = {"query": query}
                if max_results:
                    body["max_results"] = max_results
                return c.dumps(c.call_portal("search", body))
            return c.dumps(c.free_search(query, max_results))
        except Exception as e:
            return _err(e)


class _PaidTool(BaseTool):
    op: str = ""

    def _run(self, run_manager: Any = None, **kwargs: Any) -> str:
        try:
            if not c.has_wallet_key():
                raise c.AgentSearchError(c.paid_only_message(self.name))
            body = {k: v for k, v in kwargs.items() if v is not None}
            return c.dumps(c.call_portal(self.op, body))
        except Exception as e:
            return _err(e)


class AgentSearchExtractTool(_PaidTool):
    name: str = "agentsearch_extract"
    description: str = "Fetch a URL and return its main content as clean text/markdown. Paid: $0.005 per call (needs a wallet)."
    args_schema: Type[BaseModel] = ExtractInput
    op: str = "extract"


class AgentSearchRenderTool(_PaidTool):
    name: str = "agentsearch_render"
    description: str = "Render a JavaScript-heavy page in a headless browser and return markdown/text/html/links. Paid: $0.005 per call (needs a wallet)."
    args_schema: Type[BaseModel] = RenderInput
    op: str = "render"
