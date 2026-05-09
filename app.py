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

# -----------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------
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

# -----------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

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

# -----------------------------------------------------------------
# UI
# -----------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

# -----------------------------------------------------------------
# STATUS
# -----------------------------------------------------------------
@app.route("/api/status")
def status():
    pdf_count = 0
    if os.path.exists(INVOICE_FOLDER):
        for root, _, files in os.walk(INVOICE_FOLDER):
            pdf_count += sum(1 for f in files if f.lower().endswith(".pdf"))

    client_folders = 0
    if os.path.exists(CLIENTS_FOLDER):
        client_folders = len([
            d for d in os.listdir(CLIENTS_FOLDER)
            if os.path.isdir(os.path.join(CLIENTS_FOLDER, d))
        ])

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
        "pdf_count":      pdf_count,
        "client_folders": client_folders,
        "tracker_exists": tracker_exists,
        "report_exists":  report_exists,
        "creds_exists":   creds_exists,
        "folder_id_set":  folder_id_set,
    })

# -----------------------------------------------------------------
# UPLOAD — PDFs
# -----------------------------------------------------------------
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

# -----------------------------------------------------------------
# UPLOAD — Master Tracker
# -----------------------------------------------------------------
@app.route("/api/upload/tracker", methods=["POST"])
def upload_tracker():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".xlsx"):
        return jsonify({"error": "Only .xlsx files accepted"}), 400
    os.makedirs(INPUT_FOLDER, exist_ok=True)
    f.save(TRACKER_INPUT)
    return jsonify({"message": "[OK] Tracker uploaded to Input/ folder"})

# -----------------------------------------------------------------
# UPLOAD — credentials.json
# -----------------------------------------------------------------
@app.route("/api/upload/credentials", methods=["POST"])
def upload_credentials():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".json"):
        return jsonify({"error": "Only .json files accepted"}), 400
    f.save(CREDENTIALS)
    return jsonify({"message": "[OK] credentials.json saved to project root"})

# -----------------------------------------------------------------
# DELETE — credentials.json
# -----------------------------------------------------------------
@app.route("/api/credentials/delete", methods=["POST"])
def delete_credentials():
    if os.path.exists(CREDENTIALS):
        os.remove(CREDENTIALS)
        return jsonify({"message": "[OK] credentials.json removed"})
    return jsonify({"message": "[WARN] No credentials file found"}), 404

# -----------------------------------------------------------------
# DRIVE CONFIG — Get / Save / Delete
# -----------------------------------------------------------------
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

# -----------------------------------------------------------------
# DOWNLOAD — Sort Report CSV
# -----------------------------------------------------------------
@app.route("/api/download/report")
def download_report():
    if not os.path.exists(REPORT_PATH):
        return jsonify({"error": "Report not found"}), 404
    return send_file(REPORT_PATH, as_attachment=True, download_name="invoice_sort_report.csv")

# -----------------------------------------------------------------
# DOWNLOAD — Clients folder as ZIP
# -----------------------------------------------------------------
@app.route("/api/download/clients-zip")
def download_clients_zip():
    if not os.path.exists(CLIENTS_FOLDER):
        return jsonify({"error": "Clients/ folder not found. Run the workflow first."}), 404

    # Check folder is not empty
    has_files = any(
        files
        for _, _, files in os.walk(CLIENTS_FOLDER)
    )
    if not has_files:
        return jsonify({"error": "Clients/ folder is empty. Run the workflow first."}), 404

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(CLIENTS_FOLDER):
            for filename in filenames:
                file_path = os.path.join(dirpath, filename)
                # Preserve folder structure inside zip starting from "Clients/"
                arcname   = os.path.relpath(file_path, os.path.dirname(CLIENTS_FOLDER))
                zf.write(file_path, arcname)
    zip_buffer.seek(0)

    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="Clients.zip"
    )

@app.route('/api/clear/workspace', methods=['POST'])
def clear_workspace():
    import shutil

    deleted = {'invoices': 0, 'client_files': 0, 'output_files': 0}
    errors  = []

    # 1. Clear /invoices/ — delete all PDFs
    invoices_dir = os.path.join(BASE_DIR, 'invoices')
    if os.path.exists(invoices_dir):
        for f in os.listdir(invoices_dir):
            if f.lower().endswith('.pdf'):
                try:
                    os.remove(os.path.join(invoices_dir, f))
                    deleted['invoices'] += 1
                except Exception as e:
                    errors.append(str(e))

    # 2. Clear /Clients/ — wipe all subfolders
    clients_dir = os.path.join(BASE_DIR, 'Clients')
    if os.path.exists(clients_dir):
        for item in os.listdir(clients_dir):
            item_path = os.path.join(clients_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                deleted['client_files'] += 1
            except Exception as e:
                errors.append(str(e))

    # 3. Clear /Output/ — wipe EVERYTHING including .xlsx
    output_dir = os.path.join(BASE_DIR, 'Output')
    if os.path.exists(output_dir):
        for item in os.listdir(output_dir):
            item_path = os.path.join(output_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                deleted['output_files'] += 1
            except Exception as e:
                errors.append(str(e))

    return jsonify({
        'message': (
            f"✓ Cleared {deleted['invoices']} invoice(s), "
            f"{deleted['client_files']} client folder(s), "
            f"{deleted['output_files']} output file(s)."
        ),
        'deleted': deleted,
        'errors':  errors
    }), 200


@app.route("/api/download/tracker")
def download_tracker():
    # Prefer the updated output version, fall back to the input version
    if os.path.exists(TRACKER_OUTPUT):
        path = TRACKER_OUTPUT
        name = "ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx"
    elif os.path.exists(TRACKER_INPUT):
        path = TRACKER_INPUT
        name = "ACCT-108 Master Invoice Tracker 2026.xlsx"
    else:
        return jsonify({"error": "No tracker file found. Upload or run the workflow first."}), 404
    return send_file(path, as_attachment=True, download_name=name)

# -----------------------------------------------------------------
# STREAMING RUNNERS
# -----------------------------------------------------------------
@app.route("/api/run/sort")
def run_sort():     return run_and_stream("invoice_sorter.py")

@app.route("/api/run/extract")
def run_extract():  return run_and_stream("invoice_extractor.py")

@app.route("/api/run/workflow")
def run_workflow(): return run_and_stream("run_workflow.py")

# -----------------------------------------------------------------
# GOOGLE DRIVE SYNC — streaming
# -----------------------------------------------------------------
@app.route("/api/drive/sync", methods=["POST"])
def drive_sync():
    if not os.path.exists(CREDENTIALS):
        return jsonify({
            "status":  "not_configured",
            "message": "[WARN] credentials.json not found. Upload it via the dashboard first.",
        }), 501
    if not os.path.exists(DRIVE_CONFIG):
        return jsonify({
            "status":  "not_configured",
            "message": "[WARN] Drive folder ID not set. Add it in the Google Drive Sync card.",
        }), 501
    return run_and_stream("drive_sync.py")

# -----------------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
