import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form,
    HTTPException,
)
from fastapi.responses import (
    HTMLResponse,
    FileResponse,
    JSONResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"

STORAGE_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(
    title="FastAPI File Manager",
    version="1.0.0",
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Jinja2Templates(
    directory=BASE_DIR / "templates"
)


# ---------------------------------------------------------
# Security
# ---------------------------------------------------------

def safe_path(relative_path: str = "") -> Path:
    """
    Convert a user supplied relative path into a safe path
    inside STORAGE_DIR.
    """

    relative_path = relative_path.strip()

    # Remove leading slashes
    relative_path = relative_path.lstrip("/")

    target = (STORAGE_DIR / relative_path).resolve()

    try:
        target.relative_to(STORAGE_DIR.resolve())
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Invalid path",
        )

    return target


def relative_path(path: Path) -> str:
    return str(
        path.resolve()
        .relative_to(STORAGE_DIR.resolve())
    ).replace("\\", "/")


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def human_size(size: int) -> str:

    units = [
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    ]

    value = float(size)

    for unit in units:
        if value < 1024:
            return f"{value:.1f} {unit}"

        value /= 1024

    return f"{value:.1f} PB"


def file_info(path: Path) -> dict:

    stat = path.stat()

    return {
        "name": path.name,
        "path": relative_path(path),
        "type": "directory" if path.is_dir() else "file",
        "size": stat.st_size if path.is_file() else 0,
        "size_human": human_size(stat.st_size)
        if path.is_file()
        else "-",
        "modified": stat.st_mtime,
    }


# ---------------------------------------------------------
# Frontend
# ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


# ---------------------------------------------------------
# List files
# ---------------------------------------------------------

@app.get("/api/files")
async def list_files(path: str = ""):

    directory = safe_path(path)

    if not directory.exists():
        raise HTTPException(
            status_code=404,
            detail="Directory not found",
        )

    if not directory.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Not a directory",
        )

    items = []

    for item in directory.iterdir():

        try:
            info = file_info(item)
            items.append(info)

        except OSError:
            continue

    # Directories first
    items.sort(
        key=lambda x: (
            x["type"] != "directory",
            x["name"].lower(),
        )
    )

    return {
        "path": relative_path(directory)
        if directory != STORAGE_DIR
        else "",
        "items": items,
    }


# ---------------------------------------------------------
# Upload
# ---------------------------------------------------------

@app.post("/api/upload")
async def upload_file(
    path: str = Form(""),
    file: UploadFile = File(...),
):

    directory = safe_path(path)

    if not directory.exists():
        raise HTTPException(
            status_code=404,
            detail="Directory not found",
        )

    if not directory.is_dir():
        raise HTTPException(
            status_code=400,
            detail="Invalid directory",
        )

    filename = Path(file.filename or "").name

    if not filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename",
        )

    destination = safe_path(
        relative_path(directory / filename)
    )

    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail="File already exists",
        )

    with destination.open("wb") as buffer:

        while True:

            chunk = await file.read(1024 * 1024)

            if not chunk:
                break

            buffer.write(chunk)

    return {
        "success": True,
        "message": "File uploaded",
        "file": file_info(destination),
    }


# ---------------------------------------------------------
# Create directory
# ---------------------------------------------------------

@app.post("/api/mkdir")
async def create_directory(
    path: str = Form(""),
    name: str = Form(...),
):

    directory = safe_path(path)

    name = Path(name).name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Invalid folder name",
        )

    target = safe_path(
        relative_path(directory / name)
    )

    if target.exists():
        raise HTTPException(
            status_code=409,
            detail="Already exists",
        )

    target.mkdir(parents=False)

    return {
        "success": True,
        "message": "Folder created",
    }


# ---------------------------------------------------------
# Rename
# ---------------------------------------------------------

@app.post("/api/rename")
async def rename_item(
    path: str = Form(...),
    new_name: str = Form(...),
):

    source = safe_path(path)

    if not source.exists():
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    new_name = Path(new_name).name.strip()

    if not new_name:
        raise HTTPException(
            status_code=400,
            detail="Invalid name",
        )

    destination = safe_path(
        relative_path(
            source.parent / new_name
        )
    )

    if destination.exists():
        raise HTTPException(
            status_code=409,
            detail="Destination already exists",
        )

    source.rename(destination)

    return {
        "success": True,
        "message": "Renamed successfully",
    }


