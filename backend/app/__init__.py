"""Flask application factory for the Phase 3 analysis API."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .services.data_store import HistoricalDataError, HistoricalDataStore
from .services.forecast_service import ForecastAnalysisService, ForecastInputError


LOGGER = logging.getLogger(__name__)
DEFAULT_PROCESSED_ROOT = Path(__file__).resolve().parents[1] / "data" / "processed"


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_ROOT=os.environ.get(
            "HISTORICAL_DATA_ROOT",
            str(DEFAULT_PROCESSED_ROOT),
        ),
        JSON_SORT_KEYS=False,
        LOAD_HISTORICAL_DATA=True,
        FAIL_ON_DATA_LOAD_ERROR=_environment_flag(
            "FAIL_ON_DATA_LOAD_ERROR",
            default=False,
        ),
        CORS_ALLOWED_ORIGINS=os.environ.get(
            "CORS_ALLOWED_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ),
    )
    if test_config:
        app.config.update(test_config)

    store = app.config.get("DATA_STORE")
    load_error: HistoricalDataError | None = None
    if store is None and app.config["LOAD_HISTORICAL_DATA"]:
        try:
            store = HistoricalDataStore.from_processed_directory(
                app.config["DATA_ROOT"]
            )
        except HistoricalDataError as exc:
            load_error = exc
            LOGGER.error("Historical data could not be loaded: %s", exc)
            if app.config["FAIL_ON_DATA_LOAD_ERROR"]:
                raise

    app.extensions["historical_data_store"] = store
    app.extensions["historical_data_error"] = load_error
    app.extensions["forecast_analysis_service"] = (
        ForecastAnalysisService(store) if store is not None else None
    )

    from .routes.forecast_routes import forecast_api

    app.register_blueprint(forecast_api, url_prefix="/api")
    _register_cors(app)
    _register_error_handlers(app)
    return app


def _environment_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _register_cors(app: Flask) -> None:
    """Allow only explicitly configured browser origins."""
    configured = app.config.get("CORS_ALLOWED_ORIGINS", "")
    if isinstance(configured, str):
        allowed = {value.strip() for value in configured.split(",") if value.strip()}
    else:
        allowed = set(configured or ())

    @app.after_request
    def add_cors_headers(response):
        from flask import request

        origin = request.headers.get("Origin")
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers.add("Vary", "Origin")
        return response


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ForecastInputError)
    def invalid_input(exc: ForecastInputError):
        return _error("invalid_request", str(exc), 400)

    @app.errorhandler(HistoricalDataError)
    def unavailable_data(exc: HistoricalDataError):
        return _error("historical_data_unavailable", str(exc), 503)

    @app.errorhandler(404)
    def not_found(exc: HTTPException):
        return _error("not_found", "The requested API resource does not exist.", 404)

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception):
        if isinstance(exc, HTTPException):
            return _error("http_error", exc.description, exc.code or 500)
        LOGGER.exception("Unexpected API error")
        return _error("internal_error", "An unexpected internal error occurred.", 500)


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status
