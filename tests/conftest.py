"""Shared fixtures. Fake provider adapters only — no real keys, no network, no paid calls."""

from __future__ import annotations

import re
import threading
from typing import Callable, Optional

import pytest

from northstar.app import create_app
from northstar.config import ConfigStore
from northstar.providers.ai_defense import InspectionResult
from northstar.providers.errors import ProviderError
from northstar.providers.openai_adapter import GenerationResult

HOST = "127.0.0.1:5065"
FAKE_OPENAI_KEY = "sk-test-FAKEOPENAIKEY-0000000000"
FAKE_AID_KEY = "aid-test-FAKEDEFENSEKEY-000000"


class FakeOpenAI:
    """Records every generation; returns a configurable result."""

    def __init__(self, text: str = "Yes — unused items can be returned within 30 days.", **kw) -> None:
        self.text = text
        self.calls: list[dict] = []
        self.result_factory: Optional[Callable[[], GenerationResult]] = None
        self.gate: Optional[threading.Event] = None
        self.verify_calls: list[tuple] = []
        self.usage = kw.get("usage", (120, 40, 160))
        self._lock = threading.Lock()

    def generate(self, api_key, model, messages, max_output_tokens):
        with self._lock:
            self.calls.append(
                {"api_key": api_key, "model": model, "messages": [dict(m) for m in messages],
                 "max_output_tokens": max_output_tokens}
            )
        if self.gate is not None:
            self.gate.wait(5)
        if self.result_factory:
            return self.result_factory()
        i, o, t = self.usage
        return GenerationResult(ok=True, text=self.text, input_tokens=i, output_tokens=o, total_tokens=t,
                                duration_ms=321, status="completed")

    def verify(self, api_key, model):
        self.verify_calls.append((api_key, model))
        return {"ok": True, "outcome": "authenticated", "message": "fake ok"}


class FakeAIDefense:
    """Decides per stage (txid suffix). Values: 'allow', 'block', or an InspectionResult / callable."""

    def __init__(self, **decisions) -> None:
        self.decisions = {"input": "allow", "context": "allow", "output": "allow"}
        self.decisions.update(decisions)
        self.calls: list[dict] = []
        self.verify_calls: list[tuple] = []

    def inspect(self, api_key, base_url, messages, transaction_id):
        stage = transaction_id.rsplit("-", 1)[-1]
        self.calls.append({"stage": stage, "api_key": api_key, "base_url": base_url,
                           "messages": [dict(m) for m in messages], "txid": transaction_id})
        d = self.decisions.get(stage, "allow")
        if isinstance(d, InspectionResult):
            return d
        if callable(d):
            return d()
        if d in ("allow", "block"):
            return InspectionResult(decision=d, duration_ms=50, http_status=200, raw_action=d.capitalize(),
                                    classifications=["SECURITY_VIOLATION"] if d == "block" else [],
                                    event_id="evt-123" if d == "block" else None)
        return InspectionResult(decision="error", duration_ms=5,
                                error=ProviderError(d, f"fake {d}"))

    def verify(self, api_key, base_url, transaction_id):
        self.verify_calls.append((api_key, base_url))
        return {"ok": True, "outcome": "usable_decision", "message": "fake ok", "decision": "allow"}


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def store(data_dir):
    # Empty environment: never reads or overwrites the real customer's credentials.
    return ConfigStore(data_dir, env={})


@pytest.fixture
def fakes():
    return FakeOpenAI(), FakeAIDefense()


@pytest.fixture
def app(store, fakes):
    oa, aid = fakes
    application = create_app(config_store=store, openai_adapter=oa, ai_defense=aid)
    application.testing = False
    return application


class Client:
    def __init__(self, app):
        self.app = app
        self.http = app.test_client()
        page = self.http.get("/", headers={"Host": HOST})
        assert page.status_code == 200
        self.token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data).group(1).decode()
        self.page = page.data.decode()

    def headers(self, **extra):
        h = {"Host": HOST, "X-CSRF-Token": self.token, "Origin": f"http://{HOST}", "Sec-Fetch-Site": "same-origin"}
        h.update(extra)
        return h

    def get(self, path, **extra):
        return self.http.get(path, headers=self.headers(**extra))

    def post(self, path, payload, **extra):
        return self.http.post(path, json=payload, headers=self.headers(**extra))


@pytest.fixture
def client(app):
    return Client(app)


@pytest.fixture
def configured(client, store):
    store.save({"OPENAI_API_KEY": FAKE_OPENAI_KEY, "RETAIL_AI_DEFENSE_API_KEY": FAKE_AID_KEY})
    return client
