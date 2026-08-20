import os
import pty
import shutil
import asyncio
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

app = FastAPI(title="Advanced FastAPI File Manager & Terminal")

# Base directory for the file browser (Defaults to current working directory)
BASE_DIR = Path(os.getenv("BASE_DIR", ".")).resolve()

def resolve_safe_path(rel_path: str) -> Path:
    """Resolves relative path and prevents escaping BASE_DIR."""
    target = (BASE_DIR / rel_path.lstrip("/")).resolve()
    if not str(target).startswith(str(BASE_DIR)):
        raise HTTPException(status_code=403, detail="Access denied: Outside root scope.")
    return target

# --- Pydantic Models ---
class CreateFolderSchema(BaseModel):
    path: str
    folder_name: str

class SaveFileSchema(BaseModel):
    path: str
    content: str

class DeleteItemSchema(BaseModel):
    path: str

# --- File Manager API Endpoints ---
@app.get("/api/files")
async def list_directory(path: str = ""):
    target = resolve_safe_path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    items = []
    for entry in sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower())):
        rel = str(Path(entry.path).relative_to(BASE_DIR)).replace("\\", "/")
        items.append({
            "name": entry.name,
            "path": rel,
            "is_dir": entry.is_dir(),
            "size": round(entry.stat().st_size / 1024, 2) if entry.is_file() else 0
        })

    current_rel = str(target.relative_to(BASE_DIR)).replace("\\", "/")
    return {"current_path": current_rel if current_rel != "." else "", "items": items}

@app.get("/api/file/read")
async def read_file(path: str):
    target = resolve_safe_path(path)
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    try:
        content = target.read_text(encoding="utf-8")
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {str(e)}")

@app.post("/api/file/save")
async def save_file(data: SaveFileSchema):
    target = resolve_safe_path(data.path)
    try:
        target.write_text(data.content, encoding="utf-8")
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot save file: {str(e)}")

@app.post("/api/folder/create")
async def create_folder(data: CreateFolderSchema):
    target = resolve_safe_path(data.path) / data.folder_name
    target.mkdir(parents=True, exist_ok=True)
    return {"status": "success"}

@app.post("/api/upload")
async def upload_file(path: str = Query(""), file: UploadFile = File(...)):
    target_dir = resolve_safe_path(path)
    file_path = target_dir / file.filename
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success"}

@app.get("/api/download")
async def download_file(path: str):
    target = resolve_safe_path(path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=target, filename=target.name)

@app.post("/api/delete")
async def delete_item(data: DeleteItemSchema):
    target = resolve_safe_path(data.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"status": "success"}

# --- WebSocket Web Terminal Endpoint (Linux/Unix PTY) ---
@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    
    # Spawn interactive shell inside PTY pseudo-terminal
    master_fd, slave_fd = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash")
    if not os.path.exists(shell):
        shell = "/bin/sh"

    pid = os.fork()
    if pid == 0:
        # Child Process
        os.close(master_fd)
        os.setsid()
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execv(shell, [shell])
    else:
        # Parent Process
        os.close(slave_fd)
        loop = asyncio.get_running_loop()

        async def read_pty():
            try:
                while True:
                    data = await loop.run_in_executor(None, os.read, master_fd, 1024)
                    if not data:
                        break
                    await websocket.send_text(data.decode("utf-8", errors="ignore"))
            except Exception:
                pass

        read_task = asyncio.create_task(read_pty())

        try:
            while True:
                msg = await websocket.receive_text()
                os.write(master_fd, msg.encode("utf-8"))
        except WebSocketDisconnect:
            pass
        finally:
            read_task.cancel()
            os.close(master_fd)
            try:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
            except Exception:
                pass

