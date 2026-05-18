function qs(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeJsString(value) {
  return String(value ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("'", "\\'")
    .replaceAll("\n", "\\n")
    .replaceAll("\r", "\\r");
}

async function getJson(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function setClass(el, className) {
  if (el) el.className = className;
}

function setText(el, text) {
  if (el) el.textContent = text;
}

function switchTab(tab) {
  const isPrisma = tab === "prisma";
  const prismaBtn = qs("tab-prisma-btn");
  const invoicesBtn = qs("tab-invoices-btn");

  qs("tab-prisma")?.classList.toggle("active", isPrisma);
  qs("tab-invoices")?.classList.toggle("active", !isPrisma);

  setClass(prismaBtn, "tab-btn " + (isPrisma ? "active-prisma" : "inactive"));
  setClass(invoicesBtn, "tab-btn " + (!isPrisma ? "active-invoices" : "inactive"));
}

function showStatus(el, msg, colorClass, delay = 4000) {
  if (!el) return;

  el.className = "text-xs " + colorClass;
  el.textContent = msg;
  el.classList.remove("hidden");

  if (delay) {
    setTimeout(() => el.classList.add("hidden"), delay);
  }
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");

  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();

  URL.revokeObjectURL(url);
}

const CURRENCY_STYLE = {
  SGD: { label: "SGD", color: "text-blue-400", bg: "bg-blue-500" },
  IDR: { label: "IDR", color: "text-green-400", bg: "bg-green-500" },
  MYR: { label: "MYR", color: "text-yellow-400", bg: "bg-yellow-500" },
  USD: { label: "USD", color: "text-purple-400", bg: "bg-purple-500" },
};

const BTN_IDS = {
  workflow: "btn-workflow",
  extract: "btn-extract",
  sort: "btn-sort",
};

let _lastSupplierCounts = {};
let _selectedInvoices = new Set();
let _geminiEnabled = true;
let _geminiConfigured = false;
let _statusTimer = null;

window.getGlobalGeminiEnabled = function () {
  return Boolean(_geminiEnabled && _geminiConfigured);
};

function formatAmount(num) {
  const value = Number(num || 0);

  if (value >= 1_000_000) return (value / 1_000_000).toFixed(2) + "M";
  if (value >= 1_000) return (value / 1_000).toFixed(1) + "K";

  return value.toFixed(2);
}

function updateGeminiBadge(geminiActive, configured = true) {
  const badge = qs("gemini-status-badge");
  if (!badge) return;

  if (!configured) {
    badge.textContent = "No API Key";
    badge.className = "text-xs font-semibold bg-gray-700 text-gray-500 px-2 py-0.5 rounded-full flex-shrink-0";
    return;
  }

  if (geminiActive) {
    badge.textContent = "Live";
    badge.className = "text-xs font-semibold bg-violet-500 bg-opacity-20 text-violet-400 px-2 py-0.5 rounded-full flex-shrink-0";
  } else {
    badge.textContent = "Disabled";
    badge.className = "text-xs font-semibold bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full flex-shrink-0";
  }
}

function renderGlobalGeminiToggle() {
  const btn = qs("geminiToggleBtn");
  const text = qs("geminiToggleText");
  const dot = qs("geminiToggleDot");

  if (!btn || !text || !dot) return;

  if (!_geminiConfigured) {
    btn.disabled = true;
    text.textContent = "Gemini No Key";
    dot.className = "pulse-dot bg-gray-500";
    btn.className = "flex items-center gap-1.5 text-xs font-semibold text-gray-500 bg-gray-800 border border-gray-700 px-2.5 py-1 rounded-full cursor-not-allowed";
    return;
  }

  btn.disabled = false;

  if (_geminiEnabled) {
    text.textContent = "Gemini On";
    dot.className = "pulse-dot bg-violet-400";
    btn.className = "flex items-center gap-1.5 text-xs font-semibold text-violet-300 bg-violet-500 bg-opacity-10 border border-violet-500 border-opacity-30 px-2.5 py-1 rounded-full hover:bg-opacity-20 transition";
  } else {
    text.textContent = "Gemini Off";
    dot.className = "pulse-dot bg-gray-500";
    btn.className = "flex items-center gap-1.5 text-xs font-semibold text-gray-400 bg-gray-800 border border-gray-700 px-2.5 py-1 rounded-full hover:bg-gray-700 transition";
  }
}

async function loadGeminiStatus() {
  try {
    const { data } = await getJson("/api/gemini/status");

    _geminiEnabled = Boolean(data.enabled);
    _geminiConfigured = Boolean(data.configured);

    renderGlobalGeminiToggle();
    updateGeminiBadge(Boolean(data.active), _geminiConfigured);
  } catch {
    _geminiConfigured = false;
    renderGlobalGeminiToggle();
    updateGeminiBadge(false, false);
  }
}

async function toggleGlobalGemini() {
  if (!_geminiConfigured) return;

  const nextEnabled = !_geminiEnabled;

  try {
    const { data } = await getJson("/api/gemini/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: nextEnabled }),
    });

    _geminiEnabled = Boolean(data.enabled);
    _geminiConfigured = Boolean(data.configured);

    renderGlobalGeminiToggle();
    updateGeminiBadge(Boolean(data.active), _geminiConfigured);

    logLine(
      data.message || (_geminiEnabled ? "[GEMINI] Enabled" : "[GEMINI] Disabled"),
      _geminiEnabled ? "log-info" : "log-warn"
    );
  } catch (e) {
    logLine("[ERR] Gemini toggle failed: " + e.message, "log-err");
  }
}

async function refreshSummary() {
  try {
    const { data } = await getJson("/api/summary");
    const emptyEl = qs("summary-empty");
    const dataEl = qs("summary-data");

    if (!emptyEl || !dataEl) return;

    if (!data.has_data) {
      emptyEl.classList.remove("hidden");
      dataEl.classList.add("hidden");
      return;
    }

    emptyEl.classList.add("hidden");
    dataEl.classList.remove("hidden");

    const grid = qs("currency-totals-grid");

    if (grid) {
      const totals = data.currency_totals || {};
      const currencies = Object.keys(totals).sort();

      grid.innerHTML = currencies
        .map((cur) => {
          const amount = Number(totals[cur] || 0);
          const style = CURRENCY_STYLE[cur] || {
            label: cur,
            color: "text-gray-300",
            bg: "bg-gray-500",
          };

          return `
            <div class="bg-gray-900 rounded-xl p-3 flex flex-col gap-1">
              <div class="flex items-center gap-1.5">
                <div class="w-2 h-2 rounded-full ${style.bg} bg-opacity-80 flex-shrink-0"></div>
                <span class="text-xs font-bold text-gray-400">${escapeHtml(style.label)}</span>
              </div>
              <p class="text-lg font-black ${style.color} leading-tight">${formatAmount(amount)}</p>
              <p class="text-xs text-gray-600 font-mono">${amount.toLocaleString("en-SG", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}</p>
            </div>
          `;
        })
        .join("");
    }

    renderSupplierBars(_lastSupplierCounts);
  } catch {}
}

function renderSupplierBars(counts = {}) {
  const max = Math.max(...Object.values(counts), 1);
  const keyMap = {
    Meta: "meta",
    Google: "google",
    Apple: "apple",
    AdsJoy: "adsjoy",
  };

  Object.entries(keyMap).forEach(([label, id]) => {
    const count = counts[label] || 0;
    const barEl = qs("bar-" + id);
    const cntEl = qs("count-" + id);

    if (barEl) barEl.style.width = (count / max) * 100 + "%";
    if (cntEl) cntEl.textContent = count;
  });
}

async function refreshStatus() {
  try {
    const { data: d } = await getJson("/api/status");

    setText(qs("stat-pdfs"), d.pdf_count ?? "—");
    setText(qs("stat-clients"), d.client_folders ?? "—");
    setText(qs("bubble-pdfs"), d.pdf_count ?? "—");
    setText(qs("clients-zip-count"), d.client_folders ?? "—");

    const tracker = qs("stat-tracker");

    if (tracker) {
      tracker.textContent = d.tracker_exists ? "✅ Found" : "❌ Missing";
      tracker.className = "text-sm font-bold " + (d.tracker_exists ? "text-green-400" : "text-red-400");
    }

    const report = qs("stat-report");
    const dlBtn = qs("btn-download-report");
    const reportNA = qs("report-na");

    if (report && dlBtn && reportNA) {
      if (d.report_exists) {
        report.textContent = "✅ Found";
        report.className = "text-sm font-bold text-green-400";
        dlBtn.classList.remove("hidden");
        reportNA.classList.add("hidden");
      } else {
        report.textContent = "— None yet";
        report.className = "text-sm font-bold text-gray-500";
        dlBtn.classList.add("hidden");
        reportNA.classList.remove("hidden");
      }
    }

    updateDownloadButtons(d);

    _lastSupplierCounts = d.supplier_counts || {};
    refreshSummary();

    _geminiEnabled = Boolean(d.gemini_enabled ?? _geminiEnabled);
    _geminiConfigured = Boolean(d.gemini_configured ?? d.gemini ?? _geminiConfigured);

    renderGlobalGeminiToggle();
    updateGeminiBadge(Boolean(d.gemini_active ?? (_geminiEnabled && _geminiConfigured)), _geminiConfigured);

    updateDriveUI({
      fullyConnected: Boolean(d.creds_exists && d.folder_id_set),
      credsExists: Boolean(d.creds_exists),
      folderSet: Boolean(d.folder_id_set),
      authType: d.drive_auth_type || null,
      tokenExists: Boolean(d.token_exists),
    });

    const lastRefresh = qs("last-refresh");

    if (lastRefresh) {
      lastRefresh.textContent =
        "Updated " +
        new Date().toLocaleTimeString("en-SG", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        });
    }
  } catch {
    setText(qs("server-status"), "Server unreachable");

    const lastRefresh = qs("last-refresh");

    if (lastRefresh) {
      lastRefresh.textContent =
        "Failed " +
        new Date().toLocaleTimeString("en-SG", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        });
    }
  }
}

