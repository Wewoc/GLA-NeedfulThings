#!/usr/bin/env python3
"""
netz2_diagnostics/run_netz2_steps_async.py

Diagnostic harness for Net 2, priority 2 point 1 — persistent silo-async
state in _run_steps_backfill() when patch_source_field() keeps failing
even after the built-in retry.

Standalone script, deliberately not integrated into run_netz2.py:
  - different core mechanism (_run_steps_backfill() instead of
    repair_silos()) — no unified dict return, only side effects on
    raw/source/quality_log.json + log output
  - additional second run against garmin_app_controller.
    timer_run_steps_backfill() (real candidate filter, no mock)
  - run_netz2.py has already produced a verified report — stays completely
    untouched, no regression risk

Pure observation. No assert. No changes to the main repo — this script
only imports garmin_collector/garmin_app_controller etc. read-only/call-only.

IMPORTANT — write target:
  Own isolated folder (DIAGNOSE_DIR below), separate from run_netz2.py's
  diagnose_tmp/, so the two diagnostic runs don't overwrite each other's
  state. Fixture CONTENT (raw/) is derived from a real raw/ file in your
  archive (read-only access); the source/ file is deliberately created
  corrupt, exclusively for this script (see build_initial_raw() / run
  setup below).

IMPORTANT — patch_source_field() failure:
  A MISSING source/ file leads to a deliberate no-op in
  patch_source_field() (return True — "can only enrich, never
  originate"). That doesn't produce an error case. This script instead
  creates a PRESENT but deliberately invalid JSON file — this specifically
  hits the except (json.JSONDecodeError, OSError) path in
  garmin_source_writer.patch_source_field(), deterministic and
  platform-independent.

IMPORTANT — report numbering:
  This script is started via run_netz2_all.bat, not directly. The .bat
  assigns the running report number (folder output/vXXXX_NN/) and sets
  NETZ2_REPORT_ID before the call — no manually maintained
  REPORT_ID_STEPS_ASYNC value in netz2_config.py anymore.

Run via:
    run_netz2_all.bat (sets NETZ2_REPORT_ID + starts all run_netz2*.py
    scripts in sequence).

Result:
    netz2_diagnostics/output/<NETZ2_REPORT_ID>/NETZ2_BEFUND_steps_async.md
"""

import importlib
import json
import logging
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

# ══════════════════════════════════════════════════════════════════════════════
#  Configuration — from netz2_config.py + NETZ2_REPORT_ID from the
#  environment (set by run_netz2_all.bat)
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent

try:
    from netz2_config import PROJECT_ROOT_REL, REAL_ARCHIVE_BASE_DIR
except ImportError:
    print("✗  netz2_config.py missing next to run_netz2_steps_async.py.")
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

# Own isolated folder — separate from run_netz2.py's diagnose_tmp/.
DIAGNOSE_DIR = SCRIPT_DIR / "diagnose_tmp_steps_async"

OUTPUT_DIR = SCRIPT_DIR / "output" / NETZ2_REPORT_ID
OUTPUT_MD = OUTPUT_DIR / "NETZ2_BEFUND_steps_async.md"

TARGET_DATE = "2025-02-10"
STEPS_STUB = [{"startGMT": f"{TARGET_DATE}T08:00:00", "steps": 42}]

# ══════════════════════════════════════════════════════════════════════════════
#  Path setup — import the core modules directly from the main repo
#  (garmin/ AND app/ — timer_run_steps_backfill() lives in app/)
# ══════════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = (SCRIPT_DIR / PROJECT_ROOT_REL).resolve()
GARMIN_SRC_DIR = PROJECT_ROOT / "src" / "garmin"
APP_SRC_DIR = PROJECT_ROOT / "src" / "app"

if not GARMIN_SRC_DIR.is_dir():
    print(f"✗  Main repo source folder not found: {GARMIN_SRC_DIR}")
    print(f"   Check PROJECT_ROOT_REL (currently: '{PROJECT_ROOT_REL}')")
    sys.exit(1)
if not APP_SRC_DIR.is_dir():
    print(f"✗  Main repo app folder not found: {APP_SRC_DIR}")
    sys.exit(1)

sys.path.insert(0, str(GARMIN_SRC_DIR))
sys.path.insert(0, str(APP_SRC_DIR))

# GARMIN_OUTPUT_DIR MUST be set before garmin_config is imported for the
# first time (it reads BASE_DIR from the env at import time).
os.environ["GARMIN_OUTPUT_DIR"] = str(DIAGNOSE_DIR)

