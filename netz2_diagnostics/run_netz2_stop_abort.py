#!/usr/bin/env python3
"""
netz2_diagnostics/run_netz2_stop_abort.py

Diagnostic harness for Net 2, priority 2 point 2 — abort in the middle of
the steps/source backfill loop (CONCEPT finding F4: stop-event abort is
not an edge case, it's a mandatory test case for every class-I action).

Core finding before the build (analysis chat):
  _is_stopped() is checked in _run_steps_backfill() AND
  _run_source_backfill() at the START of every iteration — BEFORE the
  entire day block (fetch → write → record_attempt() →
  patch_source_field()). There is no mid-day check. A "half-written day"
  cannot structurally arise via the stop path — only day atomicity
  (a day runs through completely, or it's never started at all).

  To actually test "stop after day 1, before day 2", the stop event is set
  as a side effect of the mocked API boundary call for day 1, not day 2:
  day 1's own _is_stopped() check is already behind it at that point (so
  it runs through normally), only the iteration start for day 2 sees the
  set event and aborts BEFORE any touch (no read_raw()/fetch_raw(), no
  write, no record_attempt()).

Two scenarios in this script — same mechanism, different API boundary:
  - Steps backfill:  boundary is api.api_call()  (one call per day)
  - Source backfill: boundary is api.fetch_raw() (inside _fetch_and_assess())

Pure observation. No assert. No changes to the main repo — this script
only imports garmin_collector/garmin_app_controller etc. read-only/call-only.

IMPORTANT — write target:
  Own isolated folder (DIAGNOSE_DIR below), separate from run_netz2.py's
  diagnose_tmp/ and run_netz2_steps_async.py's diagnose_tmp_steps_async/.
  Between the two scenarios in this script, the same folder is cleared and
  rebuilt (reset_diagnose_dir()) — they run one after another, not in
  parallel, no state carries over.

IMPORTANT — report numbering:
  This script is started via run_netz2_all.bat, not directly. The .bat
  assigns the running report number (folder output/vXXXX_NN/) and sets
  NETZ2_REPORT_ID before the call.

Run via:
    run_netz2_all.bat (sets NETZ2_REPORT_ID + starts all run_netz2*.py
    scripts in sequence).

Result:
    netz2_diagnostics/output/<NETZ2_REPORT_ID>/NETZ2_BEFUND_stop_abort.md
"""

import importlib
import json
import logging
import os
import shutil
import sys
import threading
from datetime import date, timedelta
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
    print("✗  netz2_config.py missing next to run_netz2_stop_abort.py.")
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

# Own isolated folder — separate from the other run_netz2* scripts.
DIAGNOSE_DIR = SCRIPT_DIR / "diagnose_tmp_stop_abort"

OUTPUT_DIR = SCRIPT_DIR / "output" / NETZ2_REPORT_ID
OUTPUT_MD = OUTPUT_DIR / "NETZ2_BEFUND_stop_abort.md"

# 4 candidate days — enough to clearly distinguish day 1 (before stop) /
# day 2 (abort point) / day 3+ (never reached). Within both candidate
# windows (steps ≤140 days, source ≤180 days).
CANDIDATE_COUNT = 4
_BASE_OFFSET = 120  # days into the past — outside other diagnostic fixtures
CANDIDATE_DATES = sorted(
    (date.today() - timedelta(days=_BASE_OFFSET + i)).isoformat()
    for i in range(CANDIDATE_COUNT)
)

STEPS_STUB = [{"startGMT": "2000-01-01T08:00:00", "steps": 42}]

# ══════════════════════════════════════════════════════════════════════════════
#  Path setup — import the core modules directly from the main repo
#  (garmin/ AND app/ — timer_run_*_backfill() lives in app/)
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
import garmin_source_writer as source_writer  # noqa: E402
import garmin_collector as collector_bf  # noqa: E402
import garmin_app_controller as controller  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
#  Fixture setup (pattern taken from run_netz2_steps_async.py)
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


def _load_template(real_archive_base: Path) -> dict | None:
    src_file = _find_real_raw_file(real_archive_base)
    if src_file is None:
        return None
    return json.loads(src_file.read_text(encoding="utf-8"))


def _build_raw_fixture(template: dict, target_date: str, drop_steps: bool) -> dict:
    """Starting state for a target day: real raw/ file as template
    (structure copied, lists trimmed). drop_steps=True explicitly removes
    'steps' — candidate condition for the steps backfill."""
    fixture = _trim_lists(template, max_items=3)
    fixture["date"] = target_date
    if drop_steps:
        fixture.pop("steps", None)
    return fixture


