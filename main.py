import os
import shutil
import json
import asyncio
import fcntl
import struct
import termios
import pty
import select
import subprocess
import hashlib
import uuid
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import humanize

app = FastAPI(title="Nexus File Manager", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(os.getcwd()) / "uploads"
BASE_DIR.mkdir(exist_ok=True)
TRASH_DIR = Path(os.getcwd()) / ".trash"
TRASH_DIR.mkdir(exist_ok=True)
SHARES: Dict[str, str] = {}
RECENT_FILES: List[dict] = []

app.mount("/static", StaticFiles(directory="static"), name="static")


def secure_path(path: str) -> Path:
    requested = (BASE_DIR / path).resolve()
    try:
        requested.relative_to(BASE_DIR.resolve())
        return requested
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")


def get_file_info(file_path: Path) -> dict:
    stat = file_path.stat()
    is_dir = file_path.is_dir()
    size = 0 if is_dir else stat.st_size

    return {
        "name": file_path.name,
        "path": str(file_path.relative_to(BASE_DIR)),
        "type": "directory" if is_dir else "file",
        "size": size,
        "size_human": humanize.naturalsize(size) if not is_dir else "—",
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "modified_human": humanize.naturaltime(datetime.fromtimestamp(stat.st_mtime)),
        "permissions": oct(stat.st_mode)[-3:],
        "mime": get_mime_type(file_path) if not is_dir else "directory",
        "extension": file_path.suffix.lower(),
        "id": hashlib.md5(str(file_path).encode()).hexdigest()[:12]
    }


def get_mime_type(file_path: Path) -> str:
    ext = file_path.suffix.lower()
    mimes = {
        '.txt': 'text/plain', '.py': 'text/x-python', '.js': 'application/javascript',
        '.html': 'text/html', '.css': 'text/css', '.json': 'application/json',
        '.md': 'text/markdown', '.xml': 'application/xml', '.yaml': 'text/yaml',
        '.yml': 'text/yaml', '.csv': 'text/csv', '.ts': 'application/typescript',
        '.jsx': 'application/javascript', '.tsx': 'application/typescript',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.gif': 'image/gif', '.svg': 'image/svg+xml', '.webp': 'image/webp',
        '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
        '.pdf': 'application/pdf', '.zip': 'application/zip', '.tar': 'application/x-tar',
        '.gz': 'application/gzip', '.rar': 'application/x-rar',
        '.doc': 'application/msword', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xls': 'application/vnd.ms-excel', '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.ppt': 'application/vnd.ms-powerpoint', '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    }
    return mimes.get(ext, 'application/octet-stream')


def add_recent(file_info: dict):
    global RECENT_FILES
    RECENT_FILES = [f for f in RECENT_FILES if f["path"] != file_info["path"]]
    RECENT_FILES.insert(0, file_info)
    RECENT_FILES = RECENT_FILES[:20]


# ==================== FILE API ====================

@app.get("/api/files")
async def list_files(path: str = "", sort: str = "name", order: str = "asc"):
    target = secure_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    if target.is_file():
        return get_file_info(target)

    items = []
    try:
        for item in target.iterdir():
            if not item.name.startswith('.'):
                items.append(get_file_info(item))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    # Sorting
    reverse = order == "desc"
    if sort == "name":
        items.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()), reverse=reverse)
    elif sort == "size":
        items.sort(key=lambda x: x["size"], reverse=reverse)
    elif sort == "date":
        items.sort(key=lambda x: x["modified"], reverse=reverse)

    # Calculate directory sizes
    total_size = sum(item["size"] for item in items if item["type"] == "file")

    return {
        "current_path": path,
        "items": items,
        "parent": str(target.parent.relative_to(BASE_DIR)) if target != BASE_DIR else None,
        "total_size": total_size,
        "total_size_human": humanize.naturalsize(total_size),
        "item_count": len(items)
    }


@app.get("/api/files/recent")
async def get_recent():
    valid = []
    for f in RECENT_FILES[:10]:
        p = BASE_DIR / f["path"]
        if p.exists():
            valid.append(get_file_info(p))
    return {"items": valid}


