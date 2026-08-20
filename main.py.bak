import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pty
import select
import struct
import termios
import fcntl
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware


APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(os.getenv("FILE_ROOT", str(APP_DIR / "data"))).expanduser().resolve()
ROOT_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_FILE = Path(os.getenv("AUDIT_FILE", str(APP_DIR / "data" / ".audit.jsonl"))).expanduser().resolve()
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "28800"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
TERMINAL_SHELL = os.getenv("TERMINAL_SHELL", "/bin/bash")

app = FastAPI(title="Secure File Manager", version="1.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "0") == "1",
)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit(request: Optional[Request], action: str, path: str = "", details: Optional[dict] = None) -> None:
    event = {
        "time": utc_now(),
        "user": (request.session.get("user") if request else "terminal"),
        "action": action,
        "path": path,
        "ip": (request.client.host if request and request.client else None),
        "details": details or {},
    }
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


def require_auth(request: Request) -> Request:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")
    return request


def relative_path(path: Path) -> str:
    return "/" if path == ROOT_DIR else "/" + path.relative_to(ROOT_DIR).as_posix()


def safe_path(raw: str = "") -> Path:
    raw = (raw or "").replace("\\", "/").strip()
    if raw in ("", "/", "."):
        candidate = ROOT_DIR
    else:
        candidate = (ROOT_DIR / raw.lstrip("/")).resolve()
    if candidate != ROOT_DIR and ROOT_DIR not in candidate.parents:
        raise HTTPException(status_code=403, detail="Path escapes the configured file root")
    return candidate


def safe_child(parent: Path, name: str) -> Path:
    name = Path(name).name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid name")
    result = (parent / name).resolve()
    if result != ROOT_DIR and ROOT_DIR not in result.parents:
        raise HTTPException(status_code=403, detail="Path escapes the configured file root")
    return result


def stat_item(path: Path) -> dict:
    info = path.stat()
    is_dir = path.is_dir()
    return {
        "name": path.name,
        "path": relative_path(path),
        "type": "directory" if is_dir else "file",
        "size": 0 if is_dir else info.st_size,
        "modified": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
        "mode": stat.filemode(info.st_mode),
        "mime": "inode/directory" if is_dir else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
        "hidden": path.name.startswith("."),
    }


def human_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail="Permission denied")
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail="File or directory not found")
    if isinstance(exc, FileExistsError):
        return HTTPException(status_code=409, detail="A file or directory with that name already exists")
    return HTTPException(status_code=400, detail=str(exc) or "Operation failed")


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/api/session")
async def session(request: Request):
    return {"authenticated": is_authenticated(request), "user": request.session.get("user")}


@app.post("/api/login")
async def login(request: Request):
    data = await request.json()
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))
    valid = secrets.compare_digest(username, ADMIN_USER) and secrets.compare_digest(password, ADMIN_PASSWORD)
    if not valid:
        audit(request, "login_failed", details={"username": username[:64]})
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session["authenticated"] = True
    request.session["user"] = ADMIN_USER
    audit(request, "login")
    return {"ok": True, "user": ADMIN_USER}


@app.post("/api/logout")
async def logout(request: Request):
    audit(request, "logout")
    request.session.clear()
    return {"ok": True}


@app.get("/api/config")
async def config(request: Request, _auth: None = Depends(require_auth)):
    return {"root": str(ROOT_DIR), "max_upload_bytes": MAX_UPLOAD_BYTES, "terminal_shell": Path(TERMINAL_SHELL).name}


@app.get("/api/files")
async def list_files(
    request: Request,
    _auth: None = Depends(require_auth),
    path: str = Query("/"),
    show_hidden: bool = Query(False),
    search: str = Query(""),
):
    directory = safe_path(path)
    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    try:
        items = []
        for item in directory.iterdir():
            if not show_hidden and item.name.startswith("."):
                continue
            if search and search.lower() not in item.name.lower():
                continue
            try:
                items.append(stat_item(item))
            except OSError:
                continue
        items.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
        parent = relative_path(directory.parent) if directory != ROOT_DIR else None
        return {"path": relative_path(directory), "parent": parent, "items": items}
    except Exception as exc:
        raise human_error(exc)


@app.get("/api/file")
async def read_file(path: str, request: Request, _auth: None = Depends(require_auth)):
    target = safe_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.stat().st_size > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Preview is limited to 2 MB")
    try:
        data = target.read_bytes()
        is_text = b"\x00" not in data[:8192]
        if not is_text:
            return {"path": relative_path(target), "binary": True, "content": ""}
        return {"path": relative_path(target), "binary": False, "content": data.decode("utf-8", errors="replace")}
    except Exception as exc:
        raise human_error(exc)


