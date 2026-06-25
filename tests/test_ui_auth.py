"""Tests for unauthenticated UI endpoint vulnerability fix."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def _make_app():
    """Create a minimal FastAPI app with just the UI router, bypassing startup deps."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from memanto.app.ui.routes.ui_router import router as ui_router

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(ui_router)
    return app


class TestUnauthenticatedUIEndpoints:
    """Unauthenticated requests from non-localhost must be refused with HTTP 403.

    The UI router exposes management endpoints (shutdown, filesystem browse,
    config update, API-key replacement, on-prem restart) with no token-based
    authentication.  Without a localhost-origin guard any host that can reach
    the server process can kill it, read directory listings, or replace the
    stored API key.
    """

    def _remote_client(self, app):
        """Return a TestClient that simulates a remote (non-loopback) caller."""
        client = TestClient(app, raise_server_exceptions=False)
        # Patch the request to appear to come from a remote host
        return client

    def test_shutdown_rejected_from_remote(self):
        """POST /api/ui/shutdown must return 403 for a non-local request."""
        app = _make_app()
        # Starlette TestClient uses "testclient" as the host — not 127.0.0.1
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/ui/shutdown")
        # "testclient" is not in ("127.0.0.1", "::1") → must be 403
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}"

    def test_browse_rejected_from_remote(self):
        """GET /api/ui/browse?path=/etc must return 403 for a non-local request."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/ui/browse?path=/etc")
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}"

    def test_update_config_rejected_from_remote(self):
        """POST /api/ui/config must return 403 for a non-local request."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.patch("/api/ui/config", json={})
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}"

    def test_update_api_key_rejected_from_remote(self):
        """POST /api/ui/api-key must return 403 for a non-local request."""
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.put("/api/ui/api-key", json={"api_key": "stolen"})
        assert resp.status_code == 403, f"expected 403, got {resp.status_code}"
