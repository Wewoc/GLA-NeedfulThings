#!/usr/bin/env python3
"""
netz2_diagnostics/run_netz2_restore_staleness.py

Diagnostic harness for Net 2, priority 3 — restore-data staleness window.

Backend functions (check_raw_integrity(), restore_raw_days()) are already
solidly tested (test_local.py) — the Net-2-relevant point isn't there, but
in the interplay with app/panel_archive.py: _refresh_archive_info()/
_startup_integrity_check() determines missing/no_backup ONCE and passes
them as closure values to the restore button
(command=lambda: self._on_restore_data(missing, no_bkup)). If the user
clicks later, after the archive state has since changed (e.g. day X was
written again, better, via a normal sync), restore_raw_days() still runs
with the stale list.

This script reproduces exactly this sequence and observes whether a
silent downgrade occurs outside the normal downgrade protection.

Standalone script, deliberately not integrated into
run_netz2.py/run_netz2_steps_async.py — different core mechanism
(check_raw_integrity() + restore_raw_days() from garmin_backup.py, no
silo-repair/backfill path).

Pure observation. No assert. No changes to the main repo — this script
only imports garmin_backup/garmin_quality/garmin_writer etc. read-only/
call-only. No call into app/panel_archive.py itself (PyQt6 GUI layer, not
sensibly instantiable headless) — the closure staleness is reproduced
directly at the level of the two backend functions that the GUI functions
actually call.

IMPORTANT — write target:
  Own isolated folder (DIAGNOSE_DIR below), separate from the three
  already existing diagnostic folders (diagnose_tmp/,
  diagnose_tmp_steps_async/, diagnose_tmp_stop_abort/), so the diagnostic
  runs don't overwrite each other's state. Fixture CONTENT (raw/) is
  derived from a real raw/ file in your archive (read-only access).

IMPORTANT — two fixture variants from the same source file:
  backup_fixture — intraday series (heartRateValues/stressValuesArray)
    removed, structure otherwise as in the original. assess_quality()
    typically rates this as "standard" (daily aggregates present, no
    intraday) — represents the older, already-backed-up state.
  fresh_fixture — full (trimmed) template including intraday series.
    assess_quality() typically rates this as "high" — represents the
    state after a successful in-between sync.
  Which label actually results depends on the specific source file and is
  logged in the report, not assumed.

IMPORTANT — report numbering:
  This script is started via run_netz2_all.bat, not directly. The .bat
  assigns the running report number (folder output/vXXXX_NN/) and sets
  NETZ2_REPORT_ID before the call.

Run via:
    run_netz2_all.bat (sets NETZ2_REPORT_ID + starts all run_netz2*.py
    scripts in sequence).

Result:
    netz2_diagnostics/output/<NETZ2_REPORT_ID>/NETZ2_BEFUND_restore_staleness.md
"""

import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
#  Configuration — from netz2_config.py + NETZ2_REPORT_ID from the
#  environment (set by run_netz2_all.bat)
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).resolve().parent

try:
    from netz2_config import PROJECT_ROOT_REL, REAL_ARCHIVE_BASE_DIR
except ImportError:
    print("✗  netz2_config.py missing next to run_netz2_restore_staleness.py.")
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

# Own isolated folder — separate from the three other diagnostic runs.
DIAGNOSE_DIR = SCRIPT_DIR / "diagnose_tmp_restore_staleness"

OUTPUT_DIR = SCRIPT_DIR / "output" / NETZ2_REPORT_ID
OUTPUT_MD = OUTPUT_DIR / "NETZ2_BEFUND_restore_staleness.md"

TARGET_DATE = "2025-04-05"

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
import garmin_backup as backup  # noqa: E402


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


def _load_real_template(real_archive_base: Path, target_date: str) -> dict | None:
    src_file = _find_real_raw_file(real_archive_base)
    if src_file is None:
        return None
    real = json.loads(src_file.read_text(encoding="utf-8"))
    fixture = _trim_lists(real, max_items=3)
    fixture["date"] = target_date
    return fixture