@app.get("/api/download")
async def download_file(path: str, request: Request, _auth: None = Depends(require_auth)):
    target = safe_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    audit(request, "download", relative_path(target))
    return FileResponse(target, filename=target.name, media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream")


@app.get("/api/zip")
async def zip_path(path: str, request: Request, _auth: None = Depends(require_auth)):
    target = safe_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    fd, temp_name = tempfile.mkstemp(prefix="file-manager-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_name, "w", zipfile.ZIP_DEFLATED) as archive:
            if target.is_dir():
                for item in target.rglob("*"):
                    if item.is_file() and item != AUDIT_FILE:
                        archive.write(item, Path(target.name) / item.relative_to(target))
            else:
                archive.write(target, target.name)
        audit(request, "zip", relative_path(target))
        return FileResponse(temp_name, filename=f"{target.name}.zip", media_type="application/zip", background=None)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


@app.post("/api/folder")
async def create_folder(request: Request, _auth: None = Depends(require_auth), path: str = Form("/"), name: str = Form(...)):
    parent = safe_path(path)
    try:
        target = safe_child(parent, name)
        target.mkdir(parents=False, exist_ok=False)
        audit(request, "create_folder", relative_path(target))
        return stat_item(target)
    except Exception as exc:
        raise human_error(exc)


@app.post("/api/upload")
async def upload_file(request: Request, _auth: None = Depends(require_auth), path: str = Form("/"), file: UploadFile = File(...)):
    parent = safe_path(path)
    if not parent.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    target = safe_child(parent, file.filename or "upload.bin")
    written = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    output.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
                output.write(chunk)
        audit(request, "upload", relative_path(target), {"bytes": written})
        return stat_item(target)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise human_error(exc)
    finally:
        await file.close()


@app.post("/api/save")
async def save_file(payload: dict, request: Request, _auth: None = Depends(require_auth)):
    target = safe_path(str(payload.get("path", "")))
    content = payload.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content must be a string")
    if len(content.encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the configured size limit")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.tmp-{secrets.token_hex(6)}")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, target)
        audit(request, "save", relative_path(target), {"bytes": len(content.encode('utf-8'))})
        return stat_item(target)
    except Exception as exc:
        raise human_error(exc)


@app.post("/api/rename")
async def rename_path(payload: dict, request: Request, _auth: None = Depends(require_auth)):
    source = safe_path(str(payload.get("path", "")))
    name = str(payload.get("name", ""))
    if not source.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    try:
        target = safe_child(source.parent, name)
        source.rename(target)
        audit(request, "rename", relative_path(source), {"to": relative_path(target)})
        return stat_item(target)
    except Exception as exc:
        raise human_error(exc)


@app.post("/api/move")
async def move_path(payload: dict, request: Request, _auth: None = Depends(require_auth)):
    source = safe_path(str(payload.get("path", "")))
    destination = safe_path(str(payload.get("destination", "")))
    if not source.exists() or not destination.is_dir():
        raise HTTPException(status_code=404, detail="Source or destination not found")
    try:
        target = safe_child(destination, source.name)
        shutil.move(str(source), str(target))
        audit(request, "move", relative_path(source), {"to": relative_path(target)})
        return stat_item(target)
    except Exception as exc:
        raise human_error(exc)


@app.delete("/api/file")
async def delete_path(path: str, request: Request, _auth: None = Depends(require_auth)):
    target = safe_path(path)
    if target == ROOT_DIR:
        raise HTTPException(status_code=400, detail="The root directory cannot be deleted")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        audit(request, "delete", relative_path(target))
        return {"ok": True}
    except Exception as exc:
        raise human_error(exc)


@app.post("/api/extract")
async def extract_archive(payload: dict, request: Request, _auth: None = Depends(require_auth)):
    archive = safe_path(str(payload.get("path", "")))
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="Only ZIP archives are supported")
    destination = safe_child(archive.parent, archive.stem)
    try:
        destination.mkdir(exist_ok=False)
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                member_target = (destination / member.filename).resolve()
                if member_target != destination and destination not in member_target.parents:
                    raise HTTPException(status_code=400, detail="Archive contains an unsafe path")
            zf.extractall(destination)
        audit(request, "extract", relative_path(archive), {"to": relative_path(destination)})
        return {"ok": True, "path": relative_path(destination)}
    except Exception as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise human_error(exc)


@app.get("/api/audit")
async def audit_log(request: Request, _auth: None = Depends(require_auth), limit: int = Query(100, ge=1, le=500)):
    if not AUDIT_FILE.exists():
        return {"events": []}
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
        events = [json.loads(line) for line in reversed(lines)]
        return {"events": events}
    except Exception as exc:
        raise human_error(exc)


@app.websocket("/ws/terminal")
async def terminal(websocket: WebSocket):
    session = websocket.scope.get("session", {})
    if not session.get("authenticated"):
        await websocket.close(code=4401)
        return
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if origin and host and origin.split("//", 1)[-1].split("/", 1)[0] != host:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.environ["FILE_MANAGER_ROOT"] = str(ROOT_DIR)
        os.chdir(ROOT_DIR)
        os.execv(TERMINAL_SHELL, [TERMINAL_SHELL, "-i"])
    os.set_blocking(fd, False)
    audit(None, "terminal_open")

    async def send_output():
        while True:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    await websocket.send_text(base64.b64encode(chunk).decode("ascii"))
                except (OSError, WebSocketDisconnect):
                    break
            await asyncio.sleep(0)

    output_task = asyncio.create_task(send_output())
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("text") is not None:
                payload = json.loads(message["text"])
                if payload.get("type") == "input":
                    os.write(fd, base64.b64decode(payload.get("data", "")))
                elif payload.get("type") == "resize":
                    rows = max(1, min(200, int(payload.get("rows", 30))))
                    cols = max(1, min(300, int(payload.get("cols", 120))))
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except (WebSocketDisconnect, json.JSONDecodeError, OSError):
        pass
    finally:
        output_task.cancel()
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        await asyncio.sleep(0)


@app.get("/health")
async def health():
    return {"status": "ok", "time": utc_now()}
