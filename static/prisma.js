(function () {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const htmlEscape = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const isExcelFile = (file) => /\.(xlsx|xls)$/i.test(String(file?.name || ""));

  const PrismaUI = {
    plans: [],
    selectedPlans: new Set(),
    status: null,
    pendingDeleteFiles: [],
    geminiEnabled: true,
    els: {},

    init() {
      this.cacheElements();
      this.initGeminiToggle();

      if (!this.els.planList) {
        console.warn("[PRISMA] Prisma tab elements not found.");
        return;
      }

      this.bindEvents();
      this.refreshStatus();
      this.refreshPlans();
    },

    cacheElements() {
      [
        "prismaPlanInput",
        "prismaDropZone",
        "prismaUploadBadge",
        "prismaUploadStatus",
        "prismaUploadStatusText",
        "prismaUploadStatusCount",
        "prismaUploadProgress",
        "buyingGuideInput",
        "buyingGuideUploadBtn",
        "buyingGuidePickBtn",
        "buyingGuideMeta",
        "buyingGuideSelectedWrap",
        "buyingGuideSelectedName",
        "prismaTemplateInput",
        "prismaTemplateUploadBtn",
        "prismaTemplatePickBtn",
        "prismaTemplateMeta",
        "prismaTemplateSelectedWrap",
        "prismaTemplateSelectedName",
        "prismaRefreshStatusBtn",
        "prismaReadyBadge",
        "buyingGuideStatus",
        "prismaTemplateStatus",
        "prismaClientsStatus",
        "prismaPlanList",
        "prismaEmptyPlans",
        "prismaSelectedCount",
        "prismaClientMode",
        "prismaUseGemini",
        "prismaSkipUnmatched",
        "prismaConvertSelectedBtn",
        "prismaBatchResultPanel",
        "prismaBatchSummary",
        "prismaBatchResultList",
        "prismaMatchTable",
        "prismaMatchTableBody",
        "prismaLog",
        "prismaClearLogBtn",
        "prismaToastContainer",
        "prismaDeleteModal",
        "prismaDeleteModalText",
        "prismaDeleteFileList",
        "prismaDeleteCancelBtn",
        "prismaDeleteConfirmBtn",
      ].forEach((id) => {
        const key = id
          .replace(/^prisma/, "")
          .replace(/^buyingGuide/, "guide")
          .replace(/^./, (char) => char.toLowerCase());

        this.els[key] = $(`#${id}`);
      });

      this.els.planInput = $("#prismaPlanInput");
      this.els.dropZone = $("#prismaDropZone");
      this.els.uploadBadge = $("#prismaUploadBadge");
      this.els.uploadStatus = $("#prismaUploadStatus");
      this.els.uploadStatusText = $("#prismaUploadStatusText");
      this.els.uploadStatusCount = $("#prismaUploadStatusCount");
      this.els.uploadProgress = $("#prismaUploadProgress");

      this.els.buyingGuideInput = $("#buyingGuideInput");
      this.els.buyingGuideUploadBtn = $("#buyingGuideUploadBtn");
      this.els.buyingGuidePickBtn = $("#buyingGuidePickBtn");
      this.els.buyingGuideMeta = $("#buyingGuideMeta");
      this.els.buyingGuideSelectedWrap = $("#buyingGuideSelectedWrap");
      this.els.buyingGuideSelectedName = $("#buyingGuideSelectedName");

      this.els.templateInput = $("#prismaTemplateInput");
      this.els.templateUploadBtn = $("#prismaTemplateUploadBtn");
      this.els.templatePickBtn = $("#prismaTemplatePickBtn");
      this.els.templateMeta = $("#prismaTemplateMeta");
      this.els.templateSelectedWrap = $("#prismaTemplateSelectedWrap");
      this.els.templateSelectedName = $("#prismaTemplateSelectedName");

      this.els.refreshStatusBtn = $("#prismaRefreshStatusBtn");
      this.els.readyBadge = $("#prismaReadyBadge");
      this.els.guideStatus = $("#buyingGuideStatus");
      this.els.templateStatus = $("#prismaTemplateStatus");
      this.els.clientsStatus = $("#prismaClientsStatus");

      this.els.planList = $("#prismaPlanList");
      this.els.emptyPlans = $("#prismaEmptyPlans");
      this.els.selectedCount = $("#prismaSelectedCount");

      this.els.clientMode = $("#prismaClientMode");
      this.els.useGemini = $("#prismaUseGemini");
      this.els.skipUnmatched = $("#prismaSkipUnmatched");
      this.els.convertSelectedBtn = $("#prismaConvertSelectedBtn");

      this.els.batchResultPanel = $("#prismaBatchResultPanel");
      this.els.batchSummary = $("#prismaBatchSummary");
      this.els.batchResultList = $("#prismaBatchResultList");

      this.els.matchTable = $("#prismaMatchTable");
      this.els.matchTableBody = $("#prismaMatchTableBody");

      this.els.logBox = $("#prismaLog");
      this.els.clearLogBtn = $("#prismaClearLogBtn");
      this.els.toastContainer = $("#prismaToastContainer");

      this.els.deleteModal = $("#prismaDeleteModal");
      this.els.deleteModalText = $("#prismaDeleteModalText");
      this.els.deleteFileList = $("#prismaDeleteFileList");
      this.els.deleteCancelBtn = $("#prismaDeleteCancelBtn");
      this.els.deleteConfirmBtn = $("#prismaDeleteConfirmBtn");

      this.els.geminiToggleBtn = $("#geminiToggleBtn");
      this.els.geminiToggleText = $("#geminiToggleText");
      this.els.geminiToggleDot = $("#geminiToggleDot");
    },

    bindEvents() {
      this.els.refreshStatusBtn?.addEventListener("click", () => this.refreshStatus());
      this.els.buyingGuideUploadBtn?.addEventListener("click", () => this.uploadReferenceFile("buyingGuide"));
      this.els.templateUploadBtn?.addEventListener("click", () => this.uploadReferenceFile("template"));
      this.els.convertSelectedBtn?.addEventListener("click", () => this.convertSelectedPlans());
      this.els.clearLogBtn?.addEventListener("click", () => this.clearLog());
      this.els.geminiToggleBtn?.addEventListener("click", () => this.toggleGemini());

      this.bindReferencePicker(this.els.buyingGuideInput, this.els.buyingGuideSelectedWrap, this.els.buyingGuideSelectedName, "Buying Guide");
      this.bindReferencePicker(this.els.templateInput, this.els.templateSelectedWrap, this.els.templateSelectedName, "Prisma Template");

      this.els.planInput?.addEventListener("change", () => {
        const files = [...(this.els.planInput.files || [])];
        if (files.length) this.uploadPlanFiles(files);
      });

      this.els.dropZone?.addEventListener("click", () => this.els.planInput?.click());

      ["dragover", "dragleave", "drop"].forEach((eventName) => {
        this.els.dropZone?.addEventListener(eventName, (event) => {
          event.preventDefault();
          this.setDropZoneActive(eventName === "dragover");

          if (eventName === "drop") {
            this.uploadPlanFiles([...(event.dataTransfer.files || [])]);
          }
        });
      });

      this.els.deleteCancelBtn?.addEventListener("click", () => this.closeDeleteModal());
      this.els.deleteConfirmBtn?.addEventListener("click", () => this.confirmDeletePlans());

      this.els.deleteModal?.addEventListener("click", (event) => {
        if (event.target === this.els.deleteModal) this.closeDeleteModal();
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") this.closeDeleteModal();
      });
    },

    initGeminiToggle() {
      const stored = localStorage.getItem("prismaGeminiEnabled");
      this.geminiEnabled = stored === null ? true : stored === "true";
      this.renderGeminiToggle();
    },

    toggleGemini() {
      this.geminiEnabled = !this.geminiEnabled;
      localStorage.setItem("prismaGeminiEnabled", String(this.geminiEnabled));
      this.renderGeminiToggle();

      const message = this.geminiEnabled
        ? "Gemini enabled for Prisma conversions."
        : "Gemini disabled for Prisma conversions.";

      this.toast(message, this.geminiEnabled ? "info" : "warn");
      this.log(message, this.geminiEnabled ? "info" : "warn");
    },

    renderGeminiToggle() {
      if (!this.els.geminiToggleBtn || !this.els.geminiToggleText || !this.els.geminiToggleDot) return;

      if (this.geminiEnabled) {
        this.els.geminiToggleText.textContent = "Gemini On";
        this.els.geminiToggleDot.className = "pulse-dot bg-violet-400";
        this.els.geminiToggleBtn.className =
          "flex items-center gap-1.5 text-xs font-semibold text-violet-300 bg-violet-500 bg-opacity-10 border border-violet-500 border-opacity-30 px-2.5 py-1 rounded-full hover:bg-opacity-20 transition";
      } else {
        this.els.geminiToggleText.textContent = "Gemini Off";
        this.els.geminiToggleDot.className = "pulse-dot bg-gray-500";
        this.els.geminiToggleBtn.className =
          "flex items-center gap-1.5 text-xs font-semibold text-gray-400 bg-gray-800 border border-gray-700 px-2.5 py-1 rounded-full hover:bg-gray-700 transition";
      }
    },

    bindReferencePicker(input, wrap, nameEl, label) {
      input?.addEventListener("change", () => {
        const file = input.files?.[0];
        if (!file) return;

        if (nameEl) nameEl.textContent = file.name;
        wrap?.classList.remove("hidden");
        this.toast(`Selected replacement ${label}: ${file.name}`, "info");
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
        const error = new Error(data.error || data.message || `Request failed: ${response.status}`);
        error.data = data;
        throw error;
      }

      return data;
    },

    log(message, type = "info") {
      const styles = {
        info: ["ℹ", "text-blue-300"],
        success: ["✓", "text-green-300"],
        warn: ["⚠", "text-yellow-300"],
        error: ["✕", "text-red-300"],
      };

      const [prefix, colorClass] = styles[type] || styles.info;

      if (!this.els.logBox) return;

      const div = document.createElement("div");
      div.className = `${colorClass} border-b border-gray-800 border-opacity-60 py-1`;
      div.textContent = `${prefix} ${message}`;

      this.els.logBox.appendChild(div);
      this.els.logBox.scrollTop = this.els.logBox.scrollHeight;
    },

    clearLog() {
      if (!this.els.logBox) return;

      this.els.logBox.innerHTML = "";
      this.toast("Prisma log cleared.", "info");
    },

    logBackendDiagnostics(filename, data = {}) {
      const diagnostics = data.diagnostics || {};
      const warnings = Array.isArray(data.warnings) ? data.warnings : [];
      const skippedRows = Array.isArray(diagnostics.skipped_buying_guide_rows) ? diagnostics.skipped_buying_guide_rows : [];
      const previewErrors = Array.isArray(diagnostics.preview_errors) ? diagnostics.preview_errors : [];

      const outputPath = data.output_path || diagnostics.final_output_path || "";
      const gapReportPath = diagnostics.buying_guide_gap_report_path || "";
      const client = diagnostics.client || "Unknown";

      const inputRows = diagnostics.raw_rows ?? "—";
      const consolidatedRows = diagnostics.consolidated_rows ?? "—";
      const exportedRows = diagnostics.enriched_rows ?? "—";

      const consolidatedGross = Number(diagnostics.consolidated_gross_total || 0);
      const exportedGross = Number(diagnostics.exported_gross_total || 0);
      const skippedGross = Number(diagnostics.skipped_buying_guide_gross_total || 0);

      this.log(
        `${filename}: Client ${client} · ${inputRows} input row(s) → ${consolidatedRows} consolidated → ${exportedRows} exported`,
        "info"
      );

      this.log(
        `${filename}: Gross ${this.formatMoney(consolidatedGross)} → exported ${this.formatMoney(exportedGross)} · skipped ${this.formatMoney(skippedGross)}`,
        skippedGross > 0 ? "warn" : "info"
      );

      if (outputPath) {
        this.log(`${filename}: Output ready: ${this.compactDisplayPath(outputPath)}`, "success");
      }

      if (gapReportPath) {
        this.log(`${filename}: Gap report ready: ${this.compactDisplayPath(gapReportPath)}`, "warn");
      }

      if (skippedRows.length || previewErrors.length) {
        const partners = this.uniquePartnersFromRows([...previewErrors, ...skippedRows]);

        if (partners.length) {
          this.log(
            `${filename}: Action needed — add/approve Buying Guide rows for: ${partners.join(", ")}`,
            "warn"
          );
        }
      }

      if (diagnostics.gemini_used === true) {
        const before = diagnostics.bad_partners_before_gemini;
        const after = diagnostics.bad_partners_after_gemini;

        if (before !== undefined && after !== undefined) {
          this.log(
            `${filename}: Gemini cleaned bad partners: ${before} → ${after}`,
            Number(after) > 0 ? "warn" : "success"
          );
        }
      }

      if (!warnings.length) {
        this.log(`${filename}: Completed successfully with no action needed.`, "success");
      } else if (!skippedRows.length && !previewErrors.length) {
        this.log(`${filename}: Completed with ${warnings.length} warning(s).`, "warn");
      }
    },

    toast(message, type = "info") {
      if (!this.els.toastContainer) return;

      const styles = {
        success: ["✅", "border-green-700", "bg-green-950", "text-green-200"],
        error: ["❌", "border-red-700", "bg-red-950", "text-red-200"],
        warn: ["⚠️", "border-yellow-700", "bg-yellow-950", "text-yellow-200"],
        info: ["ℹ️", "border-blue-700", "bg-blue-950", "text-blue-200"],
      };

      const [icon, border, bg, text] = styles[type] || styles.info;
      const toast = document.createElement("div");

      toast.className = `pointer-events-auto transform transition-all duration-300 translate-x-4 opacity-0 ${bg} ${border} ${text} border rounded-2xl shadow-2xl px-4 py-3`;
      toast.innerHTML = `
        <div class="flex items-start gap-3">
          <span class="text-lg">${icon}</span>
          <p class="text-sm font-semibold leading-5 flex-1">${htmlEscape(message)}</p>
          <button type="button" class="text-white text-opacity-50 hover:text-opacity-100 transition">×</button>
        </div>
      `;

      const close = () => {
        toast.classList.add("translate-x-4", "opacity-0");
        setTimeout(() => toast.remove(), 250);
      };

      toast.querySelector("button")?.addEventListener("click", close);
      this.els.toastContainer.appendChild(toast);

      requestAnimationFrame(() => toast.classList.remove("translate-x-4", "opacity-0"));
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
      ["border-violet-400", "bg-violet-500", "bg-opacity-10", "scale-[1.01]"].forEach((className) => {
        this.els.dropZone?.classList.toggle(className, active);
      });
    },

    setUploadState(isUploading, text = "", count = "", progress = 0) {
      this.els.uploadBadge?.classList.toggle("hidden", !isUploading);
      this.els.uploadStatus?.classList.toggle("hidden", !isUploading && progress === 0);

      if (this.els.uploadStatusText) this.els.uploadStatusText.textContent = text || "Preparing upload…";
      if (this.els.uploadStatusCount) this.els.uploadStatusCount.textContent = count || "—";
      if (this.els.uploadProgress) this.els.uploadProgress.style.width = `${progress}%`;
    },

    async uploadPlanFiles(files) {
      const validFiles = files.filter(isExcelFile);
      const invalidFiles = files.filter((file) => !isExcelFile(file));

      if (invalidFiles.length) {
        this.toast(`${invalidFiles.length} unsupported file(s) skipped. Only .xlsx/.xls accepted.`, "warn");
        this.log(`${invalidFiles.length} unsupported file(s) skipped.`, "warn");
      }

      if (!validFiles.length) {
        this.toast("No valid media plan files found.", "warn");
        return;
      }

      const formData = new FormData();
      validFiles.forEach((file) => formData.append("files", file));

      try {
        this.setUploadState(true, "Uploading media plan files…", `${validFiles.length} file(s)`, 35);
        this.log(`Uploading ${validFiles.length} media plan file(s)...`);

        const data = await this.api("/api/prisma/upload", {
          method: "POST",
          body: formData,
        });

        this.setUploadState(true, "Upload complete. Refreshing plan list…", `${data.count || validFiles.length} uploaded`, 80);
        this.toast(data.message || "Media plan upload complete.", "success");
        this.log(data.message || "Upload complete.", "success");

        if (this.els.planInput) this.els.planInput.value = "";

        await this.refreshPlans();

        (data.saved || []).forEach((filename) => this.selectedPlans.add(filename));
        this.renderPlans();
        this.updateSelectedCount();

        this.setUploadState(true, "Done.", `${data.count || validFiles.length} uploaded`, 100);
        setTimeout(() => this.setUploadState(false, "", "", 0), 900);
      } catch (err) {
        this.setUploadState(false, "", "", 0);
        this.toast(`Upload failed: ${err.message}`, "error");
        this.log(`Upload failed: ${err.message}`, "error");
      }
    },

    async uploadReferenceFile(type) {
      const config = {
        buyingGuide: {
          input: this.els.buyingGuideInput,
          wrap: this.els.buyingGuideSelectedWrap,
          nameEl: this.els.buyingGuideSelectedName,
          url: "/api/upload/buying-guide",
          label: "Buying Guide",
        },
        template: {
          input: this.els.templateInput,
          wrap: this.els.templateSelectedWrap,
          nameEl: this.els.templateSelectedName,
          url: "/api/upload/prisma-template",
          label: "Prisma template",
        },
      }[type];

      if (!config?.input?.files.length) {
        this.toast(`Please choose a ${config.label} file first.`, "warn");
        this.log(`Please choose a ${config.label} file first.`, "warn");
        return;
      }

      const formData = new FormData();
      formData.append("file", config.input.files[0]);

      try {
        this.log(`Uploading ${config.label}...`);

        const data = await this.api(config.url, {
          method: "POST",
          body: formData,
        });

        const toastType = data.valid === false ? "warn" : "success";

        this.toast(data.message || `${config.label} uploaded.`, toastType);
        this.log(data.message || `${config.label} uploaded.`, toastType);

        config.input.value = "";
        config.wrap?.classList.add("hidden");

        if (config.nameEl) config.nameEl.textContent = "—";

        await this.refreshStatus();
      } catch (err) {
        this.toast(`${config.label} upload failed: ${err.message}`, "error");
        this.log(`${config.label} upload failed: ${err.message}`, "error");
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
        data.guide_loaded ? `Loaded · ${data.guide_rows} rows` : data.guide_exists ? "Parse error" : "Missing"
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

      if (this.els.buyingGuidePickBtn) this.els.buyingGuidePickBtn.textContent = data.guide_exists ? "Replace" : "Choose File";
      if (this.els.templatePickBtn) this.els.templatePickBtn.textContent = data.template_exists ? "Replace" : "Choose File";

      const ready = data.guide_loaded && data.template_exists;

      if (this.els.readyBadge) {
        this.els.readyBadge.textContent = ready ? "Ready" : "Setup Required";
        this.els.readyBadge.className = ready
          ? "text-xs font-semibold bg-green-500 bg-opacity-20 text-green-400 px-3 py-1 rounded-full"
          : "text-xs font-semibold bg-yellow-500 bg-opacity-20 text-yellow-400 px-3 py-1 rounded-full";
      }

      if (this.els.clientsStatus) {
        this.els.clientsStatus.textContent = data.clients?.length ? data.clients.join(", ") : "None detected";
      }

      this.renderClientModeOptions(data.clients || []);

      if (data.error) {
        this.toast(`Status warning: ${data.error}`, "warn");
        this.log(`Status warning: ${data.error}`, "warn");
      }
    },

    renderClientModeOptions(clients) {
      if (!this.els.clientMode) return;

      const current = this.els.clientMode.value || "AUTO";
      const values = [...new Set([...(clients || []), "GU", "MI", "MCP"])];

      this.els.clientMode.innerHTML = `
        <option value="AUTO">Auto Detect</option>
        ${values.map((client) => `<option value="${htmlEscape(client)}">Force ${htmlEscape(client)}</option>`).join("")}
      `;

      this.els.clientMode.value = current === "AUTO" || values.includes(current) ? current : "AUTO";
    },

    async refreshPlans() {
      try {
        const data = await this.api("/api/prisma/plans");
        this.plans = data.plans || [];

        const existing = new Set(this.plans.map((plan) => plan.filename));
        this.selectedPlans = new Set([...this.selectedPlans].filter((filename) => existing.has(filename)));

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
        this.els.emptyPlans?.classList.remove("hidden");
        return;
      }

      this.els.emptyPlans?.classList.add("hidden");
      this.els.planList.appendChild(this.createPlansToolbar());
      this.plans.forEach((plan) => this.els.planList.appendChild(this.createPlanItem(plan)));
    },

    createPlansToolbar() {
      const toolbar = document.createElement("div");
      toolbar.className = "flex items-center justify-between gap-3 mb-3";
      toolbar.innerHTML = `
        <div class="text-xs text-gray-500">Tick plans to include in batch conversion.</div>
        <div class="flex items-center gap-2">
          <button type="button" data-action="select-all" class="text-xs font-semibold bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded-lg transition">Select All</button>
          <button type="button" data-action="clear" class="text-xs font-semibold bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded-lg transition">Clear</button>
        </div>
      `;

      toolbar.querySelector('[data-action="select-all"]').addEventListener("click", () => this.selectAllPlans());
      toolbar.querySelector('[data-action="clear"]').addEventListener("click", () => this.clearSelectedPlans());

      return toolbar;
    },

    createPlanItem(plan) {
      const checked = this.selectedPlans.has(plan.filename);
      const item = document.createElement("div");

      item.className = checked
        ? "flex items-center justify-between gap-3 bg-violet-900 bg-opacity-30 border border-violet-600 rounded-xl px-4 py-3"
        : "flex items-center justify-between gap-3 bg-gray-950 border border-gray-800 rounded-xl px-4 py-3 hover:border-violet-700 transition";

      item.innerHTML = `
        <label class="flex items-center gap-3 min-w-0 cursor-pointer flex-1">
          <input type="checkbox" class="prisma-plan-checkbox w-4 h-4 accent-violet-600 flex-shrink-0" ${checked ? "checked" : ""}>
          <div class="min-w-0">
            <p class="text-sm font-bold text-white truncate">${htmlEscape(plan.filename)}</p>
            <p class="text-xs text-gray-500">
              ${htmlEscape(plan.size_kb)} KB${plan.detected_client ? ` · detected: ${htmlEscape(plan.detected_client)}` : ""}
            </p>
          </div>
        </label>
        <button type="button" class="prisma-delete-plan text-xs font-semibold bg-red-500 bg-opacity-10 text-red-400 px-2 py-1 rounded-lg hover:bg-opacity-20 flex-shrink-0">Delete</button>
      `;

      item.querySelector(".prisma-plan-checkbox").addEventListener("change", (event) => {
        this.togglePlanSelection(plan.filename, event.target.checked);
      });

      item.querySelector(".prisma-delete-plan").addEventListener("click", (event) => {
        event.stopPropagation();
        this.openDeleteModal([plan.filename]);
      });

      return item;
    },

    togglePlanSelection(filename, checked) {
      checked ? this.selectedPlans.add(filename) : this.selectedPlans.delete(filename);
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

      if (this.els.selectedCount) this.els.selectedCount.textContent = `${count} selected`;

      if (this.els.convertSelectedBtn) {
        const disabled = count === 0;
        this.els.convertSelectedBtn.disabled = disabled;
        this.els.convertSelectedBtn.classList.toggle("opacity-60", disabled);
        this.els.convertSelectedBtn.classList.toggle("cursor-not-allowed", disabled);
      }
    },

    buildConvertPayload(filename) {
      const clientMode = this.els.clientMode?.value || "AUTO";

      return {
        filename,
        use_gemini: Boolean(this.geminiEnabled),
        skip_unmatched_buying_guide: this.els.skipUnmatched ? Boolean(this.els.skipUnmatched.checked) : true,
        ...(clientMode !== "AUTO" ? { client: clientMode } : {}),
      };
    },

    async convertSelectedPlans() {
      const filenames = [...this.selectedPlans];

      if (!filenames.length) {
        this.toast("Select at least one media plan to convert.", "warn");
        this.log("Select at least one media plan to convert.", "warn");
        return;
      }

      this.setBatchConverting(true, filenames.length);
      this.renderBatchStart(filenames);

      const results = [];

      for (let index = 0; index < filenames.length; index++) {
        const filename = filenames[index];

        try {
          this.updateBatchSummary(index, filenames.length, `Converting ${filename}`);
          this.log(`Converting ${filename} (${index + 1}/${filenames.length})...`);

          const data = await this.api("/api/prisma/convert", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(this.buildConvertPayload(filename)),
          });

          results.push({ filename, ok: true, data });
          this.logBackendDiagnostics(filename, data);

          const warningCount = Array.isArray(data.warnings) ? data.warnings.length : 0;
          this.log(
            warningCount > 0
              ? `Converted ${filename} with ${warningCount} warning(s)`
              : `Converted ${filename}`,
            warningCount > 0 ? "warn" : "success"
          );
        } catch (err) {
          results.push({ filename, ok: false, error: err.message, data: err.data || {} });
          this.log(`Failed to convert ${filename}: ${err.message}`, "error");
          this.logBackendDiagnostics(filename, err.data || {});
        }

        this.renderBatchResults(results, filenames.length);
      }

      this.finishBatch(results, filenames.length);
    },

    finishBatch(results, total) {
      const successCount = results.filter((item) => item.ok).length;
      const failCount = total - successCount;

      this.updateBatchSummary(total, total, `${successCount} converted, ${failCount} failed`);

      this.toast(
        successCount && !failCount
          ? `Converted ${successCount} media plan(s).`
          : successCount
            ? `Converted ${successCount}; ${failCount} failed.`
            : "No media plans converted successfully.",
        successCount && !failCount ? "success" : successCount ? "warn" : "error"
      );

      const lastSuccess = [...results].reverse().find((item) => item.ok);
      if (lastSuccess) this.renderMatchPreview(lastSuccess.data.preview || []);

      this.setBatchConverting(false, total);
    },

    setBatchConverting(isConverting, total = 0) {
      if (!this.els.convertSelectedBtn) return;

      const disabled = isConverting || this.selectedPlans.size === 0;

      this.els.convertSelectedBtn.disabled = disabled;
      this.els.convertSelectedBtn.textContent = isConverting ? `Converting ${total} plan(s)...` : "Convert Selected";
      this.els.convertSelectedBtn.classList.toggle("opacity-60", disabled);
      this.els.convertSelectedBtn.classList.toggle("cursor-not-allowed", disabled);
    },

    renderBatchStart(filenames) {
      this.els.batchResultPanel?.classList.remove("hidden");

      if (this.els.batchSummary) this.els.batchSummary.textContent = `0 / ${filenames.length}`;
      if (!this.els.batchResultList) return;

      this.els.batchResultList.innerHTML = filenames
        .map((filename) => this.batchRowHtml(filename, "Queued", "Waiting"))
        .join("");
    },

    updateBatchSummary(done, total, label) {
      if (this.els.batchSummary) this.els.batchSummary.textContent = `${done} / ${total} · ${label}`;
    },

    batchRowHtml(filename, subtitle, status, variant = "queued", data = {}) {
      const classes = {
        queued: "bg-gray-900 border-gray-800",
        failed: "bg-red-950 border-red-800",
        success: "bg-green-950 border-green-800",
      }[variant] || "bg-gray-900 border-gray-800";

      if (variant === "success") {
        const hasGapReport = Boolean(data.gapReportDownloadUrl);

        return `
          <div class="flex items-center justify-between gap-3 ${classes} border rounded-xl px-3 py-2">
            <div class="min-w-0">
              <p class="text-xs font-bold text-green-100 truncate">${htmlEscape(filename)}</p>
              <p class="text-xs text-green-300 truncate">${htmlEscape(data.outputFile || "Prisma import")}</p>
              ${
                data.gapReportFile
                  ? `<p class="text-xs text-yellow-300 truncate">Gap report: ${htmlEscape(data.gapReportFile)}</p>`
                  : ""
              }
            </div>

            <div class="flex items-center gap-2 flex-shrink-0">
              ${
                hasGapReport
                  ? `<a href="${htmlEscape(data.gapReportDownloadUrl)}" class="text-xs font-bold bg-yellow-600 hover:bg-yellow-500 text-white px-3 py-2 rounded-lg transition">Gap Report</a>`
                  : ""
              }

              <a href="${htmlEscape(data.downloadUrl || "#")}" class="text-xs font-bold bg-green-600 hover:bg-green-500 text-white px-3 py-2 rounded-lg transition">
                Prisma
              </a>
            </div>
          </div>
        `;
      }

      const titleClass = variant === "failed" ? "text-red-100" : "text-white";
      const subtitleClass = variant === "failed" ? "text-red-300" : "text-gray-500";
      const statusClass = variant === "failed" ? "text-red-300 font-bold" : "text-gray-500";

      return `
        <div class="flex items-center justify-between gap-3 ${classes} border rounded-xl px-3 py-2">
          <div class="min-w-0">
            <p class="text-xs font-bold ${titleClass} truncate">${htmlEscape(filename)}</p>
            <p class="text-xs ${subtitleClass} truncate">${htmlEscape(subtitle)}</p>
          </div>
          <span class="text-xs ${statusClass} flex-shrink-0">${htmlEscape(status)}</span>
        </div>
      `;
    },

    renderBatchResults(results, total) {
      if (!this.els.batchResultPanel || !this.els.batchResultList) return;

      this.els.batchResultPanel.classList.remove("hidden");

      const resultMap = new Map(results.map((item) => [item.filename, item]));

      this.els.batchResultList.innerHTML = [...this.selectedPlans]
        .map((filename) => {
          const result = resultMap.get(filename);

          if (!result) return this.batchRowHtml(filename, "Queued", "Waiting");
          if (!result.ok) return this.batchRowHtml(filename, result.error, "Failed", "failed");

          return this.batchRowHtml(filename, "", "", "success", {
            outputFile: result.data.output_file || "Prisma import",
            downloadUrl: result.data.download_url || "#",
            gapReportFile: result.data.gap_report_file || "",
            gapReportDownloadUrl: result.data.gap_report_download_url || "",
          });
        })
        .join("");

      if (this.els.batchSummary) this.els.batchSummary.textContent = `${results.length} / ${total}`;
    },

    renderMatchPreview(records) {
      if (!this.els.matchTable || !this.els.matchTableBody) return;

      this.els.matchTableBody.innerHTML = "";

      if (!records.length) {
        this.els.matchTable.classList.add("hidden");
        return;
      }

      this.els.matchTableBody.innerHTML = records
        .map(
          (record) => `
            <tr class="border-b border-gray-800">
              <td class="py-3 pr-4">${htmlEscape(record.partner)}</td>
              <td class="py-3 pr-4">${htmlEscape(record.placement_name)}</td>
              <td class="py-3 pr-4">${htmlEscape(record.status)}</td>
              <td class="py-3 pr-4">${htmlEscape(record.supplier_name)}</td>
              <td class="py-3 pr-4">${htmlEscape(record.supplier_code)}</td>
              <td class="py-3 pr-4">${htmlEscape(record.placement_booking_type)}</td>
            </tr>
          `
        )
        .join("");

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
          .map((name) => `<div class="truncate">• ${htmlEscape(name)}</div>`)
          .join("");
      }

      this.els.deleteModal.classList.remove("hidden");
      this.els.deleteModal.classList.add("flex");
    },

    closeDeleteModal() {
      this.els.deleteModal?.classList.add("hidden");
      this.els.deleteModal?.classList.remove("flex");
      this.pendingDeleteFiles = [];
    },

    async confirmDeletePlans() {
      const filenames = this.pendingDeleteFiles;

      if (!filenames.length) {
        this.closeDeleteModal();
        return;
      }

      try {
        this.setDeleteButtonState(true);

        const data = await this.api("/api/prisma/plans/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
        this.setDeleteButtonState(false);
      }
    },

    setDeleteButtonState(isDeleting) {
      if (!this.els.deleteConfirmBtn) return;

      this.els.deleteConfirmBtn.disabled = isDeleting;
      this.els.deleteConfirmBtn.textContent = isDeleting ? "Deleting..." : "Delete";
      this.els.deleteConfirmBtn.classList.toggle("opacity-60", isDeleting);
      this.els.deleteConfirmBtn.classList.toggle("cursor-not-allowed", isDeleting);
    },

    compactDisplayPath(path) {
      const parts = String(path || "").replaceAll("\\", "/").split("/").filter(Boolean);
      return parts.length >= 2 ? `${parts.at(-2)}/${parts.at(-1)}` : String(path || "");
    },

    uniquePartnersFromRows(rows = []) {
      return [
        ...new Set(
          rows
            .map((row) => String(row?.partner || row?.missing_partner || "").trim())
            .filter(Boolean)
        ),
      ].sort();
    },

    formatMoney(value) {
      const number = Number(value || 0);

      return Number.isNaN(number)
        ? "0.00"
        : number.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          });
    },

    escapeHtml(value) {
      return htmlEscape(value);
    },
  };

  window.PrismaUI = PrismaUI;

  document.addEventListener("DOMContentLoaded", () => {
    PrismaUI.init();
  });
})();
