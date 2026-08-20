let currentPath = "";
let files = [];
let editingPath = null;


// ---------------------------------------------------------
// API
// ---------------------------------------------------------

async function api(url, options = {}) {

    const response = await fetch(url, options);

    let data;

    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        throw new Error(
            data.detail || "Request failed"
        );
    }

    return data;
}


// ---------------------------------------------------------
// Load files
// ---------------------------------------------------------

async function loadFiles() {

    try {

        const data = await api(
            `/api/files?path=${encodeURIComponent(currentPath)}`
        );

        files = data.items;

        document.getElementById(
            "currentPath"
        ).textContent =
            "/" + (currentPath || "");

        renderFiles();

        updateStats();

        loadStorage();

    } catch (error) {

        alert(error.message);

    }
}


// ---------------------------------------------------------
// Render
// ---------------------------------------------------------

function renderFiles() {

    const list =
        document.getElementById("fileList");

    const search =
        document
            .getElementById("search")
            .value
            .toLowerCase();

    const filtered =
        files.filter(item =>
            item.name
                .toLowerCase()
                .includes(search)
        );

    if (!filtered.length) {

        list.innerHTML = `
            <div class="empty">
                📂 No files found
            </div>
        `;

        return;
    }

    list.innerHTML =
        filtered.map(item => {

            const isFolder =
                item.type === "directory";

            const icon =
                isFolder ? "📁" : getIcon(item.name);

            return `
                <div class="file-row">

                    <div
                        class="file-name"
                        onclick="${
                            isFolder
                                ? `openFolder('${escapeJS(item.path)}')`
                                : ""
                        }"
                    >

                        <span class="file-icon">
                            ${icon}
                        </span>

                        <span>
                            ${escapeHTML(item.name)}
                        </span>

                    </div>

                    <div class="file-size">
                        ${item.size_human}
                    </div>

                    <div class="actions">

                        ${
                            isFolder
                                ? `
                                <button
                                    onclick="downloadZip('${escapeJS(item.path)}')"
                                >
                                    ZIP
                                </button>
                                `
                                : `
                                <button
                                    onclick="downloadFile('${escapeJS(item.path)}')"
                                >
                                    Download
                                </button>

                                ${isEditable(item.name)
                                    ? `
                                    <button
                                        onclick="editFile('${escapeJS(item.path)}')"
                                    >
                                        Edit
                                    </button>
                                    `
                                    : ""
                                }
                                `
                        }

                        <button
                            onclick="renameItem('${escapeJS(item.path)}')"
                        >
                            Rename
                        </button>

                        <button
                            onclick="deleteItem('${escapeJS(item.path)}')"
                        >
                            Delete
                        </button>

                    </div>

                </div>
            `;

        }).join("");
}


// ---------------------------------------------------------
// Folder
// ---------------------------------------------------------

function openFolder(path) {

    currentPath = path;

    document.getElementById(
        "search"
    ).value = "";

    loadFiles();
}


function goBack() {

    if (!currentPath) {
        return;
    }

    const parts =
        currentPath.split("/");

    parts.pop();

    currentPath =
        parts.join("/");

    loadFiles();
}


// ---------------------------------------------------------
// Create folder
// ---------------------------------------------------------

async function createFolder() {

    const name =
        prompt("Folder name:");

    if (!name) return;

    const form =
        new FormData();

    form.append(
        "path",
        currentPath
    );

    form.append(
        "name",
        name
    );

    try {

        await api(
            "/api/mkdir",
            {
                method: "POST",
                body: form
            }
        );

        loadFiles();

    } catch (error) {

        alert(error.message);

    }
}


// ---------------------------------------------------------
// Upload
// ---------------------------------------------------------

document
    .getElementById("fileInput")
    .addEventListener(
        "change",
        async function () {

            for (const file of this.files) {

                const form =
                    new FormData();

                form.append(
                    "path",
                    currentPath
                );

                form.append(
                    "file",
                    file
                );

                try {

                    await api(
                        "/api/upload",
                        {
                            method: "POST",
                            body: form
                        }
                    );

                } catch (error) {

                    alert(
                        `${file.name}: ${error.message}`
                    );
                }
            }

            this.value = "";

            loadFiles();
        }
    );


// ---------------------------------------------------------
// Download
// ---------------------------------------------------------

function downloadFile(path) {

    window.location.href =
        `/api/download?path=${encodeURIComponent(path)}`;
}


function downloadZip(path) {

    window.location.href =
        `/api/download-zip?path=${encodeURIComponent(path)}`;
}