@app.get("/api/files/stats")
async def get_stats():
    total = 0
    used = 0
    try:
        stat = os.statvfs(BASE_DIR)
        total = stat.f_blocks * stat.f_frsize
        used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
    except:
        pass

    file_count = sum(1 for _ in BASE_DIR.rglob("*") if _.is_file())
    dir_count = sum(1 for _ in BASE_DIR.rglob("*") if _.is_dir())

    return {
        "total": total,
        "used": used,
        "free": total - used,
        "total_human": humanize.naturalsize(total),
        "used_human": humanize.naturalsize(used),
        "free_human": humanize.naturalsize(total - used),
        "percent": round((used / total) * 100, 1) if total else 0,
        "files": file_count,
        "directories": dir_count
    }


@app.post("/api/files/upload")
async def upload_files(path: str = Form(""), files: List[UploadFile] = File(...)):
    target = secure_path(path)
    target.mkdir(parents=True, exist_ok=True)
    uploaded = []

    for file in files:
        file_path = target / file.filename
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
        info = get_file_info(file_path)
        uploaded.append(info)
        add_recent(info)

    return {"message": f"Uploaded {len(uploaded)} files", "files": uploaded}


@app.get("/api/files/download")
async def download_file(path: str):
    target = secure_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if target.is_file():
        return FileResponse(target, filename=target.name)

    zip_path = Path(f"/tmp/{target.name}_{uuid.uuid4().hex[:8]}.zip")
    shutil.make_archive(str(zip_path).replace('.zip', ''), 'zip', target)
    return FileResponse(zip_path, filename=f"{target.name}.zip")


@app.get("/api/files/preview")
async def preview_file(path: str):
    target = secure_path(path)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    mime = get_mime_type(target)

    if mime.startswith('image/'):
        return FileResponse(target)
    elif mime.startswith('video/'):
        return FileResponse(target, media_type=mime)
    elif mime.startswith('audio/'):
        return FileResponse(target, media_type=mime)
    elif mime == 'application/pdf':
        return FileResponse(target, media_type='application/pdf')
    elif target.stat().st_size < 10 * 1024 * 1024:
        try:
            with open(target, 'r', encoding='utf-8') as f:
                content = f.read()
            return {"type": "text", "content": content, "mime": mime}
        except:
            return {"type": "binary", "mime": mime}

    raise HTTPException(status_code=400, detail="File too large for preview")


@app.post("/api/files/mkdir")
async def create_directory(path: str, name: str):
    target = secure_path(path) / name
    target.mkdir(parents=True, exist_ok=True)
    return get_file_info(target)


@app.post("/api/files/rename")
async def rename_file(path: str, new_name: str):
    source = secure_path(path)
    dest = source.parent / new_name
    if dest.exists():
        raise HTTPException(status_code=400, detail="Already exists")
    source.rename(dest)
    return get_file_info(dest)


@app.post("/api/files/move")
async def move_files(source: str, destination: str):
    src = secure_path(source)
    dst = secure_path(destination) / src.name
    if dst.exists():
        raise HTTPException(status_code=400, detail="Already exists")
    shutil.move(str(src), str(dst))
    return get_file_info(dst)


@app.post("/api/files/copy")
async def copy_files(source: str, destination: str):
    src = secure_path(source)
    dst = secure_path(destination) / src.name
    if dst.exists():
        raise HTTPException(status_code=400, detail="Already exists")
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return get_file_info(dst)


@app.delete("/api/files/delete")
async def delete_file(path: str, permanent: bool = False):
    target = secure_path(path)

    if permanent:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"message": "Permanently deleted"}

    # Move to trash
    trash_item = TRASH_DIR / f"{uuid.uuid4().hex}_{target.name}"
    shutil.move(str(target), str(trash_item))
    return {"message": "Moved to trash"}