function updateDownloadButtons(d) {
  const trackerStatusEl = qs("tracker-dl-status-text");
  const btnTracker = qs("btn-download-tracker");
  const btnClients = qs("btn-download-clients");

  if (trackerStatusEl && btnTracker) {
    if (d.tracker_exists) {
      trackerStatusEl.textContent = "✅ Ready";
      trackerStatusEl.className = "text-xs font-semibold text-green-400";
      btnTracker.disabled = false;
      btnTracker.className = "btn-action w-full py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs";
    } else {
      trackerStatusEl.textContent = "❌ Not found — run workflow first";
      trackerStatusEl.className = "text-xs font-semibold text-red-400";
      btnTracker.disabled = true;
      btnTracker.className = "btn-action w-full py-2.5 rounded-lg bg-gray-700 text-gray-500 font-bold text-xs";
    }
  }

  if (btnClients) {
    if ((d.client_folders ?? 0) === 0) {
      btnClients.disabled = true;
      btnClients.className = "btn-action w-full py-2.5 rounded-lg bg-gray-700 text-gray-500 font-bold text-xs";
    } else {
      btnClients.disabled = false;
      btnClients.className = "btn-action w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs";
    }
  }
}

function driveAuthLabel(authType) {
  if (authType === "service_account") return "Service Account";
  if (authType === "oauth") return "OAuth";
  if (authType === "invalid") return "Invalid Key";
  if (authType === "unknown") return "Unknown Key";
  return "";
}

