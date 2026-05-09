import os
import sys
import queue
import subprocess
import threading
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from werkzeug.utils import secure_filename

app = Flask(__name__)

# -----------------------------------------------------------------
# PATHS
# -----------------------------------------------------------------
INVOICE_FOLDER = "./invoices"
INPUT_FOLDER   = "./Input"
OUTPUT_FOLDER  = "./Output"

TRACKER_INPUT  = os.path.join(INPUT_FOLDER,  "ACCT-108 Master Invoice Tracker 2026.xlsx")
TRACKER_OUTPUT = os.path.join(OUTPUT_FOLDER, "ACCT-108 Master Invoice Tracker 2026 - Updated.xlsx")
REPORT_PATH    = os.path.join(OUTPUT_FOLDER, "invoice_sort_report.csv")

ALLOWED_EXTENSIONS = {"pdf"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def stream_script(script_name, q):
    try:
        proc = subprocess.Popen(
            [sys.executable, script_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        for line in proc.stdout:
            q.put(line.rstrip())
        proc.wait()
        q.put(f"__EXIT__{proc.returncode}")
    except Exception as e:
        q.put(f"[ERR] Failed to start {script_name}: {e}")
        q.put("__EXIT__1")


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
    # Count PDFs recursively in /invoices
    pdf_count = 0
    if os.path.exists(INVOICE_FOLDER):
        for root, _, files in os.walk(INVOICE_FOLDER):
            pdf_count += sum(1 for f in files if f.lower().endswith(".pdf"))

    # Count top-level client folders
    client_folders = 0
    if os.path.exists("./Clients"):
        client_folders = len([
            d for d in os.listdir("./Clients")
            if os.path.isdir(os.path.join("./Clients", d))
        ])

    # Tracker: check Input/ for source, Output/ for updated
    tracker_exists = (
        os.path.exists(TRACKER_INPUT) or
        os.path.exists(TRACKER_OUTPUT)
    )

    # Report: now lives in Output/
    report_exists = os.path.exists(REPORT_PATH)

    return jsonify({
        "pdf_count":      pdf_count,
        "client_folders": client_folders,
        "tracker_exists": tracker_exists,
        "report_exists":  report_exists,
    })


# -----------------------------------------------------------------
# UPLOAD
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
        "saved":   saved,
        "errors":  errors,
    })


# -----------------------------------------------------------------
# STREAMING
# -----------------------------------------------------------------
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
                    msg  = "[DONE] Script finished (exit 0)." if code == "0" else f"[ERR]  Script exited with code {code}."
                    yield msg + "\n"
                    break
                yield line + "\n"
            except queue.Empty:
                yield "[WARN] Timeout - no output for 120s\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/plain",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/run/sort")
def run_sort():
    return run_and_stream("invoice_sorter.py")


@app.route("/api/run/extract")
def run_extract():
    return run_and_stream("invoice_extractor.py")


@app.route("/api/run/workflow")
def run_workflow():
    return run_and_stream("run_workflow.py")


# -----------------------------------------------------------------
# GOOGLE DRIVE (stub)
# -----------------------------------------------------------------
@app.route("/api/drive/sync", methods=["POST"])
def drive_sync():
    if not os.path.exists("credentials.json"):
        return jsonify({
            "status":  "not_configured",
            "message": "[WARN] credentials.json not found. Add your Google service account key to the project root.",
        }), 501
    return jsonify({"status": "ok", "message": "[OK] Drive sync placeholder - credentials found."})


if __name__ == "__main__":
    print("=" * 55)
    print("  Project Velocity  |  Dashboard")
    print("  http://127.0.0.1:5000")
    print("=" * 55)
    app.run(debug=True, threaded=True)
