"""Key storage, precedence, masking and request hardening."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from northstar.config import ConfigError, ConfigStore

from .conftest import FAKE_AID_KEY, FAKE_OPENAI_KEY, HOST, Client

POSIX = os.name == "posix"


def test_save_persists_and_restricts_permissions(store, data_dir):
    store.save({"OPENAI_API_KEY": FAKE_OPENAI_KEY})
    path = data_dir / "settings.json"
    assert json.loads(path.read_text())["OPENAI_API_KEY"] == FAKE_OPENAI_KEY
    if POSIX:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # Persists across "restart" (a new store instance).
    assert ConfigStore(data_dir, env={}).snapshot().openai_api_key == FAKE_OPENAI_KEY


def test_blank_preserves_and_nonblank_replaces(store):
    store.save({"OPENAI_API_KEY": FAKE_OPENAI_KEY, "RETAIL_AI_DEFENSE_API_KEY": FAKE_AID_KEY})
    store.save({"OPENAI_API_KEY": "", "RETAIL_AI_DEFENSE_API_KEY": "   "})
    snap = store.snapshot()
    assert snap.openai_api_key == FAKE_OPENAI_KEY and snap.ai_defense_api_key == FAKE_AID_KEY
    store.save({"OPENAI_API_KEY": "sk-replacement-key-123456"})
    snap = store.snapshot()
    assert snap.openai_api_key == "sk-replacement-key-123456" and snap.ai_defense_api_key == FAKE_AID_KEY


def test_unrelated_settings_preserved(store, data_dir):
    data_dir.mkdir(parents=True)
    (data_dir / "settings.json").write_text(json.dumps({"CUSTOM_NOTE": "keep me", "OPENAI_MODEL": "gpt-x"}))
    store.save({"AI_DEFENSE_REGION": "eu"})
    saved = json.loads((data_dir / "settings.json").read_text())
    assert saved == {"CUSTOM_NOTE": "keep me", "OPENAI_MODEL": "gpt-x", "AI_DEFENSE_REGION": "eu"}


def test_atomic_write_leaves_no_temp_files(store, data_dir):
    for i in range(5):
        store.save({"OPENAI_MODEL": f"model-{i}"})
    assert sorted(p.name for p in data_dir.iterdir()) == ["settings.json"]


def test_corrupt_file_is_not_overwritten(store, data_dir):
    data_dir.mkdir(parents=True)
    (data_dir / "settings.json").write_text("{not json")
    with pytest.raises(ConfigError):
        store.save({"OPENAI_API_KEY": FAKE_OPENAI_KEY})
    assert (data_dir / "settings.json").read_text() == "{not json"


def test_precedence_saved_over_env_over_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_MODEL=from-dotenv\nAI_DEFENSE_REGION=ap\nOPENAI_API_KEY=\n")
    s = ConfigStore(tmp_path / "d", env={"OPENAI_MODEL": "from-env"}, dotenv_path=dotenv)
    assert s.snapshot().openai_model == "from-env"
    assert s.snapshot().region == "ap"
    s.save({"OPENAI_MODEL": "from-ui"})
    # Restart with the same inherited environment: the UI value still wins.
    s2 = ConfigStore(tmp_path / "d", env={"OPENAI_MODEL": "from-env"}, dotenv_path=dotenv)
    assert s2.snapshot().openai_model == "from-ui"
    assert s2.public_view()["openai_key_source"] is None


def test_env_key_used_when_nothing_saved(tmp_path):
    s = ConfigStore(tmp_path / "d", env={"OPENAI_API_KEY": FAKE_OPENAI_KEY})
    assert s.snapshot().openai_configured
    assert s.public_view()["openai_key_source"] == "environment"


@pytest.mark.parametrize(
    "value",
    ["sk-abc\ndef-123456", "sk-abc\x00def-12345", "sk-" + "a" * 600, "abc12", "sk with spaces 12345"],
)
def test_malformed_keys_rejected(store, value):
    with pytest.raises(ConfigError) as exc:
        store.save({"OPENAI_API_KEY": value})
    assert value not in str(exc.value)
    assert not store.snapshot().openai_configured


def test_unknown_region_and_model_rejected(store):
    with pytest.raises(ConfigError):
        store.save({"AI_DEFENSE_REGION": "https://evil.example"})
    with pytest.raises(ConfigError):
        store.save({"OPENAI_MODEL": "gpt 4\nx"})


def test_snapshot_repr_hides_keys(store):
    store.save({"OPENAI_API_KEY": FAKE_OPENAI_KEY})
    assert FAKE_OPENAI_KEY not in repr(store.snapshot())


# ---------------------------------------------------------------- API layer

def test_config_api_returns_booleans_only(configured):
    resp = configured.get("/api/config")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert FAKE_OPENAI_KEY not in body and FAKE_AID_KEY not in body
    assert FAKE_OPENAI_KEY[:8] not in body and FAKE_OPENAI_KEY[-4:] not in body
    cfg = resp.get_json()["config"]
    assert cfg["openai_configured"] is True and cfg["ai_defense_configured"] is True
    assert "no-store" in resp.headers["Cache-Control"]


def test_config_save_api_blank_preserves(configured, store):
    resp = configured.post("/api/config", {"openai_api_key": "", "ai_defense_api_key": "",
                                           "openai_model": "gpt-6-luna", "ai_defense_region": "eu",
                                           "ai_defense_connection_name": "Northstar demo"})
    assert resp.status_code == 200
    assert FAKE_OPENAI_KEY not in resp.get_data(as_text=True)
    snap = store.snapshot()
    assert snap.openai_api_key == FAKE_OPENAI_KEY and snap.region == "eu"


def test_config_save_rejects_bad_payloads(configured):
    assert configured.post("/api/config", {"openai_api_key": 123}).status_code == 400
    assert configured.post("/api/config", {"unexpected": "x"}).status_code == 400
    assert configured.post("/api/config", {"openai_api_key": "sk-a\nb-123456789"}).status_code == 400
    assert configured.post("/api/config", ["list"]).status_code == 400


def test_page_never_contains_keys(configured):
    page = configured.http.get("/", headers={"Host": HOST}).get_data(as_text=True)
    assert FAKE_OPENAI_KEY not in page and FAKE_AID_KEY not in page


def test_verify_uses_typed_key_without_saving(client, store, fakes):
    oa, aid = fakes
    resp = client.post("/api/verify/openai", {"api_key": "sk-typed-key-1234567", "model": "gpt-6-luna"})
    assert resp.status_code == 200 and resp.get_json()["result"]["ok"] is True
    assert oa.verify_calls == [("sk-typed-key-1234567", "gpt-6-luna")]
    assert not store.snapshot().openai_configured  # verification does not save


def test_verify_falls_back_to_saved_key(configured, fakes):
    oa, aid = fakes
    configured.post("/api/verify/ai-defense", {"api_key": "", "region": "eu"})
    assert aid.verify_calls == [(FAKE_AID_KEY, "https://eu.api.inspect.aidefense.security.cisco.com")]


def test_verify_without_any_key(client, fakes):
    resp = client.post("/api/verify/openai", {"api_key": ""})
    assert resp.get_json()["result"]["outcome"] == "not_configured"
    assert fakes[0].verify_calls == []


def test_verify_rejects_arbitrary_region(configured, fakes):
    resp = configured.post("/api/verify/ai-defense", {"api_key": "", "region": "attacker.example"})
    assert resp.status_code == 400 and fakes[1].verify_calls == []


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Origin": "http://evil.example"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Sec-Fetch-Site": "same-site"}, 403),
        ({"X-CSRF-Token": "wrong"}, 403),
        ({"Host": "evil.example:5065"}, 400),
        ({"Host": "rebind.attacker.com"}, 400),
    ],
)
def test_cross_origin_and_csrf_rejected(configured, headers, expected):
    for method in ("get", "post"):
        if method == "get":
            resp = configured.get("/api/config", **headers)
        else:
            resp = configured.post("/api/config", {"openai_model": "x-model"}, **headers)
        assert resp.status_code == expected
        assert "Access-Control-Allow-Origin" not in resp.headers
        assert FAKE_OPENAI_KEY not in resp.get_data(as_text=True)


def test_missing_csrf_header_rejected(configured):
    resp = configured.http.get("/api/config", headers={"Host": HOST})
    assert resp.status_code == 403


def test_preflight_refused(configured):
    resp = configured.http.options("/api/config", headers={"Host": HOST, "Origin": "http://evil.example",
                                                           "Access-Control-Request-Method": "POST"})
    assert resp.status_code == 403 and "Access-Control-Allow-Origin" not in resp.headers


def test_non_json_rejected(configured):
    resp = configured.http.post("/api/compare", data="question=hi", headers={**configured.headers(),
                                                                             "Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 415


def test_oversized_request_rejected(configured):
    resp = configured.post("/api/compare", {"question": "x" * 40000})
    assert resp.status_code == 413


def test_localhost_names_any_port_allowed(app):
    c = app.test_client()
    for host in ("localhost:8080", "127.0.0.1", "[::1]:5065"):
        assert c.get("/healthz", headers={"Host": host}).status_code == 200


def test_security_headers(client):
    resp = client.http.get("/", headers={"Host": HOST})
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_errors_do_not_leak_details(configured, fakes, monkeypatch):
    oa, aid = fakes

    def boom(*a, **k):
        raise RuntimeError("internal detail " + FAKE_OPENAI_KEY)

    monkeypatch.setattr(oa, "generate", boom)
    resp = configured.post("/api/compare", {"question": "hello"})
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert FAKE_OPENAI_KEY not in body and "internal detail" not in body
