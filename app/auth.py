"""
Session-cookie authentication.

Sessions are signed + timestamped with itsdangerous (not just base64'd),
so a client can't forge or extend one. The cookie holds nothing but an
opaque signed blob — username and CSRF token live inside it, never in a
server-side store, which keeps the app stateless and easy to deploy.
"""
import hmac
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from .config import settings
from .security import login_throttle, new_csrf_token

router = APIRouter()

_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="fm-session")

SESSION_COOKIE = "fm_session"


class SessionData(BaseModel):
    username: str
    csrf_token: str


def create_session_cookie(username: str) -> str:
    payload = {"username": username, "csrf_token": new_csrf_token()}
    return _serializer.dumps(payload)


def read_session(token: Optional[str]) -> Optional[SessionData]:
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=settings.SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return SessionData(**data)


def get_session(fm_session: Optional[str] = Cookie(default=None)) -> SessionData:
    """FastAPI dependency: 401s automatically if there's no valid session."""
    session = read_session(fm_session)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return session


def require_csrf(request: Request, session: SessionData = Depends(get_session)) -> SessionData:
    """Use as a dependency on any state-changing route (POST/PUT/DELETE)."""
    header_token = request.headers.get("x-csrf-token", "")
    if not header_token or not hmac.compare_digest(header_token, session.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid or missing")
    return session


class LoginBody(BaseModel):
    username: str
    password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.SESSION_MAX_AGE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/api/login")
def login(body: LoginBody, request: Request, response: Response):
    client_key = request.client.host if request.client else "unknown"

    locked_seconds = login_throttle.is_locked(client_key)
    if locked_seconds:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {locked_seconds}s.",
        )

    valid = hmac.compare_digest(body.username, settings.AUTH_USERNAME) and hmac.compare_digest(
        body.password, settings.AUTH_PASSWORD
    )
    if not valid:
        login_throttle.record_failure(client_key)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    login_throttle.record_success(client_key)
    token = create_session_cookie(body.username)
    _set_session_cookie(response, token)
    session = read_session(token)
    return {"ok": True, "username": body.username, "csrf_token": session.csrf_token}


@router.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
def me(session: SessionData = Depends(get_session)):
    return {"username": session.username, "csrf_token": session.csrf_token}
