"""Client-side input checks (0.6.1). Bad input returns an "Error: ..." string before any HTTP request,
so it never counts against the free relay's per-IP limits and nothing is signed."""
from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from typing import Any, Optional
from urllib.parse import urlsplit

MAX_QUERY_CHARS = 400
MIN_QUERY_CHARS = 2
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet", ".localdomain", ".home.arpa")


class InvalidInput(ValueError):
    """Raised for input rejected before any network call."""


_QUERY_KEYS = ("query", "q", "input", "search_query", "text", "value")
_COUNT_KEYS = ("max_results", "num_results", "k", "limit", "count", "value")


def _unwrap(v: Any, keys: tuple) -> Any:
    """Unwrap a tool-input dict ({"query": "x", "max_results": 3}) passed where a scalar was expected.
    Returns the first matching key's value (recursively), or None when the dict has none of the keys
    (for example a LangChain RunnableConfig passed as a 2nd positional argument)."""
    for _ in range(4):
        if isinstance(v, (list, tuple)):
            v = next((x for x in v if isinstance(x, (str, int, float, dict)) and not isinstance(x, bool)), None)
            continue
        if isinstance(v, Mapping):
            for k in keys:
                if v.get(k) is not None:
                    v = v[k]
                    break
            else:
                return None
            continue
        return v
    return None if isinstance(v, (Mapping, list, tuple)) else v


def coerce_max_results(value: Any, lo: int = 1, hi: int = 5) -> Optional[int]:
    """Never raises. None for anything unusable (the server default), otherwise an int clamped to lo..hi.
    Accepts ints, floats, numeric strings and tool-input dicts such as {"max_results": 3}."""
    v = _unwrap(value, _COUNT_KEYS)
    if v is None or isinstance(v, bool) or isinstance(v, (Mapping, list, tuple)):
        return None
    try:
        n = int(float(v.strip())) if isinstance(v, str) else int(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(lo, min(hi, n))


def check_query(query: Any) -> str:
    """Coerce to a non-empty search string or raise InvalidInput (nothing is sent or charged).
    Unwraps tool-input dicts like {"query": "x"}; ints/floats are stringified."""
    v = _unwrap(query, _QUERY_KEYS)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        v = str(v)
    if not isinstance(v, str):
        raise InvalidInput("query is required: pass a non-empty search string, e.g. {\"query\": \"latest LangChain release\"}. Nothing was sent or charged.")
    q = v.strip()
    if not q:
        raise InvalidInput("query is empty or whitespace-only: pass a non-empty search string. Nothing was sent or charged.")
    if len(q) < MIN_QUERY_CHARS:
        raise InvalidInput(f"query {q!r} is too short (minimum {MIN_QUERY_CHARS} characters): rewrite it as a real search query, e.g. a few keywords. Don't retry it unchanged. Nothing was sent or charged.")
    if len(q) > MAX_QUERY_CHARS:
        raise InvalidInput(f"query is {len(q)} characters; keep it under {MAX_QUERY_CHARS} (a short keyword query works best). Nothing was sent or charged.")
    return q


def check_count(value: Any, name: str, lo: int = 1, hi: int = 5) -> Optional[int]:
    """None/empty/unusable dict -> None (server default). Tool-input dicts and numeric strings are unwrapped;
    numbers outside lo..hi are clamped; a non-numeric string raises InvalidInput."""
    v = _unwrap(value, _COUNT_KEYS)
    if v is None or v == "" or isinstance(v, (bool, Mapping, list, tuple)):
        return None
    try:
        n = int(float(v.strip())) if isinstance(v, str) else int(v)
    except (TypeError, ValueError, OverflowError):
        raise InvalidInput(f"{name} must be a whole number from {lo} to {hi} (or omitted for the default). Nothing was sent or charged.")
    return max(lo, min(hi, n))


def _private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


def check_url(url: Any) -> str:
    if url is None or not isinstance(url, str) or not url.strip():
        raise InvalidInput("url is required: pass a full http(s) URL, e.g. https://example.com/page. Nothing was sent or charged.")
    u = url.strip()
    if any(ch.isspace() for ch in u):
        raise InvalidInput("url contains spaces; pass a single full http(s) URL. Nothing was sent or charged.")
    try:
        parts = urlsplit(u)
        host = (parts.hostname or "").lower().rstrip(".")
        _ = parts.port  # raises on a bad port
    except ValueError:
        raise InvalidInput(f"url is not a valid URL: {u[:200]}. Nothing was sent or charged.")
    if parts.scheme.lower() not in ("http", "https"):
        hint = f" Did you mean https://{u}?" if not parts.scheme or "://" not in u else ""
        raise InvalidInput(f"url must start with http:// or https:// (got {u[:200]}).{hint} Nothing was sent or charged.")
    if parts.username is not None or parts.password is not None:
        raise InvalidInput("url must not contain a username or password. Nothing was sent or charged.")
    if not host:
        raise InvalidInput(f"url has no host: {u[:200]}. Nothing was sent or charged.")
    is_ip = False
    try:
        ipaddress.ip_address(host.strip("[]"))
        is_ip = True
    except ValueError:
        pass
    if is_ip and _private_ip(host):
        raise InvalidInput("url points at a private, loopback or reserved IP address; only public web pages can be read. Nothing was sent or charged.")
    if not is_ip and (host == "localhost" or host.endswith(_BLOCKED_SUFFIXES) or "." not in host):
        raise InvalidInput(f"url host '{host}' is not a public internet hostname; only public web pages can be read. Nothing was sent or charged.")
    return u
