import os
import asyncio
from fastapi import FastAPI, WebSocket, UploadFile, File, HTTPException, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI()

# Mount static files for the frontend UI
app.mount("/static", StaticFiles(directory="static"), name="static")

# Define the root directory to manage (defaulting to current directory)
ROOT_DIR = Path(os.getcwd()).resolve()

def get_secure_path(subpath: str) -> Path:
    """Ensure users cannot escape the ROOT_DIR using ../"""
    requested_path = (ROOT_DIR / subpath).resolve()
    if not str(requested_path).startswith(str(ROOT_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    return requested_path

# ==========================================
# FILE MANAGER ENDPOINTS
# ==========================================

@app.get("/api/files")
def list_files(path: str = ""):
    """List files and directories in a given path."""
    target_dir = get_secure_path(path)
    if not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")
    
    items = []
    for item in target_dir.iterdir():
        items.append({
            "name": item.name,
            "is_dir": item.is_dir(),
            "size": item.stat().st_size if item.is_file() else 0
        })
    return sorted(items, key=lambda x: (not x["is_dir"], x["name"]))

@app.get("/api/download")
def download_file(path: str):
    """Download a specific file."""
    target_file = get_secure_path(path)
    if not target_file.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target_file)

@app.post("/api/upload")
async def upload_file(path: str = "", file: UploadFile = File(...)):
    """Upload a file to a specific directory."""
    target_dir = get_secure_path(path)
    file_path = target_dir / file.filename
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    return {"message": f"Successfully uploaded {file.filename}"}

# ==========================================
# WEB TERMINAL WEBSOCKET
# ==========================================

@app.websocket("/ws/terminal")
async def terminal(websocket: WebSocket):
    """
    A basic pseudo-terminal. It accepts commands, runs them in the shell, 
    and returns the output. (Note: State/directory changes don't persist 
    between commands in this simplified version).
    """
    await websocket.accept()
    try:
        while True:
            command = await websocket.receive_text()
            
            # Execute command asynchronously
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ROOT_DIR) # Run commands in the root directory
            )
            
            stdout, stderr = await process.communicate()
            
            # Send output back to the web UI
            if stdout:
                await websocket.send_text(stdout.decode('utf-8', errors='replace'))
            if stderr:
                await websocket.send_text(stderr.decode('utf-8', errors='replace'))
                
            # Send a prompt indicator to show command finished
            await websocket.send_text("\r\n$ ")
            
    except WebSocketDisconnect:
        print("Client disconnected from terminal.")

@app.get("/")
def serve_ui():
    with open("static/index.html", "r") as f:
        return HTMLResponse(f.read())
