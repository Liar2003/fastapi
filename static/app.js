// ========== STATE ==========
let currentPath = '';
let selectedItems = new Set();
let viewMode = 'grid';
let sortBy = 'name';
let sortOrder = 'asc';
let clipboard = { action: null, items: [] };
let currentEditFile = null;
let isEditorDirty = false;
let history = [''];
let historyIndex = 0;
let terminalActive = false;
let terminalMaximized = false;
let terminalTheme = 'dark';
let terminals = {};
let activeTerminalId = null;
let terminalTabCount = 0;
let longPressTimer = null;
let isMobile = window.innerWidth <= 768;
let touchStartY = 0;

// ========== DOM ELEMENTS ==========
const fileContainer = document.getElementById('fileContainer');
const breadcrumb = document.getElementById('breadcrumb');
const contextMenu = document.getElementById('contextMenu');
const modal = document.getElementById('modal');
const editorModal = document.getElementById('editorModal');
const previewModal = document.getElementById('previewModal');
const terminalPanel = document.getElementById('terminalPanel');
const bottomSheet = document.getElementById('bottomSheet');
const toastContainer = document.getElementById('toastContainer');

// ========== INIT ==========
document.addEventListener('DOMContentLoaded', () => {
    loadFiles('');
    updateStats();
    setupEventListeners();
    setupKeyboardShortcuts();
    setupTouchGestures();
    checkMobile();
});

window.addEventListener('resize', () => {
    const wasMobile = isMobile;
    isMobile = window.innerWidth <= 768;
    if (wasMobile !== isMobile) {
        loadFiles(currentPath);
    }
    if (terminals[activeTerminalId]?.fit) {
        terminals[activeTerminalId].fit.fit();
    }
});

function checkMobile() {
    isMobile = window.innerWidth <= 768;
}

// ========== EVENT LISTENERS ==========
function setupEventListeners() {
    // Global click to hide menus
    document.addEventListener('click', (e) => {
        if (!contextMenu.contains(e.target)) hideContextMenu();
        if (!document.querySelector('.sort-dropdown').contains(e.target)) {
            document.getElementById('sortMenu').classList.remove('active');
        }
    });

    // Drag and drop
    document.addEventListener('dragover', (e) => {
        e.preventDefault();
        document.getElementById('dragOverlay').classList.add('active');
    });
    document.addEventListener('dragleave', (e) => {
        if (e.relatedTarget === null) {
            document.getElementById('dragOverlay').classList.remove('active');
        }
    });
    document.addEventListener('drop', (e) => {
        e.preventDefault();
        document.getElementById('dragOverlay').classList.remove('active');
        if (e.dataTransfer.files.length > 0) {
            uploadFiles(e.dataTransfer.files);
        }
    });

    // Editor textarea
    const editor = document.getElementById('editorContent');
    editor.addEventListener('input', () => {
        isEditorDirty = true;
        document.getElementById('editorUnsaved').style.display = 'inline';
        updateLineNumbers();
        updateEditorInfo();
    });
    editor.addEventListener('scroll', syncLineNumbers);
    editor.addEventListener('click', updateEditorInfo);
    editor.addEventListener('keyup', updateEditorInfo);
}

function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        const mod = e.ctrlKey || e.metaKey;

        if (mod && e.key === 'k') {
            e.preventDefault();
            document.getElementById('searchInput').focus();
        }
        if (mod && e.key === 'a' && !e.target.matches('input, textarea')) {
            e.preventDefault();
            selectAll();
        }
        if (mod && e.key === 'c' && selectedItems.size > 0 && !e.target.matches('input, textarea')) {
            e.preventDefault();
            copySelected();
        }
        if (mod && e.key === 'v' && !e.target.matches('input, textarea')) {
            e.preventDefault();
            pasteItems();
        }
        if (e.key === 'Delete' && !e.target.matches('input, textarea')) {
            deleteSelected();
        }
        if (e.key === 'F2' && !e.target.matches('input, textarea')) {
            e.preventDefault();
            renameSelected();
        }
        if (e.key === 'Escape') {
            closeModal();
            closeEditor();
            closePreview();
            hideContextMenu();
            clearSelection();
        }
    });
}

function setupTouchGestures() {
    let touchStartX = 0;

    document.addEventListener('touchstart', (e) => {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
    });

    document.addEventListener('touchend', (e) => {
        const touchEndX = e.changedTouches[0].clientX;
        const diff = touchEndX - touchStartX;

        // Swipe right to open sidebar
        if (diff > 80 && touchStartX < 50) {
            document.getElementById('sidebar').classList.add('active');
            document.getElementById('sidebarOverlay').classList.add('active');
        }
        // Swipe left to close sidebar
        if (diff < -80 && document.getElementById('sidebar').classList.contains('active')) {
            toggleSidebar();
        }
    });
}

// ========== FILE OPERATIONS ==========
async function loadFiles(path = '', addHistory = true) {
    currentPath = path;
    if (addHistory) {
        history = history.slice(0, historyIndex + 1);
        if (history[history.length - 1] !== path) {
            history.push(path);
            historyIndex = history.length - 1;
        }
    }
    updateBackButton();

    try {
        const response = await fetch(`/api/files?path=${encodeURIComponent(path)}&sort=${sortBy}&order=${sortOrder}`);
        const data = await response.json();

        if (response.ok) {
            renderBreadcrumb(path);
            renderFiles(data.items || []);
            document.getElementById('itemCount').textContent = 
                `${data.item_count} item${data.item_count !== 1 ? 's' : ''}`;
            document.getElementById('fileCountBadge').textContent = data.item_count;
            updateNavActive('files');
        }
    } catch (error) {
        showToast('Failed to load files', 'error');
    }
}

