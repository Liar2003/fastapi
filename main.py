"""
Entry point. Run with:  uvicorn main:app --host 0.0.0.0 --port $PORT
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth, files, terminal
from app.auth import read_session
from app.config import settings
from app.security import SecurityHeadersMiddleware

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title=settings.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityHeadersMiddleware)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(auth.router)
app.include_router(files.router)
app.include_router(terminal.router)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if read_session(request.cookies.get("fm_session")):
        return RedirectResponse("/")
    return templates.TemplateResponse(
        "login.html", {"request": request, "app_name": settings.APP_NAME}
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    session = read_session(request.cookies.get("fm_session"))
    if not session:
        return RedirectResponse("/login")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": settings.APP_NAME,
            "username": session.username,
            "csrf_token": session.csrf_token,
            "terminal_enabled": settings.ENABLE_TERMINAL,
        },
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
