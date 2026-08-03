#!/usr/bin/env python3
"""
netz2_diagnostics/run_netz2_bulk_import.py

Diagnostic harness for Net 2, priority 4 — bulk-export import with a
structurally broken/missing day in the middle of the GDPR export.

Preliminary question already resolved: bulk-export import uses the same
delegation mechanism as the normal API sync since v1.3.0b
(GARMIN_IMPORT_PATH env var, _run_script()/_run_module()) — no
sys.executable subprocess problem. run_import() itself follows the robust
day-by-day pattern (read → build → write → repeat). The only open
question is garmin_import.py::load_bulk() — behavior on a structurally
broken/incomplete day in the middle of the export.

Standalone script, deliberately not integrated into any of the four
existing ones — different core mechanism (garmin_import.load_bulk() +
garmin_collector.run_import(), no silo-repair/backfill/restore path).

Pure observation. No assert. No changes to garmin_import.py or
garmin_collector.py — this script only imports both modules read-only/
call-only.

IMPORTANT — two error variants, ONE archive folder instead of cfg reload:
  Variant a) UDSFile for day 2 present, but invalid JSON.
  Variant b) sleepData for day 2 completely missing (file not in export).
  Unlike the existing scripts, this one does NOT switch between two
  GARMIN_OUTPUT_DIR values via importlib.reload(cfg) — with two synthetic
  GDPR exports (different format than raw/, not derived from a real
  archive file) it's unclear whether garmin_writer/garmin_quality really
  re-read their paths fresh from cfg on every call or bind them on first
  import (only garmin_security.py explicitly documents lazy behavior for
  itself). Instead: ONE fixed archive folder (ARCHIVE_DIR) that is
  physically cleared/recreated between the two scenarios — exactly the
  already-established reset_diagnose_dir() pattern, just twice in a row
  within the same run. GARMIN_OUTPUT_DIR is set exactly once at module
  import and never changed again after that.

IMPORTANT — load_bulk() AND run_import() are BOTH called:
  load_bulk() directly first (isolated, no write effect) — shows what the
  import layer actually yields for day 2 (skipped? with gaps?) before any
  pipeline step (validator/normalizer/quality/writer) is involved. Then
  run_import() — the real production path (also used by the GUI and
  GARMIN_IMPORT_PATH) — shows the overall behavior including
  quality_log/return value. Reasoning: the question from the task ("where
  exactly does an exception hit, if any — is it caught or does it
  propagate?") can only be answered if you see whether the error already
  ends in load_bulk() or only later.

IMPORTANT — report numbering:
  This script is started via run_netz2_all.bat, not directly. The .bat
  assigns the running report number (folder output/vXXXX_NN/) and sets
  NETZ2_REPORT_ID before the call.

Run via:
    run_netz2_all.bat (sets NETZ2_REPORT_ID + starts all run_netz2*.py
    scripts in sequence).

Result:
    netz2_diagnostics/output/<NETZ2_REPORT_ID>/NETZ2_BEFUND_bulk_import.md
"""

import json
import logging
import os
import shutil
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  Configuration — from netz2_config.py + NETZ2_REPORT_ID from the
#  environment (set by run_netz2_all.bat)
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent

try:
    from netz2_config import PROJECT_ROOT_REL
except ImportError:
    print("✗  netz2_config.py missing next to run_netz2_bulk_import.py, or "
          "PROJECT_ROOT_REL is missing from it (see netz2_config.example.py).")
    sys.exit(1)

NETZ2_REPORT_ID = os.environ.get("NETZ2_REPORT_ID")
if not NETZ2_REPORT_ID:
    print("✗  NETZ2_REPORT_ID not set.")
    print("   This script is started via run_netz2_all.bat, not directly — "
          "the .bat assigns the running report number and sets "
          "NETZ2_REPORT_ID before the call.")
    sys.exit(1)

# Own isolated folder — separate from the four other diagnostic runs.
DIAGNOSE_DIR = SCRIPT_DIR / "diagnose_tmp_bulk_import"
EXPORT_DIR = DIAGNOSE_DIR / "export"      # synthetic GDPR export (input only)
ARCHIVE_DIR = DIAGNOSE_DIR / "archive"    # GARMIN_OUTPUT_DIR target (write target)

OUTPUT_DIR = SCRIPT_DIR / "output" / NETZ2_REPORT_ID
OUTPUT_MD = OUTPUT_DIR / "NETZ2_BEFUND_bulk_import.md"