def build_backup_fixture(real_archive_base: Path, target_date: str) -> dict | None:
    """
    Backup copy, lower quality: real raw/ file as template (trimmed),
    intraday series (heartRateValues/stressValuesArray) removed.
    Represents the older, already-backed-up state of day X — the starting
    state before any sync/restore in this scenario.
    """
    fixture = _load_real_template(real_archive_base, target_date)
    if fixture is None:
        return None
    if isinstance(fixture.get("heart_rates"), dict):
        fixture["heart_rates"].pop("heartRateValues", None)
    if isinstance(fixture.get("stress"), dict):
        fixture["stress"].pop("stressValuesArray", None)
    return fixture


def build_fresh_fixture(real_archive_base: Path, target_date: str) -> dict | None:
    """
    'Fresh' sync state, full (trimmed) template including intraday series.
    Represents the state that resulted from a successful sync between the
    missing/no_backup list being frozen (step 3) and the restore click
    (step 5).
    """
    return _load_real_template(real_archive_base, target_date)


# ══════════════════════════════════════════════════════════════════════════════
#  Diagnostic run
# ══════════════════════════════════════════════════════════════════════════════

def reset_diagnose_dir():
    if DIAGNOSE_DIR.exists():
        shutil.rmtree(DIAGNOSE_DIR)
    for sub in ("raw", "summary", "source", "log", "backup"):
        (DIAGNOSE_DIR / "garmin_data" / sub).mkdir(parents=True, exist_ok=True)