function renderFiles(items) {
    const emptyState = document.getElementById('emptyState');

    if (!items || items.length === 0) {
        fileContainer.innerHTML = '';
        fileContainer.appendChild(emptyState);
        emptyState.style.display = 'block';
        return;
    }

    emptyState.style.display = 'none';
    const containerClass = viewMode === 'grid' ? 'file-grid' : 'file-list';
    fileContainer.innerHTML = `<div class="${containerClass}" id="fileList"></div>`;
    const list = document.getElementById('fileList');

    items.forEach(item => {
        list.appendChild(createFileElement(item));
    });
}

function createFileElement(item) {
    const div = document.createElement('div');
    div.className = 'file-item';
    div.dataset.path = item.path;
    div.dataset.type = item.type;
    div.dataset.name = item.name;

    const iconClass = getIconClass(item);
    const iconColor = getIconColor(item);

    if (viewMode === 'grid') {
        div.innerHTML = `
            <div class="file-checkbox" onclick="event.stopPropagation(); toggleCheckbox('${item.path}')">
                <i class="fas fa-check"></i>
            </div>
            <div class="file-icon ${iconClass}">
                <i class="${getIconName(item)}"></i>
            </div>
            <div class="file-name" title="${item.name}">${item.name}</div>
            <div class="file-meta">${item.size_human}</div>
        `;
    } else {
        div.innerHTML = `
            <div class="file-checkbox ${selectedItems.has(item.path) ? 'checked' : ''}" onclick="event.stopPropagation(); toggleCheckbox('${item.path}')">
                <i class="fas fa-check"></i>
            </div>
            <div class="file-icon ${iconClass}">
                <i class="${getIconName(item)}"></i>
            </div>
            <div class="file-info">
                <div class="file-name-section">
                    <div class="file-name" title="${item.name}">${item.name}</div>
                    <div class="file-meta">${item.modified_human}</div>
                </div>
            </div>
            <div class="file-size">${item.size_human}</div>
            <div class="file-date">${new Date(item.modified).toLocaleDateString()}</div>
            <div class="file-actions">
                ${item.type === 'file' ? `<button onclick="event.stopPropagation(); previewFile('${item.path}')" title="Preview"><i class="fas fa-eye"></i></button>` : ''}
                <button onclick="event.stopPropagation(); downloadFile('${item.path}')" title="Download"><i class="fas fa-download"></i></button>
                <button onclick="event.stopPropagation(); showContextMenu(event, '${item.path}')" title="More"><i class="fas fa-ellipsis-v"></i></button>
            </div>
        `;
    }

    // Click handlers
    div.addEventListener('click', (e) => handleFileClick(e, item));
    div.addEventListener('dblclick', () => handleFileDblClick(item));

    // Long press for mobile context menu
    div.addEventListener('touchstart', (e) => {
        longPressTimer = setTimeout(() => {
            showMobileFileActions(item);
        }, 600);
    });
    div.addEventListener('touchend', () => clearTimeout(longPressTimer));
    div.addEventListener('touchmove', () => clearTimeout(longPressTimer));

    // Context menu
    div.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        if (!isMobile) showContextMenu(e, item.path);
    });

    if (selectedItems.has(item.path)) {
        div.classList.add('selected');
        const cb = div.querySelector('.file-checkbox');
        if (cb) cb.classList.add('checked');
    }

    return div;
}

function getIconClass(item) {
    if (item.type === 'directory') return 'folder';
    const mime = item.mime || '';
    if (mime.startsWith('image/')) return 'image';
    if (mime.startsWith('video/')) return 'video';
    if (mime.startsWith('audio/')) return 'audio';
    if (mime.includes('pdf')) return 'pdf';
    if (mime.includes('zip') || mime.includes('tar') || mime.includes('compressed')) return 'archive';
    if (mime.includes('javascript') || mime.includes('python') || mime.includes('code') || mime.includes('text')) return 'code';
    if (mime.includes('word') || mime.includes('excel') || mime.includes('powerpoint')) return 'doc';
    return 'default';
}

function getIconName(item) {
    if (item.type === 'directory') return 'fas fa-folder';
    const mime = item.mime || '';
    if (mime.startsWith('image/')) return 'fas fa-file-image';
    if (mime.startsWith('video/')) return 'fas fa-file-video';
    if (mime.startsWith('audio/')) return 'fas fa-file-audio';
    if (mime.includes('pdf')) return 'fas fa-file-pdf';
    if (mime.includes('zip') || mime.includes('tar')) return 'fas fa-file-archive';
    if (mime.includes('word')) return 'fas fa-file-word';
    if (mime.includes('excel')) return 'fas fa-file-excel';
    if (mime.includes('powerpoint')) return 'fas fa-file-powerpoint';
    if (mime.includes('code') || mime.includes('text')) return 'fas fa-file-code';
    return 'fas fa-file';
}

function getIconColor(item) {
    const colors = {
        folder: '#fbbf24', image: '#a78bfa', video: '#f472b6',
        audio: '#22d3ee', code: '#4ade80', pdf: '#f87171',
        archive: '#fb923c', doc: '#60a5fa', default: '#94a3b8'
    };
    return colors[getIconClass(item)] || colors.default;
}

