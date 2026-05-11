function switchTab(tab) {
  const isPrisma = tab === 'prisma';
  document.getElementById('tab-prisma').classList.toggle('active', isPrisma);
  document.getElementById('tab-invoices').classList.toggle('active', !isPrisma);
  document.getElementById('tab-prisma-btn').className   = 'tab-btn ' + (isPrisma  ? 'active-prisma'   : 'inactive');
  document.getElementById('tab-invoices-btn').className = 'tab-btn ' + (!isPrisma ? 'active-invoices' : 'inactive');
}

function showStatus(el, msg, colorClass, delay = 4000) {
  el.className = 'text-xs ' + colorClass;
  el.textContent = msg;
  el.classList.remove('hidden');
  if (delay) setTimeout(() => el.classList.add('hidden'), delay);
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href     = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const CURRENCY_STYLE = {
  SGD: { label: 'SGD', color: 'text-blue-400',   bg: 'bg-blue-500'   },
  IDR: { label: 'IDR', color: 'text-green-400',  bg: 'bg-green-500'  },
  MYR: { label: 'MYR', color: 'text-yellow-400', bg: 'bg-yellow-500' },
  USD: { label: 'USD', color: 'text-purple-400', bg: 'bg-purple-500' },
};

function formatAmount(num) {
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(2) + 'M';
  if (num >= 1_000)     return (num / 1_000).toFixed(1) + 'K';
  return num.toFixed(2);
}

let _lastSupplierCounts = {};

async function refreshSummary() {
  try {
    const res  = await fetch('/api/summary');
    const data = await res.json();

    const emptyEl = document.getElementById('summary-empty');
    const dataEl  = document.getElementById('summary-data');
    if (!emptyEl || !dataEl) return;

    if (!data.has_data) {
      emptyEl.classList.remove('hidden');
      dataEl.classList.add('hidden');
      return;
    }

    emptyEl.classList.add('hidden');
    dataEl.classList.remove('hidden');

    const grid = document.getElementById('currency-totals-grid');
    if (grid) {
      const currencies = Object.keys(data.currency_totals).sort();
      grid.innerHTML = currencies.map(cur => {
        const amount = data.currency_totals[cur];
        const style  = CURRENCY_STYLE[cur] || { label: cur, color: 'text-gray-300', bg: 'bg-gray-500' };
        return `
          <div class="bg-gray-900 rounded-xl p-3 flex flex-col gap-1">
            <div class="flex items-center gap-1.5">
              <div class="w-2 h-2 rounded-full ${style.bg} bg-opacity-80 flex-shrink-0"></div>
              <span class="text-xs font-bold text-gray-400">${style.label}</span>
            </div>
            <p class="text-lg font-black ${style.color} leading-tight">${formatAmount(amount)}</p>
            <p class="text-xs text-gray-600 font-mono">${amount.toLocaleString('en-SG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
          </div>`;
      }).join('');
    }

    renderSupplierBars(_lastSupplierCounts);

  } catch (e) {}
}

function renderSupplierBars(counts) {
  const max    = Math.max(...Object.values(counts), 1);
  const keyMap = { Meta: 'meta', Google: 'google', Apple: 'apple', AdsJoy: 'adsjoy' };
  Object.entries(keyMap).forEach(([label, id]) => {
    const count = counts[label] || 0;
    const barEl = document.getElementById('bar-' + id);
    const cntEl = document.getElementById('count-' + id);
    if (barEl) barEl.style.width = (count / max * 100) + '%';
    if (cntEl) cntEl.textContent = count;
  });
}

function updateGeminiBadge(geminiActive) {
  const badge = document.getElementById('gemini-status-badge');
  if (!badge) return;
  if (geminiActive) {
    badge.textContent = 'Live';
    badge.className   = 'text-xs font-semibold bg-violet-500 bg-opacity-20 text-violet-400 px-2 py-0.5 rounded-full flex-shrink-0';
  } else {
    badge.textContent = 'No API Key';
    badge.className   = 'text-xs font-semibold bg-gray-700 text-gray-500 px-2 py-0.5 rounded-full flex-shrink-0';
  }
}

async function refreshStatus() {
  try {
    const res = await fetch('/api/status');
    const d   = await res.json();

    document.getElementById('stat-pdfs').textContent         = d.pdf_count      ?? '—';
    document.getElementById('stat-clients').textContent      = d.client_folders  ?? '—';
    document.getElementById('bubble-pdfs').textContent       = d.pdf_count      ?? '—';
    document.getElementById('clients-zip-count').textContent = d.client_folders ?? '—';

    const tracker = document.getElementById('stat-tracker');
    tracker.textContent = d.tracker_exists ? '✅ Found' : '❌ Missing';
    tracker.className   = 'text-sm font-bold ' + (d.tracker_exists ? 'text-green-400' : 'text-red-400');

    const report   = document.getElementById('stat-report');
    const dlBtn    = document.getElementById('btn-download-report');
    const reportNA = document.getElementById('report-na');
    if (d.report_exists) {
      report.textContent = '✅ Found';
      report.className   = 'text-sm font-bold text-green-400';
      dlBtn.classList.remove('hidden');
      reportNA.classList.add('hidden');
    } else {
      report.textContent = '— None yet';
      report.className   = 'text-sm font-bold text-gray-500';
      dlBtn.classList.add('hidden');
      reportNA.classList.remove('hidden');
    }

    const trackerStatusEl = document.getElementById('tracker-dl-status-text');
    const btnTracker      = document.getElementById('btn-download-tracker');
    const btnClients      = document.getElementById('btn-download-clients');

    if (d.tracker_exists) {
      trackerStatusEl.textContent = '✅ Ready';
      trackerStatusEl.className   = 'text-xs font-semibold text-green-400';
      btnTracker.disabled  = false;
      btnTracker.className = 'btn-action w-full py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs';
    } else {
      trackerStatusEl.textContent = '❌ Not found — run workflow first';
      trackerStatusEl.className   = 'text-xs font-semibold text-red-400';
      btnTracker.disabled  = true;
      btnTracker.className = 'btn-action w-full py-2.5 rounded-lg bg-gray-700 text-gray-500 font-bold text-xs';
    }

    if ((d.client_folders ?? 0) === 0) {
      btnClients.disabled  = true;
      btnClients.className = 'btn-action w-full py-2.5 rounded-lg bg-gray-700 text-gray-500 font-bold text-xs';
    } else {
      btnClients.disabled  = false;
      btnClients.className = 'btn-action w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs';
    }

    _lastSupplierCounts = d.supplier_counts || {};
    refreshSummary();

    updateGeminiBadge(d.gemini ?? false);

    const fullyConnected = d.creds_exists && d.folder_id_set;
    updateDriveUI(fullyConnected, d.creds_exists, d.folder_id_set);

    document.getElementById('last-refresh').textContent =
      'Updated ' + new Date().toLocaleTimeString('en-SG', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  } catch (e) {
    document.getElementById('server-status').textContent = 'Server unreachable';
    document.getElementById('last-refresh').textContent =
      'Failed ' + new Date().toLocaleTimeString('en-SG', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
}

refreshStatus();
setInterval(refreshStatus, 8000);

function updateDriveUI(fullyConnected, credsExists, folderSet) {
  document.getElementById('drive-badge-connected').classList.toggle('hidden', !fullyConnected);
  document.getElementById('drive-badge-connected').classList.toggle('flex',    fullyConnected);
  document.getElementById('drive-badge-disconnected').classList.toggle('hidden', fullyConnected);
  document.getElementById('drive-not-connected').classList.toggle('hidden',    fullyConnected);
  document.getElementById('drive-connected').classList.toggle('hidden',       !fullyConnected);

  const card  = document.getElementById('drive-card');
  const badge = document.getElementById('drive-card-badge');

  if (fullyConnected) {
    card.className    = 'bg-gray-900 border border-green-700 border-opacity-50 rounded-2xl p-6';
    badge.className   = 'text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-2 py-0.5 rounded-full';
    badge.textContent = '✓ Connected';
  } else if (credsExists && !folderSet) {
    card.className    = 'bg-gray-900 border border-orange-700 border-opacity-50 rounded-2xl p-6';
    badge.className   = 'text-xs font-semibold bg-orange-500 bg-opacity-20 text-orange-400 px-2 py-0.5 rounded-full';
    badge.textContent = '⚠ Folder ID Missing';
  } else {
    card.className    = 'bg-gray-900 border border-yellow-800 border-opacity-40 rounded-2xl p-6';
    badge.className   = 'text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-2 py-0.5 rounded-full';
    badge.textContent = 'Not Connected';
  }

  const mini      = document.getElementById('drive-mini-badge');
  const label     = document.getElementById('drive-mini-label');
  const feat      = document.getElementById('drive-feature-badge');
  const pipe      = document.getElementById('pipe-drive');
  const pipeBadge = document.getElementById('pipe-drive-badge');

  if (fullyConnected) {
    mini.className    = 'bg-green-500 bg-opacity-10 border border-green-500 border-opacity-20 rounded-xl p-3 text-center';
    label.textContent = 'Connected';
    label.className   = 'text-xs text-green-400 mt-0.5';
    if (feat) { feat.textContent = 'Live'; feat.className = 'text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-2 py-0.5 rounded-full'; }
    pipe.className    = 'pipe-step flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-green-900 text-green-300 border border-green-700 border-opacity-50';
    if (pipeBadge) {
      pipeBadge.textContent = 'Live';
      pipeBadge.className   = 'text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-2 py-0.5 rounded-full flex-shrink-0';
    }
  } else {
    mini.className    = 'bg-gray-700 bg-opacity-40 border border-gray-600 border-opacity-30 rounded-xl p-3 text-center';
    label.textContent = 'Not Connected';
    label.className   = 'text-xs text-gray-400 mt-0.5';
    if (feat) { feat.textContent = 'Not Connected'; feat.className = 'text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-2 py-0.5 rounded-full'; }
    pipe.className    = 'pipe-step flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-yellow-900 text-yellow-300 border border-yellow-700 border-opacity-50';
    if (pipeBadge) {
      pipeBadge.textContent = 'Not Connected';
      pipeBadge.className   = 'text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-2 py-0.5 rounded-full flex-shrink-0';
    }
  }

  if (fullyConnected) loadFolderIDDisplay();
}

async function loadFolderIDDisplay() {
  try {
    const res  = await fetch('/api/drive/config');
    const data = await res.json();
    const id   = data.root_folder_id || '';
    const el   = document.getElementById('folder-id-display-val');
    if (el) el.textContent = id || '—';
    const inp = document.getElementById('folder-id-input-connected');
    if (inp) inp.value = id;
  } catch (e) {}
}

async function saveFolderID() {
  const input  = document.getElementById('folder-id-input');
  const id     = input.value.trim();
  const status = document.getElementById('folder-id-status');
  if (!id) { showStatus(status, '⚠ Please enter a folder ID', 'text-yellow-400'); return; }
  try {
    const res  = await fetch('/api/drive/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root_folder_id: id }),
    });
    const data = await res.json();
    showStatus(status, data.message || (res.ok ? '✓ Saved' : data.error), res.ok ? 'text-green-400' : 'text-red-400');
    if (res.ok) { input.value = ''; refreshStatus(); }
  } catch (e) { showStatus(status, '[ERR] ' + e.message, 'text-red-400'); }
}

async function saveFolderIDConnected() {
  const input  = document.getElementById('folder-id-input-connected');
  const id     = input.value.trim();
  const status = document.getElementById('folder-id-status-connected');
  if (!id) { showStatus(status, '⚠ Please enter a folder ID', 'text-yellow-400'); return; }
  try {
    const res  = await fetch('/api/drive/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root_folder_id: id }),
    });
    const data = await res.json();
    showStatus(status, data.message || (res.ok ? '✓ Updated' : data.error), res.ok ? 'text-green-400' : 'text-red-400');
    if (res.ok) { toggleEditFolderID(); refreshStatus(); }
  } catch (e) { showStatus(status, '[ERR] ' + e.message, 'text-red-400'); }
}

function toggleEditFolderID() {
  const display   = document.getElementById('folder-id-display');
  const edit      = document.getElementById('folder-id-edit');
  const btn       = document.getElementById('btn-edit-folder');
  const isEditing = !edit.classList.contains('hidden');
  display.classList.toggle('hidden', !isEditing);
  edit.classList.toggle('hidden', isEditing);
  btn.textContent = isEditing ? 'Edit' : 'Cancel';
}

function replaceCredentials() {
  document.getElementById('creds-replace-input').click();
}

async function removeCredentials() {
  if (!confirm('Disconnect Google Drive? You can reconnect anytime by uploading credentials.json again.')) return;
  try {
    const res  = await fetch('/api/credentials/delete', { method: 'POST' });
    const data = await res.json();
    logLine(data.message, 'log-warn');
    refreshStatus();
  } catch (e) { logLine('[ERR] ' + e.message, 'log-err'); }
}

async function uploadCredentials(file) {
  if (!file) return;
  const status = document.getElementById('creds-upload-status');
  showStatus(status, 'Uploading…', 'text-yellow-400', 0);
  const form = new FormData();
  form.append('file', file);
  try {
    const res  = await fetch('/api/upload/credentials', { method: 'POST', body: form });
    const data = await res.json();
    showStatus(status, data.message || (res.ok ? '✓ Key uploaded' : data.error),
      res.ok ? 'text-green-400' : 'text-red-400', res.ok ? 3000 : 0);
    if (res.ok) {
      document.getElementById('creds-filename').textContent = file.name + ' · loaded';
      refreshStatus();
    }
  } catch (e) { showStatus(status, '[ERR] ' + e.message, 'text-red-400', 0); }
}

function onCredsDragOver(e) { e.preventDefault(); document.getElementById('creds-drop-zone').classList.add('drag-over'); }
function onCredsDragLeave() { document.getElementById('creds-drop-zone').classList.remove('drag-over'); }
function onCredsDrop(e) {
  e.preventDefault();
  document.getElementById('creds-drop-zone').classList.remove('drag-over');
  if (e.dataTransfer.files.length > 0) uploadCredentials(e.dataTransfer.files[0]);
}

const terminal = document.getElementById('log-terminal');

function logLine(text, cls = 'log-ok') {
  const span = document.createElement('span');
  span.className   = cls + ' block';
  span.textContent = text;
  terminal.appendChild(span);
  terminal.scrollTop = terminal.scrollHeight;
}

function clearLog() {
  terminal.innerHTML = '<span class="log-dim">$ log cleared…</span>';
}

function classifyLine(line) {
  if (/\[ERR\]|error|fail/i.test(line))                    return 'log-err';
  if (/\[WARN\]|warn/i.test(line))                         return 'log-warn';
  if (/\[DONE\]|done|success|complete|finish/i.test(line)) return 'log-ok';
  if (/\[SKIP\]|===|---|already|skip/i.test(line))         return 'log-dim';
  return 'log-info';
}

const BTN_IDS = { workflow: 'btn-workflow', extract: 'btn-extract', sort: 'btn-sort' };

async function runStream(type) {
  const btn      = document.getElementById(BTN_IDS[type]);
  const origHTML = btn.innerHTML;
  btn.disabled   = true;
  btn.innerHTML  = '<span class="spinner"></span> Running…';
  clearLog();
  logLine('$ running ' + type + '…', 'log-dim');
  try {
    const res = await fetch('/api/run/' + type);
    if (!res.ok) { logLine('[ERR] Server error: ' + res.status, 'log-err'); return; }
    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      decoder.decode(value).split('\n').forEach(line => {
        if (line.trim()) logLine(line, classifyLine(line));
      });
    }
  } catch (e) { logLine('[ERR] ' + e.message, 'log-err'); }
  finally { btn.disabled = false; btn.innerHTML = origHTML; refreshStatus(); }
}

async function runDriveSync() {
  const btn      = document.getElementById('btn-drive');
  const origHTML = btn.innerHTML;
  btn.disabled   = true;
  btn.innerHTML  = '<span class="spinner"></span> Syncing…';
  clearLog();
  logLine('$ initiating Google Drive sync…', 'log-dim');
  try {
    const res = await fetch('/api/drive/sync', { method: 'POST' });
    if (res.headers.get('content-type')?.includes('text/plain')) {
      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        decoder.decode(value).split('\n').forEach(line => {
          if (line.trim()) logLine(line, classifyLine(line));
        });
      }
    } else {
      const data = await res.json();
      logLine(data.message || 'Response received.', res.ok ? 'log-ok' : 'log-warn');
    }
  } catch (e) { logLine('[ERR] Drive sync error: ' + e.message, 'log-err'); }
  finally { btn.disabled = false; btn.innerHTML = origHTML; refreshStatus(); }
}

