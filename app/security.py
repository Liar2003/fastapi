"""
Security building blocks shared by the rest of the app:

- safe_join(): the single choke point every file operation goes through
  to make path traversal impossible.
- CSRF token issuance + verification.
- A security-headers middleware applied to every response.
"""
import hmac
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings


class PathTraversalError(HTTPException):
    def __init__(self, detail: str = "Invalid path"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def safe_join(relative_path: str) -> Path:
    """
    Resolve a user-supplied relative path against ROOT_DIR and guarantee
    the result cannot escape it — no '..', no symlink tricks, no absolute
    path override. Raises PathTraversalError on anything suspicious.

    This is the ONLY function in the codebase that should turn a
    client-supplied string into a filesystem Path. Every route handler
    that touches the disk calls this first.
    """
    relative_path = (relative_path or "").strip()
    # Normalize separators and strip any leading slash so os.path.join
    # can't be tricked into treating it as absolute.
    relative_path = relative_path.replace("\\", "/").lstrip("/")

    candidate = (settings.ROOT_DIR / relative_path).resolve()

    try:
        candidate.relative_to(settings.ROOT_DIR)
    except ValueError:
        raise PathTraversalError(f"Path escapes root: {relative_path!r}")

    return candidate


def ensure_within_root(path: Path) -> Path:
    """Same guarantee as safe_join, but for a Path we already resolved."""
    resolved = path.resolve()
    try:
        resolved.relative_to(settings.ROOT_DIR)
    except ValueError:
        raise PathTraversalError("Resolved path escapes root")
    return resolved


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
# Double-submit pattern: a random token is issued and stored in the signed
# session; the client must echo it back in an X-CSRF-Token header on every
# state-changing request. An attacker forging a cross-site request can't
# read the cookie (browser same-origin policy) so can't produce the header.

def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf(request: Request, session_token: Optional[str]) -> None:
    if not session_token:
        raise HTTPException(status_code=403, detail="CSRF token missing from session")
    header_token = request.headers.get("x-csrf-token", "")
    if not header_token or not hmac.compare_digest(header_token, session_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")


# ---------------------------------------------------------------------------
# Brute-force lockout (in-memory — fine for a single-process deployment;
# swap for Redis if you ever run more than one worker/instance)
# ---------------------------------------------------------------------------
class LoginThrottle:
    def __init__(self):
        self._attempts: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def is_locked(self, key: str) -> Optional[int]:
        until = self._locked_until.get(key)
        if until and until > time.time():
            return int(until - time.time())
        return None

    def record_failure(self, key: str) -> None:
        now = time.time()
        window = self._attempts.setdefault(key, [])
        window.append(now)
        cutoff = now - settings.LOCKOUT_SECONDS
        window[:] = [t for t in window if t > cutoff]
        if len(window) >= settings.MAX_LOGIN_ATTEMPTS:
            self._locked_until[key] = now + settings.LOCKOUT_SECONDS
            window.clear()

    def record_success(self, key: str) -> None:
        self._attempts.pop(key, None)
        self._locked_until.pop(key, None)


login_throttle = LoginThrottle()


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # CSP: xterm/CodeMirror are loaded from cdnjs; everything else is
        # same-origin. 'unsafe-inline' is needed for the small inline
        # style/script blocks in the templates — tighten this further if
        # you move those into static files.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'"
        )
        if settings.COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