function handleFileClick(e, item) {
    if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        toggleSelection(item.path);
    } else if (e.shiftKey) {
        e.preventDefault();
        rangeSelect(item.path);
    } else {
        selectedItems.clear();
        selectedItems.add(item.path);
        updateSelection();
    }
}

function handleFileDblClick(item) {
    if (item.type === 'directory') {
        navigateTo(item.path);
    } else {
        previewFile(item.path);
    }
}

function toggleCheckbox(path) {
    toggleSelection(path);
}

function toggleSelection(path) {
    if (selectedItems.has(path)) {
        selectedItems.delete(path);
    } else {
        selectedItems.add(path);
    }
    updateSelection();
}

function rangeSelect(endPath) {
    const items = Array.from(document.querySelectorAll('.file-item'));
    const endIndex = items.findIndex(el => el.dataset.path === endPath);
    if (endIndex === -1) return;

    let startIndex = 0;
    for (let i = 0; i < items.length; i++) {
        if (selectedItems.has(items[i].dataset.path)) {
            startIndex = i;
            break;
        }
    }

    const [min, max] = [Math.min(startIndex, endIndex), Math.max(startIndex, endIndex)];
    for (let i = min; i <= max; i++) {
        selectedItems.add(items[i].dataset.path);
    }
    updateSelection();
}

function selectAll() {
    document.querySelectorAll('.file-item').forEach(el => {
        selectedItems.add(el.dataset.path);
    });
    updateSelection();
}

function clearSelection() {
    selectedItems.clear();
    updateSelection();
}

function updateSelection() {
    document.querySelectorAll('.file-item').forEach(el => {
        const isSelected = selectedItems.has(el.dataset.path);
        el.classList.toggle('selected', isSelected);
        const cb = el.querySelector('.file-checkbox');
        if (cb) cb.classList.toggle('checked', isSelected);
    });

    const toolbarActions = document.getElementById('toolbarActions');
    const toolbarSelection = document.getElementById('toolbarSelection');

    if (selectedItems.size > 0) {
        toolbarActions.style.display = 'none';
        toolbarSelection.style.display = 'flex';
        document.getElementById('selectionCount').textContent = 
            `${selectedItems.size} selected`;
    } else {
        toolbarActions.style.display = 'flex';
        toolbarSelection.style.display = 'none';
    }
}

function navigateTo(path) {
    loadFiles(path);
}

function goBack() {
    if (historyIndex > 0) {
        historyIndex--;
        loadFiles(history[historyIndex], false);
    }
}

function updateBackButton() {
    document.getElementById('backBtn').disabled = historyIndex <= 0;
}

function renderBreadcrumb(path) {
    const parts = path ? path.split('/') : [];
    let html = `<span class="breadcrumb-item" onclick="navigateTo('')">Home</span>`;
    let current = '';

    parts.forEach((part, i) => {
        current += (current ? '/' : '') + part;
        const isLast = i === parts.length - 1;
        html += `<span class="breadcrumb-separator"><i class="fas fa-chevron-right"></i></span>`;
        if (isLast) {
            html += `<span class="breadcrumb-item active">${part}</span>`;
        } else {
            html += `<span class="breadcrumb-item" onclick="navigateTo('${current}')">${part}</span>`;
        }
    });

    breadcrumb.innerHTML = html;
}

// ========== VIEW & SORT ==========
function setViewMode(mode) {
    viewMode = mode;
    document.querySelectorAll('.view-btn').forEach(btn => btn.classList.remove('active'));
    event.currentTarget.classList.add('active');
    loadFiles(currentPath, false);
}

function toggleSortMenu() {
    document.getElementById('sortMenu').classList.toggle('active');
}

function setSort(field, order) {
    sortBy = field;
    sortOrder = order;
    document.querySelectorAll('.dropdown-item').forEach(el => el.classList.remove('active'));
    event.currentTarget.classList.add('active');
    loadFiles(currentPath, false);
}

// ========== CONTEXT MENU ==========
function showContextMenu(e, path) {
    selectedItems.clear();
    selectedItems.add(path);
    updateSelection();

    const item = document.querySelector(`[data-path="${CSS.escape(path)}"]`);
    const isFile = item?.dataset.type === 'file';

    contextMenu.innerHTML = `
        ${isFile ? `<div class="context-item" onclick="previewFile('${path}')"><i class="fas fa-eye"></i> Preview</div>` : ''}
        <div class="context-item" onclick="downloadFile('${path}')"><i class="fas fa-download"></i> Download</div>
        <div class="context-item" onclick="renameSelected()"><i class="fas fa-edit"></i> Rename</div>
        <div class="context-item" onclick="copySelected()"><i class="fas fa-copy"></i> Copy</div>
        <div class="context-item" onclick="moveSelected()"><i class="fas fa-cut"></i> Cut</div>
        ${isFile ? `<div class="context-item" onclick="shareSelected()"><i class="fas fa-share-alt"></i> Share</div>` : ''}
        <div class="context-divider"></div>
        <div class="context-item danger" onclick="deleteSelected()"><i class="fas fa-trash"></i> Delete</div>
    `;

    contextMenu.style.display = 'block';
    contextMenu.style.left = `${Math.min(e.pageX, window.innerWidth - 220)}px`;
    contextMenu.style.top = `${Math.min(e.pageY, window.innerHeight - 200)}px`;
}