function onDragOver(e)  { e.preventDefault(); document.getElementById('drop-zone').classList.add('drag-over'); }
function onDragLeave()  { document.getElementById('drop-zone').classList.remove('drag-over'); }
function onDrop(e) {
  e.preventDefault();
  document.getElementById('drop-zone').classList.remove('drag-over');
  uploadFiles(e.dataTransfer.files);
}

async function uploadFiles(files) {
  if (!files || files.length === 0) return;
  const status = document.getElementById('upload-status');
  showStatus(status, 'Uploading ' + files.length + ' file(s)…', 'text-sky-400', 0);
  const form = new FormData();
  for (const f of files) form.append('files', f);
  try {
    const res  = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await res.json();
    showStatus(status, data.message || 'Upload complete', 'text-sky-400', 4000);
    refreshStatus();
    loadInvoiceList();
  } catch (e) { showStatus(status, '[ERR] Upload failed: ' + e.message, 'text-red-400', 0); }
}

// ── Invoice List ─────────────────────────────────────────────────────────────

let _selectedInvoices = new Set();

async function loadInvoiceList() {
  try {
    const res   = await fetch('/api/invoices');
    const data  = await res.json();
    const files = data.files || [];

    const panel    = document.getElementById('invoice-list-panel');
    const listEl   = document.getElementById('invoice-file-list');
    const countEl  = document.getElementById('invoice-list-count');

    // Clear stale selections
    _selectedInvoices.clear();
    updateDeleteButton();

    if (files.length === 0) {
      panel.classList.add('hidden');
      return;
    }

    panel.classList.remove('hidden');
    countEl.textContent = files.length;

    listEl.innerHTML = files.map(filename => `
      <div class="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800 transition group" id="row-${CSS.escape(filename)}">
        <input
          type="checkbox"
          class="invoice-checkbox w-3.5 h-3.5 rounded accent-red-500 cursor-pointer flex-shrink-0"
          value="${filename}"
          onchange="onInvoiceCheckbox(this)"
        />
        <span class="text-red-400 text-xs flex-shrink-0">📄</span>
        <span class="text-xs text-gray-300 font-mono truncate flex-1" title="${filename}">${filename}</span>
        <button
          onclick="deleteSingleInvoice('${filename}')"
          class="opacity-0 group-hover:opacity-100 text-xs text-gray-600 hover:text-red-400 transition px-1.5 py-0.5 rounded hover:bg-red-500 hover:bg-opacity-10 flex-shrink-0"
          title="Delete ${filename}">
          ✕
        </button>
      </div>
    `).join('');

  } catch (e) {}
}

