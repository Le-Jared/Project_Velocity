import json
import io
import os
import sys
import queue
import zipfile
import subprocess
import threading
from flask import Flask, render_template, jsonify, request, Response, stream_with_context, send_file
from werkzeug.utils import secure_filename

from run_workflow import BASE_DIR

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# ── PATH CONSTANTS ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

INVOICE_FOLDER = "./invoices"
INPUT_FOLDER   = "./Input"
OUTPUT_FOLDER  = "./Output"
CLIENTS_FOLDER = "./Clients"

TRACKER_INPUT  = os.path.join(INPUT_FOLDER,  "ACCT-108 Master Invoice Tracker 2026.xlsx")
TRACKER_OUTPUT = os.path.join(OUTPUT_FOLDER, "ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx")
REPORT_PATH    = os.path.join(OUTPUT_FOLDER, "invoice_sort_report.csv")
CREDENTIALS    = "credentials.json"
DRIVE_CONFIG   = "drive_config.json"

ALLOWED_EXTENSIONS = {"pdf"}

# Prisma paths
MEDIA_PLANS_FOLDER = "./media_plans"
PRISMA_OUTPUT_DIR  = os.path.join(OUTPUT_FOLDER, "prisma")
BUYING_GUIDE_PATH  = os.path.join(INPUT_FOLDER,  "ACCT 108 BuyingGuide.xlsx")
PRISMA_TEMPLATE    = os.path.join(
    INPUT_FOLDER,
    "ACCT-108 DIGITAL TEMPLATE MEDIA PLAN IMPORT placements.xlsx",
)