DAY1 = "2025-05-10"   # fully valid
DAY2 = "2025-05-11"   # target day — broken/missing, depending on variant
DAY3 = "2025-05-12"   # fully valid

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
# first time (it reads BASE_DIR from the env at import time). Not changed
# again for this entire run (both scenarios) — see the IMPORTANT note
# above about reusing ARCHIVE_DIR instead of a cfg reload.
os.environ["GARMIN_OUTPUT_DIR"] = str(ARCHIVE_DIR)

import garmin_config as cfg          # noqa: E402
import garmin_quality as quality     # noqa: E402
import garmin_import as importer     # noqa: E402
import garmin_collector as collector  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
#  Fixture setup — synthetic GDPR export (no relation to the real archive,
#  different format than raw/ — hence constructed directly here instead of
#  derived)
# ══════════════════════════════════════════════════════════════════════════════

def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _uds_entry(date_str: str) -> dict:
    """Minimally valid UDSFile daily entry (daily aggregates)."""
    return {
        "calendarDate": date_str,
        "totalSteps": 8123,
        "dailyStepGoal": 10000,
        "totalKilocalories": 2200.0,
        "activeKilocalories": 512.0,
        "totalDistanceMeters": 6100.0,
        "moderateIntensityMinutes": 28,
        "vigorousIntensityMinutes": 9,
        "floorsAscendedInMeters": 9.0,
        "restingHeartRate": 55,
        "minHeartRate": 48,
        "maxHeartRate": 142,
        "allDayStress": {
            "aggregatorList": [{
                "averageStressLevel": 22,
                "maxStressLevel": 78,
                "stressDuration": 3600,
                "restDuration": 20000,
                "lowDuration": 15000,
                "mediumDuration": 3000,
                "highDuration": 600,
            }]
        },
    }


def _sleep_entry(date_str: str) -> dict:
    """Minimally valid sleepData daily entry."""
    return {
        "calendarDate": date_str,
        "deepSleepSeconds": 5400,
        "lightSleepSeconds": 14400,
        "remSleepSeconds": 5400,
        "awakeSleepSeconds": 900,
    }


def reset_export_dir() -> None:
    if EXPORT_DIR.exists():
        shutil.rmtree(EXPORT_DIR)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def reset_archive_dir() -> None:
    if ARCHIVE_DIR.exists():
        shutil.rmtree(ARCHIVE_DIR)
    for sub in ("raw", "summary", "source", "log", "backup"):
        (ARCHIVE_DIR / "garmin_data" / sub).mkdir(parents=True, exist_ok=True)


def build_export(mode: str) -> Path:
    """
    Builds a minimally valid GDPR export folder (no ZIP — _load_from_dir()
    is enough) with three days:
      Day 1 (DAY1) — fully valid (UDSFile + sleepData)
      Day 2 (DAY2) — broken/incomplete depending on mode
      Day 3 (DAY3) — fully valid

    mode == "corrupt_json":
      UDSFile for day 2 present, but invalid JSON. sleepData for day 2
      remains normally present — isolates the effect to exactly that one
      file/endpoint.
    mode == "missing_file":
      sleepData for day 2 is completely missing (file not in the export).
      UDSFile for day 2 remains normally present — isolates the effect to
      exactly the one missing endpoint.
    """
    uds_dir = EXPORT_DIR / "DI_CONNECT" / "DI-Connect-Aggregator"
    sleep_dir = EXPORT_DIR / "DI_CONNECT" / "DI-Connect-Wellness"

    # ── day 1 + day 3 — always fully valid, regardless of mode ──
    for d in (DAY1, DAY3):
        _write_json(uds_dir / f"UDSFile_{d}.json", [_uds_entry(d)])
        _write_json(sleep_dir / f"{d}_sleepData.json", [_sleep_entry(d)])

    # ── day 2 — depends on variant ──
    if mode == "corrupt_json":
        uds_path = uds_dir / f"UDSFile_{DAY2}.json"
        uds_path.parent.mkdir(parents=True, exist_ok=True)
        uds_path.write_text("{ this is not valid json ]", encoding="utf-8")
        _write_json(sleep_dir / f"{DAY2}_sleepData.json", [_sleep_entry(DAY2)])
    elif mode == "missing_file":
        _write_json(uds_dir / f"UDSFile_{DAY2}.json", [_uds_entry(DAY2)])
        # sleepData for DAY2 deliberately NOT created.
    else:
        raise ValueError(f"unknown mode: {mode}")

    return EXPORT_DIR


# ══════════════════════════════════════════════════════════════════════════════
#  Diagnostic run
# ══════════════════════════════════════════════════════════════════════════════