function onInvoiceCheckbox(checkbox) {
  if (checkbox.checked) {
    _selectedInvoices.add(checkbox.value);
  } else {
    _selectedInvoices.delete(checkbox.value);
  }
  updateDeleteButton();
}

function updateDeleteButton() {
  const btn      = document.getElementById('btn-delete-selected');
  const countEl  = document.getElementById('selected-count');
  const count    = _selectedInvoices.size;
  countEl.textContent = count;
  if (count > 0) {
    btn.classList.remove('hidden');
  } else {
    btn.classList.add('hidden');
  }
}

function toggleSelectAll() {
  const checkboxes = document.querySelectorAll('.invoice-checkbox');
  const allChecked = [...checkboxes].every(cb => cb.checked);
  checkboxes.forEach(cb => {
    cb.checked = !allChecked;
    if (cb.checked) {
      _selectedInvoices.add(cb.value);
    } else {
      _selectedInvoices.delete(cb.value);
    }
  });
  const btn = document.getElementById('btn-select-all');
  btn.textContent = allChecked ? 'Select All' : 'Deselect All';
  updateDeleteButton();
}

async function deleteSingleInvoice(filename) {
  await deleteInvoices([filename]);
}

async function deleteSelectedInvoices() {
  if (_selectedInvoices.size === 0) return;
  await deleteInvoices([..._selectedInvoices]);
}

