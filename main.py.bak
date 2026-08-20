import os
import sys
import json
import asyncio
import shutil
import zipfile
import tempfile
import subprocess
import signal
import struct
import fcntl
import termios
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Advanced File Manager")

# Root directory for file operations (set via env ROOT_DIR, default: home directory)
ROOT_DIR = Path(os.getenv("ROOT_DIR", str(Path.home()))).resolve()
if not ROOT_DIR.exists():
    ROOT_DIR = Path.home().resolve()

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

def safe_path(relative_path: str = "") -> Path:
    """Resolve a relative path safely inside ROOT_DIR."""
    rel = relative_path.lstrip("/")
    if rel == "":
        return ROOT_DIR
    p = (ROOT_DIR / rel).resolve()
    # If ROOT_DIR is "/", all paths are allowed; otherwise enforce containment
    if str(ROOT_DIR) != "/" and not str(p).startswith(str(ROOT_DIR) + os.sep):
        raise HTTPException(status_code=403, detail="Access denied")
    return p


def get_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def file_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": get_relative_path(path),
        "is_dir": path.is_dir(),
        "size": stat.st_size if path.is_file() else 0,
        "size_human": format_size(stat.st_size) if path.is_file() else "",
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
    }


# -----------------------------------------------------------------------------
# Frontend (single HTML page)
# -----------------------------------------------------------------------------

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FastAPI File Manager</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; height: 100vh; display: flex; flex-direction: column; background: #1e1e1e; color: #ccc; }
        #toolbar {
            display: flex; align-items: center; gap: 8px; padding: 8px; background: #2d2d2d;
            flex-wrap: wrap; border-bottom: 1px solid #444;
        }
        #toolbar button {
            background: #3c3c3c; color: #ccc; border: 1px solid #555; padding: 6px 10px;
            cursor: pointer; border-radius: 3px;
        }
        #toolbar button:hover { background: #505050; }
        #pathInput {
            flex: 1; min-width: 200px; padding: 6px; background: #1e1e1e; color: #ccc;
            border: 1px solid #555; border-radius: 3px;
        }
        #main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        #filePanel { flex: 3; overflow: auto; }
        #terminalPanel { flex: 2; border-top: 2px solid #444; background: #000; min-height: 150px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #333; }
        th { background: #2d2d2d; position: sticky; top: 0; }
        tr:hover { background: #333; }
        tr.selected { background: #444; }
        .actions button { margin-right: 4px; background: #3c3c3c; color: #ccc; border: 1px solid #555; padding: 3px 6px; cursor: pointer; border-radius: 2px; }
        .actions button:hover { background: #505050; }
        #editorModal {
            display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.7); z-index: 100; align-items: center; justify-content: center;
        }
        #editorBox {
            background: #2d2d2d; padding: 20px; border-radius: 5px; width: 80%; height: 80%;
            display: flex; flex-direction: column;
        }
        #editorBox textarea {
            flex: 1; background: #1e1e1e; color: #ccc; border: 1px solid #555;
            resize: none; font-family: monospace; padding: 10px;
        }
        #editorBox button { margin-top: 10px; padding: 8px; background: #3c3c3c; color: #ccc; border: 1px solid #555; cursor: pointer; }
        #editorBox button:hover { background: #505050; }
    </style>
</head>
<body>
    <div id="toolbar">
        <button onclick="goUp()">⬆ Up</button>
        <button onclick="refresh()">Refresh</button>
        <input id="pathInput" placeholder="Path" onkeydown="if(event.key==='Enter') goToPath()">
        <button onclick="goToPath()">Go</button>
        <span style="flex:1"></span>
        <input type="file" id="fileInput" multiple style="display:none" onchange="uploadFiles()">
        <button onclick="document.getElementById('fileInput').click()">Upload</button>
        <button onclick="newFolder()">New Folder</button>
        <button onclick="renameSelected()">Rename</button>
        <button onclick="deleteSelected()">Delete</button>
        <button onclick="downloadSelected()">Download</button>
        <button onclick="copyMove('copy')">Copy To...</button>
        <button onclick="copyMove('move')">Move To...</button>
    </div>
    <div id="main">
        <div id="filePanel">
            <table id="fileTable">
                <thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead>
                <tbody></tbody>
            </table>
        </div>
        <div id="terminalPanel">
            <div id="terminal" style="height:100%;"></div>
        </div>
    </div>

    <div id="editorModal">
        <div id="editorBox">
            <h3 id="editorTitle">Edit File</h3>
            <textarea id="editorContent" spellcheck="false"></textarea>
            <div>
                <button onclick="saveFile()">Save</button>
                <button onclick="closeEditor()">Cancel</button>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.8.0/lib/addon-fit.min.js"></script>
    <script>
        let currentPath = '';
        let selectedPath = null;
        let editingPath = null;

        // ------------------------------------------------------------------
        // File manager functions
        // ------------------------------------------------------------------
        function refresh() {
            loadDir(currentPath);
        }

        function loadDir(path) {
            fetch('/api/list?path=' + encodeURIComponent(path))
                .then(r => r.json())
                .then(data => {
                    currentPath = data.current_path;
                    document.getElementById('pathInput').value = currentPath;
                    renderTable(data.items);
                })
                .catch(err => alert('Error: ' + err));
        }

        function renderTable(items) {
            const tbody = document.querySelector('#fileTable tbody');
            tbody.innerHTML = '';
            items.forEach(item => {
                const tr = document.createElement('tr');
                tr.onclick = () => {
                    document.querySelectorAll('#fileTable tbody tr').forEach(r => r.classList.remove('selected'));
                    tr.classList.add('selected');
                    selectedPath = item.path;
                };
                tr.ondblclick = () => {
                    if (item.is_dir) loadDir(item.path);
                    else downloadItem(item.path);
                };
                tr.innerHTML = `
                    <td>${item.is_dir ? '📁' : '📄'} ${item.name}</td>
                    <td>${item.size_human || ''}</td>
                    <td>${item.modified}</td>
                    <td class="actions">
                        <button onclick="event.stopPropagation(); openItem('${item.path}', ${item.is_dir})">Open</button>
                        ${!item.is_dir ? `<button onclick="event.stopPropagation(); editFile('${item.path}')">Edit</button>` : ''}
                        <button onclick="event.stopPropagation(); renameItem('${item.path}')">Rename</button>
                        <button onclick="event.stopPropagation(); deleteItem('${item.path}')">Delete</button>
                        <button onclick="event.stopPropagation(); downloadItem('${item.path}')">Download</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        function openItem(path, isDir) {
            if (isDir) loadDir(path);
            else downloadItem(path);
        }

        function goUp() {
            if (currentPath.includes('/')) {
                const parts = currentPath.split('/');
                parts.pop();
                loadDir(parts.join('/'));
            } else {
                loadDir('');
            }
        }

        function goToPath() {
            loadDir(document.getElementById('pathInput').value);
        }

        function uploadFiles() {
            const input = document.getElementById('fileInput');
            if (!input.files.length) return;
            const formData = new FormData();
            for (const file of input.files) {
                formData.append('files', file);
            }
            fetch('/api/upload?path=' + encodeURIComponent(currentPath), {
                method: 'POST',
                body: formData
            })
            .then(r => r.json())
            .then(() => {
                input.value = '';
                refresh();
            })
            .catch(err => alert('Upload failed: ' + err));
        }

        function newFolder() {
            const name = prompt('Folder name:');
            if (!name) return;
            fetch('/api/mkdir', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: currentPath, name: name})
            })
            .then(r => r.json())
            .then(() => refresh())
            .catch(err => alert('Error: ' + err));
        }

        function renameItem(path) {
            const newName = prompt('New name:', path.split('/').pop());
            if (!newName) return;
            fetch('/api/rename', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: path, new_name: newName})
            })
            .then(r => r.json())
            .then(() => refresh())
            .catch(err => alert('Error: ' + err));
        }

        function deleteItem(path) {
            if (!confirm('Delete ' + path + '?')) return;
            fetch('/api/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: path})
            })
            .then(r => r.json())
            .then(() => refresh())
            .catch(err => alert('Error: ' + err));
        }

        function downloadItem(path) {
            window.location.href = '/api/download?path=' + encodeURIComponent(path);
        }

        function renameSelected() {
            if (!selectedPath) return alert('Select an item first');
            renameItem(selectedPath);
        }

        function deleteSelected() {
            if (!selectedPath) return alert('Select an item first');
            deleteItem(selectedPath);
        }

        function downloadSelected() {
            if (!selectedPath) return alert('Select an item first');
            downloadItem(selectedPath);
        }

        function copyMove(op) {
            if (!selectedPath) return alert('Select an item first');
            const dest = prompt('Destination directory path (relative to root):', currentPath);
            if (dest === null) return;
            fetch('/api/' + op, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({src: selectedPath, dst: dest})
            })
            .then(r => r.json())
            .then(() => refresh())
            .catch(err => alert('Error: ' + err));
        }

        function editFile(path) {
            editingPath = path;
            fetch('/api/read?path=' + encodeURIComponent(path))
                .then(r => r.json())
                .then(data => {
                    document.getElementById('editorTitle').textContent = 'Editing: ' + path;
                    document.getElementById('editorContent').value = data.content;
                    document.getElementById('editorModal').style.display = 'flex';
                })
                .catch(err => alert('Cannot read file: ' + err));
        }

        function saveFile() {
            if (!editingPath) return;
            const content = document.getElementById('editorContent').value;
            fetch('/api/write', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({path: editingPath, content: content})
            })
            .then(r => r.json())
            .then(() => {
                closeEditor();
                refresh();
            })
            .catch(err => alert('Save failed: ' + err));
        }

        function closeEditor() {
            document.getElementById('editorModal').style.display = 'none';
            editingPath = null;
        }

        // ------------------------------------------------------------------
        // Web terminal
        // ------------------------------------------------------------------
        const term = new Terminal({
            cursorBlink: true,
            fontSize: 14,
            theme: { background: '#000000', foreground: '#cccccc' }
        });
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        fitAddon.fit();

        const wsProtocol = location.protocol === 'https:' ? 'wss://' : 'ws://';
        const ws = new WebSocket(wsProtocol + location.host + '/ws/terminal');

        ws.onopen = () => {
            term.write('\\r\\n*** Web terminal connected ***\\r\\n');
            ws.send(JSON.stringify({type: 'resize', cols: term.cols, rows: term.rows}));
        };

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === 'output') {
                term.write(msg.data);
            }
        };

        ws.onclose = () => {
            term.write('\\r\\n*** Terminal disconnected ***\\r\\n');
        };

        term.onData(data => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'input', data: data}));
            }
        });

        window.addEventListener('resize', () => {
            fitAddon.fit();
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({type: 'resize', cols: term.cols, rows: term.rows}));
            }
        });

        // Initial load
        loadDir('');
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(HTML_CONTENT)


# -----------------------------------------------------------------------------
# File API endpoints
# -----------------------------------------------------------------------------

@app.get("/api/list")
async def list_dir(path: str = ""):
    p = safe_path(path)
    if not p.exists():
        raise HTTPException(404, "Path not found")
    if not p.is_dir():
        raise HTTPException(400, "Not a directory")
    items = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                items.append(file_info(entry))
            except OSError:
                continue
    except PermissionError:
        raise HTTPException(403, "Permission denied")
    return {
        "current_path": get_relative_path(p),
        "parent": get_relative_path(p.parent) if p != ROOT_DIR else "",
        "items": items
    }


@app.post("/api/upload")
async def upload(path: str = "", files: List[UploadFile] = File(...)):
    p = safe_path(path)
    if not p.is_dir():
        raise HTTPException(400, "Target is not a directory")
    saved = []
    for f in files:
        # Use basename to prevent path traversal
        filename = Path(f.filename).name
        dest = p / filename
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)
        saved.append(filename)
    return {"saved": saved}


@app.get("/api/download")
async def download(path: str = ""):
    p = safe_path(path)
    if not p.exists():
        raise HTTPException(404, "Not found")
    if p.is_dir():
        # Create zip stream
        zip_buffer = tempfile.SpooledTemporaryFile()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file in p.rglob('*'):
                if file.is_file():
                    zf.write(file, file.relative_to(p))
        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={p.name}.zip"}
        )
    else:
        return FileResponse(p, filename=p.name)


class RenameRequest(BaseModel):
    path: str
    new_name: str

@app.post("/api/rename")
async def rename(req: RenameRequest):
    p = safe_path(req.path)
    if not p.exists():
        raise HTTPException(404, "Not found")
    new_path = p.parent / req.new_name
    if new_path.exists():
        raise HTTPException(400, "Target already exists")
    p.rename(new_path)
    return {"ok": True, "new_path": get_relative_path(new_path)}


class PathRequest(BaseModel):
    path: str

@app.post("/api/delete")
async def delete(req: PathRequest):
    p = safe_path(req.path)
    if not p.exists():
        raise HTTPException(404, "Not found")
    if p == ROOT_DIR:
        raise HTTPException(400, "Cannot delete root directory")
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    return {"ok": True}


class MkdirRequest(BaseModel):
    path: str
    name: str

@app.post("/api/mkdir")
async def mkdir(req: MkdirRequest):
    parent = safe_path(req.path)
    if not parent.is_dir():
        raise HTTPException(400, "Parent is not a directory")
    new_dir = parent / req.name
    if new_dir.exists():
        raise HTTPException(400, "Already exists")
    new_dir.mkdir(parents=False)
    return {"ok": True}


class CopyMoveRequest(BaseModel):
    src: str
    dst: str

@app.post("/api/move")
async def move(req: CopyMoveRequest):
    src = safe_path(req.src)
    dst_dir = safe_path(req.dst)
    if not src.exists():
        raise HTTPException(404, "Source not found")
    if not dst_dir.is_dir():
        raise HTTPException(400, "Destination is not a directory")
    dst = dst_dir / src.name
    if dst.exists():
        raise HTTPException(400, "Destination already exists")
    shutil.move(str(src), str(dst))
    return {"ok": True}


@app.post("/api/copy")
async def copy(req: CopyMoveRequest):
    src = safe_path(req.src)
    dst_dir = safe_path(req.dst)
    if not src.exists():
        raise HTTPException(404, "Source not found")
    if not dst_dir.is_dir():
        raise HTTPException(400, "Destination is not a directory")
    dst = dst_dir / src.name
    if dst.exists():
        raise HTTPException(400, "Destination already exists")
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return {"ok": True}


@app.get("/api/read")
async def read_file(path: str = ""):
    p = safe_path(path)
    if not p.is_file():
        raise HTTPException(400, "Not a file")
    try:
        content = p.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise HTTPException(400, "Binary file not supported for reading")
    return {"content": content}


class WriteRequest(BaseModel):
    path: str
    content: str

@app.post("/api/write")
async def write_file(req: WriteRequest):
    p = safe_path(req.path)
    if not p.is_file():
        raise HTTPException(400, "Not a file")
    p.write_text(req.content, encoding='utf-8')
    return {"ok": True}


# -----------------------------------------------------------------------------
# Web terminal WebSocket endpoint
# -----------------------------------------------------------------------------

@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    await websocket.accept()

    if sys.platform == "win32":
        await websocket.send_text(json.dumps({"type": "output", "data": "Terminal not supported on Windows."}))
        await websocket.close()
        return

    # Spawn a shell inside a PTY
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["/bin/bash"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        env={**os.environ, "TERM": "xterm-256color", "COLUMNS": "80", "LINES": "24"},
        cwd=str(ROOT_DIR)
    )
    os.close(slave)

    # Set master to non-blocking
    flags = fcntl.fcntl(master, fcntl.F_GETFL)
    fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    loop = asyncio.get_event_loop()
    output_queue = asyncio.Queue()

    def on_output():
        try:
            data = os.read(master, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if data:
            output_queue.put_nowait(data)
        else:
            output_queue.put_nowait(None)

    loop.add_reader(master, on_output)

    async def send_output():
        try:
            while True:
                data = await output_queue.get()
                if data is None:
                    break
                await websocket.send_text(json.dumps({"type": "output", "data": data.decode('utf-8', 'replace')}))
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    send_task = asyncio.create_task(send_output())

    try:
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
            except:
                continue
            if data.get("type") == "input":
                input_data = data.get("data", "")
                os.write(master, input_data.encode())
            elif data.get("type") == "resize":
                cols = int(data.get("cols", 80))
                rows = int(data.get("rows", 24))
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(master, termios.TIOCSWINSZ, winsize)
    except WebSocketDisconnect:
        pass
    finally:
        loop.remove_reader(master)
        send_task.cancel()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except:
            pass
        try:
            os.close(master)
        except:
            pass
        try:
            await send_task
        except asyncio.CancelledError:
            pass