import garmin_config as cfg  # noqa: E402
import garmin_normalizer as normalizer  # noqa: E402
import garmin_quality as quality  # noqa: E402
import garmin_writer as writer  # noqa: E402
import garmin_collector as collector_bf  # noqa: E402
import garmin_app_controller as controller  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
#  Fixture setup
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
    names."""
    if _depth > 6:
        return obj
    if isinstance(obj, list):
        trimmed = obj[:max_items]
        return [_trim_lists(x, max_items, _depth + 1) for x in trimmed]
    if isinstance(obj, dict):
        return {k: _trim_lists(v, max_items, _depth + 1) for k, v in obj.items()}
    return obj


def build_initial_raw(real_archive_base: Path, target_date: str) -> dict | None:
    """
    Minimally valid starting state for the target day: real raw/ file as
    template (structure copied, lists trimmed), 'steps' explicitly removed
    if present in the template — that's the candidate condition for the
    steps backfill (no 'steps' in fields).
    """
    src_file = _find_real_raw_file(real_archive_base)
    if src_file is None:
        return None
    real = json.loads(src_file.read_text(encoding="utf-8"))
    fixture = _trim_lists(real, max_items=3)
    fixture["date"] = target_date
    fixture.pop("steps", None)
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


class _LogCapture(logging.Handler):
    """Collects log records during the run — observes whether log.error()
    actually occurs after retry exhaustion (not just claimed)."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append({"level": record.levelname, "message": record.getMessage()})


def run_steps_async_scenario(target_date: str) -> dict:
    """
    Builds the starting state (raw/ + deliberately corrupt source/ file +
    in-memory quality_data), calls _run_steps_backfill() FOR REAL (only
    api.api_call is mocked — a boundary, not the core function itself),
    observes raw/source/quality_log state + log output afterwards, then a
    second run against the real controller candidate filter.
    """
    record = {"target_date": target_date}

    initial_raw = build_initial_raw(REAL_ARCHIVE_BASE_DIR, target_date)
    if initial_raw is None:
        record["skipped"] = True
        record["skip_reason"] = (
            "no real raw/ file found in the real archive — "
            "check REAL_ARCHIVE_BASE_DIR"
        )
        return record
    record["skipped"] = False
    record["initial_raw"] = initial_raw

    # ── write starting state raw/ + summary/ (like main()'s normal fetch
    #    path: normalize() → summarize() → write_day()) ────────────────────
    normalized_initial = normalizer.normalize(initial_raw, source="api")
    summary_initial = normalizer.summarize(normalized_initial)
    writer.write_day(normalized_initial, summary_initial, target_date)

    # ── deliberately create a corrupt source/ file — present, but invalid
    #    JSON, see module docstring above for the reasoning ────────────────
    source_path = cfg.SOURCE_DIR / f"garmin_source_{target_date}.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("{ this is deliberately not valid json",
                            encoding="utf-8")
    record["source_fixture_corrupted"] = True
    record["source_fixture_path"] = str(source_path)

    quality_data = {
        "first_day": target_date,
        "devices": [],
        "days": [{
            "date": target_date, "source": "api", "quality": "high",
            "fields": {"heart_rates": "high"}, "attempts": 0, "recheck": False,
        }],
    }
    record["quality_data_before"] = json.loads(json.dumps(quality_data))

    # ── set GARMIN_SYNC_DATES + reload cfg (_run_steps_backfill() reads
    #    cfg.SYNC_DATES, not the passed-in candidates directly) ────────────
    os.environ["GARMIN_SYNC_DATES"] = target_date
    importlib.reload(cfg)

    log_capture = _LogCapture()
    log_capture.setLevel(logging.DEBUG)
    collector_bf.log.addHandler(log_capture)
    collector_bf.log.setLevel(logging.DEBUG)

    # ── real call to _run_steps_backfill() — only api.api_call is mocked ──
    try:
        with patch.object(collector_bf.api, "api_call",
                          return_value=(STEPS_STUB, True)) as mock_api_call:
            collector_bf._run_steps_backfill(object(), quality_data)
        record["api_call_count"] = mock_api_call.call_count
        record["run_exception"] = None
    except Exception as e:
        record["api_call_count"] = None
        record["run_exception"] = f"{type(e).__name__}: {e}"
    finally:
        collector_bf.log.removeHandler(log_capture)
        os.environ.pop("GARMIN_SYNC_DATES", None)
        importlib.reload(cfg)

    record["log_records"] = log_capture.records
    record["log_has_error_after_retry"] = any(
        r["level"] == "ERROR" and "source/ patch failed after retry" in r["message"]
        for r in log_capture.records
    )

    # ── file state afterwards ──────────────────────────────────────────────
    raw_path = cfg.RAW_DIR / f"garmin_raw_{target_date}.json"
    record["raw_after"] = _read_or_none(raw_path)
    record["source_after_raw_text"] = (
        source_path.read_text(encoding="utf-8") if source_path.exists() else None
    )

    qdata_after = quality._load_quality_log()
    qentry_after = next(
        (e for e in qdata_after.get("days", []) if e.get("date") == target_date),
        None,
    )
    record["quality_log_entry_after_run1"] = qentry_after

    # ── second run: real controller candidate filter (simulates "next
    #    timer pass") ──────────────────────────────────────────────────────
    controller_state = {"base_dir": str(DIAGNOSE_DIR)}
    candidates_run2 = controller.timer_run_steps_backfill(controller_state)
    record["controller_candidates_after_run1"] = (
        [d.isoformat() for d in candidates_run2] if candidates_run2 else None
    )
    record["target_date_still_candidate"] = (
        candidates_run2 is not None
        and date.fromisoformat(target_date) in candidates_run2
    )

    return record


