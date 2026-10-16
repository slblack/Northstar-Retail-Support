"""Extra CA bundle support (adds trust anchors; never disables verification)."""

from __future__ import annotations

import os

from northstar.tls import configure_extra_cas

PEM = "-----BEGIN CERTIFICATE-----\nTUlJQ0VYQU1QTEU=\n-----END CERTIFICATE-----\n"


def test_no_directory_changes_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    assert configure_extra_cas(None) == 0
    assert configure_extra_cas(str(tmp_path / "missing")) == 0
    assert configure_extra_cas(str(tmp_path)) == 0
    assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_pem_files_are_appended(monkeypatch, tmp_path):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    (tmp_path / "corp.pem").write_text(PEM)
    (tmp_path / "not-a-cert.crt").write_text("binary junk")
    (tmp_path / "notes.txt").write_text(PEM)
    assert configure_extra_cas(str(tmp_path)) == 1
    bundle = open(os.environ["REQUESTS_CA_BUNDLE"]).read()
    assert os.environ["SSL_CERT_FILE"] == os.environ["REQUESTS_CA_BUNDLE"]
    assert PEM.strip() in bundle
    assert bundle.count("BEGIN CERTIFICATE") > 1  # standard roots retained


# ---------------------------------------------------------------- error reasons and strict-profile opt-in
import ssl

from northstar.providers.errors import tls_failure_reason, tls_message
from northstar.tls import relaxed_strict_context


def _verify_error(reason):
    err = ssl.SSLCertVerificationError(1, f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: {reason} (_ssl.c:1032)")
    err.verify_message = reason
    return err


def test_missing_ca_message_points_to_certs_mount():
    try:
        try:
            raise _verify_error("unable to get local issuer certificate")
        except ssl.SSLError as inner:
            raise ConnectionError("Connection error.") from inner
    except ConnectionError as exc:
        assert tls_failure_reason(exc) == "unable to get local issuer certificate"
        msg = tls_message("OpenAI", exc)
    assert "mount your organisation's root CA" in msg and "RELAX" not in msg
    assert msg.endswith("Verification was not disabled.")


def test_strict_profile_failure_points_to_opt_in():
    msg = tls_message("OpenAI", _verify_error("CA cert does not include key usage extension"))
    assert "NORTHSTAR_TLS_RELAX_X509_STRICT=1" in msg and "key usage" in msg


def test_relaxed_context_off_by_default(monkeypatch):
    monkeypatch.delenv("NORTHSTAR_TLS_RELAX_X509_STRICT", raising=False)
    assert relaxed_strict_context() is None


def test_relaxed_context_keeps_verification(monkeypatch):
    monkeypatch.setenv("NORTHSTAR_TLS_RELAX_X509_STRICT", "1")
    ctx = relaxed_strict_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert not ctx.verify_flags & getattr(ssl, "VERIFY_X509_STRICT", 0)
    assert ctx.cert_store_stats()["x509_ca"] > 0  # still has trust anchors


def test_openai_client_uses_relaxed_context_only_when_enabled(monkeypatch):
    from northstar.providers.openai_adapter import OpenAIAdapter

    monkeypatch.delenv("NORTHSTAR_TLS_RELAX_X509_STRICT", raising=False)
    default = OpenAIAdapter()._client("sk-test-not-real-000000")
    monkeypatch.setenv("NORTHSTAR_TLS_RELAX_X509_STRICT", "1")
    relaxed = OpenAIAdapter()._client("sk-test-not-real-000000")
    assert relaxed._client is not default._client
    assert relaxed.max_retries == 1
