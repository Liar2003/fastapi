import os
import pty
import select
import shutil
import asyncio
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="FastAPI Advanced File Manager & Web Terminal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root directory allowed for operations (defaults to working directory)
BASE_DIR = os.path.abspath(os.getcwd())

def get_safe_path(target_path: str) -> str:
    """Ensure path stays within workspace boundaries to prevent traversal attacks."""
    abs_path = os.path.abspath(os.path.join(BASE_DIR, target_path.lstrip("/")))
    if not abs_path.startswith(BASE_DIR):
        raise HTTPException(status_code=403, detail="Access denied: Outside workspace boundary")
    return abs_path

# ================= REST API ENDPOINTS =================

@app.get("/api/files")
def list_files(path: str = ""):
    target = get_safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Path not found")
    if not os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Path is not a directory")

    items = []
    for entry in os.scandir(target):
        rel_path = os.path.relpath(entry.path, BASE_DIR)
        items.append({
            "name": entry.name,
            "path": rel_path if rel_path != "." else "",
            "is_dir": entry.is_dir(),
            "size": entry.stat().st_size if not entry.is_dir() else 0,
            "mtime": entry.stat().st_mtime
        })
    return {"path": path, "items": sorted(items, key=lambda x: (not x["is_dir"], x["name"].lower()))}

@app.get("/api/read")
def read_file(path: str):
    target = get_safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=400, detail="Not a valid file")
    try:
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save")
def save_file(path: str = Form(...), content: str = Form(...)):
    target = get_safe_path(path)
    try:
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create")
def create_item(path: str = Form(...), name: str = Form(...), is_dir: bool = Form(...)):
    target_dir = get_safe_path(path)
    target_path = os.path.join(target_dir, name)
    if os.path.exists(target_path):
        raise HTTPException(status_code=400, detail="Item already exists")
    
    if is_dir:
        os.makedirs(target_path, exist_ok=True)
    else:
        with open(target_path, "w") as f:
            f.write("")
    return {"status": "success"}

@app.post("/api/upload")
async def upload_file(path: str = Form(""), file: UploadFile = File(...)):
    target_dir = get_safe_path(path)
    file_path = os.path.join(target_dir, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "success", "filename": file.filename}

@app.delete("/api/delete")
def delete_item(path: str):
    target = get_safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Path not found")
    
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    return {"status": "success"}

@app.get("/api/download")
def download_file(path: str):
    target = get_safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(status_code=400, detail="File not found")
    return FileResponse(target, filename=os.path.basename(target))

# ================= WEB TERMINAL (WEBSOCKET + PTY) =================

@app.websocket("/ws/terminal")
async def terminal_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Fork PTY process (Linux / macOS standard)
    master_fd, slave_fd = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh")
    
    pid = os.fork()
    if pid == 0:
        # Child process
        os.setsid()
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(slave_fd)
        os.close(master_fd)
        os.chdir(BASE_DIR)
        os.execv(shell, [shell])
    else:
        # Parent process
        os.close(slave_fd)
        loop = asyncio.get_event_loop()

        async def read_from_pty():
            while True:
                await asyncio.sleep(0.01)
                r, _, _ = select.select([master_fd], [], [], 0)
                if master_fd in r:
                    try:
                        output = os.read(master_fd, 1024)
                        if not output:
                            break
                        await websocket.send_text(output.decode("utf-8", errors="ignore"))
                    except Exception:
                        break

        task = asyncio.create_task(read_from_pty())

        try:
            while True:
                data = await websocket.receive_text()
                os.write(master_fd, data.encode("utf-8"))
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()
            os.close(master_fd)
            try:
                os.kill(pid, 9)
            except OSError:
                pass

# ================= FRONTEND DASHBOARD =================

@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FastAPI File Manager & Terminal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css" />
    <script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>
