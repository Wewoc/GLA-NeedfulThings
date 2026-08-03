#!/usr/bin/env python3
"""
netz2_diagnostics/run_netz2.py

Diagnostic harness for silo-repair test gaps #3 (source_without_raw) and
#7 (raw_without_summary) — Net 2, priority 1 part 2.

Analogous to scan_critical_deps.py: imports the real core modules directly
from the main repo (no copy, no duplication), builds error states, calls
repair_silos(fresh) FOR REAL (no mock), logs the return value + file state
+ error text.

Pure observation. No assert. No changes to the main repo — this script
only imports garmin_silo_repair etc. read-only/call-only.

IMPORTANT — write target:
  repair_silos() genuinely writes (write_day(), record_attempt() to
  quality_log.json). To avoid touching the real production archive while
  doing so, this diagnostic run works against an isolated folder
  (DIAGNOSE_DIR, see below) — same garmin_data/ structure as the real
  archive, but physically separate. The fixture CONTENT is still derived
  from a real raw/ file in your archive (read-only access).

IMPORTANT — report numbering:
  This script is started via run_netz2_all.bat, not directly. The .bat
  assigns the running report number (folder output/vXXXX_NN/) and sets
  NETZ2_REPORT_ID before the call — no manually maintained REPORT_ID
  value in netz2_config.py anymore.

Run via:
    run_netz2_all.bat (sets NETZ2_REPORT_ID + starts all run_netz2*.py
    scripts in sequence).

Result:
    netz2_diagnostics/output/<NETZ2_REPORT_ID>/NETZ2_BEFUND_silo_repair.md
"""