function hideContextMenu() {
    contextMenu.style.display = 'none';
}

// ========== MOBILE BOTTOM SHEET ==========
function showMobileActions() {
    const content = `
        <div class="bottom-sheet-item" onclick="showUploadModal(); closeBottomSheet();">
            <i class="fas fa-cloud-upload-alt"></i> Upload Files
        </div>
        <div class="bottom-sheet-item" onclick="showNewFolderModal(); closeBottomSheet();">
            <i class="fas fa-folder-plus"></i> New Folder
        </div>
        <div class="bottom-sheet-divider"></div>
        <div class="bottom-sheet-item" onclick="toggleTerminal(); closeBottomSheet();">
            <i class="fas fa-terminal"></i> Open Terminal
        </div>
        <div class="bottom-sheet-item" onclick="showShortcuts(); closeBottomSheet();">
            <i class="fas fa-keyboard"></i> Keyboard Shortcuts
        </div>
    `;
    showBottomSheet(content);
}

function showMobileFileActions(item) {
    const isFile = item.type === 'file';
    const content = `
        <div style="padding: 16px; text-align: center; border-bottom: 1px solid var(--border); margin-bottom: 8px;">
            <div style="font-weight: 600; margin-bottom: 4px;">${item.name}</div>
            <div style="font-size: 0.8rem; color: var(--text-muted);">${item.size_human}</div>
        </div>
        ${isFile ? `<div class="bottom-sheet-item" onclick="previewFile('${item.path}'); closeBottomSheet();"><i class="fas fa-eye"></i> Preview</div>` : ''}
        <div class="bottom-sheet-item" onclick="downloadFile('${item.path}'); closeBottomSheet();"><i class="fas fa-download"></i> Download</div>
        <div class="bottom-sheet-item" onclick="renameItem('${item.path}'); closeBottomSheet();"><i class="fas fa-edit"></i> Rename</div>
        <div class="bottom-sheet-item" onclick="copyPath('${item.path}'); closeBottomSheet();"><i class="fas fa-copy"></i> Copy</div>
        <div class="bottom-sheet-divider"></div>
        <div class="bottom-sheet-item danger" onclick="deleteItem('${item.path}'); closeBottomSheet();"><i class="fas fa-trash"></i> Delete</div>
    `;
    showBottomSheet(content);
}

function showBottomSheet(content) {
    document.getElementById('bottomSheetContent').innerHTML = content;
    bottomSheet.classList.add('active');
    document.getElementById('bottomSheetOverlay').classList.add('active');
}

function closeBottomSheet() {
    bottomSheet.classList.remove('active');
    document.getElementById('bottomSheetOverlay').classList.remove('active');
}

// ========== FILE ACTIONS ==========
async function downloadFile(path) {
    window.open(`/api/files/download?path=${encodeURIComponent(path)}`, '_blank');
}

function downloadSelected() {
    if (selectedItems.size === 0) return;
    downloadFile(Array.from(selectedItems)[0]);
    hideContextMenu();
}

async function deleteSelected() {
    if (selectedItems.size === 0) return;
    if (!confirm(`Move ${selectedItems.size} item(s) to trash?`)) return;

    for (const path of selectedItems) {
        try {
            await fetch(`/api/files/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
        } catch (e) {}
    }
    selectedItems.clear();
    loadFiles(currentPath);
    showToast('Moved to trash', 'success');
}

async function deleteItem(path) {
    if (!confirm('Move to trash?')) return;
    try {
        await fetch(`/api/files/delete?path=${encodeURIComponent(path)}`, { method: 'DELETE' });
        loadFiles(currentPath);
        showToast('Moved to trash', 'success');
    } catch (e) {
        showToast('Delete failed', 'error');
    }
}

function renameSelected() {
    if (selectedItems.size !== 1) return;
    const path = Array.from(selectedItems)[0];
    renameItem(path);
    hideContextMenu();
}

function renameItem(path) {
    const name = path.split('/').pop();
    showModal('Rename', `
        <div class="form-group">
            <label>New Name</label>
            <input type="text" id="renameInput" value="${name}" autofocus onkeyup="if(event.key==='Enter') confirmRename('${path}')">
        </div>
    `, `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="confirmRename('${path}')">Rename</button>
    `);
    setTimeout(() => document.getElementById('renameInput').focus(), 100);
}

async function confirmRename(path) {
    const newName = document.getElementById('renameInput').value.trim();
    if (!newName) return;

    try {
        const response = await fetch('/api/files/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `path=${encodeURIComponent(path)}&new_name=${encodeURIComponent(newName)}`
        });

        if (response.ok) {
            closeModal();
            loadFiles(currentPath);
            showToast('Renamed successfully', 'success');
        } else {
            const data = await response.json();
            showToast(data.detail, 'error');
        }
    } catch (error) {
        showToast('Rename failed', 'error');
    }
}

function copySelected() {
    if (selectedItems.size === 0) return;
    clipboard = { action: 'copy', items: Array.from(selectedItems) };
    showToast(`Copied ${selectedItems.size} item(s)`, 'success');
    hideContextMenu();
}

function moveSelected() {
    if (selectedItems.size === 0) return;
    clipboard = { action: 'move', items: Array.from(selectedItems) };
    showToast(`Cut ${selectedItems.size} item(s)`, 'warning');
    hideContextMenu();
}

async function pasteItems() {
    if (!clipboard.action || clipboard.items.length === 0) return;

    for (const item of clipboard.items) {
        const endpoint = clipboard.action === 'copy' ? 'copy' : 'move';
        try {
            await fetch(`/api/files/${endpoint}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: `source=${encodeURIComponent(item)}&destination=${encodeURIComponent(currentPath)}`
            });
        } catch (e) {}
    }

    clipboard = { action: null, items: [] };
    loadFiles(currentPath);
    showToast('Pasted successfully', 'success');
}