@app.get("/api/files/trash")
async def list_trash():
    items = []
    for item in TRASH_DIR.iterdir():
        stat = item.stat()
        original_name = '_'.join(item.name.split('_')[1:])
        items.append({
            "name": original_name,
            "trash_name": item.name,
            "path": str(item),
            "size": stat.st_size if item.is_file() else 0,
            "deleted_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return {"items": items}


@app.post("/api/files/restore")
async def restore_file(trash_name: str):
    source = TRASH_DIR / trash_name
    if not source.exists():
        raise HTTPException(status_code=404, detail="Not in trash")
    original_name = '_'.join(trash_name.split('_')[1:])
    dest = BASE_DIR / original_name
    if dest.exists():
        original_name = f"{uuid.uuid4().hex}_{original_name}"
        dest = BASE_DIR / original_name
    shutil.move(str(source), str(dest))
    return get_file_info(dest)


@app.get("/api/files/content")
async def get_file_content(path: str):
    target = secure_path(path)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    if target.stat().st_size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")
    try:
        with open(target, 'r', encoding='utf-8') as f:
            content = f.read()
        return {"content": content, "path": path, "mime": get_mime_type(target)}
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Binary file")


@app.post("/api/files/content")
async def save_file_content(path: str, content: str = Form(...)):
    target = secure_path(path)
    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
    return {"message": "Saved"}


@app.get("/api/files/search")
async def search_files(q: str, path: str = ""):
    target = secure_path(path)
    results = []
    for item in target.rglob(f"*{q}*"):
        if item.is_relative_to(BASE_DIR) and not item.name.startswith('.'):
            results.append(get_file_info(item))
            if len(results) >= 50:
                break
    return {"results": results, "count": len(results)}


@app.post("/api/files/share")
async def create_share(path: str):
    target = secure_path(path)
    share_id = uuid.uuid4().hex[:12]
    SHARES[share_id] = str(target)
    return {"share_id": share_id, "url": f"/share/{share_id}"}


@app.get("/share/{share_id}")
async def access_share(share_id: str):
    if share_id not in SHARES:
        raise HTTPException(status_code=404, detail="Share not found")
    path = SHARES[share_id]
    target = Path(path)
    if target.is_file():
        return FileResponse(target)
    return {"path": str(target.relative_to(BASE_DIR))}


# ==================== TERMINAL ====================

class TerminalSession:
    def __init__(self, websocket: WebSocket, session_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.fd = None
        self.pid = None
        self.active = True
        self.history = []

    async def start(self):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(BASE_DIR)
            os.putenv("TERM", "xterm-256color")
            os.putenv("PS1", "\[\e[38;5;81m\]nexus\[\e[0m\] \[\e[38;5;183m\]\w\[\e[0m\] \[\e[38;5;220m\]❯\[\e[0m\] ")
            os.execlp("bash", "bash", "--login")
        else:
            await self._handle_io()

    async def _handle_io(self):
        while self.active:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.05)
                if ready:
                    output = os.read(self.fd, 8192).decode('utf-8', errors='replace')
                    await self.websocket.send_json({"type": "output", "data": output})

                try:
                    msg = await asyncio.wait_for(self.websocket.receive_text(), timeout=0.05)
                    data = json.loads(msg)
                    if data.get("type") == "input":
                        os.write(self.fd, data["data"].encode())
                    elif data.get("type") == "resize":
                        self._resize(data.get("cols", 80), data.get("rows", 24))
                    elif data.get("type") == "close":
                        self.active = False
                except asyncio.TimeoutError:
                    pass
            except Exception as e:
                await self.websocket.send_json({"type": "error", "data": str(e)})
                break
        self.cleanup()

    def _resize(self, cols: int, rows: int):
        if self.fd:
            size = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, size)

    def cleanup(self):
        self.active = False
        if self.pid:
            try:
                os.kill(self.pid, 9)
            except:
                pass
        if self.fd:
            os.close(self.fd)


TERMINALS: Dict[str, TerminalSession] = {}

@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    await websocket.accept()
    session_id = uuid.uuid4().hex[:8]
    session = TerminalSession(websocket, session_id)
    TERMINALS[session_id] = session
    await websocket.send_json({"type": "connected", "session_id": session_id})
    await session.start()
    del TERMINALS[session_id]


# ==================== MAIN PAGE ====================

@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
