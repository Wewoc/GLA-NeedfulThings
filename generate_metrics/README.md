# generate_metrics.py — Doc Metrics Generator

Writes `docs/METRICS.md` in a target project — a single generated file that
other docs can link to instead of restating test counts, module counts, and
version numbers by hand.

## What it does

1. Runs `run_tests.ps1` in the target project (not the `.bat` wrapper — that
   has a `pause` which would block the subprocess indefinitely)
2. Reads the `SUMMARY` block from `test_all_log.txt` — not the process exit
   code, since `run_tests.ps1` runs with `$ErrorActionPreference = "Continue"`
   and keeps going after a failed suite
3. Aborts without writing anything if any suite is red, if a log line isn't
   recognized, or if the log is empty
4. Only on a fully green result: reads `SHARED_SCRIPTS` from
   `build_manifest.py` via AST (no import, no `exec()`), and `APP_VERSION`
   from `version.py` via regex
5. Writes `docs/METRICS.md` atomically (temp file → rename)

Sole-write principle: this is the only file this tool ever writes. Never
touches `REFERENCE_*.md`, `MAINTENANCE_*.md`, `README.md`, or
`build_manifest.py` itself.

## Setup

Same path convention as `apply_anchors.py` — place this script in a folder
one level above the target project:

```
PROJECT_ROOT = SCRIPT_DIR / "../garmin_collector-1_work"
SRC_DIR      = PROJECT_ROOT / "src"
```

Adjust `PROJECT_ROOT`/`SRC_DIR` at the top of the script if your target
project has a different name or layout.

## Usage

```bash
python generate_metrics.py
```

Exit code `0` on success, `1` on any abort (nothing written).

## Known limitation

The `Total` row sums `check()`-based counts and `pytest`-item counts
together — these are structurally different units for suites that run under
`pytest` instead of a plain script invocation. The sum is informative, not
a homogeneous metric.

---

*GLA-NeedfulThings · Built with Claude*