async function shareSelected() {
    if (selectedItems.size !== 1) return;
    const path = Array.from(selectedItems)[0];

    try {
        const response = await fetch('/api/files/share', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `path=${encodeURIComponent(path)}`
        });
        const data = await response.json();

        if (response.ok) {
            const url = `${window.location.origin}/share/${data.share_id}`;
            await navigator.clipboard.writeText(url);
            showToast('Share link copied!', 'success');
        }
    } catch (e) {
        showToast('Share failed', 'error');
    }
    hideContextMenu();
}

// ========== FOLDER OPERATIONS ==========
function showNewFolderModal() {
    showModal('New Folder', `
        <div class="form-group">
            <label>Folder Name</label>
            <input type="text" id="folderName" placeholder="My Folder" autofocus onkeyup="if(event.key==='Enter') createFolder()">
        </div>
    `, `
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="createFolder()">Create</button>
    `);
    setTimeout(() => document.getElementById('folderName').focus(), 100);
}

async function createFolder() {
    const name = document.getElementById('folderName').value.trim();
    if (!name) return;

    try {
        const response = await fetch('/api/files/mkdir', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `path=${encodeURIComponent(currentPath)}&name=${encodeURIComponent(name)}`
        });

        if (response.ok) {
            closeModal();
            loadFiles(currentPath);
            showToast('Folder created', 'success');
        }
    } catch (e) {
        showToast('Failed to create folder', 'error');
    }
}

// ========== UPLOAD ==========
function showUploadModal() {
    showModal('Upload Files', `
        <div class="upload-zone" id="uploadZone" onclick="document.getElementById('fileInput').click()">
            <i class="fas fa-cloud-upload-alt"></i>
            <h4>Drop files here</h4>
            <p>or click to browse</p>
            <input type="file" id="fileInput" multiple style="display:none" onchange="handleFileSelect(this)">
        </div>
        <div id="uploadProgress" style="margin-top: 16px; display: none;">
            <div style="background: var(--bg); border-radius: 8px; height: 6px; overflow: hidden;">
                <div id="uploadProgressBar" style="background: linear-gradient(90deg, var(--accent), var(--accent-secondary)); height: 100%; width: 0%; transition: width 0.3s;"></div>
            </div>
            <div style="text-align: center; margin-top: 8px; font-size: 0.8rem; color: var(--text-muted);" id="uploadProgressText">0%</div>
        </div>
    `, `
        <button class="btn btn-secondary" onclick="closeModal()">Close</button>
    `);

    const zone = document.getElementById('uploadZone');
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        uploadFiles(e.dataTransfer.files);
    });
}

function handleFileSelect(input) {
    uploadFiles(input.files);
}

async function uploadFiles(files) {
    if (!files || files.length === 0) return;

    const progressBar = document.getElementById('uploadProgressBar');
    const progressText = document.getElementById('uploadProgressText');
    const progressContainer = document.getElementById('uploadProgress');

    if (progressContainer) progressContainer.style.display = 'block';

    const formData = new FormData();
    formData.append('path', currentPath);
    for (const file of files) {
        formData.append('files', file);
    }

    try {
        // Simulate progress
        let progress = 0;
        const interval = setInterval(() => {
            progress += Math.random() * 15;
            if (progress > 90) progress = 90;
            if (progressBar) progressBar.style.width = progress + '%';
            if (progressText) progressText.textContent = Math.round(progress) + '%';
        }, 200);

        const response = await fetch('/api/files/upload', {
            method: 'POST',
            body: formData
        });

        clearInterval(interval);
        if (progressBar) progressBar.style.width = '100%';
        if (progressText) progressText.textContent = '100%';

        if (response.ok) {
            setTimeout(() => {
                closeModal();
                loadFiles(currentPath);
                showToast(`Uploaded ${files.length} file(s)`, 'success');
            }, 500);
        }
    } catch (e) {
        showToast('Upload failed', 'error');
    }
}

