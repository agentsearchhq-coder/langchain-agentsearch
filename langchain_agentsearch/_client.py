"""HTTP layer: free relay search and x402 pay-per-call via the Pocket Network Agentic Portal.

The wallet key is read from env, used only to sign, and never logged or returned.
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Optional

import httpx

FREE_RELAY_URL = "https://relay.agentsearchhq.com"
FREE_RELAY_DAILY_LIMIT = 25
DEFAULT_PORTAL_URL = "https://agent.pocket.network"
BASE_NETWORK = "eip155:8453"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
PORTAL_PAYEE = "0xF732ea490c5766071785a2310523f7fA2CEbB829"
MAX_PER_CALL_ATOMIC = 5000  # $0.005 hard ceiling
DEFAULT_SESSION_CAP_ATOMIC = 1_000_000  # $1.00
KEY_ENV_VARS = ("AGENTSEARCH_WALLET_PRIVATE_KEY", "POCKET_PRIVATE_KEY")
SERVICES = {
    "search": ("agentsearch-web-search-v1", "/v1/search"),
    "extract": ("agentsearch-web-extract-v1", "/v1/extract"),
    "render": ("agentsearch-web-render-v1", "/v1/render"),
}
PACKAGE_NAME = "langchain-agentsearch"
# Extract output shorter than this (characters of text) counts as "thin": usually a JS-heavy page.
THIN_CHARS = 200
DOCS = "https://agentsearchhq.com/?utm_source=langchain-agentsearch&utm_medium=package"

FREE_LIMIT_MESSAGE = (
    f"Free search limit reached ({FREE_RELAY_DAILY_LIMIT} searches per day per user; resets daily). "
    "For unlimited search plus extract/render, set AGENTSEARCH_WALLET_PRIVATE_KEY to the key of a NEW wallet "
    "funded with a little USDC on Base ($0.005 per call via x402, capped by AGENTSEARCH_MAX_TOTAL_ATOMIC, "
    f"default $1.00) and install langchain-agentsearch[paid]. Docs: {DOCS}"
)


def paid_only_message(name: str) -> str:
    return (
        f"{name} is paid ($0.005 per call in USDC on Base via x402). No wallet is configured, so no call was made. "
        "Set AGENTSEARCH_WALLET_PRIVATE_KEY to the key of a NEW wallet funded with a little USDC on Base and "
        f"install langchain-agentsearch[paid]. Docs: {DOCS}"
    )


class AgentSearchError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _version() -> str:
    try:
        from importlib import metadata
        return metadata.version(PACKAGE_NAME)
    except Exception:
        return "0"


def client_headers() -> dict[str, str]:
    """Anonymous package tag so AgentSearch can count usage per integration (name/version only).
    Opt out with AGENTSEARCH_NO_CLIENT_TAG=1. AGENTSEARCH_SELF=1 marks our own test traffic."""
    h: dict[str, str] = {}
    if (os.environ.get("AGENTSEARCH_NO_CLIENT_TAG") or "").strip() != "1":
        h["X-Agent-Client"] = f"{PACKAGE_NAME}/{_version()}"
    if (os.environ.get("AGENTSEARCH_SELF") or "").strip() == "1":
        h["X-AgentSearch-Self"] = "1"
    return h


def timeout_s() -> float:
    try:
        n = int(os.environ.get("AGENTSEARCH_TIMEOUT_MS", ""))
        if 1000 <= n <= 300_000:
            return n / 1000
    except ValueError:
        pass
    return 30.0


def _strip_provider(d: Any) -> Any:
    if isinstance(d, dict):
        d.pop("provider", None)
    return d


def free_search(query: str, max_results: Optional[int] = None, client: Optional[httpx.Client] = None) -> Any:
    body: dict[str, Any] = {"query": query}
    if max_results is not None:
        body["max_results"] = max_results
    c = client or httpx.Client(timeout=timeout_s())
    try:
        r = c.post(f"{FREE_RELAY_URL}/v1/search", json=body, headers={"accept": "application/json", **client_headers()})
    finally:
        if client is None:
            c.close()
    if r.status_code == 429:
        raise AgentSearchError(FREE_LIMIT_MESSAGE, 429)
    if r.status_code >= 400:
        raise AgentSearchError(f"AgentSearch relay HTTP {r.status_code}: {r.text[:500]}", r.status_code)
    try:
        return _strip_provider(r.json())
    except ValueError:
        return {"raw": r.text}


# ---------- paid mode ----------

def has_wallet_key() -> bool:
    return any((os.environ.get(n) or "").strip() for n in KEY_ENV_VARS)


def _read_wallet_key() -> Optional[str]:
    for name in KEY_ENV_VARS:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        if not re.fullmatch(r"(0x)?[0-9a-fA-F]{64}", raw):
            raise AgentSearchError(
                f"{name} is set but is not a private key (expected 64 hex characters, optional 0x prefix). "
                "The value is not shown. Nothing was signed."
            )
        return raw if raw.startswith("0x") else "0x" + raw
    return None


def _atomic_env(names: tuple[str, ...], fallback: int) -> int:
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            continue
        if not raw.isdigit():
            raise AgentSearchError(f"{name} must be a whole number of USDC atomic units (1000000 = $1.00). Nothing was signed.")
        return int(raw)
    return fallback


def usd(atomic: int) -> str:
    return f"${atomic // 1_000_000}.{atomic % 1_000_000:06d}"


class _Budget:
    def __init__(self) -> None:
        self.spent = 0
        self.lock = threading.Lock()


_budget = _Budget()


def reset_session_budget() -> None:
    global _budget
    _budget = _Budget()


def session_spent_atomic() -> int:
    return _budget.spent


def _eq(a: Any, b: str) -> bool:
    return isinstance(a, str) and a.lower() == b.lower()


def select_accept(accepts: list[Any], ceiling: int) -> Any:
    why = []
    for a in accepts or []:
        if a.scheme != "exact":
            why.append(f"{a.scheme} scheme"); continue
        if a.network != BASE_NETWORK:
            why.append(f"network {a.network}"); continue
        if not _eq(a.asset, USDC_BASE):
            why.append(f"asset {a.asset} is not USDC on Base"); continue
        if not _eq(a.pay_to, PORTAL_PAYEE):
            why.append(f"payee {a.pay_to} is not the portal's"); continue
        if not str(a.amount).isdigit() or int(a.amount) <= 0:
            why.append(f"amount {a.amount}"); continue
        if int(a.amount) > ceiling:
            why.append(f"amount {a.amount} exceeds the cap of {ceiling} atomic units"); continue
        return a
    raise AgentSearchError(f"No acceptable payment option ({'; '.join(why) or 'none offered'}). Nothing was signed.")


def call_portal(op: str, body: dict[str, Any], client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Unpaid POST -> 402 -> limits checked -> sign (x402 SDK) -> retry once with PAYMENT-SIGNATURE."""
    try:
        from eth_account import Account
        from x402 import x402ClientSync
        from x402.http import x402HTTPClientSync
        from x402.mechanisms.evm.exact import register_exact_evm_client
    except ImportError as e:  # pragma: no cover
        raise AgentSearchError(
            "Paid calls need the x402 SDK: pip install 'langchain-agentsearch[paid]'. Nothing was signed."
        ) from e

    key = _read_wallet_key()
    if not key:
        raise AgentSearchError(paid_only_message(f"agentsearch_{op}"))
    portal = (os.environ.get("AGENTSEARCH_PORTAL_URL") or DEFAULT_PORTAL_URL).strip().rstrip("/")
    if not portal.startswith("https://") and not re.match(r"http://(localhost|127\.)", portal):
        raise AgentSearchError("AGENTSEARCH_PORTAL_URL must be https://. Nothing was signed.")
    session_cap = _atomic_env(("AGENTSEARCH_MAX_TOTAL_ATOMIC", "POCKET_MAX_TOTAL_ATOMIC"), DEFAULT_SESSION_CAP_ATOMIC)
    per_call = min(_atomic_env(("AGENTSEARCH_MAX_PER_CALL_ATOMIC", "POCKET_MAX_PER_CALL_ATOMIC"), MAX_PER_CALL_ATOMIC), MAX_PER_CALL_ATOMIC)
    service_id, path = SERVICES[op]
    url = f"{portal}/v1/{service_id}{path}"

    c = client or httpx.Client(timeout=timeout_s())
    try:
        unpaid = c.post(url, json=body, headers=client_headers())
        if unpaid.status_code != 402:
            raise AgentSearchError(f"Expected 402 from the portal, got {unpaid.status_code}: {unpaid.text[:300]}. Nothing was signed.", unpaid.status_code)
        http = x402HTTPClientSync(x402ClientSync())
        try:
            required = http.get_payment_required_response(lambda n: unpaid.headers.get(n), unpaid.content)
        except Exception as e:
            raise AgentSearchError(f"The portal's 402 is not valid x402 v2 ({e}). Nothing was signed.")
        if getattr(required, "x402_version", None) != 2:
            raise AgentSearchError("Unsupported x402 version. Nothing was signed.")
        res_url = (getattr(getattr(required, "resource", None), "url", "") or "").rstrip("/")
        if not res_url.endswith(f"/v1/{service_id}"):
            raise AgentSearchError(f"The 402 is for resource {res_url}, not {service_id}. Nothing was signed.")

        with _budget.lock:
            remaining = max(session_cap - _budget.spent, 0)
            ceiling = min(per_call, remaining)
            if ceiling <= 0:
                raise AgentSearchError(
                    f"Session spend cap reached: {usd(_budget.spent)} of {usd(session_cap)} signed. "
                    "Raise AGENTSEARCH_MAX_TOTAL_ATOMIC to spend more. Nothing was signed."
                )
            chosen = select_accept(list(required.accepts), ceiling)
            amount = int(chosen.amount)

            def selector(_v: int, options: list[Any]) -> Any:
                for o in options:
                    if o.scheme == chosen.scheme and o.network == chosen.network and _eq(o.asset, chosen.asset) and _eq(o.pay_to, chosen.pay_to) and str(o.amount) == str(chosen.amount):
                        return o
                raise AgentSearchError("Selected option disappeared. Nothing was signed.")

            account = Account.from_key(key)
            signer_client = register_exact_evm_client(x402ClientSync(selector), account, networks=BASE_NETWORK)
            payer = x402HTTPClientSync(signer_client)
            signed = payer.create_payment_payload(required)
            auth = (signed.payload or {}).get("authorization") or {}
            if not _eq(auth.get("to"), PORTAL_PAYEE) or int(auth.get("value", 0)) != amount:
                raise AgentSearchError("The signed authorization does not match the approved terms; it was discarded and not sent.")
            _budget.spent += amount  # counted at signing

        try:
            paid = c.post(url, json=body, headers={**client_headers(), **payer.encode_payment_signature_header(signed)})
        except Exception as e:
            raise AgentSearchError(f"A payment of {usd(amount)} was signed but the paid request failed ({e}). Check the wallet before retrying.")
        if not 200 <= paid.status_code < 300:
            raise AgentSearchError(
                f"The portal answered {paid.status_code}: {paid.text[:300]}. Non-2xx answers are not settled; "
                f"the signed {usd(amount)} still counts against this session's cap.", paid.status_code)
        receipt = None
        try:
            receipt = payer.get_payment_settle_response(lambda n: paid.headers.get(n))
        except Exception:
            pass
        tx = getattr(receipt, "transaction", None) if receipt else None
        payment = {
            "amountAtomic": str(amount), "amountUsd": usd(amount), "asset": "USDC", "network": BASE_NETWORK,
            "payTo": PORTAL_PAYEE, "payer": account.address, "serviceId": service_id,
            "settled": bool(getattr(receipt, "success", False)), "transaction": tx,
        }
        if tx:
            payment["explorer"] = f"https://basescan.org/tx/{tx}"
        try:
            env = paid.json()
        except ValueError:
            env = {"raw": paid.text}
        data = env.get("data", env) if isinstance(env, dict) else env
        out = _strip_provider(data) if isinstance(data, dict) else {"data": data}
        return {**out, "payment": payment}
    finally:
        if client is None:
            c.close()


