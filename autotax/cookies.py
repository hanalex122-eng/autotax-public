"""Auth cookie helpers (Phase 2.7 modularization, 2026-05-29).

HttpOnly + Secure + SameSite=Strict cookies for JWT tokens. Cookie auth
runs in dual mode with Bearer token (frontend currently uses Bearer from
localStorage; cookies are set as transition path).

These functions touch only the FastAPI Response object — no DB, no
business logic.
"""
from __future__ import annotations

import os as _os
from fastapi import Response


# Cookie attribute constants — central place to tune session lifetime.
_ACCESS_TOKEN_COOKIE = "atx_token"
_REFRESH_TOKEN_COOKIE = "atx_refresh"
_ACCESS_MAX_AGE = 3600  # 1 hour (access token lifetime)
_REFRESH_MAX_AGE = 7 * 24 * 3600  # 7 days


def _is_https_env() -> bool:
    """True if we're running on HTTPS (production). Used to mark cookies
    `Secure` only when the browser will actually send them back over TLS."""
    return (
        _os.environ.get("PUBLIC_APP_URL", "").startswith("https://")
        or _os.environ.get("RAILWAY_ENVIRONMENT") == "production"
    )


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set HttpOnly + (Secure if production) + SameSite=Strict cookies for
    access + refresh tokens. Response body still carries tokens for backward
    compat with current frontend; transition to cookie-only is tracked in
    SECURITY_AUDIT.md (L-2)."""
    is_https = _is_https_env()
    response.set_cookie(
        key=_ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=True,
        secure=is_https,
        samesite="strict",
        max_age=_ACCESS_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key=_REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=is_https,
        samesite="strict",
        max_age=_REFRESH_MAX_AGE,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    """Delete both auth cookies. Called on logout."""
    response.delete_cookie(_ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(_REFRESH_TOKEN_COOKIE, path="/")


__all__ = [
    "_set_auth_cookies",
    "_clear_auth_cookies",
    "_is_https_env",
]