async function deleteInvoices(filenames) {
  const statusEl = document.getElementById('invoice-list-status');
  const statusP  = statusEl.querySelector('p');

  statusEl.classList.remove('hidden');
  statusP.className   = 'text-xs text-yellow-400';
  statusP.textContent = `⏳ Deleting ${filenames.length} file(s)…`;

  try {
    const res  = await fetch('/api/invoices/delete', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ filenames }),
    });
    const data = await res.json();

    if (res.ok) {
      statusP.className   = 'text-xs text-green-400';
      statusP.textContent = `✓ Deleted ${data.deleted.length} file(s)`;
      setTimeout(() => statusEl.classList.add('hidden'), 3000);
    } else {
      statusP.className   = 'text-xs text-red-400';
      statusP.textContent = `✕ ${data.error || 'Delete failed'}`;
    }

    _selectedInvoices.clear();
    loadInvoiceList();
    refreshStatus();

  } catch (e) {
    statusP.className   = 'text-xs text-red-400';
    statusP.textContent = '[ERR] ' + e.message;
  }
}

// Load invoice list on page ready
document.addEventListener('DOMContentLoaded', loadInvoiceList);

// ── End Invoice List ──────────────────────────────────────────────────────────

function openClearModal() {
  const modal  = document.getElementById('clear-modal');
  const status = document.getElementById('clear-modal-status');
  status.classList.add('hidden');
  status.textContent = '';
  document.getElementById('btn-clear-confirm').disabled = false;
  document.getElementById('btn-clear-confirm').innerHTML = '🗑️ Yes, Clear Everything';
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeClearModal() {
  const modal = document.getElementById('clear-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function confirmClearWorkspace() {
  const btn    = document.getElementById('btn-clear-confirm');
  const status = document.getElementById('clear-modal-status');
  const banner = document.getElementById('clear-workspace-status');

  btn.disabled  = true;
  btn.innerHTML = '<span class="spinner"></span> Clearing…';
  showStatus(status, '⏳ Clearing workspace…', 'text-yellow-400', 0);
  status.classList.remove('hidden');

  try {
    const res  = await fetch('/api/clear/workspace', { method: 'POST' });
    const data = await res.json();

    if (res.ok) {
      showStatus(status, '✓ ' + data.message, 'text-green-400', 0);
      logLine('🗑️  ' + data.message, 'log-ok');
      showStatus(banner, '✓ Workspace cleared', 'text-green-400', 5000);
      banner.classList.remove('hidden');
      refreshStatus();
      loadInvoiceList();
      setTimeout(() => closeClearModal(), 1800);
    } else {
      showStatus(status, '✕ ' + (data.error || 'Clear failed'), 'text-red-400', 0);
      btn.disabled  = false;
      btn.innerHTML = '🗑️ Yes, Clear Everything';
    }
  } catch (e) {
    showStatus(status, '✕ ' + e.message, 'text-red-400', 0);
    btn.disabled  = false;
    btn.innerHTML = '🗑️ Yes, Clear Everything';
  }
}

async function uploadTracker(file) {
  if (!file) return;
  const el = document.getElementById('tracker-upload-status');
  showStatus(el, 'Uploading…', 'text-indigo-300', 0);
  const form = new FormData();
  form.append('file', file);
  try {
    const res  = await fetch('/api/upload/tracker', { method: 'POST', body: form });
    const data = await res.json();
    showStatus(el, data.message || (res.ok ? '✓ Uploaded' : data.error),
      res.ok ? 'text-green-400' : 'text-red-400', 4000);
    refreshStatus();
  } catch (e) { showStatus(el, '[ERR] ' + e.message, 'text-red-400', 0); }
}

function downloadReport() {
  window.location.href = '/api/download/report';
}

async function downloadClientsZip() {
  const btn    = document.getElementById('btn-download-clients');
  const status = document.getElementById('clients-zip-dl-status');
  const orig   = btn.innerHTML;
  btn.disabled  = true;
  btn.innerHTML = '<span class="spinner"></span> Zipping…';
  showStatus(status, 'Preparing ZIP…', 'text-indigo-400', 0);
  try {
    const res = await fetch('/api/download/clients-zip');
    if (!res.ok) {
      const d = await res.json();
      showStatus(status, d.error || 'Download failed', 'text-red-400', 0);
      return;
    }
    const blob = await res.blob();
    triggerBlobDownload(blob, 'Clients.zip');
    showStatus(status, '✓ Download started', 'text-green-400', 4000);
  } catch (e) {
    showStatus(status, '[ERR] ' + e.message, 'text-red-400', 0);
  } finally {
    btn.disabled  = false;
    btn.innerHTML = orig;
  }
}

async function downloadTracker() {
  const btn    = document.getElementById('btn-download-tracker');
  const status = document.getElementById('tracker-dl-status');
  const orig   = btn.innerHTML;
  btn.disabled  = true;
  btn.innerHTML = '<span class="spinner"></span> Preparing…';
  showStatus(status, 'Downloading…', 'text-emerald-400', 0);
  try {
    const res = await fetch('/api/download/tracker');
    if (!res.ok) {
      const d = await res.json();
      showStatus(status, d.error || 'Download failed', 'text-red-400', 0);
      return;
    }
    const blob        = await res.blob();
    const disposition = res.headers.get('Content-Disposition') || '';
    const match       = disposition.match(/filename="?([^"]+)"?/);
    const filename    = match ? match[1] : 'tracker.xlsx';
    triggerBlobDownload(blob, filename);
    showStatus(status, '✓ Download started', 'text-green-400', 4000);
  } catch (e) {
    showStatus(status, '[ERR] ' + e.message, 'text-red-400', 0);
  } finally {
    btn.disabled  = false;
    btn.innerHTML = orig;
  }
}

function openDriveSetupModal(tab = 'oauth') {
  const modal = document.getElementById('drive-setup-modal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  switchDriveTab(tab);
}

function closeDriveSetupModal() {
  const modal = document.getElementById('drive-setup-modal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function switchDriveTab(tab) {
  const oauthContent = document.getElementById('modal-tab-oauth');
  const saContent    = document.getElementById('modal-tab-sa');
  const oauthBtn     = document.getElementById('modal-tab-oauth-btn');
  const saBtn        = document.getElementById('modal-tab-sa-btn');

  const isOAuth = tab === 'oauth';

  oauthContent.classList.toggle('hidden', !isOAuth);
  saContent.classList.toggle('hidden',     isOAuth);

  oauthBtn.className = 'flex-1 py-3 text-xs font-bold transition border-b-2 '
    + (isOAuth
      ? 'border-blue-500 text-blue-400 bg-blue-500 bg-opacity-5'
      : 'border-transparent text-gray-500 hover:text-gray-300');

  saBtn.className = 'flex-1 py-3 text-xs font-bold transition border-b-2 '
    + (!isOAuth
      ? 'border-purple-500 text-purple-400 bg-purple-500 bg-opacity-5'
      : 'border-transparent text-gray-500 hover:text-gray-300');
}
