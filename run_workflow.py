"""
ACCT-108 | Master Workflow  v2.0
=================================
Orchestrates both steps in sequence by calling the individual scripts.

Usage
-----
    python run_workflow.py

Requirements
------------
    invoice_extractor.py  —  must be in the same folder
    invoice_sorter.py     —  must be in the same folder
"""

import subprocess
import sys
import os
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# ⚙️  CONFIG
# ─────────────────────────────────────────────────────────────
EXTRACTOR_SCRIPT = "invoice_extractor.py"
SORTER_SCRIPT    = "invoice_sorter.py"

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def check_scripts_exist():
    missing = [s for s in [EXTRACTOR_SCRIPT, SORTER_SCRIPT] if not os.path.exists(s)]
    if missing:
        print(f"  ❌ Missing script(s): {', '.join(missing)}")
        print("     Make sure all scripts are in the same folder as run_workflow.py")
        sys.exit(1)


def run_step(step_number, label, script):
    print(f"\n{'─' * 65}")
    print(f"  STEP {step_number} OF 2  —  {label}")
    print(f"  Running: {script}")
    print(f"{'─' * 65}\n")

    result = subprocess.run(
        [sys.executable, script],
        capture_output=False,   # streams output live to terminal
        text=True,
    )

    if result.returncode != 0:
        print(f"\n  ❌ {script} exited with error (code {result.returncode})")
        print("     Workflow stopped. Fix the error above and re-run.")
        sys.exit(result.returncode)

    print(f"\n  ✅ {script} completed successfully")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    start = datetime.now()

    print("=" * 65)
    print("  ACCT-108 Master Workflow  |  v2.0")
    print(f"  Started: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    check_scripts_exist()

    run_step(1, "Extract invoice data → Master Tracker", EXTRACTOR_SCRIPT)
    run_step(2, "Sort & rename invoices → Clients/",     SORTER_SCRIPT)

    elapsed = (datetime.now() - start).seconds
    print("\n" + "=" * 65)
    print("  🎉 Workflow complete!")
    print(f"  ⏱️  Time elapsed: {elapsed}s")
    print("=" * 65)


if __name__ == "__main__":
    main()
