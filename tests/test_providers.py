"""Real adapter code exercised against fake transports (no network)."""

from __future__ import annotations

import json
import ssl
from types import SimpleNamespace

import pytest
import requests

from northstar.providers.ai_defense import AIDefenseClient, parse_inspection_body
from northstar.providers.openai_adapter import OpenAIAdapter, classify_openai_exception

KEY = "aid-test-FAKEDEFENSEKEY-000000"
US = "https://us.api.inspect.aidefense.security.cisco.com"


# ---------------------------------------------------------------- AI Defense
class FakeResponse:
    def __init__(self, status=200, body=None, raw=None):
        self.status_code = status
        self.content = raw if raw is not None else json.dumps(body).encode()


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **kw):
        self.calls.append({"url": url, **kw})
        if self.exc:
            raise self.exc
        return self.response


def client_with(response=None, exc=None):
    session = FakeSession(response, exc)
    return AIDefenseClient(session_factory=lambda: session), session


def test_request_shape():
    c, s = client_with(FakeResponse(200, {"action": "Allow", "is_safe": True}))
    msgs = [{"role": "user", "content": "hi"}]
    res = c.inspect(KEY, US, msgs, "run1-input")
    call = s.calls[0]
    assert call["url"] == US + "/api/v1/inspect/chat"
    assert call["headers"]["X-CSRF-Token" if False else "X-Cisco-AI-Defense-API-Key"] == KEY
    assert call["json"]["messages"] == msgs
    assert call["json"]["metadata"]["client_transaction_id"] == "run1-input"
    assert "config" not in call["json"]  # no inline enabled_rules bypassing tenant policy
    assert call["allow_redirects"] is False
    assert isinstance(call["timeout"], tuple)
    assert res.decision == "allow"


@pytest.mark.parametrize("action,decision", [("Allow", "allow"), ("Block", "block"), ("BLOCK", "block"),
                                             ("allow", "allow")])
def test_action_parsing(action, decision):
    assert parse_inspection_body({"action": action}).decision == decision


def test_is_safe_alone_is_not_a_decision():
    res = parse_inspection_body({"is_safe": False, "classifications": ["SECURITY_VIOLATION"]})
    assert res.decision == "error" and res.error.code == "no_decision"
    res = parse_inspection_body({"is_safe": True})
    assert res.decision == "error"


def test_allow_with_unsafe_flag_is_still_allow():
    # Matches the official SDK sample (monitor-only policy): action decides, not is_safe.
    res = parse_inspection_body({"is_safe": False, "action": "Allow"})
    assert res.decision == "allow" and res.is_safe is False


@pytest.mark.parametrize("body", [{"action": "Quarantine"}, {"action": 1}, [], "Allow", None])
def test_unknown_or_malformed_fail_closed(body):
    assert parse_inspection_body(body).decision == "error"


def test_sanitised_fields():
    res = parse_inspection_body({
        "action": "Block", "classifications": ["SECURITY_VIOLATION", "<script>"],
        "rules": [{"rule_name": "Prompt Injection", "rule_id": 3, "classification": "SECURITY_VIOLATION"},
                  {"rule_name": "<img src=x onerror=alert(1)>", "classification": "X"}],
        "severity": "HIGH", "event_id": "b403de99-8d19-408f-8184-ec6d7907f508", "explanation": "secret text",
    })
    pub = res.public()
    assert pub["classifications"] == ["SECURITY_VIOLATION"]
    assert pub["rules"][0]["rule_name"] == "Prompt Injection"
    assert pub["rules"][1]["rule_name"] is None
    assert "explanation" not in pub


@pytest.mark.parametrize(
    "resp,exc,code",
    [
        (FakeResponse(401, {"message": "bad"}), None, "authentication"),
        (FakeResponse(403, {}), None, "authentication"),
        (FakeResponse(429, {}), None, "rate_limit"),
        (FakeResponse(500, {"message": "x"}), None, "provider_error"),
        (FakeResponse(302, {}), None, "redirect"),
        (FakeResponse(200, raw=b"<html>"), None, "malformed"),
        (None, requests.exceptions.ConnectTimeout(), "timeout"),
        (None, requests.exceptions.ConnectionError(), "unreachable"),
        (None, requests.exceptions.SSLError(ssl.SSLCertVerificationError("certificate verify failed")), "tls"),
    ],
)
def test_http_and_transport_errors(resp, exc, code):
    c, _ = client_with(resp, exc)
    res = c.inspect(KEY, US, [{"role": "user", "content": "x"}], "t")
    assert res.decision == "error" and res.error.code == code
    assert KEY not in json.dumps(res.public())


def test_arbitrary_host_refused():
    c, s = client_with(FakeResponse(200, {"action": "Allow"}))
    with pytest.raises(ValueError):
        c.inspect(KEY, "https://attacker.example", [{"role": "user", "content": "x"}], "t")
    assert s.calls == []


