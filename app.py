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


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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


@app.route("/")
def index():
    return render_template("index.html")


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
    # Backup existing tracker before overwriting
    if os.path.exists(TRACKER_INPUT):
        backup_name = os.path.join(
            INPUT_FOLDER,
            f"ACCT-108 Master Invoice Tracker 2026_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        shutil.copy2(TRACKER_INPUT, backup_name)
    f.save(TRACKER_INPUT)
    return jsonify({"message": "[OK] Tracker uploaded to Input/ folder (previous version backed up)"})


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


@app.route("/api/clear/workspace", methods=["POST"])
def clear_workspace():
    import shutil
    deleted = {"invoices": 0, "client_files": 0, "output_files": 0, "input_files": 0}
    errors  = []

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
            if item == ".gitkeep":
                continue
            item_path = os.path.join(clients_dir, item)
            try:
                shutil.rmtree(item_path) if os.path.isdir(item_path) else os.remove(item_path)
                deleted["client_files"] += 1
            except Exception as e:
                errors.append(str(e))

    output_dir = os.path.join(BASE_DIR, "Output")
    if os.path.exists(output_dir):
        for item in os.listdir(output_dir):
            if item == ".gitkeep":
                continue
            item_path = os.path.join(output_dir, item)
            try:
                shutil.rmtree(item_path) if os.path.isdir(item_path) else os.remove(item_path)
                deleted["output_files"] += 1
            except Exception as e:
                errors.append(str(e))

    input_dir = os.path.join(BASE_DIR, "Input")
    if os.path.exists(input_dir):
        for item in os.listdir(input_dir):
            if item == ".gitkeep":
                continue
            item_path = os.path.join(input_dir, item)
            try:
                shutil.rmtree(item_path) if os.path.isdir(item_path) else os.remove(item_path)
                deleted["input_files"] += 1
            except Exception as e:
                errors.append(str(e))

    return jsonify({
        "message": (
            f"✓ Cleared {deleted['invoices']} invoice(s), "
            f"{deleted['client_files']} client folder(s), "
            f"{deleted['output_files']} output file(s), "
            f"{deleted['input_files']} input file(s)."
        ),
        "deleted": deleted,
        "errors":  errors,
    }), 200


@app.route("/api/download/tracker")
def download_tracker():
    if os.path.exists(TRACKER_OUTPUT):
        return send_file(TRACKER_OUTPUT, as_attachment=True, download_name="ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx")
    elif os.path.exists(TRACKER_INPUT):
        return send_file(TRACKER_INPUT, as_attachment=True, download_name="ACCT-108 Master Invoice Tracker 2026.xlsx")
    return jsonify({"error": "No tracker file found. Upload or run the workflow first."}), 404


# ── Invoice List & Delete ──────────────────────────────────────────────────────

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

    # Support single filename string as well
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


# ── Run Routes ─────────────────────────────────────────────────────────────────

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
