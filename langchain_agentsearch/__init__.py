"""LangChain tools for AgentSearch."""
from importlib import metadata

from ._client import AgentSearchError, FREE_LIMIT_MESSAGE, reset_session_budget, session_spent_atomic
from .tools import (AgentSearchExtractTool, AgentSearchNewsTool, AgentSearchRenderTool, AgentSearchScreenshotTool,
                    AgentSearchSearchAndReadTool, AgentSearchTool)

try:
    __version__ = metadata.version(__package__ or "langchain_agentsearch")
except metadata.PackageNotFoundError:  # pragma: no cover
    __version__ = ""

__all__ = ["AgentSearchTool", "AgentSearchExtractTool", "AgentSearchRenderTool", "AgentSearchSearchAndReadTool", "AgentSearchNewsTool",
           "AgentSearchScreenshotTool", "AgentSearchError",
           "FREE_LIMIT_MESSAGE", "reset_session_budget", "session_spent_atomic", "__version__"]