def main():
    print("=" * 65)
    print("  netz2_diagnostics — steps-backfill silo-async diagnosis")
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

    result = run_steps_async_scenario(TARGET_DATE)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md = build_report_md(result)
    OUTPUT_MD.write_text(md, encoding="utf-8")

    print()
    if result.get("skipped"):
        print(f"  skipped: {result['skip_reason']}")
    else:
        print(f"  Target date                     : {result['target_date']}")
        print(f"  api_call() calls                : {result['api_call_count']}")
        print(f"  'steps' in raw/ afterwards      : "
              f"{'steps' in (result['raw_after'] or {})}")
        print(f"  log.error() after retry occurred: "
              f"{result['log_has_error_after_retry']}")
        print(f"  Target date still controller candidate: "
              f"{result['target_date_still_candidate']}")
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


def build_report_md(result: dict) -> str:
    lines = []
    lines.append(f"# NETZ2_BEFUND_steps_async_{NETZ2_REPORT_ID}.md")
    lines.append("")
    lines.append("Pure observation — no assert, no assessment. "
                  "Assessment follows in the analysis chat.")
    lines.append("")
    lines.append(f"Main repo: `{PROJECT_ROOT}`")
    lines.append(f"Diagnose dir (write target of this run): `{DIAGNOSE_DIR}`")
    lines.append(f"Fixture source raw/ (read-only): `{REAL_ARCHIVE_BASE_DIR}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Scenario: steps backfill, persistent silo-async state")
    lines.append("")
    lines.append(f"- Target date: `{result['target_date']}`")

    if result.get("skipped"):
        lines.append(f"- **Skipped:** {result['skip_reason']}")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"- source/ fixture deliberately created corrupt: "
                  f"`{result['source_fixture_path']}`")
    lines.append("")

    lines.append("### Starting state — raw/ (derived from a real file, trimmed)")
    lines.append("")
    lines.append(_json_block(result["initial_raw"]))
    lines.append("")

    lines.append("### Starting state — quality_data (in-memory, before the run)")
    lines.append("")
    lines.append(_json_block(result["quality_data_before"]))
    lines.append("")

    lines.append("### Run 1 — _run_steps_backfill() real call")
    lines.append("")
    lines.append(f"- `api.api_call()` calls (mocked API boundary): "
                  f"{result['api_call_count']}")
    if result["run_exception"]:
        lines.append("")
        lines.append("**Uncaught exception (not caught by _run_steps_backfill):**")
        lines.append("")
        lines.append(_json_block(result["run_exception"]))
    lines.append("")

    lines.append("**Log output during the run:**")
    lines.append("")
    lines.append(_json_block(result["log_records"]))
    lines.append("")
    lines.append(f"- `log.error()` with \"source/ patch failed after retry\" "
                  f"occurred: **{result['log_has_error_after_retry']}**")
    lines.append("")

    lines.append("**raw/ file afterwards:**")
    lines.append("")
    lines.append(_json_block(result["raw_after"]))
    lines.append("")

    lines.append("**source/ file afterwards (raw text — deliberately corrupt, not valid JSON):**")
    lines.append("")
    lines.append(_json_block(result["source_after_raw_text"]))
    lines.append("")

    lines.append("**quality_log.json entry afterwards:**")
    lines.append("")
    lines.append(_json_block(result["quality_log_entry_after_run1"]))
    lines.append("")

    lines.append("### Run 2 — real controller candidate filter "
                  "(garmin_app_controller.timer_run_steps_backfill)")
    lines.append("")
    lines.append(f"- Candidate list after run 1: "
                  f"{result['controller_candidates_after_run1']}")
    lines.append(f"- Target date `{result['target_date']}` still in candidate list: "
                  f"**{result['target_date_still_candidate']}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
