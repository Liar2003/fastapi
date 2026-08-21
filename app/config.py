"""
Central configuration for the file manager.
Everything here is driven by environment variables so the same code
can run locally and in production (Railway, Render, a VPS, etc.)
without edits.
"""
import os
import secrets
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # --- Identity / auth -----------------------------------------------
    # Username + password for the single admin account. Set these as real
    # environment variables in production — do NOT rely on the defaults.
    AUTH_USERNAME: str = os.environ.get("FM_USERNAME", "admin")
    AUTH_PASSWORD: str = os.environ.get("FM_PASSWORD", "changeme123")

    # Signs session cookies + CSRF tokens. If not provided, a random key
    # is generated at process start — sessions won't survive a restart,
    # which is fine for testing but you should set FM_SECRET_KEY in prod.
    SECRET_KEY: str = os.environ.get("FM_SECRET_KEY") or secrets.token_hex(32)

    # How long a login session stays valid, in seconds.
    SESSION_MAX_AGE: int = int(os.environ.get("FM_SESSION_MAX_AGE", 60 * 60 * 12))  # 12h

    # --- Brute-force lockout --------------------------------------------
    MAX_LOGIN_ATTEMPTS: int = int(os.environ.get("FM_MAX_LOGIN_ATTEMPTS", 5))
    LOCKOUT_SECONDS: int = int(os.environ.get("FM_LOCKOUT_SECONDS", 15 * 60))  # 15 min

    # --- Storage ---------------------------------------------------------
    # Every file operation is confined inside this directory. Nothing the
    # app does can ever read or write outside of it.
    ROOT_DIR: Path = Path(os.environ.get("FM_ROOT", "./data")).resolve()

    # Max upload size per request, in bytes.
    MAX_UPLOAD_SIZE: int = int(os.environ.get("FM_MAX_UPLOAD_SIZE", 1024 * 1024 * 1024))  # 1GB

    # --- Terminal ----------------------------------------------------------
    # Disable the web terminal entirely by setting FM_ENABLE_TERMINAL=false.
    # Think carefully before exposing this on the public internet — a
    # terminal is full remote code execution as whatever user the process
    # runs as.
    ENABLE_TERMINAL: bool = _bool("FM_ENABLE_TERMINAL", True)
    TERMINAL_SHELL: str = os.environ.get("FM_SHELL", "/bin/bash")

    # --- Cookies -----------------------------------------------------------
    # Set to True automatically unless explicitly disabled — turn this off
    # only for local http:// development.
    COOKIE_SECURE: bool = _bool("FM_COOKIE_SECURE", True)

    APP_NAME: str = os.environ.get("FM_APP_NAME", "File Manager")


settings = Settings()
settings.ROOT_DIR.mkdir(parents=True, exist_ok=True)
