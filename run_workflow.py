import os
import re
import sys
import subprocess
from time import perf_counter
from datetime import datetime


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRACTOR_SCRIPT = os.path.join(BASE_DIR, "invoice_extractor.py")
SORTER_SCRIPT = os.path.join(BASE_DIR, "invoice_sorter.py")

VERSION = "v2.1"
SEP = "=" * 72
SUB_SEP = "-" * 72


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def duration_str(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"

    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}m {secs:.1f}s"


def is_verbose():
    return "--verbose" in sys.argv or "-v" in sys.argv


def print_header(verbose):
    print(SEP)
    print(f"ACCT-108 Master Workflow | {VERSION}")
    print(f"Started : {now_str()}")
    print(f"Folder  : {BASE_DIR}")
    print(f"Mode    : {'Verbose' if verbose else 'Quiet'}")
    print(SEP)


def print_step_header(step_num, total_steps, label, script_path):
    print()
    print(SUB_SEP)
    print(f"STEP {step_num}/{total_steps}: {label}")
    print(SUB_SEP)
    print(f"[RUN] {os.path.basename(script_path)}")


def parse_summary_value(output, label):
    pattern = rf"{re.escape(label)}\s*:\s*(.+)"
    match = re.search(pattern, output, re.I)
    return match.group(1).strip() if match else "-"


def compact_extractor_summary(output):
    return {
        "PDFs scanned": parse_summary_value(output, "PDFs scanned"),
        "Rows extracted": parse_summary_value(output, "Rows extracted"),
        "Rows added": parse_summary_value(output, "Rows added"),
        "Duplicates skipped": parse_summary_value(output, "Duplicates skipped"),
        "Output": parse_summary_value(output, "Output file"),
    }


def compact_sorter_summary(output):
    return {
        "PDFs scanned": parse_summary_value(output, "PDFs scanned"),
        "Files copied": parse_summary_value(output, "Files copied"),
        "Files skipped": parse_summary_value(output, "Files skipped"),
        "Audit report": parse_summary_value(output, "Audit report"),
    }


def print_summary_block(summary):
    max_label_len = max(len(k) for k in summary.keys())

    for key, value in summary.items():
        print(f"      {key:<{max_label_len}} : {value}")


def print_important_child_lines(output, prefix):
    """
    Quiet mode only prints warning/error/failure lines from child scripts.
    """
    important_tags = ("[ERR]", "[ERROR]", "[WARN]", "[FAIL]", "[SKIP] Script not found")

    for line in output.splitlines():
        stripped = line.strip()

        if any(tag in stripped for tag in important_tags):
            print(f"[{prefix}] {stripped}")


def print_verbose_child_output(output, prefix):
    for line in output.splitlines():
        if line.strip():
            print(f"[{prefix}] {line}")
        else:
            print()


def run_step(step_num, total_steps, label, script_path, prefix, summary_type, verbose=False):
    print_step_header(step_num, total_steps, label, script_path)

    if not os.path.exists(script_path):
        print(f"[FAIL] Script not found: {script_path}")
        return {
            "label": label,
            "script": os.path.basename(script_path),
            "ok": False,
            "exit_code": None,
            "duration": 0,
            "summary": {},
        }

    start = perf_counter()

    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=BASE_DIR,
    )

    duration = perf_counter() - start

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    combined_output = stdout + "\n" + stderr

    if verbose:
        if stdout:
            print_verbose_child_output(stdout, prefix)
        if stderr:
            print_verbose_child_output(stderr, f"{prefix}-ERR")
    else:
        print_important_child_lines(combined_output, prefix)

    if summary_type == "extractor":
        summary = compact_extractor_summary(combined_output)
        done_label = "Extraction complete"
    elif summary_type == "sorter":
        summary = compact_sorter_summary(combined_output)
        done_label = "Sorting complete"
    else:
        summary = {}
        done_label = "Step complete"

    if result.returncode == 0:
        print(f"[OK]  {done_label} in {duration_str(duration)}")
        if summary:
            print_summary_block(summary)
        ok = True
    else:
        print(f"[FAIL] Step failed with exit code {result.returncode} after {duration_str(duration)}")
        ok = False

    return {
        "label": label,
        "script": os.path.basename(script_path),
        "ok": ok,
        "exit_code": result.returncode,
        "duration": duration,
        "summary": summary,
    }


def print_workflow_summary(results, total_duration):
    print()
    print(SEP)
    print("WORKFLOW SUMMARY")
    print(SEP)

    for idx, result in enumerate(results, start=1):
        status = "[OK]" if result["ok"] else "[FAIL]"
        print(f"{idx}. {status} {result['label']:<45} {duration_str(result['duration'])}")

    all_ok = all(r["ok"] for r in results)

    print(SUB_SEP)
    print(f"Final Result : {'ALL STEPS PASSED' if all_ok else 'SOME STEPS FAILED'}")
    print(f"Total Time   : {duration_str(total_duration)}")
    print(f"Finished     : {now_str()}")
    print(SEP)

    return all_ok


def main():
    verbose = is_verbose()
    workflow_start = perf_counter()

    print_header(verbose)

    steps = [
        {
            "label": "Extract invoice data into Master Tracker",
            "script": EXTRACTOR_SCRIPT,
            "prefix": "EXTRACTOR",
            "summary_type": "extractor",
        },
        {
            "label": "Sort invoices into client folders",
            "script": SORTER_SCRIPT,
            "prefix": "SORTER",
            "summary_type": "sorter",
        },
    ]

    results = []

    for index, step in enumerate(steps, start=1):
        result = run_step(
            step_num=index,
            total_steps=len(steps),
            label=step["label"],
            script_path=step["script"],
            prefix=step["prefix"],
            summary_type=step["summary_type"],
            verbose=verbose,
        )

        results.append(result)

        if not result["ok"]:
            print()
            print("[STOP] Workflow stopped because a required step failed.")
            break

    total_duration = perf_counter() - workflow_start
    all_ok = print_workflow_summary(results, total_duration)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()