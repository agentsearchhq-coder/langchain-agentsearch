"""Wallet-set => paid search by default; AGENTSEARCH_WALLET_FILE reuses an existing wallet (raw hex or AgentCash JSON)."""
import json
import os
import secrets

import pytest

from langchain_agentsearch import _client


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in (*_client.KEY_ENV_VARS, "AGENTSEARCH_WALLET_FILE", "AGENTSEARCH_MODE", "AGENTSEARCH_PAYMENT_ROUTE", "AGENTSEARCH_X402_DIRECT"):
        monkeypatch.delenv(k, raising=False)


def _key():
    return "0x" + secrets.token_hex(32)  # throwaway, unfunded


def test_no_wallet_is_free(monkeypatch):
    monkeypatch.setattr(_client, "paid_extra_installed", lambda: True)
    assert not _client.has_wallet_key()
    assert _client.resolve_search_mode("auto") == "free"
    assert _client.search_mode_label("free").endswith("(no wallet configured)")


def test_wallet_key_default_paid_and_free_opt_out(monkeypatch):
    monkeypatch.setattr(_client, "paid_extra_installed", lambda: True)
    monkeypatch.setenv("AGENTSEARCH_WALLET_PRIVATE_KEY", _key())
    assert _client.resolve_search_mode("auto") == "paid"
    assert _client.search_mode_label("paid").startswith("paid: x402 to AgentSearch's API, $0.003 per search")
    monkeypatch.setenv("AGENTSEARCH_MODE", "free")
    assert _client.resolve_search_mode("auto") == "free"
    monkeypatch.setenv("AGENTSEARCH_MODE", "auto")
    assert _client.resolve_search_mode("auto") == "paid"


def test_wallet_without_paid_extra_falls_back_to_free(monkeypatch):
    monkeypatch.setattr(_client, "paid_extra_installed", lambda: False)
    monkeypatch.setenv("AGENTSEARCH_WALLET_PRIVATE_KEY", _key())
    assert _client.resolve_search_mode("auto") == "free"


def test_wallet_file_hex_and_agentcash_json(monkeypatch, tmp_path):
    key = _key()
    hexfile = tmp_path / "wallet.key"
    hexfile.write_text(key[2:] + "\n")
    monkeypatch.setenv("AGENTSEARCH_WALLET_FILE", str(hexfile))
    assert _client.has_wallet_key() and _client.wallet_source() == "AGENTSEARCH_WALLET_FILE"
    assert _client._read_wallet_key() == key
    home = tmp_path / "home"
    (home / ".agentcash").mkdir(parents=True)
    (home / ".agentcash" / "wallet.json").write_text(json.dumps({"privateKey": key, "address": "0x0"}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("AGENTSEARCH_WALLET_FILE", "agentcash")
    assert _client.wallet_file_path() == os.path.join(str(home), ".agentcash", "wallet.json")
    assert _client._read_wallet_key() == key
    monkeypatch.setattr(_client, "paid_extra_installed", lambda: True)
    assert _client.resolve_search_mode("auto") == "paid"


def test_bad_wallet_file_errors_without_leaking(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"secret": "do-not-echo-me"}))
    monkeypatch.setenv("AGENTSEARCH_WALLET_FILE", str(bad))
    with pytest.raises(_client.AgentSearchError) as e:
        _client._read_wallet_key()
    assert 'no "privateKey" field' in str(e.value) and "do-not-echo-me" not in str(e.value)
    monkeypatch.setenv("AGENTSEARCH_WALLET_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(_client.AgentSearchError, match="could not be read"):
        _client._read_wallet_key()