os.makedirs(MEDIA_PLANS_FOLDER, exist_ok=True)
os.makedirs(PRISMA_OUTPUT_DIR,  exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# ── HELPERS ────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_plan_file(filename: str) -> bool:
    return filename.lower().endswith((".xlsx", ".xls"))


def pathlib_path(p: str):
    """Convert string path to Path without polluting global namespace."""
    from pathlib import Path
    return Path(p)


def gemini_available():
    """Returns True if a Gemini API key is configured and usable."""
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return True
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return True
        except Exception:
            pass
    return False


def stream_script(script_name, q):
    try:
        proc = subprocess.Popen(
            [sys.executable, script_name],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        for line in proc.stdout:
            q.put(line.rstrip())
        proc.wait()
        q.put(f"__EXIT__{proc.returncode}")
    except Exception as e:
        q.put(f"[ERR] Failed to start {script_name}: {e}")
        q.put("__EXIT__1")


def run_and_stream(script_name):
    q = queue.Queue()
    t = threading.Thread(target=stream_script, args=(script_name, q), daemon=True)
    t.start()

    def generate():
        while True:
            try:
                line = q.get(timeout=120)
                if line.startswith("__EXIT__"):
                    code = line.replace("__EXIT__", "")
                    msg = "[DONE] Script finished (exit 0)." if code == "0" else f"[ERR] Script exited with code {code}."
                    yield msg + "\n"
                    break
                yield line + "\n"
            except queue.Empty:
                yield "[WARN] Timeout - no output for 120s\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# ── INDEX ──────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════════════════════════════════
# ── STATUS & SUMMARY ───────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/status")
def status():
    pdf_count = 0
    if os.path.exists(INVOICE_FOLDER):
        for root, _, files in os.walk(INVOICE_FOLDER):
            pdf_count += sum(1 for f in files if f.lower().endswith(".pdf"))

    client_folders = 0
    client_list    = []
    if os.path.exists(CLIENTS_FOLDER):
        client_list    = [d for d in os.listdir(CLIENTS_FOLDER) if os.path.isdir(os.path.join(CLIENTS_FOLDER, d))]
        client_folders = len(client_list)

    supplier_counts = {"Meta": 0, "Google": 0, "Apple": 0, "AdsJoy": 0}
    if os.path.exists(CLIENTS_FOLDER):
        for root, _, files in os.walk(CLIENTS_FOLDER):
            for f in files:
                if not f.lower().endswith(".pdf"):
                    continue
                fl = f.lower()
                if "_meta_"     in fl: supplier_counts["Meta"]   += 1
                elif "_google_" in fl: supplier_counts["Google"] += 1
                elif "_apple_"  in fl: supplier_counts["Apple"]  += 1
                elif "_adsjoy_" in fl: supplier_counts["AdsJoy"] += 1

    tracker_exists = os.path.exists(TRACKER_INPUT) or os.path.exists(TRACKER_OUTPUT)
    report_exists  = os.path.exists(REPORT_PATH)
    creds_exists   = os.path.exists(CREDENTIALS)

    folder_id_set = False
    if os.path.exists(DRIVE_CONFIG):
        try:
            with open(DRIVE_CONFIG) as f:
                cfg = json.load(f)
            folder_id_set = bool(cfg.get("root_folder_id", "").strip())
        except Exception:
            folder_id_set = False

    return jsonify({
        "pdf_count":       pdf_count,
        "client_folders":  client_folders,
        "client_list":     client_list,
        "supplier_counts": supplier_counts,
        "tracker_exists":  tracker_exists,
        "report_exists":   report_exists,
        "creds_exists":    creds_exists,
        "folder_id_set":   folder_id_set,
        "gemini":          gemini_available(),
    })


@app.route("/api/summary")
def summary():
    tracker_path = (
        TRACKER_OUTPUT if os.path.exists(TRACKER_OUTPUT) else
        TRACKER_INPUT  if os.path.exists(TRACKER_INPUT)  else None
    )
    if not tracker_path:
        return jsonify({"currency_totals": {}, "supplier_totals": {}, "has_data": False})

    try:
        import openpyxl
        wb = openpyxl.load_workbook(tracker_path, read_only=True, data_only=True)

        currency_totals = {}
        supplier_totals = {}

        sheet_map = {
            "Adsjoy":          "AdsJoy",
            "Apple (ASA)":     "Apple",
            "Google":          "Google",
            "Meta (facebook)": "Meta",
        }

        for sheet_name, supplier_label in sheet_map.items():
            if sheet_name not in wb.sheetnames:
                continue

            ws      = wb[sheet_name]
            headers = [
                str(c.value).strip() if c.value else ""
                for c in next(ws.iter_rows(min_row=1, max_row=1))
            ]

            cur_idx = next(
                (i for i, h in enumerate(headers) if h.strip() in ("Currency", "Currency ")),
                None
            )
            amt_idx = next(
                (i for i, h in enumerate(headers) if h.strip() == "Amount"),
                None
            )

            if cur_idx is None or amt_idx is None:
                continue

            for row in ws.iter_rows(min_row=2, values_only=True):
                cur = str(row[cur_idx]).strip() if row[cur_idx] else ""
                amt = row[amt_idx]
                if not cur or cur == "None" or amt is None:
                    continue
                try:
                    amt = float(amt)
                except (ValueError, TypeError):
                    continue
                currency_totals[cur]            = currency_totals.get(cur, 0.0) + amt
                supplier_totals[supplier_label] = supplier_totals.get(supplier_label, 0.0) + amt

        wb.close()

        return jsonify({
            "currency_totals": currency_totals,
            "supplier_totals": supplier_totals,
            "has_data":        bool(currency_totals),
        })

    except Exception as e:
        return jsonify({
            "currency_totals": {},
            "supplier_totals": {},
            "has_data":        False,
            "error":           str(e),
        })


# ═══════════════════════════════════════════════════════════════════════════
# ── INVOICE UPLOAD ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/upload", methods=["POST"])
def upload():
    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400
    os.makedirs(INVOICE_FOLDER, exist_ok=True)
    saved, errors = [], []
    for f in request.files.getlist("files"):
        if f and allowed_file(f.filename):
            filename = secure_filename(f.filename)
            f.save(os.path.join(INVOICE_FOLDER, filename))
            saved.append(filename)
        else:
            errors.append(f.filename)
    return jsonify({
        "message": f"Uploaded {len(saved)} file(s)" + (f", {len(errors)} skipped" if errors else ""),
        "saved": saved, "errors": errors,
    })


@app.route("/api/upload/tracker", methods=["POST"])
def upload_tracker():
    import shutil
    from datetime import datetime
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".xlsx"):
        return jsonify({"error": "Only .xlsx files accepted"}), 400
    os.makedirs(INPUT_FOLDER, exist_ok=True)
    if os.path.exists(TRACKER_INPUT):
        backup_name = os.path.join(
            INPUT_FOLDER,
            f"ACCT-108 Master Invoice Tracker 2026_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        shutil.copy2(TRACKER_INPUT, backup_name)
    f.save(TRACKER_INPUT)
    return jsonify({"message": "[OK] Tracker uploaded to Input/ folder (previous version backed up)"})


# ═══════════════════════════════════════════════════════════════════════════
# ── PRISMA REFERENCE FILE UPLOAD ───────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/upload/buying-guide", methods=["POST"])
def upload_buying_guide():
    """Upload ACCT 108 BuyingGuide.xlsx → Input/ (with backup + validation)."""
    import shutil
    from datetime import datetime

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".xlsx"):
        return jsonify({"error": "Only .xlsx files accepted"}), 400

    os.makedirs(INPUT_FOLDER, exist_ok=True)

    if os.path.exists(BUYING_GUIDE_PATH):
        backup = os.path.join(
            INPUT_FOLDER,
            f"ACCT 108 BuyingGuide_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        shutil.copy2(BUYING_GUIDE_PATH, backup)

    f.save(BUYING_GUIDE_PATH)

    try:
        from buying_guide import BuyingGuide
        bg = BuyingGuide(BUYING_GUIDE_PATH)
        return jsonify({
            "message": f"[OK] Buying Guide uploaded · {len(bg)} rows · clients: {', '.join(bg.clients())}",
            "rows":    len(bg),
            "clients": bg.clients(),
            "valid":   True,
        })
    except Exception as e:
        return jsonify({
            "message": f"[WARN] Saved but failed to parse: {e}",
            "error":   str(e),
            "valid":   False,
        }), 200


@app.route("/api/upload/prisma-template", methods=["POST"])
def upload_prisma_template():
    """Upload ACCT-108 DIGITAL TEMPLATE...xlsx → Input/ (with backup + validation)."""
    import shutil
    from datetime import datetime

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".xlsx"):
        return jsonify({"error": "Only .xlsx files accepted"}), 400

    os.makedirs(INPUT_FOLDER, exist_ok=True)

    if os.path.exists(PRISMA_TEMPLATE):
        backup = os.path.join(
            INPUT_FOLDER,
            f"PRISMA_TEMPLATE_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        shutil.copy2(PRISMA_TEMPLATE, backup)

    f.save(PRISMA_TEMPLATE)

    try:
        import openpyxl
        wb = openpyxl.load_workbook(PRISMA_TEMPLATE, read_only=True)
        has_sheet = "Digital import sheet ALL TYPES" in wb.sheetnames
        sheets    = list(wb.sheetnames)
        wb.close()
        if not has_sheet:
            return jsonify({
                "message": f"[WARN] Saved but missing required sheet 'Digital import sheet ALL TYPES'. Found: {sheets}",
                "valid":   False,
                "sheets":  sheets,
            }), 200
        return jsonify({
            "message": "[OK] Prisma template uploaded and validated",
            "sheets":  sheets,
            "valid":   True,
        })
    except Exception as e:
        return jsonify({
            "message": f"[WARN] Saved but failed to validate: {e}",
            "error":   str(e),
            "valid":   False,
        }), 200


# ═══════════════════════════════════════════════════════════════════════════
# ── CREDENTIALS & DRIVE CONFIG ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/upload/credentials", methods=["POST"])
def upload_credentials():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".json"):
        return jsonify({"error": "Only .json files accepted"}), 400
    f.save(CREDENTIALS)
    return jsonify({"message": "[OK] credentials.json saved to project root"})


@app.route("/api/credentials/delete", methods=["POST"])
def delete_credentials():
    if os.path.exists(CREDENTIALS):
        os.remove(CREDENTIALS)
        return jsonify({"message": "[OK] credentials.json removed"})
    return jsonify({"message": "[WARN] No credentials file found"}), 404


@app.route("/api/drive/config", methods=["GET"])
def get_drive_config():
    if not os.path.exists(DRIVE_CONFIG):
        return jsonify({"root_folder_id": ""})
    with open(DRIVE_CONFIG) as f:
        return jsonify(json.load(f))


@app.route("/api/drive/config", methods=["POST"])
def save_drive_config():
    data      = request.get_json()
    folder_id = (data or {}).get("root_folder_id", "").strip()
    if not folder_id:
        return jsonify({"error": "Folder ID cannot be empty"}), 400
    with open(DRIVE_CONFIG, "w") as f:
        json.dump({"root_folder_id": folder_id}, f)
    return jsonify({"message": f"[OK] Drive folder ID saved: {folder_id}"})


@app.route("/api/drive/config/delete", methods=["POST"])
def delete_drive_config():
    if os.path.exists(DRIVE_CONFIG):
        os.remove(DRIVE_CONFIG)
    return jsonify({"message": "[OK] Drive folder ID cleared"})


# ═══════════════════════════════════════════════════════════════════════════
# ── DOWNLOADS ──────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/download/report")
def download_report():
    if not os.path.exists(REPORT_PATH):
        return jsonify({"error": "Report not found"}), 404
    return send_file(REPORT_PATH, as_attachment=True, download_name="invoice_sort_report.csv")


@app.route("/api/download/clients-zip")
def download_clients_zip():
    if not os.path.exists(CLIENTS_FOLDER):
        return jsonify({"error": "Clients/ folder not found. Run the workflow first."}), 404
    has_files = any(files for _, _, files in os.walk(CLIENTS_FOLDER))
    if not has_files:
        return jsonify({"error": "Clients/ folder is empty. Run the workflow first."}), 404
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(CLIENTS_FOLDER):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                arcname   = os.path.relpath(file_path, os.path.dirname(CLIENTS_FOLDER))
                zf.write(file_path, arcname)
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype="application/zip", as_attachment=True, download_name="Clients.zip")