import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  Configuration — from netz2_config.py (personal/local values, kept
#  separate so this script itself stays generic) + NETZ2_REPORT_ID from the
#  environment (set by run_netz2_all.bat)
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent

try:
    from netz2_config import PROJECT_ROOT_REL, REAL_ARCHIVE_BASE_DIR
except ImportError:
    print("✗  netz2_config.py missing next to run_netz2.py.")
    print("   Please create netz2_config.py with PROJECT_ROOT_REL, "
          "REAL_ARCHIVE_BASE_DIR (see netz2_config.example.py).")
    sys.exit(1)

NETZ2_REPORT_ID = os.environ.get("NETZ2_REPORT_ID")
if not NETZ2_REPORT_ID:
    print("✗  NETZ2_REPORT_ID not set.")
    print("   This script is started via run_netz2_all.bat, not directly — "
          "the .bat assigns the running report number and sets "
          "NETZ2_REPORT_ID before the call.")
    sys.exit(1)

# Isolated diagnostic folder — this (and ONLY this) is where repair_silos()
# writes during this run. Recreated on every run (previous content is
# deliberately deleted so every run starts clean). Structural, not
# personal — stays here rather than in netz2_config.py.
DIAGNOSE_DIR = SCRIPT_DIR / "diagnose_tmp"

OUTPUT_DIR = SCRIPT_DIR / "output" / NETZ2_REPORT_ID
OUTPUT_MD = OUTPUT_DIR / "NETZ2_BEFUND_silo_repair.md"

# ══════════════════════════════════════════════════════════════════════════════
#  Path setup — import the core modules directly from the main repo
# ══════════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = (SCRIPT_DIR / PROJECT_ROOT_REL).resolve()
GARMIN_SRC_DIR = PROJECT_ROOT / "src" / "garmin"

if not GARMIN_SRC_DIR.is_dir():
    print(f"✗  Main repo source folder not found: {GARMIN_SRC_DIR}")
    print(f"   Check PROJECT_ROOT_REL (currently: '{PROJECT_ROOT_REL}')")
    sys.exit(1)

sys.path.insert(0, str(GARMIN_SRC_DIR))

# GARMIN_OUTPUT_DIR MUST be set before garmin_config is imported for the
# first time (it reads BASE_DIR from the env at import time).
os.environ["GARMIN_OUTPUT_DIR"] = str(DIAGNOSE_DIR)

import garmin_config as cfg  # noqa: E402
import garmin_normalizer as normalizer  # noqa: E402
import garmin_quality as quality  # noqa: E402
import garmin_writer as writer  # noqa: E402
import garmin_silo_repair as silo_repair  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
#  Fixture generators
# ══════════════════════════════════════════════════════════════════════════════

def _find_real_raw_file(real_archive_base: Path) -> Path | None:
    """Looks for a real raw/ file in the real archive (read-only). Picks the
    most recently modified one if several are present."""
    raw_dir = real_archive_base / "garmin_data" / "raw"
    if not raw_dir.is_dir():
        return None
    candidates = sorted(raw_dir.glob("garmin_raw_*.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _trim_lists(obj, max_items: int = 3, _depth: int = 0):
    """Recursively trims all lists to max_items entries — 'copy the
    structure, shorten the content', without guessing or changing field
    names. Leaves dict structure and keys exactly as in the original."""
    if _depth > 6:
        return obj
    if isinstance(obj, list):
        trimmed = obj[:max_items]
        return [_trim_lists(x, max_items, _depth + 1) for x in trimmed]
    if isinstance(obj, dict):
        return {k: _trim_lists(v, max_items, _depth + 1) for k, v in obj.items()}
    return obj


def build_fixture_source_without_raw(real_archive_base: Path, target_date: str) -> dict | None:
    """
    Category #3 fixture: minimally valid source/ raw file, derived from a
    real raw/ file (structure copied, content trimmed). repair_silos()
    treats this like an API response (normalize(..., source="api") is a
    passthrough for dicts).
    """
    src_file = _find_real_raw_file(real_archive_base)
    if src_file is None:
        return None
    real = json.loads(src_file.read_text(encoding="utf-8"))
    fixture = _trim_lists(real, max_items=3)
    fixture["date"] = target_date
    return fixture


def build_fixture_raw_without_summary(real_archive_base: Path, target_date: str) -> dict | None:
    """
    Category #7 fixture: minimally valid raw/ file with no corresponding
    summary/ file, same origin rule (real raw/ file, trimmed).
    """
    src_file = _find_real_raw_file(real_archive_base)
    if src_file is None:
        return None
    real = json.loads(src_file.read_text(encoding="utf-8"))
    fixture = _trim_lists(real, max_items=3)
    fixture["date"] = target_date
    return fixture


def build_fixture_broken_intraday(real_archive_base: Path, target_date: str) -> dict | None:
    """
    Broken variant for #3 — analogous to the v1.6.3.1 bug: heartRateValues
    as a flat list of ints instead of [ts, val] pairs. Observes whether the
    chain crashes (repair_silos catches it → status='error') or silently
    produces wrong values.
    """
    fixture = build_fixture_source_without_raw(real_archive_base, target_date)
    if fixture is None:
        return None
    fixture.setdefault("heart_rates", {})
    fixture["heart_rates"]["heartRateValues"] = [55, 58, 60, 62]  # malformed
    return fixture


def build_fixture_missing_date(real_archive_base: Path, target_date: str) -> dict | None:
    """
    Broken variant for #7 — raw file missing the required 'date' field in
    the content itself (the filename/date_str comes separately from the
    finding, not from the file content). Observes what summarize() does
    with it.
    """
    fixture = build_fixture_raw_without_summary(real_archive_base, target_date)
    if fixture is None:
        return None
    fixture.pop("date", None)
    return fixture


# ══════════════════════════════════════════════════════════════════════════════
#  Diagnostic run
# ══════════════════════════════════════════════════════════════════════════════

def reset_diagnose_dir():
    if DIAGNOSE_DIR.exists():
        shutil.rmtree(DIAGNOSE_DIR)
    for sub in ("raw", "summary", "source", "log"):
        (DIAGNOSE_DIR / "garmin_data" / sub).mkdir(parents=True, exist_ok=True)


def _read_or_none(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"<file present but unreadable: {e}>"


def run_scenario(name: str, category: str, fixture: dict | None, target_date: str) -> dict:
    """
    Runs one scenario: writes the fixture into the correct silo folder,
    builds a fresh dict with exactly this one finding, calls
    repair_silos() for real, logs the return value + file state
    afterwards.
    """
    record = {"name": name, "category": category, "target_date": target_date}

    if fixture is None:
        record["skipped"] = True
        record["skip_reason"] = "no real raw/ file found in the real archive — check REAL_ARCHIVE_BASE_DIR"
        return record
    record["skipped"] = False

    empty_fresh = {
        "raw_without_quality": [], "source_without_raw": [],
        "summary_without_raw": [], "raw_without_summary": [],
    }
    fresh = dict(empty_fresh)
    fresh[category] = [date.fromisoformat(target_date)]

    if category == "source_without_raw":
        target_path = cfg.SOURCE_DIR / f"garmin_source_{target_date}.json"
    elif category == "raw_without_summary":
        target_path = cfg.RAW_DIR / f"garmin_raw_{target_date}.json"
    else:
        raise ValueError(f"Unknown category: {category}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    record["fixture_written_to"] = str(target_path)
    record["fixture_content"] = fixture

    # ── real call, no mock ──────────────────────────────────────────────
    try:
        result = silo_repair.repair_silos(fresh)
        record["repair_result"] = result
        record["repair_exception"] = None
    except Exception as e:
        record["repair_result"] = None
        record["repair_exception"] = f"{type(e).__name__}: {e}"

    # ── file state afterwards ──────────────────────────────────────────────
    raw_path = cfg.RAW_DIR / f"garmin_raw_{target_date}.json"
    summary_path = cfg.SUMMARY_DIR / f"garmin_{target_date}.json"
    record["raw_after"] = _read_or_none(raw_path)
    record["summary_after"] = _read_or_none(summary_path)

    qdata = quality._load_quality_log()
    qentry = next((e for e in qdata.get("days", []) if e.get("date") == target_date), None)
    record["quality_log_entry_after"] = qentry

    return record


def main():
    print("=" * 65)
    print("  netz2_diagnostics — silo-repair diagnosis #3/#7")
    print("=" * 65)
    print(f"  Main repo   : {PROJECT_ROOT}")
    print(f"  Real archive (read-only): {REAL_ARCHIVE_BASE_DIR}")
    print(f"  Diagnose dir (write target): {DIAGNOSE_DIR}")
    print(f"  Report ID   : {NETZ2_REPORT_ID}")
    print()

    if not REAL_ARCHIVE_BASE_DIR.exists():
        print(f"✗  REAL_ARCHIVE_BASE_DIR does not exist: {REAL_ARCHIVE_BASE_DIR}")
        print("   Please point it to your real archive in netz2_config.py.")
        sys.exit(1)

    reset_diagnose_dir()

    scenarios = []

    # ── #3 good case ────────────────────────────────────────────────────────
    f3 = build_fixture_source_without_raw(REAL_ARCHIVE_BASE_DIR, "2025-01-15")
    scenarios.append(run_scenario("#3 good case (source_without_raw)",
                                   "source_without_raw", f3, "2025-01-15"))

    # ── #3 bad case — malformed intraday array ───────────────────────────
    f3b = build_fixture_broken_intraday(REAL_ARCHIVE_BASE_DIR, "2025-01-16")
    scenarios.append(run_scenario("#3 bad case (heartRateValues malformed)",
                                   "source_without_raw", f3b, "2025-01-16"))

    # ── #7 good case ────────────────────────────────────────────────────────
    f7 = build_fixture_raw_without_summary(REAL_ARCHIVE_BASE_DIR, "2025-01-17")
    scenarios.append(run_scenario("#7 good case (raw_without_summary)",
                                   "raw_without_summary", f7, "2025-01-17"))

    # ── #7 bad case — required 'date' field missing in content ────────────
    f7b = build_fixture_missing_date(REAL_ARCHIVE_BASE_DIR, "2025-01-18")
    scenarios.append(run_scenario("#7 bad case (raw without 'date' field in content)",
                                   "raw_without_summary", f7b, "2025-01-18"))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md = build_report_md(scenarios)
    OUTPUT_MD.write_text(md, encoding="utf-8")

    print()
    for s in scenarios:
        status = "skipped" if s.get("skipped") else "ran"
        print(f"  {s['name']}: {status}")
    print()
    print(f"  ✓  Report: {OUTPUT_MD}")


# ══════════════════════════════════════════════════════════════════════════════
#  Report
# ══════════════════════════════════════════════════════════════════════════════

def _json_block(obj) -> str:
    if obj is None:
        return "```\nNone\n```"
    if isinstance(obj, str):
        return f"```\n{obj}\n```"
    return "```json\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```"


def build_report_md(scenarios: list[dict]) -> str:
    lines = []
    lines.append(f"# NETZ2_BEFUND_silo_repair_{NETZ2_REPORT_ID}.md")
    lines.append("")
    lines.append("Pure observation — no assert, no assessment. Assessment follows in the analysis chat.")
    lines.append("")
    lines.append(f"Main repo: `{PROJECT_ROOT}`")
    lines.append(f"Diagnose dir (write target of this run): `{DIAGNOSE_DIR}`")
    lines.append(f"Fixture source (read-only): `{REAL_ARCHIVE_BASE_DIR}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    for s in scenarios:
        lines.append(f"## {s['name']}")
        lines.append("")
        lines.append(f"- Category: `{s['category']}`")
        lines.append(f"- Date: `{s['target_date']}`")

        if s.get("skipped"):
            lines.append(f"- **Skipped:** {s['skip_reason']}")
            lines.append("")
            continue

        lines.append(f"- Fixture written to: `{s['fixture_written_to']}`")
        lines.append("")
        lines.append("**Fixture content (trimmed, derived from a real raw/ file):**")
        lines.append("")
        lines.append(_json_block(s["fixture_content"]))
        lines.append("")
        lines.append("**repair_silos(fresh) — return value:**")
        lines.append("")
        lines.append(_json_block(s["repair_result"]))
        if s["repair_exception"]:
            lines.append("")
            lines.append("**Uncaught exception (not caught by repair_silos):**")
            lines.append("")
            lines.append(_json_block(s["repair_exception"]))
        lines.append("")
        lines.append("**raw/ file afterwards:**")
        lines.append("")
        lines.append(_json_block(s["raw_after"]))
        lines.append("")
        lines.append("**summary/ file afterwards:**")
        lines.append("")
        lines.append(_json_block(s["summary_after"]))
        lines.append("")
        lines.append("**quality_log.json entry afterwards:**")
        lines.append("")
        lines.append(_json_block(s["quality_log_entry_after"]))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
