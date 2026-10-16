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
