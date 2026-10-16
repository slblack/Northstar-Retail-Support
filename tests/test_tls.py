"""Extra CA bundle support (adds trust anchors; never disables verification)."""

from __future__ import annotations

import os
import ssl

import pytest

from northstar.providers.errors import tls_failure_reason, tls_message
from northstar.tls import configure_extra_cas, relaxed_strict_context

# A real, test-only, self-signed CA certificate (no private key kept), so OpenSSL can parse it.
PEM = """-----BEGIN CERTIFICATE-----
MIIDKTCCAhGgAwIBAgIUEaqPe/LnX59Xp8fvVab50Xj0vmwwDQYJKoZIhvcNAQEL
BQAwHDEaMBgGA1UEAwwRTm9ydGhzdGFyIFRlc3QgQ0EwHhcNMjYxMDE2MTEzMzM3
WhcNMzYxMDEzMTEzMzM3WjAcMRowGAYDVQQDDBFOb3J0aHN0YXIgVGVzdCBDQTCC
ASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBANAG9XkbwyEoMxxBwjU9+TAg
76U1NvoN+Dh6QB+VAsPMk7hmC+Vn3V9oCHoMsw5+gMXofOf1meT026lPKp/WyS2g
CiJw56XEnakBs3lgfVTXGzBBWWpw5dPaHjWMuTgliAueGpKdf1iJL1rZz5iiSUhs
jV20xNRoS9DDoEpiy+ZURBlEnRX8WG035Kesl6uyiBBQu8VwhUaIafh6OKP0I4t6
JnQ+rq7uAM0LB161WR5DCTaGt5/QxRMFz5kFi2E+w7u2/Gi4gFD7T6fvMUx++nWY
B4hNPOU6Q8Gga+aZ+yqQpFGsAdb7Vv6OWaf3WmhQofV3hcV9ddMjLgrW7whxhcMC
AwEAAaNjMGEwHQYDVR0OBBYEFJ1Dp48YphOJNqq8eZWfJVUO9JlQMB8GA1UdIwQY
MBaAFJ1Dp48YphOJNqq8eZWfJVUO9JlQMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0P
AQH/BAQDAgEGMA0GCSqGSIb3DQEBCwUAA4IBAQBEIYHFq4yAaMT7l/bJKOjNbjJj
hH8Yi7/Mk2x2BrsFLV2R+2QnulFp9rGyRTCMbDIis8JRADMs6cvXpZwJd3ulRw2x
pVQfSxUWUFVif4M3boHKaLBIMSL3k2pbg+AUcOhfoQiSJc7eZAbEZKLrj9l8IINL
fwbA42Lvtfzs0l9J731efeCBmKQXkxxYi68vdV66Giv9IoPEZcthKfJiS2lww/t5
mUR3esZahQSBtLtUXT1edzWroOdoOp2oF7O1gwwE252jnz8x7xQX7tBi6QrBPd+o
suebw/YqY1qJeSxteArc+fpLRS1rH5thZKvOd3YRdK6mmZsvwdfasARvAGnv
-----END CERTIFICATE-----
"""
GARBAGE_PEM = "-----BEGIN CERTIFICATE-----\nTUlJQ0VYQU1QTEU=\n-----END CERTIFICATE-----\n"

TLS_ENV = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NORTHSTAR_TLS_RELAX_X509_STRICT")


@pytest.fixture(autouse=True)
def isolated_tls_env():
    """configure_extra_cas() writes to os.environ; restore it exactly after every test,
    whether or not the variables existed beforehand (they don't on a clean CI runner)."""
    saved = {k: os.environ.get(k) for k in TLS_ENV}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_no_directory_changes_nothing(tmp_path):
    os.environ.pop("REQUESTS_CA_BUNDLE", None)
    assert configure_extra_cas(None) == 0
    assert configure_extra_cas(str(tmp_path / "missing")) == 0
    assert configure_extra_cas(str(tmp_path)) == 0
    assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_pem_files_are_appended(tmp_path):
    os.environ.pop("SSL_CERT_FILE", None)
    os.environ.pop("REQUESTS_CA_BUNDLE", None)
    # Comment lines like those written by scripts/export-network-root-ca.ps1 are accepted.
    (tmp_path / "corp.pem").write_text("# Subject: CN=Northstar Test CA\n" + PEM)
    (tmp_path / "not-a-cert.crt").write_text("binary junk")
    (tmp_path / "corrupt.pem").write_text(GARBAGE_PEM)
    (tmp_path / "notes.txt").write_text(PEM)
    assert configure_extra_cas(str(tmp_path)) == 1
    bundle = open(os.environ["REQUESTS_CA_BUNDLE"]).read()
    assert os.environ["SSL_CERT_FILE"] == os.environ["REQUESTS_CA_BUNDLE"]
    assert PEM.strip() in bundle
    assert bundle.count("BEGIN CERTIFICATE") > 1  # standard roots retained
    assert GARBAGE_PEM.strip() not in bundle  # unparseable files are skipped, not trusted
    ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])  # the combined bundle loads


def test_only_unparseable_files_changes_nothing(tmp_path):
    os.environ.pop("SSL_CERT_FILE", None)
    (tmp_path / "corrupt.pem").write_text(GARBAGE_PEM)
    assert configure_extra_cas(str(tmp_path)) == 0
    assert "SSL_CERT_FILE" not in os.environ


# ---------------------------------------------------------------- error reasons and strict-profile opt-in
def _verify_error(reason):
    err = ssl.SSLCertVerificationError(
        1, f"[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: {reason} (_ssl.c:1032)"
    )
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


def test_relaxed_context_off_by_default():
    os.environ.pop("NORTHSTAR_TLS_RELAX_X509_STRICT", None)
    assert relaxed_strict_context() is None


def test_relaxed_context_keeps_verification():
    os.environ.pop("SSL_CERT_FILE", None)
    os.environ["NORTHSTAR_TLS_RELAX_X509_STRICT"] = "1"
    ctx = relaxed_strict_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert not ctx.verify_flags & getattr(ssl, "VERIFY_X509_STRICT", 0)
    assert ctx.cert_store_stats()["x509_ca"] > 0  # still has trust anchors


def test_relaxed_context_uses_extra_ca_bundle(tmp_path):
    (tmp_path / "corp.pem").write_text(PEM)
    configure_extra_cas(str(tmp_path))
    os.environ["NORTHSTAR_TLS_RELAX_X509_STRICT"] = "1"
    ctx = relaxed_strict_context()
    subjects = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
    assert "Northstar Test CA" in subjects


def test_openai_client_uses_relaxed_context_only_when_enabled():
    from northstar.providers.openai_adapter import OpenAIAdapter

    os.environ.pop("NORTHSTAR_TLS_RELAX_X509_STRICT", None)
    default = OpenAIAdapter()._client("sk-test-not-real-000000")
    os.environ["NORTHSTAR_TLS_RELAX_X509_STRICT"] = "1"
    relaxed = OpenAIAdapter()._client("sk-test-not-real-000000")
    assert relaxed._client is not default._client
    assert relaxed.max_retries == 1