// ========== PREVIEW ==========
async function previewFile(path) {
    try {
        const response = await fetch(`/api/files/preview?path=${encodeURIComponent(path)}`);
        const data = await response.json();

        const name = path.split('/').pop();
        document.getElementById('previewName').textContent = name;
        document.getElementById('previewIcon').className = getIconName({mime: data.mime || '', type: data.type || 'file'});

        // Hide all preview types
        document.getElementById('previewImage').style.display = 'none';
        document.getElementById('previewVideo').style.display = 'none';
        document.getElementById('previewAudio').style.display = 'none';
        document.getElementById('previewPDF').style.display = 'none';
        document.getElementById('previewCode').style.display = 'none';
        document.getElementById('previewBinary').style.display = 'none';
        document.getElementById('previewEditBtn').style.display = 'none';

        if (response.headers.get('content-type')?.includes('application/json')) {
            if (data.type === 'text') {
                document.getElementById('previewCode').style.display = 'block';
                document.getElementById('previewCode').querySelector('code').textContent = data.content;
                document.getElementById('previewEditBtn').style.display = 'flex';
                document.getElementById('previewEditBtn').onclick = () => { closePreview(); editFile(path); };
            } else if (data.type === 'binary') {
                document.getElementById('previewBinary').style.display = 'block';
            }
        } else {
            // Direct file response
            const url = `/api/files/preview?path=${encodeURIComponent(path)}`;
            const mime = data.mime || '';

            if (mime.startsWith('image/')) {
                document.getElementById('previewImage').style.display = 'block';
                document.getElementById('previewImage').src = url;
            } else if (mime.startsWith('video/')) {
                document.getElementById('previewVideo').style.display = 'block';
                document.getElementById('previewVideo').src = url;
            } else if (mime.startsWith('audio/')) {
                document.getElementById('previewAudio').style.display = 'block';
                document.getElementById('previewAudio').src = url;
            } else if (mime === 'application/pdf') {
                document.getElementById('previewPDF').style.display = 'block';
                document.getElementById('previewPDF').src = url;
            }
        }

        previewModal.classList.add('active');
        document.body.style.overflow = 'hidden';
    } catch (e) {
        showToast('Preview failed', 'error');
    }
}

function downloadPreview() {
    const name = document.getElementById('previewName').textContent;
    const path = currentPath ? `${currentPath}/${name}` : name;
    downloadFile(path);
}

function editPreview() {
    const name = document.getElementById('previewName').textContent;
    const path = currentPath ? `${currentPath}/${name}` : name;
    closePreview();
    editFile(path);
}

function closePreview() {
    previewModal.classList.remove('active');
    document.body.style.overflow = '';
    document.getElementById('previewVideo')?.pause();
    document.getElementById('previewAudio')?.pause();
}

// ========== EDITOR ==========
async function editFile(path) {
    try {
        const response = await fetch(`/api/files/content?path=${encodeURIComponent(path)}`);
        const data = await response.json();

        if (response.ok) {
            currentEditFile = path;
            document.getElementById('editorFilename').textContent = path.split('/').pop();
            document.getElementById('editorContent').value = data.content;
            isEditorDirty = false;
            document.getElementById('editorUnsaved').style.display = 'none';
            editorModal.classList.add('active');
            document.body.style.overflow = 'hidden';
            updateLineNumbers();
            updateEditorInfo();
            setTimeout(() => document.getElementById('editorContent').focus(), 100);
        }
    } catch (e) {
        showToast('Failed to load file', 'error');
    }
}

function updateLineNumbers() {
    const textarea = document.getElementById('editorContent');
    const lines = textarea.value.split('\n').length;
    const lineNumbers = document.getElementById('lineNumbers');
    lineNumbers.innerHTML = Array.from({length: lines}, (_, i) => i + 1).join('<br>');
}

function syncLineNumbers() {
    const textarea = document.getElementById('editorContent');
    const lineNumbers = document.getElementById('lineNumbers');
    lineNumbers.scrollTop = textarea.scrollTop;
}

function updateEditorInfo() {
    const textarea = document.getElementById('editorContent');
    const lines = textarea.value.split('\n').length;
    const chars = textarea.value.length;
    document.getElementById('editorInfo').textContent = `UTF-8 | ${lines} lines | ${chars} chars`;

    const pos = textarea.selectionStart;
    const textUpToCursor = textarea.value.substring(0, pos);
    const line = textUpToCursor.split('\n').length;
    const col = textUpToCursor.split('\n').pop().length + 1;
    document.getElementById('editorCursor').textContent = `Ln ${line}, Col ${col}`;
}

async function saveFile() {
    if (!currentEditFile) return;

    const content = document.getElementById('editorContent').value;

    try {
        const response = await fetch('/api/files/content', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `path=${encodeURIComponent(currentEditFile)}&content=${encodeURIComponent(content)}`
        });

        if (response.ok) {
            isEditorDirty = false;
            document.getElementById('editorUnsaved').style.display = 'none';
            showToast('File saved', 'success');
        }
    } catch (e) {
        showToast('Save failed', 'error');
    }
}

function closeEditor() {
    if (isEditorDirty && !confirm('Unsaved changes. Discard?')) return;
    editorModal.classList.remove('active');
    document.body.style.overflow = '';
    currentEditFile = null;
    isEditorDirty = false;
}

// ========== SEARCH ==========
async function handleSearch(e) {
    if (e.key !== 'Enter') return;
    const query = e.target.value.trim();
    if (!query) {
        loadFiles(currentPath);
        return;
    }

    try {
        const response = await fetch(`/api/files/search?q=${encodeURIComponent(query)}&path=${encodeURIComponent(currentPath)}`);
        const data = await response.json();

        if (response.ok) {
            renderFiles(data.results);
            document.getElementById('itemCount').textContent = `${data.count} results`;
            showToast(`Found ${data.count} results`, 'info');
        }
    } catch (e) {
        showToast('Search failed', 'error');
    }
}

