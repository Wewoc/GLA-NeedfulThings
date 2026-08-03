#!/usr/bin/env python3
"""
netz2_diagnostics/netz2_delta.py

Hash comparison of the six Net-2 core modules against the last
netz2_diagnostics run — "conditional diagnostic requirement".

Purpose: prevent a future build task on one of the six Net-2 core modules
from building on a stale netz2_diagnostics finding without anyone
noticing. Pure file-hash comparison (SHA256) — no classification logic,
no code understanding, no calls into production code.

Deliberately does NOT reuse build_dep_map.py: its delta mechanism compares
exception/file-I/O AST records between two full scans — a different
question than "has file X changed since report Y". For "detect a pure
file change", that's the structurally wrong lever.

Pure observation. No assert. No changes to the main repo — reads the six
core module files read-only only, does not call any production code at
all (unlike run_netz2*.py — there is no DIAGNOSE_DIR here, no
garmin_config import, no GARMIN_OUTPUT_DIR override, because nothing is
executed).

IMPORTANT — garmin_import_mirror.py:
  One of the six core modules, but has no dedicated run_netz2_*.py
  scenario — the mirror-container part is already covered by the Net-3
  regression tests (test_local.py). Still hashed here (for completeness
  of the six core modules), but flagged with its own note on change
  instead of "diagnosis potentially stale" — there is no
  netz2_diagnostics diagnosis that could go stale for it.

IMPORTANT — garmin_quality.py:
  Facade — implementation lives in garmin/quality/_assess.py and
  garmin/quality/_maint.py. All three files together form a combined
  hash for the core-module entry "garmin_quality.py" — if any of the
  three changes, the module counts as changed.

IMPORTANT — report numbering:
  Started via run_netz2_all.bat like the other run_netz2_*.py scripts,
  NETZ2_REPORT_ID must be set. Deliberately NOT picked up by the
  run_netz2*.py glob in run_netz2_all.bat (filename doesn't start with
  "run_netz2") — it's not another diagnostic scenario, it's the
  pre-check for one; own, explicit call in the .bat, before the scenario
  loop.

IMPORTANT — first run:
  The very first run of this script finds no baseline (there has never
  been a netz2_delta.py snapshot before) — reports "no baseline (first
  run)" for all six modules, not "unchanged". Only the SECOND run
  (with no file change in between) reports "unchanged". Relevant for the
  test run described in the rules.

Run via:
    run_netz2_all.bat (sets NETZ2_REPORT_ID before the call).

Result:
    netz2_diagnostics/output/<NETZ2_REPORT_ID>/delta/NETZ2_DELTA_<NETZ2_REPORT_ID>.md
    netz2_diagnostics/output/<NETZ2_REPORT_ID>/delta/netz2_module_hashes.json
    (snapshot for the next run's comparison — "auto_last" principle,
    analogous to build_dep_map.py, but without its AST semantics.)
"""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

try:
    from netz2_config import PROJECT_ROOT_REL
except ImportError:
    print("✗  netz2_config.py missing next to netz2_delta.py.")
    print("   Please create netz2_config.py with PROJECT_ROOT_REL "
          "(see netz2_config.example.py).")
    sys.exit(1)

NETZ2_REPORT_ID = os.environ.get("NETZ2_REPORT_ID")
if not NETZ2_REPORT_ID:
    print("✗  NETZ2_REPORT_ID not set.")
    print("   This script is started via run_netz2_all.bat, not directly — "
          "the .bat assigns the running report number and sets "
          "NETZ2_REPORT_ID before the call.")
    sys.exit(1)

PROJECT_ROOT = (SCRIPT_DIR / PROJECT_ROOT_REL).resolve()
GARMIN_SRC_DIR = PROJECT_ROOT / "src" / "garmin"

OUTPUT_ROOT = SCRIPT_DIR / "output"
DELTA_DIR = OUTPUT_ROOT / NETZ2_REPORT_ID / "delta"
SNAPSHOT_PATH = DELTA_DIR / "netz2_module_hashes.json"
REPORT_MD = DELTA_DIR / f"NETZ2_DELTA_{NETZ2_REPORT_ID}.md"