@app.route("/api/download/tracker")
def download_tracker():
    if os.path.exists(TRACKER_OUTPUT):
        return send_file(TRACKER_OUTPUT, as_attachment=True, download_name="ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx")
    elif os.path.exists(TRACKER_INPUT):
        return send_file(TRACKER_INPUT, as_attachment=True, download_name="ACCT-108 Master Invoice Tracker 2026.xlsx")
    return jsonify({"error": "No tracker file found. Upload or run the workflow first."}), 404


# ═══════════════════════════════════════════════════════════════════════════
# ── CLEAR WORKSPACE ────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/clear/workspace", methods=["POST"])
def clear_workspace():
    import shutil
    deleted = {
        "invoices":     0,
        "client_files": 0,
        "output_files": 0,
        "input_files":  0,
        "media_plans":  0,
    }
    errors = []

    invoices_dir = os.path.join(BASE_DIR, "invoices")
    if os.path.exists(invoices_dir):
        for f in os.listdir(invoices_dir):
            if f.lower().endswith(".pdf"):
                try:
                    os.remove(os.path.join(invoices_dir, f))
                    deleted["invoices"] += 1
                except Exception as e:
                    errors.append(str(e))

    clients_dir = os.path.join(BASE_DIR, "Clients")
    if os.path.exists(clients_dir):
        for item in os.listdir(clients_dir):
            if item == ".gitkeep": continue
            item_path = os.path.join(clients_dir, item)
            try:
                shutil.rmtree(item_path) if os.path.isdir(item_path) else os.remove(item_path)
                deleted["client_files"] += 1
            except Exception as e:
                errors.append(str(e))

    output_dir = os.path.join(BASE_DIR, "Output")
    if os.path.exists(output_dir):
        for item in os.listdir(output_dir):
            if item == ".gitkeep": continue
            item_path = os.path.join(output_dir, item)
            try:
                shutil.rmtree(item_path) if os.path.isdir(item_path) else os.remove(item_path)
                deleted["output_files"] += 1
            except Exception as e:
                errors.append(str(e))

    input_dir = os.path.join(BASE_DIR, "Input")
    if os.path.exists(input_dir):
        for item in os.listdir(input_dir):
            if item == ".gitkeep": continue
            item_path = os.path.join(input_dir, item)
            try:
                shutil.rmtree(item_path) if os.path.isdir(item_path) else os.remove(item_path)
                deleted["input_files"] += 1
            except Exception as e:
                errors.append(str(e))

    media_dir = os.path.join(BASE_DIR, "media_plans")
    if os.path.exists(media_dir):
        for item in os.listdir(media_dir):
            if item == ".gitkeep": continue
            item_path = os.path.join(media_dir, item)
            try:
                shutil.rmtree(item_path) if os.path.isdir(item_path) else os.remove(item_path)
                deleted["media_plans"] += 1
            except Exception as e:
                errors.append(str(e))

    return jsonify({
        "message": (
            f"✓ Cleared {deleted['invoices']} invoice(s), "
            f"{deleted['client_files']} client folder(s), "
            f"{deleted['output_files']} output file(s), "
            f"{deleted['input_files']} input file(s), "
            f"{deleted['media_plans']} media plan(s)."
        ),
        "deleted": deleted,
        "errors":  errors,
    }), 200


