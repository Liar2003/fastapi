"""
Core file-manager REST API. Every route depends on get_session (read
operations) or require_csrf (anything that mutates the filesystem), and
every path that reaches the disk goes through safe_join() first.
"""
import io
import os
import shutil
import stat
import time
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .auth import SessionData, get_session, require_csrf
from .config import settings
from .security import ensure_within_root, safe_join

router = APIRouter(prefix="/api", tags=["files"])

TEXT_EDIT_MAX_BYTES = 5 * 1024 * 1024  # 5MB cap on in-browser editing
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1MB

# Extensions we consider safe to open in the text editor without sniffing.
# Anything else falls back to a binary-sniff check.
LIKELY_TEXT_EXT = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yml", ".yaml",
    ".html", ".htm", ".css", ".scss", ".xml", ".csv", ".ini", ".cfg", ".conf",
    ".sh", ".bash", ".env", ".gitignore", ".php", ".rb", ".go", ".rs", ".c",
    ".h", ".cpp", ".java", ".sql", ".log", ".toml", ".lock",
}


def _entry_meta(p: Path) -> dict:
    st = p.lstat()
    is_dir = p.is_dir() and not p.is_symlink()
    return {
        "name": p.name,
        "is_dir": is_dir,
        "is_symlink": p.is_symlink(),
        "size": 0 if is_dir else st.st_size,
        "modified": int(st.st_mtime),
        "mode": stat.filemode(st.st_mode),
    }


def _rel(path: Path) -> str:
    return str(path.relative_to(settings.ROOT_DIR)).replace("\\", "/")


# ---------------------------------------------------------------------------
# Listing / info
# ---------------------------------------------------------------------------
@router.get("/list")
def list_dir(path: str = "", session: SessionData = Depends(get_session)):
    target = safe_join(path)
    if not target.exists():
        raise HTTPException(404, "Path not found")
    if not target.is_dir():
        raise HTTPException(400, "Not a directory")

    entries = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    entries.append(_entry_meta(Path(entry.path)))
                except (FileNotFoundError, PermissionError):
                    continue
    except PermissionError:
        raise HTTPException(403, "Permission denied")

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {
        "path": path.strip("/"),
        "entries": entries,
        "root_label": settings.ROOT_DIR.name,
    }


@router.get("/info")
def info(path: str, session: SessionData = Depends(get_session)):
    target = safe_join(path)
    if not target.exists():
        raise HTTPException(404, "Path not found")
    st = target.lstat()
    return {
        **_entry_meta(target),
        "path": _rel(target),
        "owner_readable": os.access(target, os.R_OK),
        "owner_writable": os.access(target, os.W_OK),
        "created": int(getattr(st, "st_ctime", st.st_mtime)),
    }


# ---------------------------------------------------------------------------
# Create / rename / delete / move / copy
# ---------------------------------------------------------------------------
class MkdirBody(BaseModel):
    path: str = ""
    name: str


@router.post("/mkdir")
def mkdir(body: MkdirBody, session: SessionData = Depends(require_csrf)):
    if not body.name or "/" in body.name or body.name in (".", ".."):
        raise HTTPException(400, "Invalid folder name")
    parent = safe_join(body.path)
    if not parent.is_dir():
        raise HTTPException(404, "Parent folder not found")
    target = ensure_within_root(parent / body.name)
    if target.exists():
        raise HTTPException(409, "Already exists")
    target.mkdir(parents=True, exist_ok=False)
    return {"ok": True}


class RenameBody(BaseModel):
    path: str
    new_name: str


@router.post("/rename")
def rename(body: RenameBody, session: SessionData = Depends(require_csrf)):
    if not body.new_name or "/" in body.new_name or body.new_name in (".", ".."):
        raise HTTPException(400, "Invalid name")
    src = safe_join(body.path)
    if not src.exists():
        raise HTTPException(404, "Not found")
    dst = ensure_within_root(src.parent / body.new_name)
    if dst.exists():
        raise HTTPException(409, "Target already exists")
    src.rename(dst)
    return {"ok": True}


class PathsBody(BaseModel):
    paths: List[str]


