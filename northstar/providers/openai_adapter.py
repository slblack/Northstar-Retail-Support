"""OpenAI Responses API adapter (official ``openai`` Python SDK)."""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from .errors import ProviderError, find_tls_error, tls_message
from ..tls import relaxed_strict_context

OPENAI_TIMEOUT_SECONDS = 45.0
OPENAI_MAX_RETRIES = 1  # bounded: one retry for transient failures, never unbounded


@dataclass
class GenerationResult:
    ok: bool
    text: str = field(default="", repr=False)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: int = 0
    status: Optional[str] = None
    incomplete_reason: Optional[str] = None
    error: Optional[ProviderError] = None


def _usage_int(usage: Any, name: str) -> Optional[int]:
    value = getattr(usage, name, None) if usage is not None else None
    return value if isinstance(value, int) and value >= 0 else None


def classify_openai_exception(exc: BaseException) -> ProviderError:
    """Map SDK exceptions to safe, actionable messages without echoing provider text."""
    import openai  # local import keeps module import cheap for tests

    if find_tls_error(exc):
        return ProviderError("tls", tls_message("OpenAI", exc))
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("timeout", "OpenAI did not respond before the timeout. Try again shortly.")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError(
            "connectivity", "Could not reach OpenAI. Check network access, proxy settings and firewall rules."
        )
    if isinstance(exc, openai.AuthenticationError):
        return ProviderError("authentication", "OpenAI rejected the API key. Enter a valid key in Setup.", 401)
    if isinstance(exc, openai.PermissionDeniedError):
        return ProviderError(
            "model_access",
            "The OpenAI key is not permitted to use this model or project. Check model access in your OpenAI project.",
            403,
        )
    if isinstance(exc, openai.NotFoundError):
        return ProviderError(
            "model_access",
            "The configured model was not found or is not available to this key. Change the model in Setup.",
            404,
        )
    if isinstance(exc, openai.RateLimitError):
        code = getattr(exc, "code", None)
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            code = code or body.get("code") or (body.get("error") or {}).get("code")
        if code == "insufficient_quota":
            return ProviderError(
                "quota", "OpenAI reports insufficient quota or credit for this key. Check billing.", 429
            )
        return ProviderError("rate_limit", "OpenAI rate limit reached. Wait a moment and try again.", 429)
    if isinstance(exc, openai.BadRequestError):
        return ProviderError(
            "bad_request",
            "OpenAI rejected the request (400). The model may not support a parameter used by this app.",
            400,
        )
    if isinstance(exc, openai.InternalServerError):
        return ProviderError("provider_error", "OpenAI returned a server error. Try again later.", 500)
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", None)
        return ProviderError("provider_error", f"OpenAI returned HTTP {status}.", status)
    if isinstance(exc, ssl.SSLError):
        return ProviderError("tls", "TLS error while contacting OpenAI.")
    return ProviderError("provider_error", "Unexpected error while calling OpenAI.")


class OpenAIAdapter:
    """Thin wrapper around ``client.responses.create``. No tools are ever passed."""

    def __init__(
        self,
        timeout: float = OPENAI_TIMEOUT_SECONDS,
        max_retries: int = OPENAI_MAX_RETRIES,
        client_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self._client_factory = client_factory

    def _client(self, api_key: str):
        if self._client_factory is not None:
            return self._client_factory(api_key=api_key, timeout=self.timeout, max_retries=self.max_retries)
        import openai

        kwargs = {"api_key": api_key, "timeout": self.timeout, "max_retries": self.max_retries}
        ctx = relaxed_strict_context()
        if ctx is not None:
            # Opt-in only: same trust bundle, chain and hostname checks; Python 3.13's extra
            # VERIFY_X509_STRICT profile checks are relaxed (see northstar/tls.py).
            kwargs["http_client"] = openai.DefaultHttpxClient(verify=ctx, timeout=self.timeout)
        return openai.OpenAI(**kwargs)

    def generate(
        self, api_key: str, model: str, messages: Sequence[dict], max_output_tokens: int
    ) -> GenerationResult:
        start = time.perf_counter()
        try:
            client = self._client(api_key)
            response = client.responses.create(
                model=model,
                input=[{"role": m["role"], "content": m["content"]} for m in messages],
                max_output_tokens=max_output_tokens,
                store=False,
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a safe message
            return GenerationResult(
                ok=False,
                duration_ms=int((time.perf_counter() - start) * 1000),
                error=classify_openai_exception(exc),
            )
        duration = int((time.perf_counter() - start) * 1000)
        usage = getattr(response, "usage", None)
        text = getattr(response, "output_text", "") or ""
        status = getattr(response, "status", None)
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) if details is not None else None
        result = GenerationResult(
            ok=True,
            text=text,
            input_tokens=_usage_int(usage, "input_tokens"),
            output_tokens=_usage_int(usage, "output_tokens"),
            total_tokens=_usage_int(usage, "total_tokens"),
            duration_ms=duration,
            status=status if isinstance(status, str) else None,
            incomplete_reason=reason if isinstance(reason, str) else None,
        )
        if not text.strip():
            result.ok = False
            if result.status == "incomplete":
                result.error = ProviderError(
                    "incomplete",
                    "The model stopped before producing visible text"
                    + (f" ({result.incomplete_reason})" if result.incomplete_reason else "")
                    + ". Consider raising OPENAI_MAX_OUTPUT_TOKENS.",
                )
            else:
                result.error = ProviderError("empty", "The model returned no text output.")
        return result

    def verify(self, api_key: str, model: str) -> dict:
        """Authenticate with a model-list request, then check the configured model is visible."""
        try:
            client = self._client(api_key)
            page = client.models.list()
            # Touch the first page only; do not paginate.
            _ = getattr(page, "data", None)
        except Exception as exc:  # noqa: BLE001
            err = classify_openai_exception(exc)
            return {"ok": False, "outcome": err.code, "message": err.message}
        try:
            client.models.retrieve(model)
        except Exception as exc:  # noqa: BLE001
            err = classify_openai_exception(exc)
            if err.code == "model_access":
                return {
                    "ok": False,
                    "outcome": "model_unavailable",
                    "message": "Key authenticated, but the configured model is not available to it.",
                }
            return {"ok": False, "outcome": err.code, "message": err.message}
        return {
            "ok": True,
            "outcome": "authenticated",
            "message": "Key authenticated and the configured model is listed. "
            "This does not guarantee available credit or rate limits.",
        }