@pytest.mark.parametrize(
    "resp,outcome,ok",
    [
        (FakeResponse(200, {"action": "Allow"}), "usable_decision", True),
        (FakeResponse(200, {"is_safe": True}), "authenticated_no_policy_decision", False),
        (FakeResponse(401, {}), "rejected", False),
    ],
)
def test_verify_outcomes(resp, outcome, ok):
    c, _ = client_with(resp)
    r = c.verify(KEY, US, "verify-1")
    assert r["outcome"] == outcome and r["ok"] is ok


def test_verify_unreachable():
    c, _ = client_with(None, requests.exceptions.ConnectionError())
    assert c.verify(KEY, US, "v")["outcome"] == "unreachable"


# ---------------------------------------------------------------- OpenAI
class FakeResponses:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.kwargs = result, exc, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return self.result


def adapter_with(result=None, exc=None):
    responses = FakeResponses(result, exc)
    fake_client = SimpleNamespace(responses=responses, models=SimpleNamespace(
        list=lambda: SimpleNamespace(data=[]), retrieve=lambda m: SimpleNamespace(id=m)))
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return fake_client

    return OpenAIAdapter(client_factory=factory), responses, seen


def ok_response(text="Hello", status="completed"):
    return SimpleNamespace(output_text=text, status=status, incomplete_details=None,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15))


def test_generate_parameters():
    a, r, seen = adapter_with(ok_response())
    msgs = ({"role": "system", "content": "s"}, {"role": "user", "content": "u"})
    res = a.generate("sk-x", "gpt-6-luna", msgs, 800)
    assert r.kwargs["store"] is False
    assert r.kwargs["model"] == "gpt-6-luna"
    assert r.kwargs["max_output_tokens"] == 800
    assert r.kwargs["input"] == list(msgs)
    assert "tools" not in r.kwargs
    assert seen["max_retries"] <= 1 and seen["timeout"] <= 60
    assert (res.input_tokens, res.output_tokens, res.total_tokens) == (10, 5, 15)
    assert res.ok and res.text == "Hello"


def test_incomplete_without_text_is_error():
    resp = ok_response(text="", status="incomplete")
    resp.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    a, _, _ = adapter_with(resp)
    res = a.generate("sk-x", "m", [{"role": "user", "content": "u"}], 100)
    assert not res.ok and res.error.code == "incomplete" and res.output_tokens == 5


def _status_error(cls, status, body=None):
    import httpx2
    import openai

    req = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    return getattr(openai, cls)("provider says: key sk-LEAK", response=httpx2.Response(status, request=req), body=body)


@pytest.mark.parametrize(
    "factory,code",
    [
        (lambda: _status_error("AuthenticationError", 401), "authentication"),
        (lambda: _status_error("PermissionDeniedError", 403), "model_access"),
        (lambda: _status_error("NotFoundError", 404), "model_access"),
        (lambda: _status_error("RateLimitError", 429, {"code": "insufficient_quota"}), "quota"),
        (lambda: _status_error("RateLimitError", 429, {"code": "rate_limit_exceeded"}), "rate_limit"),
        (lambda: _status_error("BadRequestError", 400), "bad_request"),
        (lambda: _status_error("InternalServerError", 500), "provider_error"),
    ],
)
def test_openai_error_mapping(factory, code):
    exc = factory()
    err = classify_openai_exception(exc)
    assert err.code == code
    assert "sk-LEAK" not in err.message


def test_openai_connection_and_timeout_mapping():
    import httpx2
    import openai

    req = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    assert classify_openai_exception(openai.APITimeoutError(request=req)).code == "timeout"
    assert classify_openai_exception(openai.APIConnectionError(request=req)).code == "connectivity"
    try:
        try:
            raise ssl.SSLCertVerificationError("certificate verify failed: unable to get local issuer certificate")
        except ssl.SSLError as inner:
            raise openai.APIConnectionError(request=req) from inner
    except openai.APIConnectionError as exc:
        assert classify_openai_exception(exc).code == "tls"


def test_generate_maps_exceptions():
    a, _, _ = adapter_with(exc=_status_error("AuthenticationError", 401))
    res = a.generate("sk-x", "m", [{"role": "user", "content": "u"}], 100)
    assert not res.ok and res.error.code == "authentication" and res.input_tokens is None


def test_openai_verify_model_unavailable():
    a, r, _ = adapter_with(ok_response())
    assert a.verify("sk-x", "m")["ok"] is True

    def missing(m):
        raise _status_error("NotFoundError", 404)

    fake = SimpleNamespace(responses=r, models=SimpleNamespace(list=lambda: SimpleNamespace(data=[]), retrieve=missing))
    a2 = OpenAIAdapter(client_factory=lambda **kw: fake)
    assert a2.verify("sk-x", "m")["outcome"] == "model_unavailable"


def test_real_sdk_client_constructs_with_bounded_settings():
    """The default factory builds the official SDK client with bounded timeout/retries (no request sent)."""
    a = OpenAIAdapter()
    c = a._client("sk-test-not-real-000000")
    assert c.max_retries == 1
    assert float(c.timeout) == 45.0 if not hasattr(c.timeout, "read") else c.timeout.read == 45.0