function updateDriveUI(state) {
  const fullyConnected = Boolean(state.fullyConnected);
  const credsExists = Boolean(state.credsExists);
  const folderSet = Boolean(state.folderSet);
  const authType = state.authType;
  const authLabel = driveAuthLabel(authType);

  qs("drive-not-connected")?.classList.toggle("hidden", fullyConnected);
  qs("drive-connected")?.classList.toggle("hidden", !fullyConnected);

  const card = qs("drive-card");
  const badge = qs("drive-card-badge");

  if (card && badge) {
    if (fullyConnected) {
      card.className = "bg-gray-900 border border-green-700 border-opacity-50 rounded-2xl p-6";
      badge.className = "text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-2 py-0.5 rounded-full";
      badge.textContent = authLabel ? `✓ Connected · ${authLabel}` : "✓ Connected";
    } else if (credsExists && !folderSet) {
      card.className = "bg-gray-900 border border-orange-700 border-opacity-50 rounded-2xl p-6";
      badge.className = "text-xs font-semibold bg-orange-500 bg-opacity-20 text-orange-400 px-2 py-0.5 rounded-full";
      badge.textContent = authLabel ? `⚠ Folder ID Missing · ${authLabel}` : "⚠ Folder ID Missing";
    } else {
      card.className = "bg-gray-900 border border-yellow-800 border-opacity-40 rounded-2xl p-6";
      badge.className = "text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-2 py-0.5 rounded-full";
      badge.textContent = "Not Connected";
    }
  }

  const mini = qs("drive-mini-badge");
  const label = qs("drive-mini-label");

  if (mini && label) {
    if (fullyConnected) {
      mini.className = "bg-green-500 bg-opacity-10 border border-green-500 border-opacity-20 rounded-xl p-3 text-center";
      label.textContent = authLabel || "Connected";
      label.className = "text-xs text-green-400 mt-0.5";
    } else {
      mini.className = "bg-gray-700 bg-opacity-40 border border-gray-600 border-opacity-30 rounded-xl p-3 text-center";
      label.textContent = credsExists ? "Needs Folder ID" : "Not Connected";
      label.className = "text-xs text-gray-400 mt-0.5";
    }
  }

  const feat = qs("drive-feature-badge");

  if (feat) {
    feat.textContent = fullyConnected ? "Live" : "Not Connected";
    feat.className = fullyConnected
      ? "text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-2 py-0.5 rounded-full"
      : "text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-2 py-0.5 rounded-full";
  }

  const pipe = qs("pipe-drive");

  if (pipe) {
    pipe.className = fullyConnected
      ? "pipe-step flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-green-900 text-green-300 border border-green-700 border-opacity-50"
      : "pipe-step flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-yellow-900 text-yellow-300 border border-yellow-700 border-opacity-50";
  }

  const pipeBadge = qs("pipe-drive-badge");

  if (pipeBadge) {
    pipeBadge.textContent = fullyConnected ? "Live" : "Not Connected";
    pipeBadge.className = fullyConnected
      ? "text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-2 py-0.5 rounded-full flex-shrink-0"
      : "text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-2 py-0.5 rounded-full flex-shrink-0";
  }

  if (fullyConnected) loadFolderIDDisplay();
}