# ---------------------------------------------------------
# Delete
# ---------------------------------------------------------

@app.delete("/api/delete")
async def delete_item(path: str):

    target = safe_path(path)

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    # Never allow deleting storage root
    if target == STORAGE_DIR.resolve():
        raise HTTPException(
            status_code=403,
            detail="Cannot delete root",
        )

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    return {
        "success": True,
        "message": "Deleted successfully",
    }


# ---------------------------------------------------------
# Download
# ---------------------------------------------------------

@app.get("/api/download")
async def download_file(path: str):

    target = safe_path(path)

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    if not target.is_file():
        raise HTTPException(
            status_code=400,
            detail="Not a file",
        )

    return FileResponse(
        path=target,
        filename=target.name,
    )


# ---------------------------------------------------------
# ZIP download
# ---------------------------------------------------------

@app.get("/api/download-zip")
async def download_zip(path: str):

    target = safe_path(path)

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    zip_name = target.name + ".zip"

    temp_zip = STORAGE_DIR / (
        ".tmp_" + zip_name
    )

    if temp_zip.exists():
        temp_zip.unlink()

    with zipfile.ZipFile(
        temp_zip,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as zip_file:

        if target.is_file():

            zip_file.write(
                target,
                arcname=target.name,
            )

        else:

            for item in target.rglob("*"):

                if item.is_file():

                    zip_file.write(
                        item,
                        arcname=item.relative_to(
                            target.parent
                        ),
                    )

    return FileResponse(
        path=temp_zip,
        filename=zip_name,
        media_type="application/zip",
    )


# ---------------------------------------------------------
# File information
# ---------------------------------------------------------

@app.get("/api/info")
async def get_info(path: str):

    target = safe_path(path)

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="Not found",
        )

    return file_info(target)


# ---------------------------------------------------------
# Text editor
# ---------------------------------------------------------

ALLOWED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".py",
    ".php",
    ".xml",
    ".yml",
    ".yaml",
    ".env",
    ".sql",
    ".csv",
    ".log",
}


@app.get("/api/read")
async def read_file(path: str):

    target = safe_path(path)

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    if not target.is_file():
        raise HTTPException(
            status_code=400,
            detail="Not a file",
        )

    if (
        target.suffix.lower()
        not in ALLOWED_TEXT_EXTENSIONS
        and target.name != ".env"
    ):
        raise HTTPException(
            status_code=400,
            detail="File type cannot be edited",
        )

    try:

        content = target.read_text(
            encoding="utf-8"
        )

    except UnicodeDecodeError:

        raise HTTPException(
            status_code=400,
            detail="Binary file",
        )

    return {
        "path": relative_path(target),
        "content": content,
    }


@app.put("/api/write")
async def write_file(
    path: str = Form(...),
    content: str = Form(...),
):

    target = safe_path(path)

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    if not target.is_file():
        raise HTTPException(
            status_code=400,
            detail="Not a file",
        )

    if (
        target.suffix.lower()
        not in ALLOWED_TEXT_EXTENSIONS
        and target.name != ".env"
    ):
        raise HTTPException(
            status_code=400,
            detail="File type cannot be edited",
        )

    target.write_text(
        content,
        encoding="utf-8",
    )

    return {
        "success": True,
        "message": "File saved",
    }


# ---------------------------------------------------------
# Storage statistics
# ---------------------------------------------------------

@app.get("/api/storage")
async def storage_stats():

    total_size = 0
    file_count = 0
    folder_count = 0

    for item in STORAGE_DIR.rglob("*"):

        try:

            if item.is_file():

                file_count += 1
                total_size += item.stat().st_size

            elif item.is_dir():

                folder_count += 1

        except OSError:
            pass

    return {
        "files": file_count,
        "folders": folder_count,
        "size": total_size,
        "size_human": human_size(total_size),
    }