// ---------------------------------------------------------
// Rename
// ---------------------------------------------------------

async function renameItem(path) {

    const oldName =
        path.split("/").pop();

    const newName =
        prompt(
            "New name:",
            oldName
        );

    if (!newName || newName === oldName) {
        return;
    }

    const form =
        new FormData();

    form.append(
        "path",
        path
    );

    form.append(
        "new_name",
        newName
    );

    try {

        await api(
            "/api/rename",
            {
                method: "POST",
                body: form
            }
        );

        loadFiles();

    } catch (error) {

        alert(error.message);

    }
}


// ---------------------------------------------------------
// Delete
// ---------------------------------------------------------

async function deleteItem(path) {

    const name =
        path.split("/").pop();

    if (
        !confirm(
            `Delete "${name}"?`
        )
    ) {
        return;
    }

    try {

        await api(
            `/api/delete?path=${encodeURIComponent(path)}`,
            {
                method: "DELETE"
            }
        );

        loadFiles();

    } catch (error) {

        alert(error.message);

    }
}


// ---------------------------------------------------------
// Editor
// ---------------------------------------------------------

function isEditable(name) {

    const extensions = [
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
        ".log"
    ];

    return extensions.some(
        ext =>
            name.toLowerCase().endsWith(ext)
    );
}


async function editFile(path) {

    try {

        const data =
            await api(
                `/api/read?path=${encodeURIComponent(path)}`
            );

        editingPath = path;

        document.getElementById(
            "editorTitle"
        ).textContent =
            path.split("/").pop();

        document.getElementById(
            "editorContent"
        ).value =
            data.content;

        document
            .getElementById("editorModal")
            .classList.remove("hidden");

    } catch (error) {

        alert(error.message);

    }
}


async function saveEditor() {

    if (!editingPath) return;

    const form =
        new FormData();

    form.append(
        "path",
        editingPath
    );

    form.append(
        "content",
        document.getElementById(
            "editorContent"
        ).value
    );

    try {

        await api(
            "/api/write",
            {
                method: "PUT",
                body: form
            }
        );

        alert("Saved successfully");

        closeEditor();

    } catch (error) {

        alert(error.message);

    }
}


function closeEditor() {

    editingPath = null;

    document
        .getElementById("editorModal")
        .classList.add("hidden");
}


// ---------------------------------------------------------
// Stats
// ---------------------------------------------------------

function updateStats() {

    const filesCount =
        files.filter(
            x => x.type === "file"
        ).length;

    const foldersCount =
        files.filter(
            x => x.type === "directory"
        ).length;

    document.getElementById(
        "fileCount"
    ).textContent =
        filesCount;

    document.getElementById(
        "folderCount"
    ).textContent =
        foldersCount;
}


async function loadStorage() {

    try {

        const data =
            await api("/api/storage");

        document.getElementById(
            "storageSize"
        ).textContent =
            data.size_human;

    } catch {
        // Ignore
    }
}


// ---------------------------------------------------------
// Icons
// ---------------------------------------------------------

function getIcon(name) {

    const lower =
        name.toLowerCase();

    if (
        lower.endsWith(".jpg") ||
        lower.endsWith(".jpeg") ||
        lower.endsWith(".png") ||
        lower.endsWith(".gif") ||
        lower.endsWith(".webp")
    ) {
        return "🖼️";
    }

    if (
        lower.endsWith(".mp4") ||
        lower.endsWith(".mkv") ||
        lower.endsWith(".webm")
    ) {
        return "🎬";
    }

    if (
        lower.endsWith(".mp3") ||
        lower.endsWith(".wav") ||
        lower.endsWith(".ogg")
    ) {
        return "🎵";
    }

    if (
        lower.endsWith(".zip") ||
        lower.endsWith(".rar") ||
        lower.endsWith(".7z")
    ) {
        return "📦";
    }

    if (
        lower.endsWith(".pdf")
    ) {
        return "📕";
    }

    if (
        lower.endsWith(".py") ||
        lower.endsWith(".php") ||
        lower.endsWith(".js") ||
        lower.endsWith(".ts")
    ) {
        return "💻";
    }

    if (
        lower.endsWith(".txt") ||
        lower.endsWith(".md")
    ) {
        return "📝";
    }

    return "📄";
}


// ---------------------------------------------------------
// Security helpers
// ---------------------------------------------------------

function escapeHTML(value) {

    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function escapeJS(value) {

    return value
        .replaceAll("\\", "\\\\")
        .replaceAll("'", "\\'");
}


// ---------------------------------------------------------
// Start
// ---------------------------------------------------------

loadFiles();