import os
import sys
import subprocess
from datetime import datetime

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
EXTRACTOR_SCRIPT = os.path.join(BASE_DIR, "invoice_extractor.py")
SORTER_SCRIPT    = os.path.join(BASE_DIR, "invoice_sorter.py")

SEP = "-" * 65

def run_step(step_num, label, script_path):
    print(f"\n{SEP}")
    print(f"  STEP {step_num}: {label}")
    print(SEP)

    if not os.path.exists(script_path):
        print(f"[SKIP] Script not found: {script_path}")
        return False

    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=BASE_DIR,
    )

    if result.returncode != 0:
        print(f"\n[ERROR] Step {step_num} exited with code {result.returncode}")
        return False

    print(f"\n[OK] Step {step_num} complete.")
    return True


def main():
    print(SEP)
    print("  ACCT-108 Master Workflow  |  v2.1")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)

    steps = [
        (1, "Extract invoice data -> Master Tracker", EXTRACTOR_SCRIPT),
        (2, "Sort invoices into client folders",      SORTER_SCRIPT),
    ]

    results = []
    for step_num, label, script in steps:
        ok = run_step(step_num, label, script)
        results.append((label, ok))

    print(f"\n{SEP}")
    print("  WORKFLOW SUMMARY")
    print(SEP)
    for label, ok in results:
        status = "[OK]   " if ok else "[FAIL] "
        print(f"  {status} {label}")

    all_ok = all(ok for _, ok in results)
    print(f"\n  Result: {'ALL STEPS PASSED' if all_ok else 'SOME STEPS FAILED'}")
    print(f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEP)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()