async function loadFolderIDDisplay() {
  try {
    const { data } = await getJson("/api/drive/config");
    const id = data.root_folder_id || "";

    setText(qs("folder-id-display-val"), id || "—");

    const input = qs("folder-id-input-connected");
    if (input) input.value = id;
  } catch {}
}

async function saveFolderID() {
  const input = qs("folder-id-input");
  const status = qs("folder-id-status");
  const id = input?.value.trim();

  if (!id) {
    showStatus(status, "⚠ Please enter a folder ID", "text-yellow-400");
    return;
  }

  try {
    const { res, data } = await getJson("/api/drive/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root_folder_id: id }),
    });

    showStatus(status, data.message || data.error || (res.ok ? "✓ Saved" : "Save failed"), res.ok ? "text-green-400" : "text-red-400");

    if (res.ok) {
      input.value = "";
      refreshStatus();
    }
  } catch (e) {
    showStatus(status, "[ERR] " + e.message, "text-red-400");
  }
}

async function saveFolderIDConnected() {
  const input = qs("folder-id-input-connected");
  const status = qs("folder-id-status-connected");
  const id = input?.value.trim();

  if (!id) {
    showStatus(status, "⚠ Please enter a folder ID", "text-yellow-400");
    return;
  }

  try {
    const { res, data } = await getJson("/api/drive/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root_folder_id: id }),
    });

    showStatus(status, data.message || data.error || (res.ok ? "✓ Updated" : "Update failed"), res.ok ? "text-green-400" : "text-red-400");

    if (res.ok) {
      toggleEditFolderID();
      refreshStatus();
    }
  } catch (e) {
    showStatus(status, "[ERR] " + e.message, "text-red-400");
  }
}

function toggleEditFolderID() {
  const display = qs("folder-id-display");
  const edit = qs("folder-id-edit");
  const btn = qs("btn-edit-folder");

  if (!display || !edit || !btn) return;

  const isEditing = !edit.classList.contains("hidden");

  display.classList.toggle("hidden", !isEditing);
  edit.classList.toggle("hidden", isEditing);
  btn.textContent = isEditing ? "Edit" : "Cancel";
}

function replaceCredentials() {
  qs("creds-replace-input")?.click();
}

function getCredentialStatusEl() {
  const connected = qs("drive-connected");
  const isConnected = connected && !connected.classList.contains("hidden");

  return isConnected ? qs("creds-replace-status") || qs("creds-upload-status") : qs("creds-upload-status");
}

