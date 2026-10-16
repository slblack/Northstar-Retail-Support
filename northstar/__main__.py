"""Entry point: ``python -m northstar``.

Environment variables:
  NORTHSTAR_HOST           bind address (default 127.0.0.1)
  NORTHSTAR_PORT           port (default 5065; if unset and 5065 is busy, 5066 is tried)
  NORTHSTAR_DATA_DIR       where settings.json is stored (default ./data)
  NORTHSTAR_ALLOWED_HOSTS  extra Host header names, comma separated (default none)
  NORTHSTAR_EXTRA_CA_DIR   folder of extra PEM CA certificates (default none; /certs in Docker)
"""

from __future__ import annotations

import errno
import logging
import os
import socket
import sys

DEFAULT_PORT = 5065
ALTERNATIVE_PORT = 5066


def _port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1), errno.EACCES):
                return False
            raise
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("northstar")

    from .tls import configure_extra_cas

    configure_extra_cas(os.environ.get("NORTHSTAR_EXTRA_CA_DIR"))

    from .app import create_app
    from .security import is_loopback_bind

    host = os.environ.get("NORTHSTAR_HOST", "127.0.0.1").strip()
    port_env = os.environ.get("NORTHSTAR_PORT", "").strip()
    port = int(port_env) if port_env else DEFAULT_PORT

    if not is_loopback_bind(host):
        log.warning(
            "Binding to %s (not loopback). This is intended only inside a container whose port is "
            "published to 127.0.0.1 on the host. Do not expose this demo to a network.",
            host,
        )

    if not _port_free(host, port):
        if port_env:
            log.error("Port %s is already in use. Choose another with NORTHSTAR_PORT; no process was stopped.", port)
            return 2
        log.warning("Port %s is already in use; trying documented alternative port %s.", port, ALTERNATIVE_PORT)
        port = ALTERNATIVE_PORT
        if not _port_free(host, port):
            log.error("Port %s is also in use. Set NORTHSTAR_PORT to a free port; no process was stopped.", port)
            return 2

    extra_hosts = tuple(h for h in os.environ.get("NORTHSTAR_ALLOWED_HOSTS", "").split(",") if h.strip())
    app = create_app(extra_hosts=extra_hosts)
    shown = "127.0.0.1" if not is_loopback_bind(host) else host
    log.info("Northstar Retail Support listening on http://%s:%s (debug off, reloader off)", shown, port)
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
