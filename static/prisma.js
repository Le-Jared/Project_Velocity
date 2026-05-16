// static/prisma.js

(function () {
  "use strict";

  const PrismaUI = {
    plans: [],
    selectedPlans: new Set(),
    status: null,
    pendingDeleteFiles: [],
    els: {},

    init() {
      this.cacheElements();

      if (!this.els.planList) {
        console.warn("[PRISMA] Prisma tab elements not found.");
        return;
      }

      this.bindEvents();
      this.refreshStatus();
      this.refreshPlans();
    },

    cacheElements() {
      this.els = {
        // Media plan upload
        planInput: document.querySelector("#prismaPlanInput"),
        dropZone: document.querySelector("#prismaDropZone"),
        uploadBadge: document.querySelector("#prismaUploadBadge"),
        uploadStatus: document.querySelector("#prismaUploadStatus"),
        uploadStatusText: document.querySelector("#prismaUploadStatusText"),
        uploadStatusCount: document.querySelector("#prismaUploadStatusCount"),
        uploadProgress: document.querySelector("#prismaUploadProgress"),

        // Reference files: Buying Guide
        buyingGuideInput: document.querySelector("#buyingGuideInput"),
        buyingGuideUploadBtn: document.querySelector("#buyingGuideUploadBtn"),
        buyingGuidePickBtn: document.querySelector("#buyingGuidePickBtn"),
        buyingGuideMeta: document.querySelector("#buyingGuideMeta"),
        buyingGuideSelectedWrap: document.querySelector("#buyingGuideSelectedWrap"),
        buyingGuideSelectedName: document.querySelector("#buyingGuideSelectedName"),

        // Reference files: Prisma Template
        templateInput: document.querySelector("#prismaTemplateInput"),
        templateUploadBtn: document.querySelector("#prismaTemplateUploadBtn"),
        templatePickBtn: document.querySelector("#prismaTemplatePickBtn"),
        templateMeta: document.querySelector("#prismaTemplateMeta"),
        templateSelectedWrap: document.querySelector("#prismaTemplateSelectedWrap"),
        templateSelectedName: document.querySelector("#prismaTemplateSelectedName"),

        // Status
        refreshStatusBtn: document.querySelector("#prismaRefreshStatusBtn"),
        readyBadge: document.querySelector("#prismaReadyBadge"),
        guideStatus: document.querySelector("#buyingGuideStatus"),
        templateStatus: document.querySelector("#prismaTemplateStatus"),
        clientsStatus: document.querySelector("#prismaClientsStatus"),

        // Plans
        planList: document.querySelector("#prismaPlanList"),
        emptyPlans: document.querySelector("#prismaEmptyPlans"),
        selectAllPlansBtn: document.querySelector("#prismaSelectAllPlansBtn"),
        clearSelectedPlansBtn: document.querySelector("#prismaClearSelectedPlansBtn"),
        selectedCount: document.querySelector("#prismaSelectedCount"),

        // Convert
        clientMode: document.querySelector("#prismaClientMode"),
        convertSelectedBtn: document.querySelector("#prismaConvertSelectedBtn"),

        // Batch Results
        batchResultPanel: document.querySelector("#prismaBatchResultPanel"),
        batchSummary: document.querySelector("#prismaBatchSummary"),
        batchResultList: document.querySelector("#prismaBatchResultList"),

        // Match preview
        matchTable: document.querySelector("#prismaMatchTable"),
        matchTableBody: document.querySelector("#prismaMatchTableBody"),

        // Log / toast
        logBox: document.querySelector("#prismaLog"),
        toastContainer: document.querySelector("#prismaToastContainer"),

        // Delete modal
        deleteModal: document.querySelector("#prismaDeleteModal"),
        deleteModalText: document.querySelector("#prismaDeleteModalText"),
        deleteFileList: document.querySelector("#prismaDeleteFileList"),
        deleteCancelBtn: document.querySelector("#prismaDeleteCancelBtn"),
        deleteConfirmBtn: document.querySelector("#prismaDeleteConfirmBtn"),
      };
    },

    bindEvents() {
      // Reference files
      this.els.buyingGuideUploadBtn?.addEventListener("click", () => this.uploadBuyingGuide());
      this.els.templateUploadBtn?.addEventListener("click", () => this.uploadTemplate());
      this.els.refreshStatusBtn?.addEventListener("click", () => this.refreshStatus());

      // Batch selection
      this.els.selectAllPlansBtn?.addEventListener("click", () => this.selectAllPlans());
      this.els.clearSelectedPlansBtn?.addEventListener("click", () => this.clearSelectedPlans());

      // Batch convert
      this.els.convertSelectedBtn?.addEventListener("click", () => this.convertSelectedPlans());

      // Buying Guide replacement selection
      this.els.buyingGuideInput?.addEventListener("change", () => {
        const file = this.els.buyingGuideInput.files?.[0];

        if (file) {
          if (this.els.buyingGuideSelectedName) {
            this.els.buyingGuideSelectedName.textContent = file.name;
          }

          this.els.buyingGuideSelectedWrap?.classList.remove("hidden");
          this.toast(`Selected replacement Buying Guide: ${file.name}`, "info");
        }
      });

      // Prisma Template replacement selection
      this.els.templateInput?.addEventListener("change", () => {
        const file = this.els.templateInput.files?.[0];

        if (file) {
          if (this.els.templateSelectedName) {
            this.els.templateSelectedName.textContent = file.name;
          }

          this.els.templateSelectedWrap?.classList.remove("hidden");
          this.toast(`Selected replacement Prisma Template: ${file.name}`, "info");
        }
      });

      // Media plan file picker auto-upload
      this.els.planInput?.addEventListener("change", () => {
        const files = Array.from(this.els.planInput.files || []);

        if (files.length) {
          this.uploadPlanFiles(files);
        }
      });

      // Drag/drop zone
      this.els.dropZone?.addEventListener("click", () => {
        this.els.planInput?.click();
      });

      this.els.dropZone?.addEventListener("dragover", (event) => {
        event.preventDefault();
        this.setDropZoneActive(true);
      });

      this.els.dropZone?.addEventListener("dragleave", () => {
        this.setDropZoneActive(false);
      });

      this.els.dropZone?.addEventListener("drop", (event) => {
        event.preventDefault();
        this.setDropZoneActive(false);

        const files = Array.from(event.dataTransfer.files || []);
        this.uploadPlanFiles(files);
      });

      // Delete modal
      this.els.deleteCancelBtn?.addEventListener("click", () => this.closeDeleteModal());
      this.els.deleteConfirmBtn?.addEventListener("click", () => this.confirmDeletePlans());

      this.els.deleteModal?.addEventListener("click", (event) => {
        if (event.target === this.els.deleteModal) {
          this.closeDeleteModal();
        }
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          this.closeDeleteModal();
        }
      });
    },

    async api(url, options = {}) {
      const response = await fetch(url, options);

      let data;

      try {
        data = await response.json();
      } catch {
        data = { error: "Invalid JSON response from server." };
      }

      if (!response.ok) {
        throw new Error(data.error || data.message || `Request failed: ${response.status}`);
      }

      return data;
    },

    log(message, type = "info") {
    const prefix = {
        info: "ℹ",
        success: "✓",
        warn: "⚠",
        error: "✕",
    }[type] || "ℹ";

    console.log("[PRISMA]", message);

    if (!this.els.logBox) return;

    const div = document.createElement("div");

    const colorClass = {
        info: "text-blue-300",
        success: "text-green-300",
        warn: "text-yellow-300",
        error: "text-red-300",
    }[type] || "text-gray-400";

    div.className = `${colorClass} border-b border-gray-800 border-opacity-60 py-1`;
    div.textContent = `${prefix} ${message}`;

    this.els.logBox.appendChild(div);
    this.els.logBox.scrollTop = this.els.logBox.scrollHeight;
    },

    toast(message, type = "info") {
      if (!this.els.toastContainer) return;

      const styles = {
        success: {
          icon: "✅",
          border: "border-green-700",
          bg: "bg-green-950",
          text: "text-green-200",
        },
        error: {
          icon: "❌",
          border: "border-red-700",
          bg: "bg-red-950",
          text: "text-red-200",
        },
        warn: {
          icon: "⚠️",
          border: "border-yellow-700",
          bg: "bg-yellow-950",
          text: "text-yellow-200",
        },
        info: {
          icon: "ℹ️",
          border: "border-blue-700",
          bg: "bg-blue-950",
          text: "text-blue-200",
        },
      };

      const s = styles[type] || styles.info;

      const toast = document.createElement("div");
      toast.className = `
        pointer-events-auto transform transition-all duration-300 translate-x-4 opacity-0
        ${s.bg} ${s.border} ${s.text}
        border rounded-2xl shadow-2xl px-4 py-3
      `;

      toast.innerHTML = `
        <div class="flex items-start gap-3">
          <span class="text-lg">${s.icon}</span>
          <p class="text-sm font-semibold leading-5 flex-1">${this.escapeHtml(message)}</p>
          <button type="button" class="text-white text-opacity-50 hover:text-opacity-100 transition">×</button>
        </div>
      `;

      const close = () => {
        toast.classList.add("translate-x-4", "opacity-0");
        setTimeout(() => toast.remove(), 250);
      };

      toast.querySelector("button").addEventListener("click", close);

      this.els.toastContainer.appendChild(toast);

      requestAnimationFrame(() => {
        toast.classList.remove("translate-x-4", "opacity-0");
      });

      setTimeout(close, 4200);
    },

    pill(el, ok, text) {
      if (!el) return;

      el.textContent = text;
      el.className = ok
        ? "text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-2 py-1 rounded-full"
        : "text-xs font-semibold bg-red-500 bg-opacity-20 text-red-400 px-2 py-1 rounded-full";
    },

    setDropZoneActive(active) {
      if (!this.els.dropZone) return;

      this.els.dropZone.classList.toggle("border-violet-400", active);
      this.els.dropZone.classList.toggle("bg-violet-500", active);
      this.els.dropZone.classList.toggle("bg-opacity-10", active);
      this.els.dropZone.classList.toggle("scale-[1.01]", active);
    },

    isValidPlanFile(file) {
      const name = file.name.toLowerCase();
      return name.endsWith(".xlsx") || name.endsWith(".xls");
    },

    setUploadState(isUploading, text = "", count = "", progress = 0) {
      if (this.els.uploadBadge) {
        this.els.uploadBadge.classList.toggle("hidden", !isUploading);
      }

      if (this.els.uploadStatus) {
        this.els.uploadStatus.classList.toggle("hidden", !isUploading && progress === 0);
      }

      if (this.els.uploadStatusText) {
        this.els.uploadStatusText.textContent = text || "Preparing upload…";
      }

      if (this.els.uploadStatusCount) {
        this.els.uploadStatusCount.textContent = count || "—";
      }

      if (this.els.uploadProgress) {
        this.els.uploadProgress.style.width = `${progress}%`;
      }
    },

    async uploadPlanFiles(files) {
      const validFiles = files.filter((file) => this.isValidPlanFile(file));
      const invalidFiles = files.filter((file) => !this.isValidPlanFile(file));

      if (invalidFiles.length) {
        this.toast(`${invalidFiles.length} unsupported file(s) skipped. Only .xlsx/.xls accepted.`, "warn");
        this.log(`${invalidFiles.length} unsupported file(s) skipped.`, "warn");
      }

      if (!validFiles.length) {
        this.toast("No valid media plan files found.", "warn");
        return;
      }

      const formData = new FormData();

      validFiles.forEach((file) => {
        formData.append("files", file);
      });

      try {
        this.setUploadState(true, "Uploading media plan files…", `${validFiles.length} file(s)`, 35);
        this.log(`Uploading ${validFiles.length} media plan file(s)...`);

        const data = await this.api("/api/prisma/upload", {
          method: "POST",
          body: formData,
        });

        this.setUploadState(
          true,
          "Upload complete. Refreshing plan list…",
          `${data.count || validFiles.length} uploaded`,
          80
        );

        this.toast(data.message || "Media plan upload complete.", "success");
        this.log(data.message || "Upload complete.", "success");

        if (this.els.planInput) {
          this.els.planInput.value = "";
        }

        await this.refreshPlans();

        // Auto-select newly uploaded files silently for batch conversion.
        if (data.saved?.length) {
          data.saved.forEach((filename) => this.selectedPlans.add(filename));
          this.renderPlans();
          this.updateSelectedCount();
        }

        this.setUploadState(true, "Done.", `${data.count || validFiles.length} uploaded`, 100);

        setTimeout(() => {
          this.setUploadState(false, "", "", 0);
        }, 900);
      } catch (err) {
        this.setUploadState(false, "", "", 0);
        this.toast(`Upload failed: ${err.message}`, "error");
        this.log(`Upload failed: ${err.message}`, "error");
      }
    },

    async refreshStatus() {
      try {
        const data = await this.api("/api/prisma/status");
        this.status = data;
        this.renderStatus(data);
      } catch (err) {
        this.toast(`Failed to load Prisma status: ${err.message}`, "error");
        this.log(`Failed to load Prisma status: ${err.message}`, "error");
      }
    },

    renderStatus(data) {
      this.pill(
        this.els.guideStatus,
        data.guide_loaded,
        data.guide_loaded
          ? `Loaded · ${data.guide_rows} rows`
          : data.guide_exists
            ? "Parse error"
            : "Missing"
      );

      this.pill(
        this.els.templateStatus,
        data.template_exists,
        data.template_exists ? "Loaded" : "Missing"
      );

      if (this.els.buyingGuideMeta) {
        this.els.buyingGuideMeta.textContent = data.guide_loaded
          ? `Currently loaded · ${data.guide_rows} rows · upload a new .xlsx file to replace it`
          : data.guide_exists
            ? "File exists but could not be parsed · upload a replacement .xlsx file"
            : "No Buying Guide uploaded yet · choose a .xlsx file to add one";
      }

      if (this.els.templateMeta) {
        this.els.templateMeta.textContent = data.template_exists
          ? "Currently loaded · upload a new .xlsx file to replace it"
          : "No Prisma Template uploaded yet · choose a .xlsx file to add one";
      }

      if (this.els.buyingGuidePickBtn) {
        this.els.buyingGuidePickBtn.textContent = data.guide_exists ? "Replace" : "Choose File";
      }

      if (this.els.templatePickBtn) {
        this.els.templatePickBtn.textContent = data.template_exists ? "Replace" : "Choose File";
      }

      if (this.els.readyBadge) {
        const ready = data.guide_loaded && data.template_exists;

        this.els.readyBadge.textContent = ready ? "Ready" : "Setup Required";
        this.els.readyBadge.className = ready
          ? "text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-3 py-1 rounded-full"
          : "text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-3 py-1 rounded-full";
      }

      if (this.els.clientsStatus) {
        this.els.clientsStatus.textContent =
          data.clients && data.clients.length ? data.clients.join(", ") : "None detected";
      }

      this.renderClientModeOptions(data.clients || []);

      if (data.error) {
        this.toast(`Status warning: ${data.error}`, "warn");
        this.log(`Status warning: ${data.error}`, "warn");
      }
    },

    renderClientModeOptions(clients) {
      if (!this.els.clientMode) return;

      const currentValue = this.els.clientMode.value || "AUTO";
      const defaults = ["GU", "MI", "MCP"];
      const values = [...new Set([...(clients || []), ...defaults])];

      this.els.clientMode.innerHTML = "";

      const autoOption = document.createElement("option");
      autoOption.value = "AUTO";
      autoOption.textContent = "Auto Detect";
      this.els.clientMode.appendChild(autoOption);

      values.forEach((client) => {
        const option = document.createElement("option");
        option.value = client;
        option.textContent = `Force ${client}`;
        this.els.clientMode.appendChild(option);
      });

      this.els.clientMode.value = values.includes(currentValue) || currentValue === "AUTO"
        ? currentValue
        : "AUTO";
    },

    async refreshPlans() {
      try {
        const data = await this.api("/api/prisma/plans");
        this.plans = data.plans || [];

        // Remove selections for files that no longer exist.
        const existing = new Set(this.plans.map((plan) => plan.filename));
        this.selectedPlans = new Set(
          Array.from(this.selectedPlans).filter((filename) => existing.has(filename))
        );

        this.renderPlans();
        this.updateSelectedCount();
      } catch (err) {
        this.toast(`Failed to load media plans: ${err.message}`, "error");
        this.log(`Failed to load media plans: ${err.message}`, "error");
      }
    },

    renderPlans() {
      if (!this.els.planList) return;

      this.els.planList.innerHTML = "";

      if (!this.plans.length) {
        if (this.els.emptyPlans) {
          this.els.emptyPlans.classList.remove("hidden");
        }
        return;
      }

      if (this.els.emptyPlans) {
        this.els.emptyPlans.classList.add("hidden");
      }

      const toolbar = document.createElement("div");
      toolbar.className = "flex items-center justify-between gap-3 mb-3";

      toolbar.innerHTML = `
        <div class="text-xs text-gray-500">
          Tick plans to include in batch conversion.
        </div>

        <div class="flex items-center gap-2">
          <button id="prismaSelectAllPlansBtnInline"
                  type="button"
                  class="text-xs font-semibold bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded-lg transition">
            Select All
          </button>

          <button id="prismaClearSelectedPlansBtnInline"
                  type="button"
                  class="text-xs font-semibold bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded-lg transition">
            Clear
          </button>
        </div>
      `;

      toolbar.querySelector("#prismaSelectAllPlansBtnInline").addEventListener("click", () => {
        this.selectAllPlans();
      });

      toolbar.querySelector("#prismaClearSelectedPlansBtnInline").addEventListener("click", () => {
        this.clearSelectedPlans();
      });

      this.els.planList.appendChild(toolbar);

      this.plans.forEach((plan) => {
        const checked = this.selectedPlans.has(plan.filename);

        const item = document.createElement("div");

        item.className = checked
          ? "flex items-center justify-between gap-3 bg-violet-900 bg-opacity-30 border border-violet-600 rounded-xl px-4 py-3"
          : "flex items-center justify-between gap-3 bg-gray-950 border border-gray-800 rounded-xl px-4 py-3 hover:border-violet-700 transition";

        item.innerHTML = `
          <label class="flex items-center gap-3 min-w-0 cursor-pointer flex-1">
            <input type="checkbox"
                   class="prisma-plan-checkbox w-4 h-4 accent-violet-600 flex-shrink-0"
                   data-filename="${this.escapeHtml(plan.filename)}"
                   ${checked ? "checked" : ""}>

            <div class="min-w-0">
              <p class="text-sm font-bold text-white truncate">${this.escapeHtml(plan.filename)}</p>
              <p class="text-xs text-gray-500">
                ${plan.size_kb} KB${plan.detected_client ? ` · detected: ${this.escapeHtml(plan.detected_client)}` : ""}
              </p>
            </div>
          </label>

          <button type="button"
                  class="prisma-delete-plan text-xs font-semibold bg-red-500 bg-opacity-10 text-red-400 px-2 py-1 rounded-lg hover:bg-opacity-20 flex-shrink-0"
                  data-filename="${this.escapeHtml(plan.filename)}">
            Delete
          </button>
        `;

        const checkbox = item.querySelector(".prisma-plan-checkbox");

        checkbox.addEventListener("change", () => {
          this.togglePlanSelection(plan.filename, checkbox.checked);
        });

        item.querySelector(".prisma-delete-plan").addEventListener("click", (event) => {
          event.stopPropagation();
          this.openDeleteModal([plan.filename]);
        });

        this.els.planList.appendChild(item);
      });
    },

    togglePlanSelection(filename, checked) {
      if (checked) {
        this.selectedPlans.add(filename);
      } else {
        this.selectedPlans.delete(filename);
      }

      this.renderPlans();
      this.updateSelectedCount();
    },

    selectAllPlans() {
      this.plans.forEach((plan) => this.selectedPlans.add(plan.filename));
      this.renderPlans();
      this.updateSelectedCount();
    },

    clearSelectedPlans() {
      this.selectedPlans.clear();
      this.renderPlans();
      this.updateSelectedCount();
    },

    updateSelectedCount() {
      const count = this.selectedPlans.size;

      if (this.els.selectedCount) {
        this.els.selectedCount.textContent = `${count} selected`;
      }

      if (this.els.convertSelectedBtn) {
        this.els.convertSelectedBtn.disabled = count === 0;
        this.els.convertSelectedBtn.classList.toggle("opacity-60", count === 0);
        this.els.convertSelectedBtn.classList.toggle("cursor-not-allowed", count === 0);
      }
    },

    async uploadBuyingGuide() {
      if (!this.els.buyingGuideInput?.files.length) {
        this.toast("Please choose a Buying Guide file first.", "warn");
        this.log("Please choose a Buying Guide file first.", "warn");
        return;
      }

      const formData = new FormData();
      formData.append("file", this.els.buyingGuideInput.files[0]);

      try {
        this.log("Uploading Buying Guide...");

        const data = await this.api("/api/upload/buying-guide", {
          method: "POST",
          body: formData,
        });

        this.toast(data.message || "Buying Guide uploaded.", data.valid ? "success" : "warn");
        this.log(data.message || "Buying Guide uploaded.", data.valid ? "success" : "warn");

        this.els.buyingGuideInput.value = "";

        this.els.buyingGuideSelectedWrap?.classList.add("hidden");

        if (this.els.buyingGuideSelectedName) {
          this.els.buyingGuideSelectedName.textContent = "—";
        }

        await this.refreshStatus();
      } catch (err) {
        this.toast(`Buying Guide upload failed: ${err.message}`, "error");
        this.log(`Buying Guide upload failed: ${err.message}`, "error");
      }
    },

    async uploadTemplate() {
      if (!this.els.templateInput?.files.length) {
        this.toast("Please choose a Prisma template file first.", "warn");
        this.log("Please choose a Prisma template file first.", "warn");
        return;
      }

      const formData = new FormData();
      formData.append("file", this.els.templateInput.files[0]);

      try {
        this.log("Uploading Prisma template...");

        const data = await this.api("/api/upload/prisma-template", {
          method: "POST",
          body: formData,
        });

        this.toast(data.message || "Prisma template uploaded.", data.valid ? "success" : "warn");
        this.log(data.message || "Prisma template uploaded.", data.valid ? "success" : "warn");

        this.els.templateInput.value = "";

        this.els.templateSelectedWrap?.classList.add("hidden");

        if (this.els.templateSelectedName) {
          this.els.templateSelectedName.textContent = "—";
        }

        await this.refreshStatus();
      } catch (err) {
        this.toast(`Prisma template upload failed: ${err.message}`, "error");
        this.log(`Prisma template upload failed: ${err.message}`, "error");
      }
    },

    async convertSelectedPlans() {
      const filenames = Array.from(this.selectedPlans);

      if (!filenames.length) {
        this.toast("Select at least one media plan to convert.", "warn");
        this.log("Select at least one media plan to convert.", "warn");
        return;
      }

      const clientMode = this.els.clientMode?.value || "AUTO";

      this.setBatchConverting(true, filenames.length);
      this.renderBatchStart(filenames);

      const results = [];

      for (let index = 0; index < filenames.length; index++) {
        const filename = filenames[index];

        try {
          this.updateBatchSummary(index, filenames.length, `Converting ${filename}`);

          this.log(`Converting ${filename} (${index + 1}/${filenames.length})...`);

          const payload = {
            filename,
            use_gemini: false,
          };

          if (clientMode !== "AUTO") {
            payload.client = clientMode;
          }

          const data = await this.api("/api/prisma/convert", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
          });

          results.push({
            filename,
            ok: true,
            data,
          });

          this.log(`Converted ${filename}`, "success");
          this.renderBatchResults(results, filenames.length);
        } catch (err) {
          results.push({
            filename,
            ok: false,
            error: err.message,
          });

          this.log(`Failed to convert ${filename}: ${err.message}`, "error");
          this.renderBatchResults(results, filenames.length);
        }
      }

      const successCount = results.filter((item) => item.ok).length;
      const failCount = results.length - successCount;

      this.updateBatchSummary(
        filenames.length,
        filenames.length,
        `${successCount} converted, ${failCount} failed`
      );

      if (successCount && !failCount) {
        this.toast(`Converted ${successCount} media plan(s).`, "success");
      } else if (successCount && failCount) {
        this.toast(`Converted ${successCount}; ${failCount} failed.`, "warn");
      } else {
        this.toast("No media plans converted successfully.", "error");
      }

      // Show match preview for the last successful conversion.
      const lastSuccess = [...results].reverse().find((item) => item.ok);

      if (lastSuccess) {
        this.renderMatchPreview(lastSuccess.data.preview || []);
      }

      this.setBatchConverting(false, filenames.length);
    },

    setBatchConverting(isConverting, total = 0) {
      if (!this.els.convertSelectedBtn) return;

      this.els.convertSelectedBtn.disabled = isConverting || this.selectedPlans.size === 0;
      this.els.convertSelectedBtn.textContent = isConverting
        ? `Converting ${total} plan(s)...`
        : "Convert Selected";

      this.els.convertSelectedBtn.classList.toggle("opacity-60", isConverting || this.selectedPlans.size === 0);
      this.els.convertSelectedBtn.classList.toggle("cursor-not-allowed", isConverting || this.selectedPlans.size === 0);
    },

    renderBatchStart(filenames) {
      if (this.els.batchResultPanel) {
        this.els.batchResultPanel.classList.remove("hidden");
      }

      if (this.els.batchSummary) {
        this.els.batchSummary.textContent = `0 / ${filenames.length}`;
      }

      if (this.els.batchResultList) {
        this.els.batchResultList.innerHTML = filenames
          .map((filename) => `
            <div class="flex items-center justify-between gap-3 bg-gray-900 border border-gray-800 rounded-xl px-3 py-2"
                 data-result-row="${this.escapeHtml(filename)}">
              <div class="min-w-0">
                <p class="text-xs font-bold text-white truncate">${this.escapeHtml(filename)}</p>
                <p class="text-xs text-gray-500">Queued</p>
              </div>

              <span class="text-xs text-gray-500 flex-shrink-0">Waiting</span>
            </div>
          `)
          .join("");
      }
    },

    updateBatchSummary(done, total, label) {
      if (this.els.batchSummary) {
        this.els.batchSummary.textContent = `${done} / ${total} · ${label}`;
      }
    },

    renderBatchResults(results, total) {
      if (!this.els.batchResultPanel || !this.els.batchResultList) return;

      this.els.batchResultPanel.classList.remove("hidden");

      const resultMap = new Map(results.map((item) => [item.filename, item]));

      this.els.batchResultList.innerHTML = Array.from(this.selectedPlans)
        .map((filename) => {
          const result = resultMap.get(filename);

          if (!result) {
            return `
              <div class="flex items-center justify-between gap-3 bg-gray-900 border border-gray-800 rounded-xl px-3 py-2">
                <div class="min-w-0">
                  <p class="text-xs font-bold text-white truncate">${this.escapeHtml(filename)}</p>
                  <p class="text-xs text-gray-500">Queued</p>
                </div>

                <span class="text-xs text-gray-500 flex-shrink-0">Waiting</span>
              </div>
            `;
          }

          if (!result.ok) {
            return `
              <div class="flex items-center justify-between gap-3 bg-red-950 border border-red-800 rounded-xl px-3 py-2">
                <div class="min-w-0">
                  <p class="text-xs font-bold text-red-100 truncate">${this.escapeHtml(filename)}</p>
                  <p class="text-xs text-red-300 truncate">${this.escapeHtml(result.error)}</p>
                </div>

                <span class="text-xs font-bold text-red-300 flex-shrink-0">Failed</span>
              </div>
            `;
          }

          const outputFile = result.data.output_file || "Prisma import";
          const downloadUrl = result.data.download_url || "#";

          return `
            <div class="flex items-center justify-between gap-3 bg-green-950 border border-green-800 rounded-xl px-3 py-2">
              <div class="min-w-0">
                <p class="text-xs font-bold text-green-100 truncate">${this.escapeHtml(filename)}</p>
                <p class="text-xs text-green-300 truncate">${this.escapeHtml(outputFile)}</p>
              </div>

              <a href="${this.escapeHtml(downloadUrl)}"
                 class="text-xs font-bold bg-green-600 hover:bg-green-500 text-white px-3 py-2 rounded-lg transition flex-shrink-0">
                Download
              </a>
            </div>
          `;
        })
        .join("");

      if (this.els.batchSummary) {
        const done = results.length;
        this.els.batchSummary.textContent = `${done} / ${total}`;
      }
    },

    renderMatchPreview(records) {
      if (!this.els.matchTable || !this.els.matchTableBody) return;

      this.els.matchTableBody.innerHTML = "";

      if (!records.length) {
        this.els.matchTable.classList.add("hidden");
        return;
      }

      records.forEach((record) => {
        const tr = document.createElement("tr");
        tr.className = "border-b border-gray-800";

        tr.innerHTML = `
          <td class="py-3 pr-4">${this.escapeHtml(record.partner || "")}</td>
          <td class="py-3 pr-4">${this.escapeHtml(record.placement_name || "")}</td>
          <td class="py-3 pr-4">${this.escapeHtml(record.status || "")}</td>
          <td class="py-3 pr-4">${this.escapeHtml(record.supplier_name || "")}</td>
          <td class="py-3 pr-4">${this.escapeHtml(String(record.supplier_code || ""))}</td>
          <td class="py-3 pr-4">${this.escapeHtml(record.placement_booking_type || "")}</td>
        `;

        this.els.matchTableBody.appendChild(tr);
      });

      this.els.matchTable.classList.remove("hidden");
    },

    openDeleteModal(filenames) {
      this.pendingDeleteFiles = filenames;

      if (!this.els.deleteModal) return;

      const count = filenames.length;

      if (this.els.deleteModalText) {
        this.els.deleteModalText.textContent =
          count === 1
            ? "This media plan will be removed from the uploaded plans folder."
            : `${count} media plans will be removed from the uploaded plans folder.`;
      }

      if (this.els.deleteFileList) {
        this.els.deleteFileList.innerHTML = filenames
          .map((name) => `<div class="truncate">• ${this.escapeHtml(name)}</div>`)
          .join("");
      }

      this.els.deleteModal.classList.remove("hidden");
      this.els.deleteModal.classList.add("flex");
    },

    closeDeleteModal() {
      if (!this.els.deleteModal) return;

      this.els.deleteModal.classList.add("hidden");
      this.els.deleteModal.classList.remove("flex");
      this.pendingDeleteFiles = [];
    },

    async confirmDeletePlans() {
      const filenames = this.pendingDeleteFiles;

      if (!filenames.length) {
        this.closeDeleteModal();
        return;
      }

      try {
        if (this.els.deleteConfirmBtn) {
          this.els.deleteConfirmBtn.disabled = true;
          this.els.deleteConfirmBtn.textContent = "Deleting...";
          this.els.deleteConfirmBtn.classList.add("opacity-60", "cursor-not-allowed");
        }

        const data = await this.api("/api/prisma/plans/delete", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ filenames }),
        });

        this.toast(data.message || "Deleted media plan.", "success");
        this.log(data.message || "Deleted.", "success");

        filenames.forEach((filename) => this.selectedPlans.delete(filename));

        this.closeDeleteModal();

        await this.refreshPlans();
      } catch (err) {
        this.toast(`Delete failed: ${err.message}`, "error");
        this.log(`Delete failed: ${err.message}`, "error");
      } finally {
        if (this.els.deleteConfirmBtn) {
          this.els.deleteConfirmBtn.disabled = false;
          this.els.deleteConfirmBtn.textContent = "Delete";
          this.els.deleteConfirmBtn.classList.remove("opacity-60", "cursor-not-allowed");
        }
      }
    },

    escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    },
  };

  window.PrismaUI = PrismaUI;

  document.addEventListener("DOMContentLoaded", () => {
    PrismaUI.init();
  });
})();