</head>
<body class="bg-gray-900 text-gray-100 h-screen flex flex-col font-sans">
    
    <!-- Header -->
    <header class="bg-gray-800 border-b border-gray-700 px-6 py-3 flex justify-between items-center">
        <h1 class="text-xl font-bold text-blue-400">⚡ FastExplorer & Terminal</h1>
        <div class="flex space-x-2">
            <button onclick="showCreateModal(false)" class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded text-sm">+ File</button>
            <button onclick="showCreateModal(true)" class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded text-sm">+ Folder</button>
            <label class="bg-green-600 hover:bg-green-500 text-white px-3 py-1.5 rounded text-sm cursor-pointer">
                Upload <input type="file" id="fileInput" class="hidden" onchange="uploadFile()">
            </label>
        </div>
    </header>

    <!-- Main Content Area -->
    <div class="flex-1 flex overflow-hidden">
        <!-- File Explorer -->
        <main class="flex-1 flex flex-col border-r border-gray-700 overflow-y-auto p-4">
            <div class="text-sm mb-4 text-gray-400 flex items-center space-x-2" id="breadcrumb"></div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm text-gray-300">
                    <thead class="bg-gray-800 text-gray-400 uppercase text-xs">
                        <tr>
                            <th class="p-3">Name</th>
                            <th class="p-3">Size</th>
                            <th class="p-3">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="fileList" class="divide-y divide-gray-800"></tbody>
                </table>
            </div>
        </main>

        <!-- Editor Pane (Hidden by default) -->
        <div id="editorPane" class="w-1/2 bg-gray-950 p-4 flex-col hidden border-l border-gray-800">
            <div class="flex justify-between items-center mb-2">
                <span id="editorFilename" class="font-bold text-gray-300"></span>
                <div>
                    <button onclick="saveEditorFile()" class="bg-blue-600 text-white px-3 py-1 rounded text-xs">Save</button>
                    <button onclick="closeEditor()" class="bg-gray-700 text-white px-3 py-1 rounded text-xs ml-2">Close</button>
                </div>
            </div>
            <textarea id="fileEditor" class="w-full flex-1 bg-gray-900 border border-gray-800 rounded p-3 font-mono text-sm text-gray-100 focus:outline-none"></textarea>
        </div>
    </div>

    <!-- Web Terminal Drawer -->
    <div class="h-64 bg-black border-t border-gray-700 flex flex-col">
        <div class="bg-gray-800 px-4 py-1 text-xs text-gray-400 font-mono border-b border-gray-700">Terminal Shell</div>
        <div id="terminal" class="flex-1 p-2"></div>
    </div>

    <script>
        let currentPath = "";
        let editingPath = "";

        // Fetch & List Files
        async function loadFiles(path = "") {
            currentPath = path;
            const res = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
            const data = await res.json();
            
            // Breadcrumbs
            const parts = path.split('/').filter(Boolean);
            let bc = `<span class="cursor-pointer hover:underline text-blue-400" onclick="loadFiles('')">Root</span>`;
            let buildPath = "";
            parts.forEach((p) => {
                buildPath += "/" + p;
                bc += ` / <span class="cursor-pointer hover:underline text-blue-400" onclick="loadFiles('${buildPath}')">${p}</span>`;
            });
            document.getElementById('breadcrumb').innerHTML = bc;

            // List Table
            const tbody = document.getElementById('fileList');
            tbody.innerHTML = "";

            if (path) {
                const parentPath = parts.slice(0, -1).join('/');
                tbody.innerHTML += `
                    <tr class="hover:bg-gray-800 cursor-pointer" onclick="loadFiles('${parentPath}')">
                        <td class="p-3 text-yellow-400">📁 .. (Parent Directory)</td>
                        <td class="p-3">-</td>
                        <td class="p-3"></td>
                    </tr>`;
            }

            data.items.forEach(item => {
                const icon = item.is_dir ? '📁' : '📄';
                const sizeStr = item.is_dir ? '-' : (item.size / 1024).toFixed(1) + ' KB';
                const actionBtn = item.is_dir 
                    ? `<button onclick="event.stopPropagation(); deleteItem('${item.path}')" class="text-red-400 hover:text-red-300">Delete</button>`
                    : `<button onclick="event.stopPropagation(); editFile('${item.path}')" class="text-blue-400 hover:text-blue-300 mr-2">Edit</button>
                       <a href="/api/download?path=${encodeURIComponent(item.path)}" onclick="event.stopPropagation()" class="text-green-400 hover:text-green-300 mr-2">Download</a>
                       <button onclick="event.stopPropagation(); deleteItem('${item.path}')" class="text-red-400 hover:text-red-300">Delete</button>`;

                tbody.innerHTML += `
                    <tr class="hover:bg-gray-800 ${item.is_dir ? 'cursor-pointer' : ''}" onclick="${item.is_dir ? `loadFiles('${item.path}')` : ''}">
                        <td class="p-3 font-medium">${icon} ${item.name}</td>
                        <td class="p-3 text-gray-400">${sizeStr}</td>
                        <td class="p-3">${actionBtn}</td>
                    </tr>`;
            });
        }

        // Create File / Folder
        async function showCreateModal(isDir) {
            const name = prompt(`Enter ${isDir ? 'folder' : 'file'} name:`);
            if (!name) return;
            const formData = new FormData();
            formData.append("path", currentPath);
            formData.append("name", name);
            formData.append("is_dir", isDir);

            await fetch('/api/create', { method: 'POST', body: formData });
            loadFiles(currentPath);
        }

        // Upload File
        async function uploadFile() {
            const fileInput = document.getElementById('fileInput');
            if (!fileInput.files.length) return;

            const formData = new FormData();
            formData.append("path", currentPath);
            formData.append("file", fileInput.files[0]);

            await fetch('/api/upload', { method: 'POST', body: formData });
            fileInput.value = "";
            loadFiles(currentPath);
        }

        // Delete File/Folder
        async function deleteItem(path) {
            if (!confirm("Are you sure you want to delete this?")) return;
            await fetch(`/api/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
            loadFiles(currentPath);
        }

        // File Editor Functions
        async function editFile(path) {
            editingPath = path;
            const res = await fetch(`/api/read?path=${encodeURIComponent(path)}`);
            const data = await res.json();
            document.getElementById('editorFilename').innerText = path;
            document.getElementById('fileEditor').value = data.content;
            document.getElementById('editorPane').classList.remove('hidden');
            document.getElementById('editorPane').classList.add('flex');
        }

        async function saveEditorFile() {
            const formData = new FormData();
            formData.append("path", editingPath);
            formData.append("content", document.getElementById('fileEditor').value);
            await fetch('/api/save', { method: 'POST', body: formData });
            alert("File saved successfully!");
        }

        function closeEditor() {
            document.getElementById('editorPane').classList.add('hidden');
            document.getElementById('editorPane').classList.remove('flex');
        }

        // Initialize Web Terminal via xterm.js & WebSockets
        const term = new Terminal({ theme: { background: '#000000' } });
        term.open(document.getElementById('terminal'));
        
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/terminal`);

        socket.onmessage = (event) => term.write(event.data);
        term.onData((data) => socket.send(data));

        // Initial Load
        loadFiles();
    </script>
</body>
</html>
    """