async function handleMobileSearch(e) {
    if (e.key !== 'Enter') return;
    const query = e.target.value.trim();
    if (!query) {
        toggleMobileSearch();
        loadFiles(currentPath);
        return;
    }

    try {
        const response = await fetch(`/api/files/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        toggleMobileSearch();
        renderFiles(data.results);
        showToast(`Found ${data.count} results`, 'info');
    } catch (e) {
        showToast('Search failed', 'error');
    }
}

function toggleMobileSearch() {
    document.getElementById('mobileSearchOverlay').classList.toggle('active');
    if (document.getElementById('mobileSearchOverlay').classList.contains('active')) {
        setTimeout(() => document.getElementById('mobileSearchInput').focus(), 100);
    }
}

// ========== RECENT & TRASH ==========
async function showRecent() {
    updateNavActive('recent');
    try {
        const response = await fetch('/api/files/recent');
        const data = await response.json();
        renderFiles(data.items);
        breadcrumb.innerHTML = '<span class="breadcrumb-item active">Recent Files</span>';
        document.getElementById('itemCount').textContent = `${data.items.length} recent`;
    } catch (e) {
        showToast('Failed to load recent files', 'error');
    }
}

async function showTrash() {
    updateNavActive('trash');
    try {
        const response = await fetch('/api/files/trash');
        const data = await response.json();

        fileContainer.innerHTML = '<div class="file-list" id="fileList"></div>';
        const list = document.getElementById('fileList');

        if (data.items.length === 0) {
            fileContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon"><i class="fas fa-trash-alt"></i></div>
                    <h3>Trash is empty</h3>
                    <p>Deleted files will appear here</p>
                </div>
            `;
        } else {
            data.items.forEach(item => {
                const div = document.createElement('div');
                div.className = 'file-item';
                div.innerHTML = `
                    <div class="file-icon default"><i class="fas fa-trash-alt"></i></div>
                    <div class="file-info">
                        <div class="file-name-section">
                            <div class="file-name">${item.name}</div>
                            <div class="file-meta">Deleted ${new Date(item.deleted_at).toLocaleDateString()}</div>
                        </div>
                    </div>
                    <div class="file-actions">
                        <button onclick="restoreFile('${item.trash_name}')" title="Restore"><i class="fas fa-undo"></i></button>
                        <button onclick="permanentDelete('${item.trash_name}')" title="Delete Forever" style="color: var(--danger);"><i class="fas fa-times"></i></button>
                    </div>
                `;
                list.appendChild(div);
            });
        }

        breadcrumb.innerHTML = '<span class="breadcrumb-item active">Trash</span>';
        document.getElementById('itemCount').textContent = `${data.items.length} items`;
    } catch (e) {
        showToast('Failed to load trash', 'error');
    }
}

async function restoreFile(trashName) {
    try {
        await fetch('/api/files/restore', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: `trash_name=${encodeURIComponent(trashName)}`
        });
        showTrash();
        showToast('File restored', 'success');
    } catch (e) {
        showToast('Restore failed', 'error');
    }
}

async function permanentDelete(trashName) {
    if (!confirm('Permanently delete? This cannot be undone.')) return;
    try {
        await fetch(`/api/files/delete?path=${encodeURIComponent(trashName)}&permanent=true`, { method: 'DELETE' });
        showTrash();
        showToast('Permanently deleted', 'success');
    } catch (e) {
        showToast('Delete failed', 'error');
    }
}

// ========== STATS ==========
async function updateStats() {
    try {
        const response = await fetch('/api/files/stats');
        const data = await response.json();

        document.getElementById('storageFill').style.width = data.percent + '%';
        document.getElementById('storagePercent').textContent = data.percent + '%';
        document.getElementById('storageUsed').textContent = data.used_human;
        document.getElementById('storageTotal').textContent = 'of ' + data.total_human;
    } catch (e) {}
}

// ========== TERMINAL ==========
function toggleTerminal() {
    terminalPanel.classList.toggle('active');
    terminalActive = terminalPanel.classList.contains('active');
    document.getElementById('terminalStatus').classList.toggle('active', terminalActive);

    if (terminalActive && Object.keys(terminals).length === 0) {
        newTerminalTab();
    }

    if (terminalActive && activeTerminalId && terminals[activeTerminalId]) {
        setTimeout(() => terminals[activeTerminalId].fit.fit(), 100);
    }
}