def _read_or_none(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"<file present but unreadable: {e}>"


def _write_day_real_path(raw_content: dict, target_date: str) -> tuple[str, dict]:
    """
    Writes a day via the real fetch path (normalize → summarize → assess →
    write_day → _upsert_quality → _save_quality_log), analogous to
    main()'s normal flow after a successful API fetch. Returns
    (label, fields).
    """
    normalized = normalizer.normalize(raw_content, source="api")
    summary = normalizer.summarize(normalized)
    label = quality.assess_quality(normalized)
    fields = quality.assess_quality_fields(normalized)
    writer.write_day(normalized, summary, target_date)

    data = quality._load_quality_log()
    quality._upsert_quality(
        data, date.fromisoformat(target_date),
        label, f"Quality: {label}", written=True, source="api", fields=fields,
    )
    quality._save_quality_log(data, skip_backup=True)
    return label, fields


def run_restore_staleness_scenario(target_date: str) -> dict:
    """
    Reproduces the sequence described in the task:
      2. Starting state — backup copy of day X present, raw/ itself empty.
      3. Call check_raw_integrity(), 'freeze' missing/no_backup.
      4. Simulate time offset — day X is written again, better.
      5. restore_raw_days() with the FROZEN list from step 3.
      6. Observe — file state, quality_log entry, return value.
    """
    record = {"target_date": target_date}

    backup_fixture = build_backup_fixture(REAL_ARCHIVE_BASE_DIR, target_date)
    fresh_fixture = build_fresh_fixture(REAL_ARCHIVE_BASE_DIR, target_date)
    if backup_fixture is None or fresh_fixture is None:
        record["skipped"] = True
        record["skip_reason"] = (
            "no real raw/ file found in the real archive — "
            "check REAL_ARCHIVE_BASE_DIR"
        )
        return record
    record["skipped"] = False
    record["backup_fixture_content"] = backup_fixture
    record["fresh_fixture_content"] = fresh_fixture

    backup_label = quality.assess_quality(
        normalizer.normalize(backup_fixture, source="api"))
    record["backup_fixture_quality"] = backup_label

    # ── step 2 — create a backup copy of day X (directly under
    #    backup/raw/<month>/, as backup_raw() would have done for an
    #    earlier-written, then-valid state). raw/ itself deliberately
    #    stays empty at this point. ──────────────────────────────────────
    month = target_date[:7]
    backup_month_dir = cfg.RAW_BACKUP_DIR / month
    backup_month_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_month_dir / f"garmin_raw_{target_date}.json"
    backup_path.write_text(
        json.dumps(backup_fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    record["backup_fixture_path"] = str(backup_path)

    # quality_log entry with write=True, so check_raw_integrity() recognizes
    # the day as "missing" (raw/ doesn't exist yet at this point).
    qlog_data = {
        "first_day": target_date, "devices": [],
        "days": [{
            "date": target_date, "quality": backup_label, "reason": "ok",
            "write": True, "source": "api", "recheck": False, "attempts": 0,
            "last_checked": target_date, "last_attempt": None, "fields": {},
        }],
    }
    quality._save_quality_log(qlog_data, skip_backup=True)

    # ── step 3 — call check_raw_integrity(), 'freeze' the list
    #    (corresponds to panel_archive._startup_integrity_check() →
    #    closure values into the restore button via
    #    command=lambda: ...(missing, no_bkup)). ────────────────────────
    integrity_result = backup.check_raw_integrity()
    record["integrity_result"] = integrity_result
    frozen_missing = list(integrity_result.get("missing_days", []))
    frozen_no_backup = list(integrity_result.get("no_backup", []))
    record["frozen_missing_days"] = frozen_missing
    record["frozen_no_backup"] = frozen_no_backup
    record["target_in_frozen_missing"] = target_date in frozen_missing
    record["target_in_frozen_no_backup"] = target_date in frozen_no_backup

    # ── step 4 — simulate a time offset: day X gets written again, better,
    #    in the meantime (like a successful sync that ran between freezing
    #    the list and the restore click). ─────────────────────────────────
    fresh_label, fresh_fields = _write_day_real_path(fresh_fixture, target_date)
    record["fresh_write_label"] = fresh_label
    record["fresh_write_fields"] = fresh_fields

    raw_path = cfg.RAW_DIR / f"garmin_raw_{target_date}.json"
    record["raw_before_restore"] = _read_or_none(raw_path)

    qdata_before = quality._load_quality_log()
    record["quality_log_entry_before_restore"] = next(
        (e for e in qdata_before.get("days", []) if e.get("date") == target_date),
        None,
    )

    # ── step 5 — call restore_raw_days() with the FROZEN list from step 3
    #    (not re-checked — exactly what simulates the GUI bug). ──────────
    restore_result = backup.restore_raw_days(frozen_missing)
    record["restore_result"] = restore_result
    record["target_in_restored"] = target_date in restore_result.get("restored", [])
    record["target_in_failed"] = target_date in restore_result.get("failed", [])

    # ── step 6 — observe ──────────────────────────────────────────────────
    record["raw_after_restore"] = _read_or_none(raw_path)
    record["raw_after_restore_matches_backup"] = (
        record["raw_after_restore"] == backup_fixture)
    record["raw_after_restore_matches_fresh"] = (
        record["raw_after_restore"] == fresh_fixture)

    qdata_after = quality._load_quality_log()
    record["quality_log_entry_after_restore"] = next(
        (e for e in qdata_after.get("days", []) if e.get("date") == target_date),
        None,
    )
    record["quality_log_unchanged_by_restore"] = (
        record["quality_log_entry_before_restore"]
        == record["quality_log_entry_after_restore"]
    )

    return record


def main():
    print("=" * 65)
    print("  netz2_diagnostics — restore-data staleness window diagnosis")
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

    result = run_restore_staleness_scenario(TARGET_DATE)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md = build_report_md(result)
    OUTPUT_MD.write_text(md, encoding="utf-8")

    print()
    if result.get("skipped"):
        print(f"  skipped: {result['skip_reason']}")
    else:
        print(f"  Target date                          : {result['target_date']}")
        print(f"  Backup quality (starting state)      : {result['backup_fixture_quality']}")
        print(f"  Fresh write (time offset)            : {result['fresh_write_label']}")
        print(f"  Target date in frozen missing list   : {result['target_in_frozen_missing']}")
        print(f"  restore_raw_days() → target_in_restored: {result['target_in_restored']}")
        print(f"  raw/ after restore == backup version : {result['raw_after_restore_matches_backup']}")
        print(f"  raw/ after restore == fresh version  : {result['raw_after_restore_matches_fresh']}")
        print(f"  quality_log unchanged by restore     : {result['quality_log_unchanged_by_restore']}")
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
    lines.append(f"# NETZ2_BEFUND_restore_staleness_{NETZ2_REPORT_ID}.md")
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
    lines.append("## Scenario: restore-data staleness window")
    lines.append("")
    lines.append(f"- Target date: `{result['target_date']}`")

    if result.get("skipped"):
        lines.append(f"- **Skipped:** {result['skip_reason']}")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"- Backup fixture path: `{result['backup_fixture_path']}`")
    lines.append("")

    lines.append("### Step 2 — starting state: backup copy present, raw/ empty")
    lines.append("")
    lines.append(f"- Backup quality (assess_quality on backup fixture): "
                  f"**{result['backup_fixture_quality']}**")
    lines.append("")
    lines.append("**Backup fixture content (intraday series removed):**")
    lines.append("")
    lines.append(_json_block(result["backup_fixture_content"]))
    lines.append("")

    lines.append("### Step 3 — check_raw_integrity(), list frozen")
    lines.append("")
    lines.append("**check_raw_integrity() — return value:**")
    lines.append("")
    lines.append(_json_block(result["integrity_result"]))
    lines.append("")
    lines.append(f"- Target date in frozen `missing_days`: "
                  f"**{result['target_in_frozen_missing']}**")
    lines.append(f"- Target date in frozen `no_backup`: "
                  f"**{result['target_in_frozen_no_backup']}**")
    lines.append("")

    lines.append("### Step 4 — time offset: day X written again, better")
    lines.append("")
    lines.append(f"- Write label (assess_quality on fresh fixture): "
                  f"**{result['fresh_write_label']}**")
    lines.append("")
    lines.append("**Fresh fixture content (full, including intraday series):**")
    lines.append("")
    lines.append(_json_block(result["fresh_fixture_content"]))
    lines.append("")
    lines.append("**raw/ file immediately before the restore call (= fresh state):**")
    lines.append("")
    lines.append(_json_block(result["raw_before_restore"]))
    lines.append("")
    lines.append("**quality_log.json entry immediately before the restore call:**")
    lines.append("")
    lines.append(_json_block(result["quality_log_entry_before_restore"]))
    lines.append("")

    lines.append("### Step 5 — restore_raw_days() with the FROZEN list")
    lines.append("")
    lines.append("**restore_raw_days(frozen_missing) — return value:**")
    lines.append("")
    lines.append(_json_block(result["restore_result"]))
    lines.append("")
    lines.append(f"- Target date in `restored`: **{result['target_in_restored']}**")
    lines.append(f"- Target date in `failed`: **{result['target_in_failed']}**")
    lines.append("")

    lines.append("### Step 6 — observation")
    lines.append("")
    lines.append("**raw/ file after the restore:**")
    lines.append("")
    lines.append(_json_block(result["raw_after_restore"]))
    lines.append("")
    lines.append(f"- raw/ after restore == backup version (step 2): "
                  f"**{result['raw_after_restore_matches_backup']}**")
    lines.append(f"- raw/ after restore == fresh version (step 4): "
                  f"**{result['raw_after_restore_matches_fresh']}**")
    lines.append("")
    lines.append("**quality_log.json entry after the restore:**")
    lines.append("")
    lines.append(_json_block(result["quality_log_entry_after_restore"]))
    lines.append("")
    lines.append(f"- quality_log entry unchanged by restore_raw_days(): "
                  f"**{result['quality_log_unchanged_by_restore']}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