_SNAPSHOT_VERSION = 1

# ══════════════════════════════════════════════════════════════════════════════
#  Six Net-2 core modules
# ══════════════════════════════════════════════════════════════════════════════
#
# Paths relative to GARMIN_SRC_DIR (src/garmin/). "paths" with more than one
# entry are combined into a single hash (facade + implementation).
# "scenario" is the run_netz2_*.py script whose finding is considered
# potentially stale if this module changes — None if no gla-netz2
# scenario exists (garmin_import_mirror.py, see docstring above).

CORE_MODULES = {
    "garmin_quality.py": {
        "paths": ["garmin_quality.py", "quality/_assess.py", "quality/_maint.py"],
        "scenario": (
            "run_netz2.py, run_netz2_steps_async.py, run_netz2_stop_abort.py, "
            "run_netz2_restore_staleness.py, run_netz2_bulk_import.py "
            "(all five — each imports garmin_quality)"
        ),
    },
    "garmin_silo_repair.py": {
        "paths": ["garmin_silo_repair.py"],
        "scenario": "run_netz2.py",
    },
    "garmin_collector.py": {
        "paths": ["garmin_collector.py"],
        "scenario": (
            "run_netz2_steps_async.py, run_netz2_stop_abort.py, "
            "run_netz2_bulk_import.py"
        ),
    },
    "garmin_backup.py": {
        "paths": ["garmin_backup.py"],
        "scenario": "run_netz2_restore_staleness.py",
    },
    "garmin_import.py": {
        "paths": ["garmin_import.py"],
        "scenario": "run_netz2_bulk_import.py",
    },
    "garmin_import_mirror.py": {
        "paths": ["garmin_import_mirror.py"],
        "scenario": None,  # no netz2_diagnostics scenario — see docstring
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#  Hashing
# ══════════════════════════════════════════════════════════════════════════════

def _hash_file(path: Path) -> str | None:
    """SHA256 of the file content. None if the file doesn't exist or isn't
    readable — noted in the report as 'not found', not silently skipped."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def compute_module_hashes() -> dict:
    """
    One hash per core-module entry. For multiple "paths" (facade +
    implementation): individual hashes in a fixed order (definition order
    in CORE_MODULES, not filesystem order) combined into one hash —
    deterministic, no sorting needed since the order is already fixed in
    CORE_MODULES. A missing file is included as the placeholder "<missing>"
    — a sub-file appearing/disappearing therefore also changes the
    combined hash.
    """
    result = {}
    for module_key, meta in CORE_MODULES.items():
        per_file = {}
        missing = []
        for rel in meta["paths"]:
            full = GARMIN_SRC_DIR / rel
            h = _hash_file(full)
            per_file[rel] = h
            if h is None:
                missing.append(rel)

        if missing and len(missing) == len(meta["paths"]):
            combined = None  # not a single file readable
        else:
            combined_input = "|".join(
                f"{rel}:{per_file[rel] or '<missing>'}" for rel in meta["paths"]
            )
            combined = hashlib.sha256(combined_input.encode("utf-8")).hexdigest()

        result[module_key] = {
            "combined_hash": combined,
            "per_file": per_file,
            "missing": missing,
        }
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  Baseline — find the last previous snapshot (auto_last principle)
# ══════════════════════════════════════════════════════════════════════════════

def find_last_snapshot() -> Path | None:
    """
    Looks for the most recently written netz2_module_hashes.json under
    output/*/delta/ — sorted by file mtime (not folder name, robust
    against version jumps e.g. v1658_10 vs. v1659_01). The current run
    hasn't written its own snapshot yet when this function runs — so it
    can't find itself as the baseline.
    """
    candidates = sorted(
        OUTPUT_ROOT.glob("*/delta/netz2_module_hashes.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def load_snapshot(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_snapshot(current_hashes: dict, out_path: Path) -> None:
    snapshot = {
        "version": _SNAPSHOT_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_id": NETZ2_REPORT_ID,
        "modules": {
            k: {"combined_hash": v["combined_hash"], "missing": v["missing"]}
            for k, v in current_hashes.items()
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Report
# ══════════════════════════════════════════════════════════════════════════════

def build_report_md(current_hashes: dict, baseline: dict | None,
                     baseline_path: Path | None) -> str:
    lines = []
    lines.append(f"# NETZ2_DELTA_{NETZ2_REPORT_ID}.md")
    lines.append("")
    lines.append(
        "Pure file-hash comparison of the six Net-2 core modules against "
        "the last netz2_diagnostics run. No assert, no assessment of the "
        "code content."
    )
    lines.append("")
    lines.append(f"Main repo: `{PROJECT_ROOT}`")
    if baseline is None:
        lines.append(
            "Baseline: **none found — first run.** All modules count as "
            "'no comparison baseline', not as 'unchanged'."
        )
    else:
        b_id = baseline.get("report_id", "?")
        b_ts = baseline.get("generated_at", "?")
        lines.append(f"Baseline: report `{b_id}` ({b_ts}) — `{baseline_path}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("| Core module | Status | Affected scenario |")
    lines.append("|---|---|---|")

    for module_key, meta in CORE_MODULES.items():
        cur = current_hashes[module_key]
        scenario = meta["scenario"] or "— (no netz2_diagnostics scenario, see below)"

        if cur["combined_hash"] is None:
            status = "⚠ none of the source files readable"
        elif baseline is None:
            status = "– no baseline (first run)"
        else:
            b_mod = baseline.get("modules", {}).get(module_key)
            b_hash = b_mod.get("combined_hash") if b_mod else None
            if b_mod is None:
                status = "– no baseline for this module (new in snapshot)"
            elif b_hash == cur["combined_hash"]:
                status = "✓ unchanged"
            else:
                if meta["scenario"] is None:
                    status = (
                        "⚠ changed — no netz2_diagnostics scenario present, "
                        "check coverage via test_local.py (Net 3)"
                    )
                else:
                    status = "✗ changed — diagnosis potentially stale"

        lines.append(f"| `{module_key}` | {status} | {scenario} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Details per module")
    lines.append("")

    for module_key, meta in CORE_MODULES.items():
        cur = current_hashes[module_key]
        lines.append(f"### {module_key}")
        lines.append("")
        for rel in meta["paths"]:
            h = cur["per_file"].get(rel)
            if h is None:
                lines.append(f"- `{rel}` — **not found**")
            else:
                lines.append(f"- `{rel}` — `{h[:16]}…`")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("  netz2_diagnostics — netz2_delta.py")
    print("=" * 65)
    print(f"  Main repo   : {PROJECT_ROOT}")
    print(f"  Report ID   : {NETZ2_REPORT_ID}")
    print()

    if not GARMIN_SRC_DIR.is_dir():
        print(f"✗  Main repo source folder not found: {GARMIN_SRC_DIR}")
        print("   Check PROJECT_ROOT_REL in netz2_config.py.")
        sys.exit(1)

    baseline_path = find_last_snapshot()
    baseline = load_snapshot(baseline_path) if baseline_path else None

    current_hashes = compute_module_hashes()

    DELTA_DIR.mkdir(parents=True, exist_ok=True)
    md = build_report_md(current_hashes, baseline, baseline_path)
    REPORT_MD.write_text(md, encoding="utf-8")
    write_snapshot(current_hashes, SNAPSHOT_PATH)

    print()
    for module_key in CORE_MODULES:
        cur = current_hashes[module_key]
        if baseline is None:
            state = "first run — no baseline"
        else:
            b_mod = baseline.get("modules", {}).get(module_key)
            b_hash = b_mod.get("combined_hash") if b_mod else None
            if b_mod is None:
                state = "new in snapshot"
            elif b_hash == cur["combined_hash"]:
                state = "unchanged"
            else:
                state = "CHANGED"
        print(f"  {module_key}: {state}")

    print()
    print(f"  ✓  Report:   {REPORT_MD}")
    print(f"  ✓  Snapshot: {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
