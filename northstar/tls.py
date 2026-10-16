"""Optional extra trusted CA certificates (for networks that inspect HTTPS).

If ``NORTHSTAR_EXTRA_CA_DIR`` (default ``/certs`` in the container) contains ``*.pem`` or
``*.crt`` files, they are appended to the standard trust bundle and the combined file is
used by both ``requests`` (AI Defense) and the OpenAI SDK. TLS verification is never
disabled; this only *adds* trust anchors you explicitly supply.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("northstar.tls")

PEM_BEGIN = "-----BEGIN CERTIFICATE-----"


def _base_bundle() -> str:
    for candidate in (
        os.environ.get("SSL_CERT_FILE"),
        "/etc/ssl/certs/ca-certificates.crt",
    ):
        if candidate and Path(candidate).is_file():
            return Path(candidate).read_text(encoding="utf-8", errors="ignore")
    try:
        import certifi

        return Path(certifi.where()).read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""


def configure_extra_cas(directory: str | None) -> int:
    """Returns the number of extra certificate files added (0 if none)."""
    if not directory:
        return 0
    folder = Path(directory)
    if not folder.is_dir():
        return 0
    extra: list[str] = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in (".pem", ".crt") or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if PEM_BEGIN in text:
            extra.append(text.strip())
        else:
            log.warning("Skipped %s: not a PEM certificate (convert DER .cer files to PEM).", path.name)
    if not extra:
        return 0
    bundle = _base_bundle().rstrip() + "\n\n" + "\n\n".join(extra) + "\n"
    fd, out = tempfile.mkstemp(prefix="northstar-ca-", suffix=".pem")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(bundle)
    os.environ["SSL_CERT_FILE"] = out
    os.environ["REQUESTS_CA_BUNDLE"] = out
    log.info("Added %d extra CA certificate file(s) to the trust bundle.", len(extra))
    return len(extra)
