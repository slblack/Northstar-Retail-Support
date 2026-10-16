"""Safe provider error representation shared by adapters."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProviderError:
    code: str
    message: str
    http_status: Optional[int] = None

    def public(self) -> dict:
        data = {"code": self.code, "message": self.message}
        if self.http_status is not None:
            data["http_status"] = self.http_status
        return data


def find_tls_error(exc: BaseException) -> bool:
    """Walk the exception chain looking for a certificate verification failure."""
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        text = type(current).__name__ + " " + str(current)[:500]
        if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text:
            return True
        current = current.__cause__ or current.__context__
        # requests wraps urllib3 errors in .args
        if current is None and getattr(exc, "args", None):
            for arg in exc.args:
                if isinstance(arg, BaseException) and id(arg) not in seen:
                    current = arg
                    break
    return False