def _read_or_none(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"<file present but unreadable: {e}>"


class _LogCapture(logging.Handler):
    """Collects log records during the run — observes what's actually
    logged (not just claimed)."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append({"level": record.levelname, "message": record.getMessage()})


def reset_diagnose_dir():
    if DIAGNOSE_DIR.exists():
        shutil.rmtree(DIAGNOSE_DIR)
    for sub in ("raw", "summary", "source", "log"):
        (DIAGNOSE_DIR / "garmin_data" / sub).mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Scenario 1 — steps backfill, abort after day 1 / before day 2
#  API boundary: api.api_call()
# ══════════════════════════════════════════════════════════════════════════════

def run_steps_backfill_abort_scenario(template: dict) -> dict:
    """
    Builds CANDIDATE_COUNT candidate days (raw/ + source/ present, 'steps'
    missing — real candidate condition of timer_run_steps_backfill()),
    calls _run_steps_backfill() FOR REAL. Stop event is set as a side
    effect of the mocked api.api_call() for CANDIDATE_DATES[0] (see module
    docstring — day 1 runs through normally as a result, only day 2 aborts).
    """
    record = {"candidate_dates": CANDIDATE_DATES}

    for d in CANDIDATE_DATES:
        raw_fixture = _build_raw_fixture(template, d, drop_steps=True)
        normalized = normalizer.normalize(raw_fixture, source="api")
        summary = normalizer.summarize(normalized)
        writer.write_day(normalized, summary, d)
        source_writer.write_source(raw_fixture, d)

    record["raw_before"] = {
        d: _read_or_none(cfg.RAW_DIR / f"garmin_raw_{d}.json") for d in CANDIDATE_DATES
    }
    record["source_before"] = {
        d: _read_or_none(cfg.SOURCE_DIR / f"garmin_source_{d}.json") for d in CANDIDATE_DATES
    }

    quality_data = {
        "first_day": CANDIDATE_DATES[0],
        "devices": [],
        "days": [
            {"date": d, "source": "api", "quality": "high",
             "fields": {"heart_rates": "high"}, "attempts": 0, "recheck": False}
            for d in CANDIDATE_DATES
        ],
    }

    stop_event = threading.Event()
    collector_bf.set_stop_event(stop_event)

    def _api_call_side_effect(client, method, date_str, label=None):
        if date_str == CANDIDATE_DATES[0]:
            stop_event.set()
        return (STEPS_STUB, True)

    os.environ["GARMIN_SYNC_DATES"] = ",".join(CANDIDATE_DATES)
    importlib.reload(cfg)

    log_capture = _LogCapture()
    log_capture.setLevel(logging.DEBUG)
    collector_bf.log.addHandler(log_capture)
    collector_bf.log.setLevel(logging.DEBUG)

    try:
        with patch.object(collector_bf.api, "api_call",
                          side_effect=_api_call_side_effect) as mock_call:
            collector_bf._run_steps_backfill(object(), quality_data)
        record["api_call_count"] = mock_call.call_count
        record["run_exception"] = None
    except Exception as e:
        record["api_call_count"] = None
        record["run_exception"] = f"{type(e).__name__}: {e}"
    finally:
        collector_bf.log.removeHandler(log_capture)
        collector_bf.set_stop_event(None)
        os.environ.pop("GARMIN_SYNC_DATES", None)
        importlib.reload(cfg)

    record["log_records"] = log_capture.records

    record["raw_after_run1"] = {
        d: _read_or_none(cfg.RAW_DIR / f"garmin_raw_{d}.json") for d in CANDIDATE_DATES
    }
    record["source_after_run1"] = {
        d: _read_or_none(cfg.SOURCE_DIR / f"garmin_source_{d}.json") for d in CANDIDATE_DATES
    }
    qdata_after = quality._load_quality_log()
    record["quality_log_valid_after_run1"] = isinstance(qdata_after, dict) and "days" in qdata_after
    record["quality_log_entries_after_run1"] = {
        d: next((e for e in qdata_after.get("days", []) if e.get("date") == d), None)
        for d in CANDIDATE_DATES
    }

    record["per_day_summary"] = {}
    for i, d in enumerate(CANDIDATE_DATES):
        raw_has_steps = "steps" in (record["raw_after_run1"].get(d) or {})
        q_entry = record["quality_log_entries_after_run1"].get(d)
        record["per_day_summary"][d] = {
            "position": i + 1,
            "raw_has_steps_after": raw_has_steps,
            "quality_log_entry_present": q_entry is not None,
        }

    # ── run 2 — undisturbed, real controller candidate filter ────────────
    controller_state = {"base_dir": str(DIAGNOSE_DIR)}
    candidates_run2 = controller.timer_run_steps_backfill(controller_state)
    record["controller_candidates_before_run2"] = (
        sorted(dd.isoformat() for dd in candidates_run2) if candidates_run2 else None
    )

    if candidates_run2:
        sync_dates_run2 = ",".join(sorted(dd.isoformat() for dd in candidates_run2))
        os.environ["GARMIN_SYNC_DATES"] = sync_dates_run2
        importlib.reload(cfg)
        try:
            with patch.object(collector_bf.api, "api_call",
                              return_value=(STEPS_STUB, True)) as mock_call2:
                collector_bf._run_steps_backfill(object(), quality_data)
            record["run2_api_call_count"] = mock_call2.call_count
            record["run2_exception"] = None
        except Exception as e:
            record["run2_api_call_count"] = None
            record["run2_exception"] = f"{type(e).__name__}: {e}"
        finally:
            os.environ.pop("GARMIN_SYNC_DATES", None)
            importlib.reload(cfg)
    else:
        record["run2_api_call_count"] = None
        record["run2_exception"] = None

    record["raw_after_run2"] = {
        d: _read_or_none(cfg.RAW_DIR / f"garmin_raw_{d}.json") for d in CANDIDATE_DATES
    }
    candidates_after_run2 = controller.timer_run_steps_backfill(controller_state)
    record["controller_candidates_after_run2"] = (
        sorted(dd.isoformat() for dd in candidates_after_run2) if candidates_after_run2 else None
    )

    return record


# ══════════════════════════════════════════════════════════════════════════════
#  Scenario 2 — source backfill, abort after day 1 / before day 2
#  API boundary: api.fetch_raw() (inside _fetch_and_assess())
# ══════════════════════════════════════════════════════════════════════════════

def run_source_backfill_abort_scenario(template: dict) -> dict:
    """
    Analogous to scenario 1, but for _run_source_backfill(). Candidate
    condition per timer_run_source_backfill(): raw/+summary/ present,
    source/ MISSING. Mock boundary is api.fetch_raw() instead of
    api.api_call() — the only structural difference from scenario 1, same
    stop logic/placement in the collector.
    """
    record = {"candidate_dates": CANDIDATE_DATES}

    # raw/summary present, source/ deliberately NOT created (candidate condition).
    for d in CANDIDATE_DATES:
        raw_fixture = _build_raw_fixture(template, d, drop_steps=False)
        normalized = normalizer.normalize(raw_fixture, source="api")
        summary = normalizer.summarize(normalized)
        writer.write_day(normalized, summary, d)

    record["raw_before"] = {
        d: _read_or_none(cfg.RAW_DIR / f"garmin_raw_{d}.json") for d in CANDIDATE_DATES
    }
    record["source_before"] = {
        d: _read_or_none(cfg.SOURCE_DIR / f"garmin_source_{d}.json") for d in CANDIDATE_DATES
    }

    quality_data = {
        "first_day": CANDIDATE_DATES[0],
        "devices": [],
        "days": [
            {"date": d, "source": "api", "quality": "high",
             "fields": {"heart_rates": "high"}, "attempts": 0, "recheck": False}
            for d in CANDIDATE_DATES
        ],
    }

    stop_event = threading.Event()
    collector_bf.set_stop_event(stop_event)

    def _fetch_raw_side_effect(client, date_str):
        raw_fixture = _build_raw_fixture(template, date_str, drop_steps=False)
        if date_str == CANDIDATE_DATES[0]:
            stop_event.set()
        return (raw_fixture, [])

    os.environ["GARMIN_SYNC_DATES"] = ",".join(CANDIDATE_DATES)
    importlib.reload(cfg)

    log_capture = _LogCapture()
    log_capture.setLevel(logging.DEBUG)
    collector_bf.log.addHandler(log_capture)
    collector_bf.log.setLevel(logging.DEBUG)

    try:
        with patch.object(collector_bf.api, "fetch_raw",
                          side_effect=_fetch_raw_side_effect) as mock_fetch:
            collector_bf._run_source_backfill(object(), quality_data)
        record["fetch_raw_call_count"] = mock_fetch.call_count
        record["run_exception"] = None
    except Exception as e:
        record["fetch_raw_call_count"] = None
        record["run_exception"] = f"{type(e).__name__}: {e}"
    finally:
        collector_bf.log.removeHandler(log_capture)
        collector_bf.set_stop_event(None)
        os.environ.pop("GARMIN_SYNC_DATES", None)
        importlib.reload(cfg)

    record["log_records"] = log_capture.records

    record["raw_after_run1"] = {
        d: _read_or_none(cfg.RAW_DIR / f"garmin_raw_{d}.json") for d in CANDIDATE_DATES
    }
    record["source_after_run1"] = {
        d: _read_or_none(cfg.SOURCE_DIR / f"garmin_source_{d}.json") for d in CANDIDATE_DATES
    }
    qdata_after = quality._load_quality_log()
    record["quality_log_valid_after_run1"] = isinstance(qdata_after, dict) and "days" in qdata_after
    record["quality_log_entries_after_run1"] = {
        d: next((e for e in qdata_after.get("days", []) if e.get("date") == d), None)
        for d in CANDIDATE_DATES
    }

    record["per_day_summary"] = {}
    for i, d in enumerate(CANDIDATE_DATES):
        source_written = record["source_after_run1"].get(d) is not None
        q_entry = record["quality_log_entries_after_run1"].get(d)
        record["per_day_summary"][d] = {
            "position": i + 1,
            "source_written_after": source_written,
            "quality_log_entry_present": q_entry is not None,
        }

    # ── run 2 — undisturbed, real controller candidate filter ────────────
    controller_state = {"base_dir": str(DIAGNOSE_DIR)}
    candidates_run2 = controller.timer_run_source_backfill(controller_state)
    record["controller_candidates_before_run2"] = (
        sorted(dd.isoformat() for dd in candidates_run2) if candidates_run2 else None
    )

    if candidates_run2:
        sync_dates_run2 = ",".join(sorted(dd.isoformat() for dd in candidates_run2))
        os.environ["GARMIN_SYNC_DATES"] = sync_dates_run2
        importlib.reload(cfg)

        def _fetch_raw_run2(client, date_str):
            return (_build_raw_fixture(template, date_str, drop_steps=False), [])

        try:
            with patch.object(collector_bf.api, "fetch_raw",
                              side_effect=_fetch_raw_run2) as mock_fetch2:
                collector_bf._run_source_backfill(object(), quality_data)
            record["run2_fetch_raw_call_count"] = mock_fetch2.call_count
            record["run2_exception"] = None
        except Exception as e:
            record["run2_fetch_raw_call_count"] = None
            record["run2_exception"] = f"{type(e).__name__}: {e}"
        finally:
            os.environ.pop("GARMIN_SYNC_DATES", None)
            importlib.reload(cfg)
    else:
        record["run2_fetch_raw_call_count"] = None
        record["run2_exception"] = None

    record["source_after_run2"] = {
        d: _read_or_none(cfg.SOURCE_DIR / f"garmin_source_{d}.json") for d in CANDIDATE_DATES
    }
    candidates_after_run2 = controller.timer_run_source_backfill(controller_state)
    record["controller_candidates_after_run2"] = (
        sorted(dd.isoformat() for dd in candidates_after_run2) if candidates_after_run2 else None
    )

    return record


# ══════════════════════════════════════════════════════════════════════════════
#  Orchestration
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 65)
    print("  netz2_diagnostics — abort in the middle of the backfill loop")
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

    template = _load_template(REAL_ARCHIVE_BASE_DIR)
    if template is None:
        print("✗  No real raw/ file found in the real archive.")
        sys.exit(1)

    print("  Scenario 1 — steps backfill ...")
    reset_diagnose_dir()
    result_steps = run_steps_backfill_abort_scenario(template)

    print("  Scenario 2 — source backfill ...")
    reset_diagnose_dir()
    result_source = run_source_backfill_abort_scenario(template)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md = build_report_md(result_steps, result_source)
    OUTPUT_MD.write_text(md, encoding="utf-8")

    print()
    print("  Steps backfill:")
    for d, s in result_steps["per_day_summary"].items():
        print(f"    Day {s['position']} ({d}): raw has 'steps' afterwards = "
              f"{s['raw_has_steps_after']}, quality_log entry present = "
              f"{s['quality_log_entry_present']}")
    print(f"    Candidates before run 2: {result_steps['controller_candidates_before_run2']}")
    print(f"    Candidates after run 2 : {result_steps['controller_candidates_after_run2']}")
    print()
    print("  Source backfill:")
    for d, s in result_source["per_day_summary"].items():
        print(f"    Day {s['position']} ({d}): source/ written afterwards = "
              f"{s['source_written_after']}, quality_log entry present = "
              f"{s['quality_log_entry_present']}")
    print(f"    Candidates before run 2: {result_source['controller_candidates_before_run2']}")
    print(f"    Candidates after run 2 : {result_source['controller_candidates_after_run2']}")
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


def _scenario_section(title: str, result: dict, api_boundary: str,
                      call_count_key: str, run2_call_count_key: str,
                      after_key: str, run2_after_key: str,
                      presence_field: str, presence_label: str) -> list[str]:
    lines = []
    lines.append(f"## {title}")
    lines.append("")
    lines.append(f"API boundary (mocked): `{api_boundary}`")
    lines.append("")
    lines.append(f"Candidate days (oldest first): {result['candidate_dates']}")
    lines.append("")
    lines.append(f"- `{api_boundary}` calls in run 1: {result[call_count_key]}")
    if result["run_exception"]:
        lines.append("")
        lines.append("**Uncaught exception in run 1 (not caught):**")
        lines.append("")
        lines.append(_json_block(result["run_exception"]))
    lines.append("")
    lines.append(f"- `quality_log.json` structurally valid after run 1: "
                  f"**{result['quality_log_valid_after_run1']}**")
    lines.append("")

    lines.append("### Per day — result after run 1 (abort)")
    lines.append("")
    lines.append(f"| Position | Date | {presence_label} | quality_log entry present |")
    lines.append("|---|---|---|---|")
    for d, s in result["per_day_summary"].items():
        lines.append(f"| {s['position']} | {d} | {s[presence_field]} | "
                      f"{s['quality_log_entry_present']} |")
    lines.append("")

    lines.append("**Log output during run 1:**")
    lines.append("")
    lines.append(_json_block(result["log_records"]))
    lines.append("")

    lines.append("### Raw data after run 1 (abort)")
    lines.append("")
    lines.append("**raw/ before (starting state):**")
    lines.append("")
    lines.append(_json_block(result["raw_before"]))
    lines.append("")
    lines.append(f"**{after_key} (after the abort):**")
    lines.append("")
    lines.append(_json_block(result[after_key]))
    lines.append("")
    lines.append("**quality_log entries after the abort:**")
    lines.append("")
    lines.append(_json_block(result["quality_log_entries_after_run1"]))
    lines.append("")

    lines.append("### Run 2 — undisturbed, real controller candidate filter")
    lines.append("")
    lines.append(f"- Candidate list before run 2: {result['controller_candidates_before_run2']}")
    lines.append(f"- `{api_boundary}` calls in run 2: {result[run2_call_count_key]}")
    if result.get("run2_exception"):
        lines.append("")
        lines.append("**Uncaught exception in run 2:**")
        lines.append("")
        lines.append(_json_block(result["run2_exception"]))
    lines.append("")
    lines.append(f"**{run2_after_key} (after run 2):**")
    lines.append("")
    lines.append(_json_block(result[run2_after_key]))
    lines.append("")
    lines.append(f"- Candidate list after run 2: {result['controller_candidates_after_run2']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def build_report_md(result_steps: dict, result_source: dict) -> str:
    lines = []
    lines.append(f"# NETZ2_BEFUND_stop_abort_{NETZ2_REPORT_ID}.md")
    lines.append("")
    lines.append("Pure observation — no assert, no assessment. "
                  "Assessment follows in the analysis chat.")
    lines.append("")
    lines.append(f"Main repo: `{PROJECT_ROOT}`")
    lines.append(f"Diagnose dir (write target, cleared between scenarios): `{DIAGNOSE_DIR}`")
    lines.append(f"Fixture source raw/ (read-only): `{REAL_ARCHIVE_BASE_DIR}`")
    lines.append("")
    lines.append("**Mechanism:** the stop event is set as a side effect of the mocked "
                  "API boundary call for day 1 (CANDIDATE_DATES[0]) — day 1's "
                  "own `_is_stopped()` check is already behind that point, so "
                  "it runs through normally. Only the iteration start for "
                  "day 2 sees the set event and aborts before it.")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.extend(_scenario_section(
        title="Scenario 1 — steps backfill",
        result=result_steps,
        api_boundary="api.api_call",
        call_count_key="api_call_count",
        run2_call_count_key="run2_api_call_count",
        after_key="raw_after_run1",
        run2_after_key="raw_after_run2",
        presence_field="raw_has_steps_after",
        presence_label="'steps' in raw/ afterwards",
    ))

    lines.extend(_scenario_section(
        title="Scenario 2 — source backfill",
        result=result_source,
        api_boundary="api.fetch_raw",
        call_count_key="fetch_raw_call_count",
        run2_call_count_key="run2_fetch_raw_call_count",
        after_key="source_after_run1",
        run2_after_key="source_after_run2",
        presence_field="source_written_after",
        presence_label="source/ written afterwards",
    ))

    return "\n".join(lines)


if __name__ == "__main__":
    main()
