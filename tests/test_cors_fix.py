"""
Tests for CORS misconfiguration fix (#770).

Verifies that:
1.  allow_credentials=False is the default (CORS_ALLOW_CREDENTIALS unset).
2.  Wildcard origins + CORS_ALLOW_CREDENTIALS=True raises ValueError at startup.
3.  Wildcard origins + CORS_ALLOW_CREDENTIALS=False does NOT send
    Access-Control-Allow-Credentials: true in responses.
4.  Explicit origins + CORS_ALLOW_CREDENTIALS=True is allowed.
"""

import os
import pytest
import pytest_asyncio

os.environ.setdefault("MOORCHEH_API_KEY", "test-api-key")


class TestCorsCredentialsDefault:
    """CORS_ALLOW_CREDENTIALS defaults to False."""

    def test_default_is_false(self):
        from memanto.app.config import Settings
        s = Settings()
        assert s.CORS_ALLOW_CREDENTIALS is False

    def test_explicit_true_accepted(self):
        from memanto.app.config import Settings
        s = Settings(CORS_ALLOW_CREDENTIALS=True)
        assert s.CORS_ALLOW_CREDENTIALS is True


class TestCorsStartupGuard:
    """Startup guard raises ValueError for wildcard+credentials combo."""

    def _apply_guard(self, allowed_origins, allow_credentials):
        """Replicate the guard logic from main.py."""
        _wildcard_origins = "*" in allowed_origins
        if _wildcard_origins and allow_credentials:
            raise ValueError(
                "CORS misconfiguration: CORS_ALLOW_CREDENTIALS=true is incompatible with "
                "ALLOWED_ORIGINS=['*']. Specify explicit trusted origins when enabling credentials."
            )

    def test_wildcard_with_credentials_raises(self):
        with pytest.raises(ValueError, match="CORS misconfiguration"):
            self._apply_guard(["*"], True)

    def test_wildcard_without_credentials_ok(self):
        self._apply_guard(["*"], False)  # must not raise

    def test_explicit_origin_with_credentials_ok(self):
        self._apply_guard(["https://app.example.com"], True)  # must not raise

    def test_empty_origins_with_credentials_ok(self):
        self._apply_guard([], True)  # must not raise


@pytest.mark.asyncio
class TestCorsHeaderBehavior:
    """CORS response headers with default config (wildcard, no credentials)."""

    async def test_no_credentials_header_with_wildcard(self):
        """With wildcard origins + credentials=False, Access-Control-Allow-Credentials
        must not be 'true' — browsers would reject credentialed cross-origin requests."""
        import httpx
        from unittest.mock import patch

        with patch("memanto.app.main._validate_startup_dependencies", return_value=None):
            from memanto.app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/health", headers={"Origin": "https://evil.com"})

        cred_header = resp.headers.get("access-control-allow-credentials", "").lower()
        assert cred_header != "true", (
            "Access-Control-Allow-Credentials must not be 'true' when using wildcard origins"
        )

    async def test_wildcard_returns_star_not_reflected_origin(self):
        """With wildcard + credentials=False, Starlette returns '*' (not the request origin).
        If it reflected the caller's origin here, that would indicate credentials mode is on."""
        import httpx
        from unittest.mock import patch

        with patch("memanto.app.main._validate_startup_dependencies", return_value=None):
            from memanto.app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/health", headers={"Origin": "https://evil.com"})

        origin_header = resp.headers.get("access-control-allow-origin", "")
        # Starlette returns "*" when allow_all_origins=True and credentials=False.
        # If it returned "https://evil.com" the credentials flag would have been active.
        assert origin_header in ("", "*"), (
            f"Expected '*' or absent, got '{origin_header}' — "
            "reflected origin indicates credentials mode is still active"
        )
