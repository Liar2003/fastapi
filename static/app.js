// ============================================================================
// File manager frontend. No build step — plain ES2020, loaded as a single
// script. CodeMirror + xterm.js are loaded from cdnjs in index.html.
// ============================================================================
(() => {
  const appEl = document.getElementById('app');
  const CSRF = appEl.dataset.csrf;
  const USERNAME = appEl.dataset.username;
  const TERMINAL_ENABLED = appEl.dataset.terminalEnabled === 'true';

  const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'];

  const state = {
    currentPath: '',
    entries: [],
    selected: new Set(), // set of _path strings
    clipboard: null,     // { mode: 'cut'|'copy', paths: [...] }
    searchMode: false,
    lastQuery: '',
  };

  // ---- DOM refs -------------------------------------------------------------
  const tbody = document.getElementById('fileTableBody');
  const promptBar = document.getElementById('promptBar');
  const emptyState = document.getElementById('emptyState');
  const loadingState = document.getElementById('loadingState');
  const statusLeft = document.getElementById('statusLeft');
  const statusRight = document.getElementById('statusRight');
  const toastStack = document.getElementById('toastStack');
  const modalRoot = document.getElementById('modalRoot');
  const content = document.getElementById('content');
  const dropOverlay = document.getElementById('dropOverlay');
  const searchInput = document.getElementById('searchInput');
  const selectAllCheckbox = document.getElementById('selectAll');
  const fileInput = document.getElementById('fileInput');

  const btnNewFolder = document.getElementById('btnNewFolder');
  const btnUpload = document.getElementById('btnUpload');
  const btnDownload = document.getElementById('btnDownload');
  const btnCut = document.getElementById('btnCut');
  const btnCopy = document.getElementById('btnCopy');
  const btnPaste = document.getElementById('btnPaste');
  const btnCompress = document.getElementById('btnCompress');
  const btnDelete = document.getElementById('btnDelete');
  const btnLogout = document.getElementById('btnLogout');

  const btnTerminal = document.getElementById('btnTerminal');
  const btnCloseTerminal = document.getElementById('btnCloseTerminal');
  const terminalDrawer = document.getElementById('terminalDrawer');
  const terminalDragHandle = document.getElementById('terminalDragHandle');
  const termStatusDot = document.getElementById('termStatusDot');
  const termStatusText = document.getElementById('termStatusText');

  const ICONS = {
    folder: `<svg class="file-icon dir" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>`,
    file: `<svg class="file-icon file" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>`,
  };

  // ---- utils ------------------------------------------------------------
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }
  function fmtSize(bytes) {
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }
  function fmtDate(unixSeconds) {
    const d = new Date(unixSeconds * 1000);
    return d.toLocaleString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  }
  function joinPath(base, name) {
    return base ? `${base}/${name}` : name;
  }
  function shellQuote(s) {
    return `'${String(s).replace(/'/g, `'\\''`)}'`;
  }

  // ---- API helpers --------------------------------------------------------
  async function apiFetchRaw(url, opts = {}) {
    const headers = opts.headers ? { ...opts.headers } : {};
    const fetchOpts = { ...opts, headers, credentials: 'same-origin' };
    if (opts.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      fetchOpts.body = JSON.stringify(opts.json);
    }
    if (opts.method && opts.method !== 'GET') {
      headers['X-CSRF-Token'] = CSRF;
    }
    const res = await fetch(url, fetchOpts);
    if (res.status === 401) {
      window.location.href = '/login';
      throw new Error('Not authenticated');
    }
    if (!res.ok) {
      let msg = `Request failed (${res.status})`;
      try {
        const d = await res.clone().json();
        if (d && d.detail) msg = d.detail;
      } catch (_) { /* not json */ }
      throw new Error(msg);
    }
    return res;
  }
  async function apiFetch(url, opts = {}) {
    const res = await apiFetchRaw(url, opts);
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('application/json')) return res.json();
    return null;
  }

  // ---- toasts -------------------------------------------------------------
  function toast(type, title, message, opts = {}) {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<div class="toast-title">${escapeHtml(title)}</div>${message ? `<div>${escapeHtml(message)}</div>` : ''}`;
    toastStack.appendChild(el);
    if (!opts.persist) setTimeout(() => el.remove(), opts.duration || 4200);
    return el;
  }

  // ---- modals ---------------------------------------------------------------
  function showModal(innerHtml) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `<div class="modal">${innerHtml}</div>`;
    modalRoot.appendChild(backdrop);
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) backdrop.remove(); });
    return backdrop;
  }
  function promptModal(title, label, value = '') {
    return new Promise((resolve) => {
      const backdrop = showModal(`
        <h3>${escapeHtml(title)}</h3>
        <div class="field"><label>${escapeHtml(label)}</label><input type="text" id="modalInput" value="${escapeHtml(value)}"></div>
        <div class="modal-actions">
          <button class="btn" id="modalCancel">cancel</button>
          <button class="btn btn-primary" id="modalOk">confirm</button>
        </div>
      `);
      const input = backdrop.querySelector('#modalInput');
      input.focus();
      input.select();
      const finish = (val) => { backdrop.remove(); resolve(val); };
      backdrop.querySelector('#modalCancel').onclick = () => finish(null);
      backdrop.querySelector('#modalOk').onclick = () => finish(input.value.trim());
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') finish(input.value.trim());
        if (e.key === 'Escape') finish(null);
      });
    });
  }
  function confirmModal(title, messageHtml, danger = false) {
    return new Promise((resolve) => {
      const backdrop = showModal(`
        <h3>${escapeHtml(title)}</h3>
        <p style="font-size:13px;color:var(--text-secondary);line-height:1.5;">${messageHtml}</p>
        <div class="modal-actions">
          <button class="btn" id="modalCancel">cancel</button>
          <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" id="modalOk">confirm</button>
        </div>
      `);
      const finish = (val) => { backdrop.remove(); resolve(val); };
      backdrop.querySelector('#modalCancel').onclick = () => finish(false);
      backdrop.querySelector('#modalOk').onclick = () => finish(true);
    });
  }

  // ---- directory loading / rendering --------------------------------------
  async function loadDir(path) {
    state.currentPath = path;
    state.searchMode = false;
    searchInput.value = '';
    state.selected.clear();
    loadingState.classList.remove('hidden');
    emptyState.classList.add('hidden');
    tbody.innerHTML = '';
    try {
      const data = await apiFetch(`/api/list?path=${encodeURIComponent(path)}`);
      state.entries = data.entries.map((e) => ({ ...e, _path: joinPath(path, e.name) }));
      renderPrompt();
      renderTable();
    } catch (err) {
      toast('error', 'Could not load folder', err.message);
    } finally {
      loadingState.classList.add('hidden');
    }
  }

  async function runSearch(query) {
    if (!query) { loadDir(state.currentPath); return; }
    state.searchMode = true;
    state.lastQuery = query;
    loadingState.classList.remove('hidden');
    try {
      const data = await apiFetch(`/api/search?path=${encodeURIComponent(state.currentPath)}&query=${encodeURIComponent(query)}`);
      state.entries = data.results.map((r) => ({ ...r, _path: r.path }));
      state.selected.clear();
      renderPrompt();
      renderTable();
      if (data.truncated) toast('info', 'Showing first 500 matches');
    } catch (err) {
      toast('error', 'Search failed', err.message);
    } finally {
      loadingState.classList.add('hidden');
    }
  }

  function refreshView() {
    if (state.searchMode) runSearch(state.lastQuery);
    else loadDir(state.currentPath);
  }

  function renderPrompt() {
    if (state.searchMode) {
      promptBar.innerHTML = `
        <span class="prompt-user">${escapeHtml(USERNAME)}</span><span class="prompt-at">@</span><span class="prompt-host">filemanager</span><span class="prompt-colon">:</span>
        <span style="color:var(--text-secondary)">grep -r "${escapeHtml(state.lastQuery)}" ~/${escapeHtml(state.currentPath)}</span>
        <span class="prompt-seg" id="exitSearch" style="margin-left:8px;color:var(--danger)">[x cancel]</span>
      `;
      promptBar.querySelector('#exitSearch').addEventListener('click', () => loadDir(state.currentPath));
      return;
    }
    const parts = state.currentPath ? state.currentPath.split('/').filter(Boolean) : [];
    let html = `<span class="prompt-user">${escapeHtml(USERNAME)}</span><span class="prompt-at">@</span><span class="prompt-host">filemanager</span><span class="prompt-colon">:</span>`;
    html += `<span class="prompt-seg" data-path="">~</span>`;
    let acc = '';
    for (const part of parts) {
      acc = acc ? `${acc}/${part}` : part;
      html += `<span class="prompt-slash">/</span><span class="prompt-seg" data-path="${escapeHtml(acc)}">${escapeHtml(part)}</span>`;
    }
    html += `<span class="prompt-dollar">$</span><span class="prompt-cursor"></span>`;
    promptBar.innerHTML = html;
    promptBar.querySelectorAll('.prompt-seg').forEach((seg) => {
      seg.addEventListener('click', () => loadDir(seg.dataset.path));
    });
  }

  function renderTable() {
    tbody.innerHTML = '';
    emptyState.classList.toggle('hidden', state.entries.length !== 0);
    const n = state.entries.length;
    statusLeft.textContent = state.searchMode
      ? `${n} match${n === 1 ? '' : 'es'} for "${state.lastQuery}"`
      : `${n} item${n === 1 ? '' : 's'}`;

    for (const entry of state.entries) {
      const tr = document.createElement('tr');
      tr.dataset.path = entry._path;
      if (state.selected.has(entry._path)) tr.classList.add('selected');
      const displayName = state.searchMode ? entry._path : entry.name;
      tr.innerHTML = `
        <td class="col-check"><input type="checkbox" ${state.selected.has(entry._path) ? 'checked' : ''}></td>
        <td>
          <div class="file-name-cell">
            ${entry.is_dir ? ICONS.folder : ICONS.file}
            <span class="fname">${escapeHtml(displayName)}</span>
            ${entry.is_symlink ? '<span class="symlink-badge">link</span>' : ''}
          </div>
        </td>
        <td class="col-size">${entry.is_dir ? '—' : fmtSize(entry.size)}</td>
        <td class="col-modified">${fmtDate(entry.modified)}</td>
      `;
      tr.querySelector('input[type=checkbox]').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSelect(entry._path);
      });
      const nameCell = tr.querySelector('.file-name-cell');
      nameCell.addEventListener('click', () => selectOnly(entry._path));
      nameCell.addEventListener('dblclick', () => openEntry(entry));
      tr.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        openContextMenu(e.clientX, e.clientY, entry);
      });
      tbody.appendChild(tr);
    }
    selectAllCheckbox.checked = n > 0 && state.selected.size === n;
    updateToolbarState();
  }

  function selectOnly(path) {
    state.selected.clear();
    state.selected.add(path);
    refreshSelectionUI();
  }
  function toggleSelect(path) {
    if (state.selected.has(path)) state.selected.delete(path);
    else state.selected.add(path);
    refreshSelectionUI();
  }
  function refreshSelectionUI() {
    for (const tr of tbody.children) {
      const sel = state.selected.has(tr.dataset.path);
      tr.classList.toggle('selected', sel);
      tr.querySelector('input[type=checkbox]').checked = sel;
    }
    selectAllCheckbox.checked = state.entries.length > 0 && state.selected.size === state.entries.length;
    updateToolbarState();
  }
  function updateToolbarState() {
    const n = state.selected.size;
    btnDownload.disabled = n === 0;
    btnCut.disabled = n === 0;
    btnCopy.disabled = n === 0;
    btnCompress.disabled = n === 0;
    btnDelete.disabled = n === 0;
    btnPaste.disabled = !state.clipboard;
    statusRight.textContent = n ? `${n} selected` : '';
  }
  selectAllCheckbox.addEventListener('change', () => {
    if (selectAllCheckbox.checked) state.entries.forEach((e) => state.selected.add(e._path));
    else state.selected.clear();
    refreshSelectionUI();
  });

  // ---- open / preview / edit -----------------------------------------------
  async function openEntry(entry) {
    if (entry.is_dir) {
      loadDir(entry._path);
      return;
    }
    const ext = entry.name.split('.').pop().toLowerCase();
    if (IMAGE_EXTS.includes(ext)) { openImagePreview(entry._path, entry.name); return; }
    try {
      const data = await apiFetch(`/api/read?path=${encodeURIComponent(entry._path)}`);
      openEditor(entry._path, data.content);
    } catch (err) {
      const proceed = await confirmModal(
        'Can\u2019t open in editor',
        `${escapeHtml(err.message)}<br><br>Download the file instead?`
      );
      if (proceed) window.location.href = `/api/download?path=${encodeURIComponent(entry._path)}`;
    }
  }

  function openImagePreview(path, name) {
    const backdrop = showModal(`
      <h3>${escapeHtml(name)}</h3>
      <img src="/api/download?path=${encodeURIComponent(path)}" alt="${escapeHtml(name)}"
           style="max-width:100%;max-height:60vh;display:block;margin:0 auto;border-radius:4px;">
      <div class="modal-actions"><button class="btn btn-primary" id="modalOk">close</button></div>
    `);
    backdrop.querySelector('#modalOk').onclick = () => backdrop.remove();
  }

  function guessMode(path) {
    const ext = path.split('.').pop().toLowerCase();
    const map = {
      js: 'javascript', jsx: 'javascript', ts: 'javascript', tsx: 'javascript', json: 'javascript',
      py: 'python', html: 'htmlmixed', htm: 'htmlmixed', css: 'css', scss: 'css',
      md: 'markdown', sh: 'shell', bash: 'shell', sql: 'sql', yml: 'yaml', yaml: 'yaml',
      xml: 'xml',
    };
    return map[ext] || null;
  }

  function openEditor(path, content) {
    const backdrop = document.createElement('div');
    backdrop.className = 'editor-backdrop';
    backdrop.innerHTML = `
      <div class="editor-header">
        <span class="dirty-dot hidden" id="dirtyDot"></span>
        <span class="path">/${escapeHtml(path)}</span>
        <div class="spacer"></div>
        <button class="btn btn-primary" id="editorSave">Save (Ctrl+S)</button>
        <button class="btn" id="editorClose">Close</button>
      </div>
      <div class="editor-body" id="editorBody"></div>
    `;
    modalRoot.appendChild(backdrop);

    const cm = CodeMirror(backdrop.querySelector('#editorBody'), {
      value: content,
      lineNumbers: true,
      theme: 'dracula',
      mode: guessMode(path),
      tabSize: 2,
      viewportMargin: Infinity,
    });
    const dirtyDot = backdrop.querySelector('#dirtyDot');
    let dirty = false;
    cm.on('change', () => { dirty = true; dirtyDot.classList.remove('hidden'); });

    async function save() {
      try {
        await apiFetch('/api/write', { method: 'POST', json: { path, content: cm.getValue() } });
        dirty = false;
        dirtyDot.classList.add('hidden');
        toast('success', 'Saved');
      } catch (err) {
        toast('error', 'Save failed', err.message);
      }
    }
    backdrop.querySelector('#editorSave').onclick = save;
    backdrop.querySelector('#editorClose').onclick = async () => {
      if (dirty) {
        const ok = await confirmModal('Discard changes?', 'You have unsaved changes in this file.', true);
        if (!ok) return;
      }
      backdrop.remove();
      refreshView();
    };
    cm.setOption('extraKeys', {
      'Ctrl-S': () => { save(); return false; },
      'Cmd-S': () => { save(); return false; },
    });
    setTimeout(() => { cm.refresh(); cm.focus(); }, 30);
  }

  // ---- create / rename / delete / move / copy / compress -------------------
  btnNewFolder.addEventListener('click', async () => {
    const name = await promptModal('New folder', 'folder name');
    if (!name) return;
    try {
      await apiFetch('/api/mkdir', { method: 'POST', json: { path: state.currentPath, name } });
      toast('success', 'Folder created');
      refreshView();
    } catch (err) { toast('error', 'Could not create folder', err.message); }
  });

  async function renameEntry(entry) {
    const name = await promptModal('Rename', 'new name', entry.name);
    if (!name || name === entry.name) return;
    try {
      await apiFetch('/api/rename', { method: 'POST', json: { path: entry._path, new_name: name } });
      toast('success', 'Renamed');
      refreshView();
    } catch (err) { toast('error', 'Rename failed', err.message); }
  }

  async function deleteSelected() {
    const paths = [...state.selected];
    if (!paths.length) return;
    const ok = await confirmModal(
      'Delete items',
      `Delete ${paths.length} item${paths.length === 1 ? '' : 's'}? This can\u2019t be undone.`,
      true
    );
    if (!ok) return;
    try {
      const data = await apiFetch('/api/delete', { method: 'POST', json: { paths } });
      const failed = data.results.filter((r) => !r.ok);
      if (failed.length) toast('error', `${failed.length} item(s) failed to delete`, failed.map((f) => f.error).join(', '));
      else toast('success', 'Deleted');
      refreshView();
    } catch (err) { toast('error', 'Delete failed', err.message); }
  }
  btnDelete.addEventListener('click', deleteSelected);

  function cutSelected() {
    if (!state.selected.size) return;
    state.clipboard = { mode: 'cut', paths: [...state.selected] };
    toast('success', 'Cut to clipboard', `${state.clipboard.paths.length} item(s)`);
    updateToolbarState();
  }
  function copySelected() {
    if (!state.selected.size) return;
    state.clipboard = { mode: 'copy', paths: [...state.selected] };
    toast('success', 'Copied to clipboard', `${state.clipboard.paths.length} item(s)`);
    updateToolbarState();
  }
  btnCut.addEventListener('click', cutSelected);
  btnCopy.addEventListener('click', copySelected);

  btnPaste.addEventListener('click', async () => {
    if (!state.clipboard) return;
    const endpoint = state.clipboard.mode === 'cut' ? '/api/move' : '/api/copy';
    try {
      const data = await apiFetch(endpoint, {
        method: 'POST',
        json: { paths: state.clipboard.paths, destination: state.currentPath },
      });
      const failed = data.results.filter((r) => !r.ok);
      if (failed.length) toast('error', `${failed.length} item(s) failed`, failed.map((f) => f.error).join(', '));
      else toast('success', state.clipboard.mode === 'cut' ? 'Moved' : 'Copied');
      if (state.clipboard.mode === 'cut') state.clipboard = null;
      updateToolbarState();
      refreshView();
    } catch (err) { toast('error', 'Paste failed', err.message); }
  });

  async function compressSelected() {
    const paths = [...state.selected];
    if (!paths.length) return;
    const defaultName = paths.length === 1 ? paths[0].split('/').pop() : 'archive';
    const name = await promptModal('Compress to .zip', 'archive name', defaultName);
    if (!name) return;
    try {
      await apiFetch('/api/compress', {
        method: 'POST',
        json: { paths, archive_name: name, destination: state.currentPath },
      });
      toast('success', 'Archive created');
      refreshView();
    } catch (err) { toast('error', 'Compress failed', err.message); }
  }
  btnCompress.addEventListener('click', compressSelected);

  async function extractEntry(entry) {
    try {
      const data = await apiFetch('/api/extract', { method: 'POST', json: { path: entry._path } });
      toast('success', 'Extracted to', data.destination);
      refreshView();
    } catch (err) { toast('error', 'Extract failed', err.message); }
  }

  async function showInfo(entry) {
    try {
      const info = await apiFetch(`/api/info?path=${encodeURIComponent(entry._path)}`);
      const backdrop = showModal(`
        <h3>Properties</h3>
        <dl class="info-grid">
          <dt>name</dt><dd>${escapeHtml(info.name)}</dd>
          <dt>path</dt><dd>/${escapeHtml(info.path)}</dd>
          <dt>type</dt><dd>${info.is_dir ? 'directory' : 'file'}${info.is_symlink ? ' (symlink)' : ''}</dd>
          <dt>size</dt><dd>${fmtSize(info.size)}</dd>
          <dt>modified</dt><dd>${fmtDate(info.modified)}</dd>
          <dt>permissions</dt><dd>${escapeHtml(info.mode)}</dd>
        </dl>
        <div class="modal-actions"><button class="btn btn-primary" id="modalOk">close</button></div>
      `);
      backdrop.querySelector('#modalOk').onclick = () => backdrop.remove();
    } catch (err) { toast('error', 'Could not load info', err.message); }
  }

  function triggerBlobDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  async function downloadSelected() {
    const paths = [...state.selected];
    if (!paths.length) return;
    if (paths.length === 1) {
      const entry = state.entries.find((e) => e._path === paths[0]);
      if (entry && !entry.is_dir) {
        window.location.href = `/api/download?path=${encodeURIComponent(paths[0])}`;
        return;
      }
    }
    try {
      const res = await apiFetchRaw('/api/download-zip', { method: 'POST', json: { paths } });
      const blob = await res.blob();
      triggerBlobDownload(blob, 'files.zip');
    } catch (err) { toast('error', 'Download failed', err.message); }
  }
  btnDownload.addEventListener('click', downloadSelected);

  // ---- context menu -------------------------------------------------------
  let currentMenu = null;
  function closeContextMenu() { if (currentMenu) { currentMenu.remove(); currentMenu = null; } }
  document.addEventListener('click', closeContextMenu);
  content.addEventListener('scroll', closeContextMenu, true);

  function openContextMenu(x, y, entry) {
    closeContextMenu();
    if (!state.selected.has(entry._path)) selectOnly(entry._path);
    const multi = state.selected.size > 1;
    const isZip = !multi && !entry.is_dir && entry.name.toLowerCase().endsWith('.zip');

    const menu = document.createElement('div');
    menu.className = 'context-menu';
    const maxX = window.innerWidth - 200;
    const maxY = window.innerHeight - 320;
    menu.style.left = `${Math.min(x, maxX)}px`;
    menu.style.top = `${Math.min(y, maxY)}px`;
    menu.innerHTML = `
      ${!multi ? `<button data-act="open">${entry.is_dir ? 'Open' : 'Open / Edit'}</button>` : ''}
      ${!multi ? `<button data-act="rename">Rename</button>` : ''}
      <button data-act="download">Download</button>
      <button data-act="cut">Cut</button>
      <button data-act="copy">Copy</button>
      <button data-act="compress">Compress\u2026</button>
      ${isZip ? `<button data-act="extract">Extract here</button>` : ''}
      ${!multi && TERMINAL_ENABLED ? `<button data-act="terminal-here">Open terminal here</button>` : ''}
      ${!multi ? `<button data-act="info">Properties</button>` : ''}
      <div class="divider"></div>
      <button data-act="delete" class="danger">Delete</button>
    `;
    document.body.appendChild(menu);
    currentMenu = menu;
    menu.addEventListener('click', (e) => {
      const act = e.target.closest('button')?.dataset.act;
      if (!act) return;
      handleContextAction(act, entry);
    });
  }

  function handleContextAction(act, entry) {
    switch (act) {
      case 'open': openEntry(entry); break;
      case 'rename': renameEntry(entry); break;
      case 'download': downloadSelected(); break;
      case 'cut': cutSelected(); break;
      case 'copy': copySelected(); break;
      case 'compress': compressSelected(); break;
      case 'extract': extractEntry(entry); break;
      case 'terminal-here': openTerminalAt(state.searchMode ? entry._path.split('/').slice(0, -1).join('/') : state.currentPath); break;
      case 'info': showInfo(entry); break;
      case 'delete': deleteSelected(); break;
    }
  }

  // ---- upload ---------------------------------------------------------------
  btnUpload.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { uploadFiles(fileInput.files); fileInput.value = ''; });

  function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const form = new FormData();
    for (const f of fileList) form.append('files', f, f.name);

    const toastEl = toast('info', `Uploading ${fileList.length} item${fileList.length === 1 ? '' : 's'}\u2026`, '', { persist: true });
    const track = document.createElement('div'); track.className = 'progress-track';
    const fill = document.createElement('div'); fill.className = 'progress-fill';
    track.appendChild(fill); toastEl.appendChild(track);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/upload?path=${encodeURIComponent(state.currentPath)}`);
    xhr.setRequestHeader('X-CSRF-Token', CSRF);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) fill.style.width = `${Math.round((e.loaded / e.total) * 100)}%`;
    };
    xhr.onload = () => {
      toastEl.remove();
      if (xhr.status >= 200 && xhr.status < 300) {
        toast('success', 'Upload complete');
        refreshView();
      } else {
        let msg = 'Upload failed';
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (_) { /* ignore */ }
        toast('error', 'Upload failed', msg);
      }
    };
    xhr.onerror = () => { toastEl.remove(); toast('error', 'Upload failed', 'Network error'); };
    xhr.send(form);
  }

  ['dragenter', 'dragover'].forEach((evt) => content.addEventListener(evt, (e) => {
    e.preventDefault();
    dropOverlay.classList.remove('hidden');
  }));
  content.addEventListener('dragleave', (e) => {
    if (e.target === content || e.target === dropOverlay) dropOverlay.classList.add('hidden');
  });
  content.addEventListener('drop', (e) => {
    e.preventDefault();
    dropOverlay.classList.add('hidden');
    if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  });

  // ---- search -----------------------------------------------------------
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') runSearch(searchInput.value.trim());
    if (e.key === 'Escape') { searchInput.value = ''; loadDir(state.currentPath); }
  });

  // ---- keyboard shortcuts -----------------------------------------------
  document.addEventListener('keydown', (e) => {
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || document.querySelector('.editor-backdrop, .modal-backdrop')) return;
    if (e.key === 'Delete' && state.selected.size) deleteSelected();
    if (e.key === 'Escape') { state.selected.clear(); refreshSelectionUI(); }
  });

  // ---- terminal -----------------------------------------------------------
  let term = null, fitAddon = null, ws = null;

  function setTermStatus(status) {
    if (!termStatusDot) return;
    termStatusDot.className = `dot ${status}`;
    termStatusText.textContent = `terminal \u2014 ${status}`;
  }

  function initTerminalIfNeeded() {
    if (term || !TERMINAL_ENABLED) return;
    term = new Terminal({
      fontFamily: '"IBM Plex Mono", monospace',
      fontSize: 13,
      cursorBlink: true,
      theme: {
        background: '#0a0c10',
        foreground: '#e9e6dd',
        cursor: '#e8a33d',
        selectionBackground: '#a97a3055',
      },
    });
    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminalBody'));
    term.onData((data) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'input', data }));
    });
    window.addEventListener('resize', () => {
      if (terminalDrawer.classList.contains('open')) { fitAddon.fit(); sendResize(); }
    });
  }

  function sendResize() {
    if (!ws || ws.readyState !== WebSocket.OPEN || !term) return;
    ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  }

  function connectTerminal() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    setTermStatus('connecting');
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/terminal`);
    ws.onopen = () => {
      setTermStatus('connected');
      setTimeout(() => { fitAddon.fit(); sendResize(); }, 60);
    };
    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'output') term.write(msg.data);
      else if (msg.type === 'exit') { setTermStatus('disconnected'); term.write('\r\n[process exited]\r\n'); }
    };
    ws.onclose = () => setTermStatus('disconnected');
    ws.onerror = () => setTermStatus('disconnected');
  }

  function openTerminalAt(path) {
    initTerminalIfNeeded();
    terminalDrawer.classList.add('open');
    connectTerminal();
    const trySend = (attempts) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        fitAddon.fit();
        sendResize();
        const target = path ? `./${path}` : '.';
        ws.send(JSON.stringify({ type: 'input', data: `cd ${shellQuote(target)} && clear\n` }));
        term.focus();
      } else if (attempts > 0) {
        setTimeout(() => trySend(attempts - 1), 150);
      }
    };
    setTimeout(() => trySend(10), 150);
  }

  if (btnTerminal) {
    btnTerminal.addEventListener('click', () => {
      initTerminalIfNeeded();
      terminalDrawer.classList.toggle('open');
      if (terminalDrawer.classList.contains('open')) {
        connectTerminal();
        setTimeout(() => { fitAddon.fit(); sendResize(); term.focus(); }, 240);
      }
    });
  }
  if (btnCloseTerminal) {
    btnCloseTerminal.addEventListener('click', () => terminalDrawer.classList.remove('open'));
  }

  // Drag-resize the terminal drawer from its header.
  if (terminalDragHandle) {
    let dragging = false, startY = 0, startHeight = 0;
    terminalDragHandle.addEventListener('mousedown', (e) => {
      if (e.target.closest('button')) return;
      dragging = true;
      startY = e.clientY;
      startHeight = terminalDrawer.getBoundingClientRect().height;
      document.body.style.userSelect = 'none';
    });
    window.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const delta = startY - e.clientY;
      const newHeight = Math.min(Math.max(startHeight + delta, 160), window.innerHeight - 100);
      terminalDrawer.style.height = `${newHeight}px`;
    });
    window.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      document.body.style.userSelect = '';
      if (fitAddon) { fitAddon.fit(); sendResize(); }
    });
  }

  // ---- logout -----------------------------------------------------------
  btnLogout.addEventListener('click', async () => {
    try { await apiFetch('/api/logout', { method: 'POST' }); } catch (_) { /* ignore */ }
    window.location.href = '/login';
  });

  // ---- boot -----------------------------------------------------------------
  loadDir('');
})();
