"""WSGI application and optional local Flask entry point."""

from __future__ import annotations

import os

try:
    from backend.app import create_app
except ModuleNotFoundError as exc:
    if exc.name != "backend":
        raise
    # Supports ``python backend/run.py`` from the repository root.
    from app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "false").strip().lower()
        in {"1", "true", "yes", "on"},
    )