async function removeCredentials() {
  if (!confirm("Disconnect Google Drive? This will remove credentials.json and token.json if present.")) return;

  try {
    const { data } = await getJson("/api/credentials/delete", { method: "POST" });
    logLine(data.message || "[WARN] Disconnect response received.", "log-warn");
    refreshStatus();
  } catch (e) {
    logLine("[ERR] " + e.message, "log-err");
  }
}

async function uploadCredentials(file) {
  if (!file) return;

  const status = getCredentialStatusEl();

  showStatus(status, "Uploading…", "text-yellow-400", 0);

  const form = new FormData();
  form.append("file", file);

  try {
    const { res, data } = await getJson("/api/upload/credentials", {
      method: "POST",
      body: form,
    });

    showStatus(
      status,
      data.message || data.error || (res.ok ? "✓ Key uploaded" : "Upload failed"),
      res.ok ? "text-green-400" : "text-red-400",
      res.ok ? 3000 : 0
    );

    if (res.ok) {
      setText(qs("creds-filename"), file.name + " · loaded");
      refreshStatus();
    }
  } catch (e) {
    showStatus(status, "[ERR] " + e.message, "text-red-400", 0);
  } finally {
    const input = qs("creds-input");
    const replaceInput = qs("creds-replace-input");

    if (input) input.value = "";
    if (replaceInput) replaceInput.value = "";
  }
}

function onCredsDragOver(e) {
  e.preventDefault();
  qs("creds-drop-zone")?.classList.add("drag-over");
}

function onCredsDragLeave() {
  qs("creds-drop-zone")?.classList.remove("drag-over");
}

function onCredsDrop(e) {
  e.preventDefault();
  qs("creds-drop-zone")?.classList.remove("drag-over");

  if (e.dataTransfer.files.length > 0) {
    uploadCredentials(e.dataTransfer.files[0]);
  }
}

function logLine(text, cls = "log-ok") {
  const terminal = qs("log-terminal");
  if (!terminal) return;

  const span = document.createElement("span");
  span.className = cls + " block";
  span.textContent = text;

  terminal.appendChild(span);
  terminal.scrollTop = terminal.scrollHeight;
}

function clearLog() {
  const terminal = qs("log-terminal");
  if (!terminal) return;

  terminal.innerHTML = '<span class="log-dim">$ log cleared…</span>';
}

function classifyLine(line) {
  if (/\[ERR\]|error|fail/i.test(line)) return "log-err";
  if (/\[WARN\]|warn/i.test(line)) return "log-warn";
  if (/\[DONE\]|done|success|complete|finish/i.test(line)) return "log-ok";
  if (/\[SKIP\]|===|---|already|skip/i.test(line)) return "log-dim";

  return "log-info";
}

async function streamResponseToLog(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();

    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    lines.forEach((line) => {
      if (line.trim()) logLine(line, classifyLine(line));
    });
  }

  buffer += decoder.decode();

  if (buffer.trim()) {
    logLine(buffer, classifyLine(buffer));
  }
}

