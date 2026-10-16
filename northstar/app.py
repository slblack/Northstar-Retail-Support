"""Flask application factory for Northstar Retail Support."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from . import __version__, security
from .comparison import Services, run_comparison
from .config import (
    AI_DEFENSE_REGION_HOSTS,
    ConfigError,
    ConfigStore,
    validate_key,
    validate_model,
    validate_region,
)
from .knowledge import load_articles
from .labels import LabelIndex, load_suggestions
from .policy_docs import CSV_NAME, POLICY_NAME, ZIP_NAME, build_zip
from .providers.ai_defense import AIDefenseClient
from .providers.openai_adapter import OpenAIAdapter

log = logging.getLogger("northstar")

MAX_REQUEST_BYTES = 32 * 1024
MAX_QUESTION_CHARS = 4000
MAX_CONCURRENT_RUNS = 2
MAX_CONCURRENT_VERIFICATIONS = 2


def default_data_dir() -> Path:
    env = os.environ.get("NORTHSTAR_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def default_dotenv() -> Path:
    return Path(__file__).resolve().parent.parent / ".env"


class BadInput(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _json_body(allowed: set[str]) -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadInput("Request body must be a JSON object.")
    unknown = set(data) - allowed
    if unknown:
        raise BadInput("Request contains unsupported fields.")
    for key, value in data.items():
        if value is not None and not isinstance(value, str):
            raise BadInput("All fields must be strings.")
    return data


def create_app(
    config_store: Optional[ConfigStore] = None,
    openai_adapter: Optional[OpenAIAdapter] = None,
    ai_defense: Optional[AIDefenseClient] = None,
    extra_hosts: tuple[str, ...] = (),
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    store = config_store or ConfigStore(default_data_dir(), dotenv_path=default_dotenv())
    services = Services(
        openai=openai_adapter or OpenAIAdapter(),
        ai_defense=ai_defense or AIDefenseClient(),
        articles=load_articles(),
        labels=LabelIndex.default(),
    )
    suggestions = load_suggestions()
    executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_RUNS * 2, thread_name_prefix="northstar-run")
    run_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
    verify_slots = threading.BoundedSemaphore(MAX_CONCURRENT_VERIFICATIONS)
    csrf_token = security.install(app, extra_hosts)

    app.extensions["northstar"] = {"store": store, "services": services, "executor": executor}

    # ------------------------------------------------------------------ errors
    @app.errorhandler(BadInput)
    def _bad_input(exc: BadInput):
        return jsonify({"ok": False, "error": {"code": "invalid_input", "message": exc.message}}), exc.status

    @app.errorhandler(ConfigError)
    def _config_error(exc: ConfigError):
        return jsonify({"ok": False, "error": {"code": "invalid_input", "message": str(exc)}}), 400

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        messages = {413: "Request too large.", 404: "Not found.", 405: "Method not allowed."}
        msg = messages.get(exc.code or 500, "Request could not be processed.")
        if request.path.startswith("/api/") or exc.code in (413, 405):
            return jsonify({"ok": False, "error": {"code": f"http_{exc.code}", "message": msg}}), exc.code
        return Response(msg, status=exc.code, mimetype="text/plain")

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        ref = uuid.uuid4().hex[:12]
        log.error("Unhandled error ref=%s type=%s", ref, type(exc).__name__)
        return (
            jsonify({"ok": False, "error": {"code": "internal", "message": f"Internal error (ref {ref})."}}),
            500,
        )

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return render_template(
            "index.html",
            csrf_token=csrf_token,
            suggestions=suggestions,
            max_chars=MAX_QUESTION_CHARS,
            version=__version__,
            policy_name=POLICY_NAME,
            csv_name=CSV_NAME,
        )

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "version": __version__})

    @app.get("/download/policy-studio.zip")
    def download_zip():
        resp = Response(build_zip(), mimetype="application/zip")
        resp.headers["Content-Disposition"] = f'attachment; filename="{ZIP_NAME}"'
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------ config
    @app.get("/api/config")
    def get_config():
        return jsonify({"ok": True, "config": store.public_view()})

    @app.post("/api/config")
    def save_config():
        data = _json_body(
            {"openai_api_key", "ai_defense_api_key", "openai_model", "ai_defense_region", "ai_defense_connection_name"}
        )
        updates: dict[str, Any] = {}
        mapping = {
            "openai_api_key": "OPENAI_API_KEY",
            "ai_defense_api_key": "RETAIL_AI_DEFENSE_API_KEY",
            "openai_model": "OPENAI_MODEL",
            "ai_defense_region": "AI_DEFENSE_REGION",
            "ai_defense_connection_name": "AI_DEFENSE_CONNECTION_NAME",
        }
        for field, name in mapping.items():
            if field in data and data[field] is not None:
                updates[name] = data[field]
        store.save(updates)
        # Log setting names only — never values.
        log.info("Settings saved (fields=%s)", ",".join(sorted(k for k, v in updates.items() if str(v).strip())))
        return jsonify({"ok": True, "config": store.public_view()})

    # ------------------------------------------------------------------ verify
    @app.post("/api/verify/openai")
    def verify_openai():
        data = _json_body({"api_key", "model"})
        snap = store.snapshot()
        key = (data.get("api_key") or "").strip()
        key = validate_key(key, "OpenAI API key") if key else snap.openai_api_key
        model = validate_model(data["model"]) if (data.get("model") or "").strip() else snap.openai_model
        if not key:
            return jsonify({"ok": True, "result": {"ok": False, "outcome": "not_configured",
                                                   "message": "No OpenAI key entered or saved."}})
        if not verify_slots.acquire(blocking=False):
            raise BadInput("Another verification is running. Try again shortly.", 429)
        try:
            result = services.openai.verify(key, model)
        finally:
            verify_slots.release()
        return jsonify({"ok": True, "result": result, "model": model})

    @app.post("/api/verify/ai-defense")
    def verify_ai_defense():
        data = _json_body({"api_key", "region"})
        snap = store.snapshot()
        key = (data.get("api_key") or "").strip()
        key = validate_key(key, "AI Defense API key") if key else snap.ai_defense_api_key
        region = validate_region(data["region"]) if (data.get("region") or "").strip() else snap.region
        if not key:
            return jsonify({"ok": True, "result": {"ok": False, "outcome": "not_configured",
                                                   "message": "No AI Defense key entered or saved."}})
        if not verify_slots.acquire(blocking=False):
            raise BadInput("Another verification is running. Try again shortly.", 429)
        try:
            result = services.ai_defense.verify(key, AI_DEFENSE_REGION_HOSTS[region], f"verify-{uuid.uuid4().hex}")
        finally:
            verify_slots.release()
        return jsonify({"ok": True, "result": result, "region": region})

    # ------------------------------------------------------------------ compare
    @app.post("/api/compare")
    def compare():
        data = _json_body({"question"})
        question = data.get("question")
        if not isinstance(question, str):
            raise BadInput("A customer message is required.")
        if "\x00" in question:
            raise BadInput("The message contains a null byte.")
        question = question.replace("\r\n", "\n").strip()
        if not 1 <= len(question) <= MAX_QUESTION_CHARS:
            raise BadInput(f"The customer message must be 1–{MAX_QUESTION_CHARS} characters.")
        if not run_slots.acquire(blocking=False):
            raise BadInput("A comparison is already running. Wait for it to finish.", 429)
        try:
            snap = store.snapshot()  # one configuration snapshot per paired run
            result = run_comparison(services, snap, question, executor)
        finally:
            run_slots.release()
        return jsonify({"ok": True, "run": result})

    return app
