import os
import shutil
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse

app = FastAPI(title="FastAPI File Manager")

# Define storage directory
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

def safe_path(filename: str) -> str:
    """Sanitizes filename to prevent path traversal attacks."""
    clean_name = os.path.basename(filename)
    return os.path.join(UPLOAD_DIR, clean_name)

@app.get("/", response_class=HTMLResponse)
async def list_files():
    """Web interface listing uploaded files with upload/download/delete options."""
    files_html = ""
    for item in sorted(os.listdir(UPLOAD_DIR)):
        file_path = os.path.join(UPLOAD_DIR, item)
        if os.path.isfile(file_path):
            size_kb = round(os.path.getsize(file_path) / 1024, 2)
            files_html += f"""
            <tr>
                <td><strong>{item}</strong></td>
                <td>{size_kb} KB</td>
                <td>
                    <a href="/download/{item}">Download</a> | 
                    <form action="/delete/{item}" method="post" style="display:inline;">
                        <button type="submit" onclick="return confirm('Delete {item}?')">Delete</button>
                    </form>
                </td>
            </tr>
            """

    if not files_html:
        files_html = '<tr><td colspan="3" style="text-align:center;">No files found.</td></tr>'

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>FastAPI File Manager</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 800px; margin: 20px auto; padding: 0 15px; color: #333; }}
            h1 {{ color: #2c3e50; }}
            .card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; border: 1px solid #ddd; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #eee; }}
            th {{ background: #f1f1f1; }}
            button {{ background: #e74c3c; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer; }}
            button:hover {{ background: #c0392b; }}
            .btn-upload {{ background: #2ecc71; padding: 8px 15px; font-weight: bold; }}
            .btn-upload:hover {{ background: #27ae60; }}
            a {{ color: #3498db; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h1>📁 File Manager</h1>
        
        <div class="card">
            <h3>Upload File</h3>
            <form action="/upload" method="post" enctype="multipart/form-data">
                <input type="file" name="file" required>
                <button type="submit" class="btn-upload">Upload</button>
            </form>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Filename</th>
                    <th>Size</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {files_html}
            </tbody>
        </table>
    </body>
    </html>
    """

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handles file uploads."""
    dest_path = safe_path(file.filename)
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return RedirectResponse(url="/", status_code=303)

@app.get("/download/{filename}")
async def download_file(filename: str):
    """Handles file downloads."""
    filepath = safe_path(filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=filepath, filename=filename)

@app.post("/delete/{filename}")
async def delete_file(filename: str):
    """Handles file deletion."""
    filepath = safe_path(filename)
    if os.path.isfile(filepath):
        os.remove(filepath)
        return RedirectResponse(url="/", status_code=303)
    raise HTTPException(status_code=404, detail="File not found")