# ═══════════════════════════════════════════════════════════════════════════
# ── INVOICE LIST & DELETE ──────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/invoices", methods=["GET"])
def list_invoices():
    """Return a sorted list of all PDF filenames in the invoices/ folder."""
    if not os.path.exists(INVOICE_FOLDER):
        return jsonify({"files": []})
    files = sorted([
        f for f in os.listdir(INVOICE_FOLDER)
        if f.lower().endswith(".pdf")
    ])
    return jsonify({"files": files})


@app.route("/api/invoices/delete", methods=["POST"])
def delete_invoice():
    """Delete one or more invoices by filename from the invoices/ folder."""
    data      = request.get_json() or {}
    filenames = data.get("filenames", [])

    if isinstance(filenames, str):
        filenames = [filenames]

    if not filenames:
        return jsonify({"error": "No filenames provided"}), 400

    deleted, errors = [], []
    for filename in filenames:
        safe_name = os.path.basename(secure_filename(filename))
        path      = os.path.join(INVOICE_FOLDER, safe_name)
        if not os.path.exists(path):
            errors.append(f"{filename} not found")
            continue
        try:
            os.remove(path)
            deleted.append(safe_name)
        except Exception as e:
            errors.append(f"{filename}: {str(e)}")

    return jsonify({
        "message": f"Deleted {len(deleted)} file(s)" + (f", {len(errors)} error(s)" if errors else ""),
        "deleted": deleted,
        "errors":  errors,
    }), 200 if deleted else 400


