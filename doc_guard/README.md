# doc_guard.py — Doc Drift Guard

Read-only cross-check between code and documentation in a target project.
Writes `docs/DOC_DRIFT_REPORT.md`, never touches the files it checks.

## What it checks

| Check | What | Precision |
|---|---|---|
| A | Every signature string in `SCRIPT_SIGNATURES_BASE` (`build_manifest.py`) against the real source — AST for `def`/`class`, substring fallback for constants/fragments | High |
| B | Every module in `SHARED_SCRIPTS` mentioned as backtick text anywhere in `REFERENCE_*.md` (headings and table cells) | Medium, deliberately coarse — finds "missing entirely", not "documented but stale" |
| C | Test counts in `MAINTENANCE_*.md` against `docs/METRICS.md` — recognizes three formats: combined (`N checks, M sections/classes`), split (`Check count: N`), and no claim at all | High, with an honest `no_count_claimed` status for files that legitimately state no running total |
| D | Every module mentioned anywhere in `README.md` (plain substring) | Low, intentionally weak |

## Setup

Same path convention as `apply_anchors.py` and `generate_metrics.py` — place
this script one level above the target project:

```
PROJECT_ROOT = SCRIPT_DIR / "../garmin_collector-1_work"
SRC_DIR      = PROJECT_ROOT / "src"
```

Adjust `PROJECT_ROOT`/`SRC_DIR` at the top of the script for a different
target project name or layout. Companion tool: `generate_metrics/`
— run that first so `docs/METRICS.md` reflects a current test run before
Check C compares against it.

## Usage

```bash
python doc_guard.py
```

Exit code `1` if any check found something worth looking at, `0` if clean.
Not a build gate — a signal to go read the report.

## Known limits

- Checks B and D can only prove absence, never staleness — if a function is
  renamed but the old name is still documented, neither check catches it
- Check B only scans the `REFERENCE_*.md` files, not a project handbook or
  other narrative docs — modules documented only there will show as
  "missing" even though they're covered

---

*GLA-NeedfulThings · Built with Claude*
