"""Client-side input checks (0.6.1). Bad input returns an "Error: ..." string before any HTTP request,
so it never counts against the free relay's per-IP limits and nothing is signed."""
from __future__ import annotations

import ipaddress
from typing import Any, Optional
from urllib.parse import urlsplit

MAX_QUERY_CHARS = 400
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet", ".localdomain", ".home.arpa")


class InvalidInput(ValueError):
    """Raised for input rejected before any network call."""


def check_query(query: Any) -> str:
    if query is None or not isinstance(query, str):
        raise InvalidInput("query is required: pass a non-empty search string, e.g. {\"query\": \"latest LangChain release\"}. Nothing was sent or charged.")
    q = query.strip()
    if not q:
        raise InvalidInput("query is empty or whitespace-only: pass a non-empty search string. Nothing was sent or charged.")
    if len(q) > MAX_QUERY_CHARS:
        raise InvalidInput(f"query is {len(q)} characters; keep it under {MAX_QUERY_CHARS} (a short keyword query works best). Nothing was sent or charged.")
    return q


def check_count(value: Any, name: str, lo: int = 1, hi: int = 5) -> Optional[int]:
    """None/empty -> None (server default). Numbers outside lo..hi are clamped."""
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
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
