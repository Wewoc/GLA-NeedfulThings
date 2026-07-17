"""
scope_snapshot_config_v[VERSION]_[NN].py
Garmin Local Archive — v[VERSION] · Session Start · [DATE]
Symbol scope for: [SHORT DESCRIPTION OF THE BUILD TASK]

Naming scheme:  scope_snapshot_config_v[version without dots]_[running number, two digits].py
Location:       scope_snapshot/ (next to scope_snapshot.py)
Execution:      run_scope_snapshot.bat
Report output:  SCOPE_SNAPSHOT_[version without dots].md  (in scope_output/)

IMPORTANT: SCOPE_FILES is NOT guessed freely. Its basis is exclusively the
set of Claude-confirmed 'relevant' matches from the previous
DEPS_CRITICAL_[version].md run, deduplicated to unique file paths.
Order in the session flow:

    DEPS report is generated
          |
          v
    Review by Claude (relevant matches confirmed, filtered)
          |
          v
    this config is derived from that
          |
          v
    scope_snapshot.py runs -> SCOPE_SNAPSHOT_[version].md
          |
          v
    Build task
"""

# ── Meta ──────────────────────────────────────────────────────────────────────
# CONFIG_ID:    v[version without dots]_[nn] — identical to the corresponding
#               scan_config_v[version]_[nn].py, so the DEPS report and
#               Scope Snapshot can be unambiguously matched to each other.
# SESSION_NOTE: Short version/topic info — appears in the report header
# PROJECT_ROOT: Relative path from the scope_snapshot/ folder to the repo root.
#               Also needed to resolve facade/import-neighbor references
#               (module path -> file).
#               ⚠ Same path-consistency trap as with scan_config: cross-check
#               against the corresponding scan_config_v[version]_[nn].py.

CONFIG_ID    = "v[VERSION]_[NN]"
SESSION_NOTE = "v[VERSION] — [session topic]"
PROJECT_ROOT = "../[repo-folder]"

# ── Scope Files ───────────────────────────────────────────────────────────────
# Unique, deduplicated file paths (relative to PROJECT_ROOT) from the
# Claude-confirmed 'relevant' matches of this session's DEPS report.
# No pattern, no heuristic here — a plain list.
#
# Example:
# SCOPE_FILES = [
#     "garmin/garmin_quality.py",
#     "garmin/garmin_writer.py",
# ]

SCOPE_FILES = [
    # "path/to/file.py",
]