# --- Front-End Single Page Application (SPA) ---
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>FastAPI Advanced File Manager & Web Terminal</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
        <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
        <style>
            * { box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 0; background: #1e1e1e; color: #d4d4d4; }
            .header { display: flex; background: #252526; border-bottom: 1px solid #3c3c3c; }
            .tab-btn { padding: 12px 24px; background: none; border: none; color: #888; cursor: pointer; font-size: 14px; font-weight: bold; }
            .tab-btn.active { color: #fff; border-bottom: 2px solid #0e639c; background: #1e1e1e; }
            .container { padding: 20px; }
            .tab-content { display: none; }
            .tab-content.active { display: block; }
            .toolbar { display: flex; gap: 10px; margin-bottom: 15px; align-items: center; }
            input[type="text"], button { padding: 8px 12px; background: #3c3c3c; border: 1px solid #555; color: white; border-radius: 4px; }
            button { cursor: pointer; background: #0e639c; border: none; }
            button:hover { background: #1177bb; }
            table { width: 100%; border-collapse: collapse; background: #252526; border-radius: 6px; overflow: hidden; }
            th, td { padding: 10px 15px; text-align: left; border-bottom: 1px solid #3c3c3c; }
            th { background: #2d2d2d; }
            a.item-link { color: #4ec9b0; text-decoration: none; cursor: pointer; }
            a.item-link:hover { text-decoration: underline; }
            #editor-modal { display:none; fixed: true; position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); padding: 40px; }
            .modal-box { background:#252526; height:100%; display:flex; flex-direction:column; padding:20px; border-radius:8px; }
            textarea { flex:1; background:#1e1e1e; color:#d4d4d4; font-family: monospace; padding:10px; border:1px solid #3c3c3c; resize:none; margin: 10px 0; }
            #terminal-container { height: 75vh; background: #000; padding: 10px; border-radius: 6px; }
        </style>
    </head>
    <body>
        <div class="header">
            <button class="tab-btn active" onclick="switchTab('files')">📁 File Manager</button>
            <button class="tab-btn" onclick="switchTab('terminal')">💻 Web Terminal</button>
        </div>

        <div class="container">
            <!-- FILE MANAGER TAB -->
            <div id="tab-files" class="tab-content active">
                <div class="toolbar">
                    <button onclick="loadFiles(currentPath)">🔄 Refresh</button>
                    <button onclick="createFolder()">📁 New Folder</button>
                    <input type="file" id="upload-input" style="display:none" onchange="uploadFile()">
                    <button onclick="document.getElementById('upload-input').click()">⬆️ Upload</button>
                    <span id="breadcrumb" style="margin-left:15px; font-weight:bold;">/</span>
                </div>
                <table>
                    <thead>
                        <tr><th>Name</th><th>Size</th><th>Actions</th></tr>
                    </thead>
                    <tbody id="file-list"></tbody>
                </table>
            </div>

            <!-- TERMINAL TAB -->
            <div id="tab-terminal" class="tab-content">
                <div id="terminal-container"></div>
            </div>
        </div>

        <!-- EDITOR MODAL -->
        <div id="editor-modal">
            <div class="modal-box">
                <h3 id="editor-title" style="margin:0;">Edit File</h3>
                <textarea id="editor-content"></textarea>
                <div>
                    <button onclick="saveFile()">Save</button>
                    <button onclick="closeEditor()" style="background:#e74c3c">Cancel</button>
                </div>
            </div>
        </div>

        <script>
            let currentPath = "";
            let editingFilePath = "";
            let term, socket;

            function switchTab(tab) {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                if(tab === 'files') {
                    document.querySelectorAll('.tab-btn')[0].classList.add('active');
                    document.getElementById('tab-files').classList.add('active');
                } else {
                    document.querySelectorAll('.tab-btn')[1].classList.add('active');
                    document.getElementById('tab-terminal').classList.add('active');
                    if (!term) initTerminal();
                }
            }

            async function loadFiles(path = "") {
                currentPath = path;
                document.getElementById('breadcrumb').innerText = "/" + path;
                const res = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
                const data = await res.json();
                const tbody = document.getElementById('file-list');
                tbody.innerHTML = "";

                if (path !== "") {
                    const parentPath = path.split('/').slice(0, -1).join('/');
                    tbody.innerHTML += `<tr><td colspan="3"><a class="item-link" onclick="loadFiles('${parentPath}')">📁 .. (Parent Directory)</a></td></tr>`;
                }

                data.items.forEach(item => {
                    const icon = item.is_dir ? '📁' : '📄';
                    const actionHtml = item.is_dir ? 
                        `<button onclick="deleteItem('${item.path}')" style="background:#e74c3c">Delete</button>` :
                        `<button onclick="openEditor('${item.path}')">Edit</button> 
                         <a href="/api/download?path=${encodeURIComponent(item.path)}"><button style="background:#2ecc71">Download</button></a>
                         <button onclick="deleteItem('${item.path}')" style="background:#e74c3c">Delete</button>`;
                    
                    const nameClick = item.is_dir ? `loadFiles('${item.path}')` : `openEditor('${item.path}')`;
                    tbody.innerHTML += `
                        <tr>
                            <td>${icon} <a class="item-link" onclick="${nameClick}">${item.name}</a></td>
                            <td>${item.is_dir ? '-' : item.size + ' KB'}</td>
                            <td>${actionHtml}</td>
                        </tr>`;
                });
            }

            async function createFolder() {
                const name = prompt("Folder name:");
                if (!name) return;
                await fetch('/api/folder/create', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ path: currentPath, folder_name: name })
                });
                loadFiles(currentPath);
            }

            async function uploadFile() {
                const input = document.getElementById('upload-input');
                if (!input.files[0]) return;
                const formData = new FormData();
                formData.append('file', input.files[0]);
                await fetch(`/api/upload?path=${encodeURIComponent(currentPath)}`, { method: 'POST', body: formData });
                input.value = "";
                loadFiles(currentPath);
            }

            async function openEditor(filePath) {
                editingFilePath = filePath;
                const res = await fetch(`/api/file/read?path=${encodeURIComponent(filePath)}`);
                const data = await res.json();
                document.getElementById('editor-title').innerText = "Edit: " + filePath;
                document.getElementById('editor-content').value = data.content;
                document.getElementById('editor-modal').style.display = 'block';
            }

            function closeEditor() { document.getElementById('editor-modal').style.display = 'none'; }

            async function saveFile() {
                const content = document.getElementById('editor-content').value;
                await fetch('/api/file/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ path: editingFilePath, content: content })
                });
                closeEditor();
                loadFiles(currentPath);
            }

            async function deleteItem(path) {
                if(!confirm(`Delete ${path}?`)) return;
                await fetch('/api/delete', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ path: path })
                });
                loadFiles(currentPath);
            }

            function initTerminal() {
                term = new Terminal({ cursorBlink: true, theme: { background: '#000000' } });
                term.open(document.getElementById('terminal-container'));
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                socket = new WebSocket(`${protocol}//${window.location.host}/ws/terminal`);

                socket.onmessage = (event) => term.write(event.data);
                term.onData((data) => socket.send(data));
            }

            // Initial load
            loadFiles();
        </script>
    </body>
    </html>
    """