async function runStream(type) {
  const btn = qs(BTN_IDS[type]);
  if (!btn) return;

  const origHTML = btn.innerHTML;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Running…';

  clearLog();
  logLine("$ running " + type + "…", "log-dim");

  try {
    const res = await fetch("/api/run/" + type);

    if (!res.ok && !res.headers.get("content-type")?.includes("text/plain")) {
      const data = await res.json().catch(() => ({}));
      logLine(data.message || data.error || "[ERR] Server error: " + res.status, "log-err");
      return;
    }

    await streamResponseToLog(res);
  } catch (e) {
    logLine("[ERR] " + e.message, "log-err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHTML;
    refreshStatus();
  }
}

async function runDriveSync() {
  const btn = qs("btn-drive");
  if (!btn) return;

  const origHTML = btn.innerHTML;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Syncing…';

  clearLog();
  logLine("$ initiating Google Drive sync…", "log-dim");

  try {
    const res = await fetch("/api/drive/sync", { method: "POST" });
    const type = res.headers.get("content-type") || "";

    if (type.includes("text/plain")) {
      await streamResponseToLog(res);
    } else {
      const data = await res.json().catch(() => ({}));
      logLine(data.message || data.error || "Response received.", res.ok ? "log-ok" : "log-warn");
    }
  } catch (e) {
    logLine("[ERR] Drive sync error: " + e.message, "log-err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = origHTML;
    refreshStatus();
  }
}

function onDragOver(e) {
  e.preventDefault();
  qs("drop-zone")?.classList.add("drag-over");
}

function onDragLeave() {
  qs("drop-zone")?.classList.remove("drag-over");
}

function onDrop(e) {
  e.preventDefault();
  qs("drop-zone")?.classList.remove("drag-over");
  uploadFiles(e.dataTransfer.files);
}

async function uploadFiles(files) {
  if (!files || files.length === 0) return;

  const status = qs("upload-status");

  showStatus(status, "Uploading " + files.length + " file(s)…", "text-sky-400", 0);

  const form = new FormData();

  for (const file of files) {
    form.append("files", file);
  }

  try {
    const { res, data } = await getJson("/api/upload", {
      method: "POST",
      body: form,
    });

    showStatus(
      status,
      data.message || data.error || "Upload complete",
      res.ok ? "text-sky-400" : "text-red-400",
      res.ok ? 4000 : 0
    );

    refreshStatus();
    loadInvoiceList();
  } catch (e) {
    showStatus(status, "[ERR] Upload failed: " + e.message, "text-red-400", 0);
  }
}

async function loadInvoiceList() {
  try {
    const { data } = await getJson("/api/invoices");
    const files = data.files || [];
    const panel = qs("invoice-list-panel");
    const listEl = qs("invoice-file-list");
    const countEl = qs("invoice-list-count");

    if (!panel || !listEl || !countEl) return;

    _selectedInvoices.clear();
    updateDeleteButton();

    if (!files.length) {
      panel.classList.add("hidden");
      listEl.innerHTML = "";
      countEl.textContent = "0";
      return;
    }

    panel.classList.remove("hidden");
    countEl.textContent = files.length;

    listEl.innerHTML = files
      .map((filename) => {
        const safeHtml = escapeHtml(filename);
        const safeJs = escapeJsString(filename);
        const safeId = CSS.escape(filename);

        return `
          <div class="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800 transition group" id="row-${safeId}">
            <input
              type="checkbox"
              class="invoice-checkbox w-3.5 h-3.5 rounded accent-red-500 cursor-pointer flex-shrink-0"
              value="${safeHtml}"
              onchange="onInvoiceCheckbox(this)"
            />
            <span class="text-red-400 text-xs flex-shrink-0">📄</span>
            <span class="text-xs text-gray-300 font-mono truncate flex-1" title="${safeHtml}">${safeHtml}</span>
            <button
              onclick="deleteSingleInvoice('${safeJs}')"
              class="opacity-0 group-hover:opacity-100 text-xs text-gray-600 hover:text-red-400 transition px-1.5 py-0.5 rounded hover:bg-red-500 hover:bg-opacity-10 flex-shrink-0"
              title="Delete ${safeHtml}">
              ✕
            </button>
          </div>
        `;
      })
      .join("");
  } catch {}
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
  const count = _selectedInvoices.size;

  setText(qs("selected-count"), count);
  qs("btn-delete-selected")?.classList.toggle("hidden", count === 0);
}

function toggleSelectAll() {
  const checkboxes = [...document.querySelectorAll(".invoice-checkbox")];

  if (!checkboxes.length) return;

  const allChecked = checkboxes.every((cb) => cb.checked);

  checkboxes.forEach((cb) => {
    cb.checked = !allChecked;

    if (cb.checked) {
      _selectedInvoices.add(cb.value);
    } else {
      _selectedInvoices.delete(cb.value);
    }
  });

  setText(qs("btn-select-all"), allChecked ? "Select All" : "Deselect All");
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
  const statusEl = qs("invoice-list-status");
  const statusP = statusEl?.querySelector("p");

  statusEl?.classList.remove("hidden");

  if (statusP) {
    statusP.className = "text-xs text-yellow-400";
    statusP.textContent = `⏳ Deleting ${filenames.length} file(s)…`;
  }

  try {
    const { res, data } = await getJson("/api/invoices/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filenames }),
    });

    if (statusP) {
      if (res.ok) {
        statusP.className = "text-xs text-green-400";
        statusP.textContent = `✓ Deleted ${(data.deleted || []).length} file(s)`;
        setTimeout(() => statusEl?.classList.add("hidden"), 3000);
      } else {
        statusP.className = "text-xs text-red-400";
        statusP.textContent = `✕ ${data.error || data.message || "Delete failed"}`;
      }
    }

    _selectedInvoices.clear();
    loadInvoiceList();
    refreshStatus();
  } catch (e) {
    if (statusP) {
      statusP.className = "text-xs text-red-400";
      statusP.textContent = "[ERR] " + e.message;
    }
  }
}

async function uploadTracker(file) {
  if (!file) return;

  const el = qs("tracker-upload-status");

  showStatus(el, "Uploading…", "text-indigo-300", 0);

  const form = new FormData();
  form.append("file", file);

  try {
    const { res, data } = await getJson("/api/upload/tracker", {
      method: "POST",
      body: form,
    });

    showStatus(
      el,
      data.message || data.error || (res.ok ? "✓ Uploaded" : "Upload failed"),
      res.ok ? "text-green-400" : "text-red-400",
      res.ok ? 4000 : 0
    );

    refreshStatus();
  } catch (e) {
    showStatus(el, "[ERR] " + e.message, "text-red-400", 0);
  } finally {
    const input = qs("tracker-input");
    if (input) input.value = "";
  }
}

function downloadReport() {
  window.location.href = "/api/download/report";
}

async function downloadClientsZip() {
  const btn = qs("btn-download-clients");
  const status = qs("clients-zip-dl-status");

  if (!btn) return;

  const orig = btn.innerHTML;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Zipping…';

  showStatus(status, "Preparing ZIP…", "text-indigo-400", 0);

  try {
    const res = await fetch("/api/download/clients-zip");

    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      showStatus(status, d.error || d.message || "Download failed", "text-red-400", 0);
      return;
    }

    const blob = await res.blob();

    triggerBlobDownload(blob, "Clients.zip");
    showStatus(status, "✓ Download started", "text-green-400", 4000);
  } catch (e) {
    showStatus(status, "[ERR] " + e.message, "text-red-400", 0);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function parseFilenameFromDisposition(disposition, fallback) {
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);

  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {}
  }

  const normalMatch = disposition.match(/filename="?([^"]+)"?/i);
  return normalMatch ? normalMatch[1] : fallback;
}