def _read_or_none(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"<file present but unreadable: {e}>"


class _LogCapture(logging.Handler):
    """Collects log records during the run — in particular the
    load_bulk warnings when reading a broken file (_read_dir_json()) and
    any error logs from run_import()."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append({
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        })


def run_bulk_import_scenario(mode: str) -> dict:
    """
    Builds the GDPR export for the given variant, calls load_bulk()
    directly (isolated, no write effect), then run_import() (real
    production path), and observes return values, file state, and
    quality_log — without assessing.
    """
    record = {"mode": mode}

    reset_export_dir()
    build_export(mode)
    record["export_root"] = str(EXPORT_DIR)

    reset_archive_dir()

    log_capture = _LogCapture()
    log_capture.setLevel(logging.DEBUG)
    importer.log.addHandler(log_capture)
    importer.log.setLevel(logging.DEBUG)
    collector.log.addHandler(log_capture)
    collector.log.setLevel(logging.DEBUG)

    # ── step A — load_bulk() directly, isolated from the rest of the pipeline ──
    try:
        loaded_days = list(importer.load_bulk(EXPORT_DIR))
        record["load_bulk_exception"] = None
    except Exception as e:
        loaded_days = []
        record["load_bulk_exception"] = f"{type(e).__name__}: {e}"

    record["loaded_dates"] = [d.get("date") for d in loaded_days]
    record["day2_in_loaded"] = DAY2 in record["loaded_dates"]
    day2_loaded = next((d for d in loaded_days if d.get("date") == DAY2), None)
    record["day2_raw_dict_from_load_bulk"] = day2_loaded
    record["day2_has_user_summary"] = bool(day2_loaded and "user_summary" in day2_loaded)
    record["day2_has_sleep"] = bool(day2_loaded and "sleep" in day2_loaded)
    record["log_records_load_bulk"] = list(log_capture.records)

    # ── step B — real run_import() call (production path) ──
    # Reset the archive again — step A didn't write anything, but a clean
    # starting state for the real run is still mandatory.
    reset_archive_dir()
    log_capture.records.clear()

    try:
        run_result = collector.run_import(str(EXPORT_DIR))
        record["run_import_exception"] = None
    except Exception as e:
        run_result = None
        record["run_import_exception"] = f"{type(e).__name__}: {e}"

    record["run_import_result"] = run_result
    record["log_records_run_import"] = list(log_capture.records)

    importer.log.removeHandler(log_capture)
    collector.log.removeHandler(log_capture)

    # ── file state afterwards ──────────────────────────────────────────────
    for label, d in (("day1", DAY1), ("day2", DAY2), ("day3", DAY3)):
        raw_path = cfg.RAW_DIR / f"garmin_raw_{d}.json"
        summary_path = cfg.SUMMARY_DIR / f"garmin_{d}.json"
        record[f"{label}_raw_exists"] = raw_path.exists()
        record[f"{label}_summary_exists"] = summary_path.exists()
        record[f"{label}_raw_content"] = _read_or_none(raw_path)

    qdata = quality._load_quality_log()
    record["quality_log_days"] = qdata.get("days", [])
    record["quality_log_day1_entry"] = next(
        (e for e in qdata.get("days", []) if e.get("date") == DAY1), None)
    record["quality_log_day2_entry"] = next(
        (e for e in qdata.get("days", []) if e.get("date") == DAY2), None)
    record["quality_log_day3_entry"] = next(
        (e for e in qdata.get("days", []) if e.get("date") == DAY3), None)

    return record


def main():
    print("=" * 65)
    print("  netz2_diagnostics — bulk import diagnosis (broken/missing day)")
    print("=" * 65)
    print(f"  Main repo    : {PROJECT_ROOT}")
    print(f"  Export dir   : {EXPORT_DIR}")
    print(f"  Archive dir  : {ARCHIVE_DIR}")
    print(f"  Report ID    : {NETZ2_REPORT_ID}")
    print()

    results = {}
    for mode in ("corrupt_json", "missing_file"):
        print(f"  --- Scenario: {mode} ---")
        results[mode] = run_bulk_import_scenario(mode)
        r = results[mode]
        print(f"  Day 2 delivered by load_bulk()  : {r['day2_in_loaded']}")
        print(f"  run_import() return value       : {r['run_import_result']}")
        print(f"  Day 2 raw/ written               : {r['day2_raw_exists']}")
        print(f"  quality_log entry day 2          : "
              f"{r['quality_log_day2_entry']}")
        print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md = build_report_md(results)
    OUTPUT_MD.write_text(md, encoding="utf-8")

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


def _scenario_md(mode: str, title: str, r: dict) -> list:
    lines = []
    lines.append(f"## Scenario: {title} (`mode={mode}`)")
    lines.append("")
    lines.append(f"- Export folder: `{r['export_root']}`")
    lines.append(f"- Day 1 (`{DAY1}`) / day 3 (`{DAY3}`): fully valid, unchanged across both scenarios")
    lines.append(f"- Day 2 (`{DAY2}`): target day of this variant")
    lines.append("")

    lines.append("### Step A — `load_bulk()` directly (isolated, no write effect)")
    lines.append("")
    lines.append(f"- Exception during `load_bulk()` consumption: {_json_block(r['load_bulk_exception'])}")
    lines.append(f"- Delivered days (`date` values): {_json_block(r['loaded_dates'])}")
    lines.append(f"- Day 2 included in delivered days: **{r['day2_in_loaded']}**")
    lines.append(f"- Day 2 has `user_summary` key: **{r['day2_has_user_summary']}**")
    lines.append(f"- Day 2 has `sleep` key: **{r['day2_has_sleep']}**")
    lines.append("")
    lines.append("**Day 2 — raw dict as delivered by `load_bulk()`:**")
    lines.append("")
    lines.append(_json_block(r["day2_raw_dict_from_load_bulk"]))
    lines.append("")
    lines.append("**Log output during `load_bulk()`:**")
    lines.append("")
    lines.append(_json_block(r["log_records_load_bulk"]))
    lines.append("")

    lines.append("### Step B — `run_import()` (real production path, archive freshly reset)")
    lines.append("")
    lines.append(f"- Exception during `run_import()`: {_json_block(r['run_import_exception'])}")
    lines.append(f"- Return value `run_import()`: {_json_block(r['run_import_result'])}")
    lines.append("")
    lines.append("**Log output during `run_import()`:**")
    lines.append("")
    lines.append(_json_block(r["log_records_run_import"]))
    lines.append("")

    lines.append("### File state after `run_import()`")
    lines.append("")
    lines.append("| Day | raw/ present | summary/ present |")
    lines.append("|---|---|---|")
    for label, key, d in (("Day 1", "day1", DAY1), ("Day 2", "day2", DAY2), ("Day 3", "day3", DAY3)):
        lines.append(f"| `{d}` | {r[f'{key}_raw_exists']} | {r[f'{key}_summary_exists']} |")
    lines.append("")
    lines.append("**Day 1 — raw/ content:**")
    lines.append("")
    lines.append(_json_block(r["day1_raw_content"]))
    lines.append("")
    lines.append("**Day 2 — raw/ content:**")
    lines.append("")
    lines.append(_json_block(r["day2_raw_content"]))
    lines.append("")
    lines.append("**Day 3 — raw/ content:**")
    lines.append("")
    lines.append(_json_block(r["day3_raw_content"]))
    lines.append("")

    lines.append("### quality_log.json after `run_import()`")
    lines.append("")
    lines.append("**All entries:**")
    lines.append("")
    lines.append(_json_block(r["quality_log_days"]))
    lines.append("")
    lines.append(f"**Day 1 entry:** {_json_block(r['quality_log_day1_entry'])}")
    lines.append("")
    lines.append(f"**Day 2 entry:** {_json_block(r['quality_log_day2_entry'])}")
    lines.append("")
    lines.append(f"**Day 3 entry:** {_json_block(r['quality_log_day3_entry'])}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def build_report_md(results: dict) -> str:
    lines = []
    lines.append(f"# NETZ2_BEFUND_bulk_import_{NETZ2_REPORT_ID}.md")
    lines.append("")
    lines.append("Pure observation — no assert, no assessment. "
                  "Assessment follows together with the other priority findings.")
    lines.append("")
    lines.append(f"Main repo: `{PROJECT_ROOT}`")
    lines.append(f"Export dir (write target for fixtures, then read-only): `{EXPORT_DIR}`")
    lines.append(f"Archive dir (write target of run_import()): `{ARCHIVE_DIR}`")
    lines.append("")
    lines.append("Both scenarios run one after another against the same "
                  "(physically reset between scenarios) archive folder — no "
                  "`GARMIN_OUTPUT_DIR` switch/`cfg` reload, see script docstring.")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.extend(_scenario_md(
        "corrupt_json",
        "UDSFile for day 2 present, but invalid JSON (sleepData day 2 intact)",
        results["corrupt_json"],
    ))
    lines.extend(_scenario_md(
        "missing_file",
        "sleepData for day 2 completely missing (UDSFile day 2 intact)",
        results["missing_file"],
    ))

    return "\n".join(lines)


if __name__ == "__main__":
    main()