@router.post("/delete")
def delete(body: PathsBody, session: SessionData = Depends(require_csrf)):
    if not body.paths:
        raise HTTPException(400, "No paths given")
    if len(body.paths) > 500:
        raise HTTPException(400, "Too many items in one request")
    results = []
    for p in body.paths:
        try:
            target = safe_join(p)
            if target == settings.ROOT_DIR:
                results.append({"path": p, "ok": False, "error": "Cannot delete root"})
                continue
            if not target.exists():
                results.append({"path": p, "ok": False, "error": "Not found"})
                continue
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
            results.append({"path": p, "ok": True})
        except Exception as exc:  # noqa: BLE001 — surface per-item errors to the client
            results.append({"path": p, "ok": False, "error": str(exc)})
    return {"results": results}


class TransferBody(BaseModel):
    paths: List[str]
    destination: str


@router.post("/move")
def move(body: TransferBody, session: SessionData = Depends(require_csrf)):
    dest_dir = safe_join(body.destination)
    if not dest_dir.is_dir():
        raise HTTPException(400, "Destination is not a directory")
    results = []
    for p in body.paths:
        try:
            src = safe_join(p)
            dst = ensure_within_root(dest_dir / src.name)
            if dst.exists():
                results.append({"path": p, "ok": False, "error": "Target already exists"})
                continue
            shutil.move(str(src), str(dst))
            results.append({"path": p, "ok": True})
        except Exception as exc:  # noqa: BLE001
            results.append({"path": p, "ok": False, "error": str(exc)})
    return {"results": results}


@router.post("/copy")
def copy(body: TransferBody, session: SessionData = Depends(require_csrf)):
    dest_dir = safe_join(body.destination)
    if not dest_dir.is_dir():
        raise HTTPException(400, "Destination is not a directory")
    results = []
    for p in body.paths:
        try:
            src = safe_join(p)
            dst = ensure_within_root(dest_dir / src.name)
            if dst.exists():
                results.append({"path": p, "ok": False, "error": "Target already exists"})
                continue
            if src.is_dir() and not src.is_symlink():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            results.append({"path": p, "ok": True})
        except Exception as exc:  # noqa: BLE001
            results.append({"path": p, "ok": False, "error": str(exc)})
    return {"results": results}


# ---------------------------------------------------------------------------
# Text read / write (in-browser editor)
# ---------------------------------------------------------------------------
def _looks_like_text(target: Path) -> bool:
    if target.suffix.lower() in LIKELY_TEXT_EXT or target.name.startswith("."):
        return True
    try:
        with open(target, "rb") as fh:
            chunk = fh.read(8192)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