# ═══════════════════════════════════════════════════════════════════════════
# ── PRISMA: STATUS · UPLOAD · LIST · CONVERT · DOWNLOAD · DELETE ───────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/prisma/status", methods=["GET"])
def prisma_status():
    """Return Buying Guide + template status for the Prisma tab."""
    guide_loaded    = False
    guide_rows      = 0
    clients         = []
    guide_exists    = os.path.exists(BUYING_GUIDE_PATH)
    template_exists = os.path.exists(PRISMA_TEMPLATE)
    error           = None

    if guide_exists:
        try:
            from buying_guide import BuyingGuide
            bg            = BuyingGuide(BUYING_GUIDE_PATH)
            guide_loaded  = True
            guide_rows    = len(bg)
            clients       = bg.clients()
        except Exception as e:
            error = str(e)

    return jsonify({
        "guide_loaded":    guide_loaded,
        "guide_exists":    guide_exists,
        "guide_rows":      guide_rows,
        "clients":         clients,
        "template_exists": template_exists,
        "ready":           guide_loaded and template_exists,
        "gemini":          gemini_available(),
        "error":           error,
    })


@app.route("/api/prisma/upload", methods=["POST"])
def prisma_upload():
    """Upload one or more media plan xlsx files."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400

    os.makedirs(MEDIA_PLANS_FOLDER, exist_ok=True)
    saved, errors = [], []
    for f in files:
        if not f or not allowed_plan_file(f.filename or ""):
            errors.append(f.filename)
            continue
        filename = secure_filename(f.filename)
        f.save(os.path.join(MEDIA_PLANS_FOLDER, filename))
        saved.append(filename)

    return jsonify({
        "message": f"✓ Uploaded {len(saved)} file(s)" + (f", {len(errors)} skipped" if errors else ""),
        "count":   len(saved),
        "saved":   saved,
        "errors":  errors,
    })


@app.route("/api/prisma/plans", methods=["GET"])
def prisma_plans():
    """List uploaded media plans with light client detection."""
    if not os.path.exists(MEDIA_PLANS_FOLDER):
        return jsonify({"plans": []})

    try:
        from plan_parser import detect_client
    except Exception:
        detect_client = lambda _p: None  # noqa: E731

    plans = []
    for name in sorted(os.listdir(MEDIA_PLANS_FOLDER)):
        full = os.path.join(MEDIA_PLANS_FOLDER, name)
        if not os.path.isfile(full) or not allowed_plan_file(name):
            continue
        try:
            detected = detect_client(full)
        except Exception:
            detected = None
        plans.append({
            "filename":        name,
            "size_kb":         round(os.path.getsize(full) / 1024, 1),
            "detected_client": detected,
        })
    return jsonify({"plans": plans})


@app.route("/api/prisma/convert", methods=["POST"])
def prisma_convert():
    """Convert an uploaded plan into a Prisma-import xlsx."""
    data            = request.get_json() or {}
    filename        = data.get("filename")
    client_override = (data.get("client") or "").strip().upper() or None
    use_gemini      = bool(data.get("use_gemini", True))

    if not filename:
        return jsonify({"error": "filename required"}), 400

    path = os.path.join(MEDIA_PLANS_FOLDER, secure_filename(filename))
    if not os.path.exists(path):
        return jsonify({"error": "file not found"}), 404
    if not os.path.exists(BUYING_GUIDE_PATH):
        return jsonify({"error": "Buying Guide missing — upload it via the Reference Files card"}), 400
    if not os.path.exists(PRISMA_TEMPLATE):
        return jsonify({"error": "Prisma template missing — upload it via the Reference Files card"}), 400

    try:
        from plan_parser    import parse_plan
        from prisma_builder import build_prisma_import
    except Exception as e:
        return jsonify({"error": f"Module import failed: {e}"}), 500

    try:
        adapter, placements = parse_plan(path)
        client_code = client_override or adapter.client_code

        # Gemini fallback — fill missing fields when configured
        if use_gemini and gemini_available():
            try:
                from gemini_fallback_prisma import enrich_placements
                placements = enrich_placements(placements, plan_label=adapter.label)
            except Exception as e:
                print(f"[GEMINI] Prisma enrichment skipped: {e}")

        result = build_prisma_import(
            placements        = placements,
            client_code       = client_code,
            template_path     = pathlib_path(PRISMA_TEMPLATE),
            buying_guide_path = pathlib_path(BUYING_GUIDE_PATH),
            output_dir        = pathlib_path(PRISMA_OUTPUT_DIR),
        )

        return jsonify({
            "ok":                 True,
            "client":             client_code,
            "adapter":            adapter.label,
            "placement_count":    len(placements),
            "matched_count":      result["matched"],
            "unmatched_channels": result["unmatched"],
            "output_file":        result["output_path"].name,
            "download_url":       f"/api/prisma/download/{result['output_path'].name}",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/prisma/download/<path:name>", methods=["GET"])
def prisma_download(name):
    safe_name = secure_filename(name)
    full      = os.path.join(PRISMA_OUTPUT_DIR, safe_name)
    if not os.path.exists(full):
        return jsonify({"error": "File not found"}), 404
    return send_file(full, as_attachment=True, download_name=safe_name)


@app.route("/api/prisma/plans/delete", methods=["POST"])
def prisma_delete_plans():
    data      = request.get_json() or {}
    filenames = data.get("filenames", [])
    if isinstance(filenames, str):
        filenames = [filenames]
    if not filenames:
        return jsonify({"error": "No filenames provided"}), 400

    deleted, errors = [], []
    for filename in filenames:
        safe = os.path.basename(secure_filename(filename))
        path = os.path.join(MEDIA_PLANS_FOLDER, safe)
        if not os.path.exists(path):
            errors.append(f"{filename} not found")
            continue
        try:
            os.remove(path)
            deleted.append(safe)
        except Exception as e:
            errors.append(f"{filename}: {str(e)}")

    return jsonify({
        "message": f"Deleted {len(deleted)} file(s)" + (f", {len(errors)} error(s)" if errors else ""),
        "deleted": deleted,
        "errors":  errors,
    }), (200 if deleted else 400)


@app.route("/api/prisma/files/delete", methods=["POST"])
def delete_prisma_reference_files():
    """Delete the buying guide and/or template from Input/."""
    data    = request.get_json() or {}
    targets = data.get("targets", [])
    if isinstance(targets, str):
        targets = [targets]

    deleted, errors = [], []

    if "buying_guide" in targets:
        if os.path.exists(BUYING_GUIDE_PATH):
            try:
                os.remove(BUYING_GUIDE_PATH)
                deleted.append("buying_guide")
            except Exception as e:
                errors.append(f"buying_guide: {e}")
        else:
            errors.append("buying_guide not found")

    if "template" in targets:
        if os.path.exists(PRISMA_TEMPLATE):
            try:
                os.remove(PRISMA_TEMPLATE)
                deleted.append("template")
            except Exception as e:
                errors.append(f"template: {e}")
        else:
            errors.append("template not found")

    return jsonify({
        "message": f"Deleted: {', '.join(deleted) or 'nothing'}",
        "deleted": deleted,
        "errors":  errors,
    }), (200 if deleted else 400)


# ═══════════════════════════════════════════════════════════════════════════
# ── RUN ROUTES ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/run/sort")
def run_sort():     return run_and_stream("invoice_sorter.py")

@app.route("/api/run/extract")
def run_extract():  return run_and_stream("invoice_extractor.py")

@app.route("/api/run/workflow")
def run_workflow(): return run_and_stream("run_workflow.py")


@app.route("/api/drive/sync", methods=["POST"])
def drive_sync():
    if not os.path.exists(CREDENTIALS):
        return jsonify({"status": "not_configured", "message": "[WARN] credentials.json not found. Upload it via the dashboard first."}), 501
    if not os.path.exists(DRIVE_CONFIG):
        return jsonify({"status": "not_configured", "message": "[WARN] Drive folder ID not set. Add it in the Google Drive Sync card."}), 501
    return run_and_stream("drive_sync.py")


# ═══════════════════════════════════════════════════════════════════════════
# ── MAIN ───────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