function newTerminalTab() {
    terminalTabCount++;
    const tabId = `term-${terminalTabCount}`;

    const tab = document.createElement('div');
    tab.className = 'terminal-tab active';
    tab.dataset.tab = tabId;
    tab.innerHTML = `
        <i class="fas fa-terminal"></i>
        <span>bash-${terminalTabCount}</span>
        <button class="tab-close" onclick="closeTerminalTab('${tabId}')"><i class="fas fa-times"></i></button>
    `;
    tab.onclick = (e) => {
        if (!e.target.closest('.tab-close')) switchTerminalTab(tabId);
    };

    document.querySelectorAll('.terminal-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('terminalTabs').appendChild(tab);

    // Create terminal instance
    const termDiv = document.createElement('div');
    termDiv.id = tabId;
    termDiv.style.width = '100%';
    termDiv.style.height = '100%';

    const container = document.getElementById('terminalBody');
    Array.from(container.children).forEach(c => c.style.display = 'none');
    container.appendChild(termDiv);

    const term = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: 'JetBrains Mono, Fira Code, Consolas, monospace',
        theme: getTerminalTheme(),
        cols: 80,
        rows: 24,
        allowTransparency: true,
        scrollback: 10000
    });

    const fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(termDiv);
    fit.fit();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/terminal`);

    ws.onopen = () => {
        term.writeln('\x1b[38;5;81m╔══════════════════════════════════════╗\x1b[0m');
        term.writeln('\x1b[38;5;81m║\x1b[0m  \x1b[1;38;5;183mNexus Terminal\x1b[0m v3.0              \x1b[38;5;81m║\x1b[0m');
        term.writeln('\x1b[38;5;81m╚══════════════════════════════════════╝\x1b[0m');
        term.writeln('');
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'output') term.write(data.data);
        if (data.type === 'error') term.writeln(`\r\n\x1b[38;5;196mError: ${data.data}\x1b[0m`);
    };

    ws.onclose = () => {
        term.writeln('\r\n\x1b[38;5;196m[Disconnected]\x1b[0m');
    };

    term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'input', data }));
        }
    });

    term.onResize(({ cols, rows }) => {
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'resize', cols, rows }));
        }
    });

    terminals[tabId] = { term, fit, ws, div: termDiv };
    activeTerminalId = tabId;

    window.addEventListener('resize', () => {
        if (terminals[tabId]) terminals[tabId].fit.fit();
    });
}

function switchTerminalTab(tabId) {
    document.querySelectorAll('.terminal-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`[data-tab="${tabId}"]`)?.classList.add('active');

    Object.values(terminals).forEach(t => t.div.style.display = 'none');
    if (terminals[tabId]) {
        terminals[tabId].div.style.display = 'block';
        activeTerminalId = tabId;
        setTimeout(() => terminals[tabId].fit.fit(), 50);
    }
}

function closeTerminalTab(tabId) {
    if (terminals[tabId]) {
        terminals[tabId].ws.close();
        terminals[tabId].term.dispose();
        terminals[tabId].div.remove();
        delete terminals[tabId];
    }

    document.querySelector(`[data-tab="${tabId}"]`)?.remove();

    const remaining = Object.keys(terminals);
    if (remaining.length > 0) {
        switchTerminalTab(remaining[0]);
    } else {
        activeTerminalId = null;
    }
}

function toggleTerminalTheme() {
    const themes = ['dark', 'light', 'matrix'];
    const current = themes.indexOf(terminalTheme);
    terminalTheme = themes[(current + 1) % themes.length];

    const theme = getTerminalTheme();
    Object.values(terminals).forEach(t => t.term.options.theme = theme);
    showToast(`Terminal theme: ${terminalTheme}`, 'info');
}

function getTerminalTheme() {
    const themes = {
        dark: { background: '#0f172a', foreground: '#f1f5f9', cursor: '#38bdf8', selectionBackground: '#334155' },
        light: { background: '#f8fafc', foreground: '#0f172a', cursor: '#3b82f6', selectionBackground: '#e2e8f0' },
        matrix: { background: '#000000', foreground: '#00ff00', cursor: '#00ff00', selectionBackground: '#003300' }
    };
    return themes[terminalTheme];
}

function toggleTerminalSize() {
    terminalPanel.classList.toggle('maximized');
    const icon = document.getElementById('terminalSizeIcon');
    icon.className = terminalPanel.classList.contains('maximized') ? 'fas fa-compress' : 'fas fa-expand';
    if (activeTerminalId && terminals[activeTerminalId]) {
        setTimeout(() => terminals[activeTerminalId].fit.fit(), 200);
    }
}

function clearTerminal() {
    if (activeTerminalId && terminals[activeTerminalId]) {
        terminals[activeTerminalId].term.clear();
    }
}

// ========== UI HELPERS ==========
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('active');
    document.getElementById('sidebarOverlay').classList.toggle('active');
}

function updateNavActive(page) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelector(`[data-page="${page}"]`)?.classList.add('active');
}

function showShortcuts() {
    showModal('Keyboard Shortcuts', `
        <div style="display: grid; gap: 12px;">
            <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                <span>Select All</span><kbd style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-family: monospace;">Ctrl+A</kbd>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                <span>Copy</span><kbd style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-family: monospace;">Ctrl+C</kbd>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                <span>Paste</span><kbd style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-family: monospace;">Ctrl+V</kbd>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                <span>Delete</span><kbd style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-family: monospace;">Delete</kbd>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                <span>Rename</span><kbd style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-family: monospace;">F2</kbd>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                <span>Search</span><kbd style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-family: monospace;">Ctrl+K</kbd>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 8px 0;">
                <span>Close/Cancel</span><kbd style="background: var(--bg-tertiary); padding: 2px 8px; border-radius: 4px; font-family: monospace;">Esc</kbd>
            </div>
        </div>
    `, `
        <button class="btn btn-primary" onclick="closeModal()">Got it</button>
    `);
}

// ========== MODAL SYSTEM ==========
function showModal(title, body, footer) {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = body;
    document.getElementById('modalFooter').innerHTML = footer;
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    modal.classList.remove('active');
    document.body.style.overflow = '';
}

// ========== TOAST SYSTEM ==========
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icons = {
        success: 'fa-check-circle',
        error: 'fa-exclamation-circle',
        warning: 'fa-exclamation-triangle',
        info: 'fa-info-circle'
    };

    toast.innerHTML = `<i class="fas ${icons[type]}"></i><span>${message}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(50px)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ========== REFRESH ==========
function refreshFiles() {
    loadFiles(currentPath, false);
    updateStats();
    showToast('Refreshed', 'success');
}

// Periodic stats update
setInterval(updateStats, 30000);