@router.get("/read")
def read_file(path: str, session: SessionData = Depends(get_session)):
    target = safe_join(path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    size = target.stat().st_size
    if size > TEXT_EDIT_MAX_BYTES:
        raise HTTPException(413, f"File too large to edit in-browser ({size} bytes)")
    if not _looks_like_text(target):
        raise HTTPException(415, "File does not appear to be text")
    return {"path": _rel(target), "content": target.read_text(encoding="utf-8", errors="replace")}


class WriteBody(BaseModel):
    path: str
    content: str


@router.post("/write")
def write_file(body: WriteBody, session: SessionData = Depends(require_csrf)):
    if len(body.content.encode("utf-8")) > TEXT_EDIT_MAX_BYTES:
        raise HTTPException(413, "Content too large")
    target = safe_join(body.path)
    if target.exists() and target.is_dir():
        raise HTTPException(400, "Path is a directory")
    target.write_text(body.content, encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Upload / download
# ---------------------------------------------------------------------------
@router.post("/upload")
async def upload(
    path: str = Query(default=""),
    files: List[UploadFile] = File(...),
    session: SessionData = Depends(require_csrf),
):
    if not files:
        raise HTTPException(400, "No files provided")
    dest_dir = safe_join(path)
    if not dest_dir.is_dir():
        raise HTTPException(400, "Destination is not a directory")

    saved = []
    for f in files:
        name = os.path.basename(f.filename or "")
        if not name or name in (".", ".."):
            continue
        target = ensure_within_root(dest_dir / name)
        total = 0
        try:
            with open(target, "wb") as out:
                while chunk := await f.read(UPLOAD_CHUNK_SIZE):
                    total += len(chunk)
                    if total > settings.MAX_UPLOAD_SIZE:
                        raise HTTPException(413, f"{name} exceeds max upload size")
                    out.write(chunk)
        except HTTPException:
            target.unlink(missing_ok=True)  # don't leave a truncated file behind
            raise
        finally:
            await f.close()
        saved.append({"name": name, "size": total})
    return {"ok": True, "saved": saved}


@router.get("/download")
def download(path: str, session: SessionData = Depends(get_session)):
    target = safe_join(path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(target, filename=target.name)


@router.post("/download-zip")
def download_zip(body: PathsBody, session: SessionData = Depends(require_csrf)):
    if not body.paths:
        raise HTTPException(400, "No paths given")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in body.paths:
            target = safe_join(p)
            if not target.exists():
                continue
            if target.is_dir():
                for root, _dirs, files in os.walk(target):
                    for fname in files:
                        fpath = Path(root) / fname
                        arcname = target.name / fpath.relative_to(target)
                        zf.write(fpath, arcname)
            else:
                zf.write(target, target.name)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="files.zip"'},
    )


# ---------------------------------------------------------------------------
# Compress / extract
# ---------------------------------------------------------------------------
class CompressBody(BaseModel):
    paths: List[str]
    archive_name: str
    destination: str = ""


@router.post("/compress")
def compress(body: CompressBody, session: SessionData = Depends(require_csrf)):
    name = body.archive_name.strip()
    if not name:
        raise HTTPException(400, "Archive name required")
    if not name.lower().endswith(".zip"):
        name += ".zip"
    dest_dir = safe_join(body.destination)
    archive_path = ensure_within_root(dest_dir / name)
    if archive_path.exists():
        raise HTTPException(409, "Archive already exists")

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in body.paths:
            target = safe_join(p)
            if not target.exists():
                continue
            if target.is_dir():
                for root, _dirs, files in os.walk(target):
                    for fname in files:
                        fpath = Path(root) / fname
                        arcname = target.name / fpath.relative_to(target)
                        zf.write(fpath, arcname)
            else:
                zf.write(target, target.name)
    return {"ok": True, "archive": _rel(archive_path)}


class ExtractBody(BaseModel):
    path: str
    destination: Optional[str] = None


@router.post("/extract")
def extract(body: ExtractBody, session: SessionData = Depends(require_csrf)):
    archive_path = safe_join(body.path)
    if not archive_path.is_file() or archive_path.suffix.lower() != ".zip":
        raise HTTPException(400, "Not a .zip file")

    if body.destination is not None:
        dest_dir = safe_join(body.destination)
    else:
        dest_dir = archive_path.parent / archive_path.stem
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_dir = ensure_within_root(dest_dir)

    with zipfile.ZipFile(archive_path) as zf:
        for member in zf.infolist():
            member_path = ensure_within_root(dest_dir / member.filename)  # blocks zip-slip
            if member.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
            else:
                member_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(member_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    return {"ok": True, "destination": _rel(dest_dir)}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
@router.get("/search")
def search(path: str = "", query: str = "", session: SessionData = Depends(get_session)):
    query = query.strip().lower()
    if not query:
        return {"results": []}
    start = safe_join(path)
    results = []
    for root, dirs, files in os.walk(start):
        for name in dirs + files:
            if query in name.lower():
                full = Path(root) / name
                try:
                    meta = _entry_meta(full)
                except (FileNotFoundError, PermissionError):
                    continue
                meta["path"] = _rel(full)
                results.append(meta)
                if len(results) >= 500:
                    return {"results": results, "truncated": True}
    return {"results": results, "truncated": False}


# ---------------------------------------------------------------------------
# Permissions (Unix only — no-op / 501 on other platforms)
# ---------------------------------------------------------------------------
class ChmodBody(BaseModel):
    path: str
    mode: str  # octal string, e.g. "755"


@router.post("/chmod")
def chmod(body: ChmodBody, session: SessionData = Depends(require_csrf)):
    if os.name != "posix":
        raise HTTPException(501, "chmod is only supported on POSIX systems")
    try:
        mode = int(body.mode, 8)
        if not (0 <= mode <= 0o7777):
            raise ValueError
    except ValueError:
        raise HTTPException(400, "Mode must be an octal string like '755'")
    target = safe_join(body.path)
    if not target.exists():
        raise HTTPException(404, "Not found")
    os.chmod(target, mode)
    return {"ok": True}