async function downloadTracker() {
  const btn = qs("btn-download-tracker");
  const status = qs("tracker-dl-status");

  if (!btn) return;

  const orig = btn.innerHTML;

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Preparing…';

  showStatus(status, "Downloading…", "text-emerald-400", 0);

  try {
    const res = await fetch("/api/download/tracker");

    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      showStatus(status, d.error || d.message || "Download failed", "text-red-400", 0);
      return;
    }

    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const filename = parseFilenameFromDisposition(disposition, "tracker.xlsx");

    triggerBlobDownload(blob, filename);
    showStatus(status, "✓ Download started", "text-green-400", 4000);
  } catch (e) {
    showStatus(status, "[ERR] " + e.message, "text-red-400", 0);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

function openDriveSetupModal(tab = "oauth") {
  const modal = qs("drive-setup-modal");

  if (!modal) return;

  modal.classList.remove("hidden");
  modal.classList.add("flex");

  switchDriveTab(tab);
}

function closeDriveSetupModal() {
  const modal = qs("drive-setup-modal");

  if (!modal) return;

  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

function switchDriveTab(tab) {
  const oauthContent = qs("modal-tab-oauth");
  const saContent = qs("modal-tab-sa");
  const oauthBtn = qs("modal-tab-oauth-btn");
  const saBtn = qs("modal-tab-sa-btn");
  const isOAuth = tab === "oauth";

  oauthContent?.classList.toggle("hidden", !isOAuth);
  saContent?.classList.toggle("hidden", isOAuth);

  if (oauthBtn) {
    oauthBtn.className =
      "flex-1 py-3 text-xs font-bold transition border-b-2 " +
      (isOAuth
        ? "border-blue-500 text-blue-400 bg-blue-500 bg-opacity-5"
        : "border-transparent text-gray-500 hover:text-gray-300");
  }

  if (saBtn) {
    saBtn.className =
      "flex-1 py-3 text-xs font-bold transition border-b-2 " +
      (!isOAuth
        ? "border-purple-500 text-purple-400 bg-purple-500 bg-opacity-5"
        : "border-transparent text-gray-500 hover:text-gray-300");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  qs("geminiToggleBtn")?.addEventListener("click", toggleGlobalGemini);

  loadGeminiStatus();
  refreshStatus();
  loadInvoiceList();

  if (_statusTimer) clearInterval(_statusTimer);
  _statusTimer = setInterval(refreshStatus, 8000);
});