def _text_len(v: Any) -> int:
    """Characters of page text in an extract/render result (markdown/text/content fields, any depth)."""
    if isinstance(v, dict):
        return sum(len(x) if k in ("markdown", "text", "content") and isinstance(x, str) else _text_len(x)
                   for k, x in v.items() if k != "payment")
    if isinstance(v, list):
        return sum(_text_len(x) for x in v)
    return 0


def fallback_enabled(flag: Optional[bool]) -> bool:
    if flag is not None:
        return bool(flag)
    return (os.environ.get("AGENTSEARCH_EXTRACT_RENDER_FALLBACK") or "").strip() == "1"


def extract_with_fallback(body: dict[str, Any], render_fallback: Optional[bool] = None,
                          client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Extract; if the result is thin (< THIN_CHARS of text) and fallback is on, render the same URL.
    Off by default because render is a second $0.005 call (still bounded by the session cap)."""
    out = call_portal("extract", body, client)
    if not fallback_enabled(render_fallback) or _text_len(out) >= THIN_CHARS:
        return out
    rbody: dict[str, Any] = {"url": body["url"]}
    if body.get("max_chars"):
        rbody["max_chars"] = body["max_chars"]
    fm = [f for f in (body.get("formats") or ["markdown"]) if f in ("markdown", "text", "html", "links")]
    rbody["formats"] = fm or ["markdown"]
    try:
        r = call_portal("render", rbody, client)
    except AgentSearchError as e:
        return {**out, "render_fallback": {"used": False, "error": str(e)}}
    return {**r, "render_fallback": {"used": True, "reason": f"extract returned under {THIN_CHARS} chars",
                                     "extract_payment": out.get("payment")}}


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)
