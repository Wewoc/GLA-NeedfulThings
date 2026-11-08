#!/usr/bin/env python3
"""
generate_metrics.py — Needful Things

Generates src/docs/METRICS.md — the only file this tool writes to.
All other documentation files (README, MAINTENANCE_*, SESSION_BASE, handbook, ...)
link to this file from now on instead of carrying numbers themselves.

Flow (see analysis chat v1.6.5.5):
    1. Run run_tests.ps1 (cwd = src/, so relative paths in the script are correct)
    2. Read src/test_all_log.txt — do NOT take the process exit code as the
       sole truth. run_tests.ps1 keeps going with $ErrorActionPreference =
       "Continue" even when a suite is red — the actual truth is in the
       ZUSAMMENFASSUNG ("summary") block of the log file.
    3. Check every suite line in the ZUSAMMENFASSUNG block:
       - "Ergebnis nicht erkannt — siehe Log oben" ("result not recognized —
         see log above")                          → abort (no number)
       - failed > 0 in any suite                   → abort (red build)
       - no suite line found at all                → abort (log empty/broken)
       - exit code of run_tests.ps1 != 0           → abort, but only if CHECK_EXIT_CODE
                                                     is switched on (default: off)
    4. Only with a fully green result: read build_manifest.py (SHARED_SCRIPTS,
       via AST — no import, no exec) and version.py (APP_VERSION, via
       regex).
    5. Write src/docs/METRICS.md atomically (temp file → os.replace).

On any error in 1–4: abort, docs/METRICS.md stays untouched.
Better no file than one with a wrong or outdated state.

Runs locally on the maintainer's machine — not part of SHARED_SCRIPTS, not part of the build.
Pure stdlib, no external dependencies.
"""

import ast
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
# Same convention as apply_anchors.py — path relative to the script location,
# no hard-coded absolute path. Prerequisite: this script lives in
# a NeedfulThings subfolder whose parent folder is a sibling of
# my_project (identical to apply_anchors.py PROJECT_ROOT) — adjust to your project.
SCRIPT_DIR   = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPT_DIR / "../my_project").resolve()
SRC_DIR      = PROJECT_ROOT / "src"

DOCS_DIR    = SRC_DIR / "docs"
OUTPUT_FILE = DOCS_DIR / "METRICS.md"

RUN_TESTS_PS1 = SRC_DIR / "run_tests.ps1"
LOG_FILE      = SRC_DIR / "test_all_log.txt"
BUILD_MANIFEST = SRC_DIR / "compiler" / "build_manifest.py"
VERSION_FILE   = SRC_DIR / "version.py"

# Summary line format from run_tests.ps1 — identical for the "own
# format" and the normalized pytest format, because run_tests.ps1 maps both onto
# the same line before it lands in SuiteSummaries.
_SUITE_LINE_RE = re.compile(
    r'^\s*(?P<label>\S.*?)\s{2,}'
    r'(?P<total>\d+)\s+checks?\s+—\s+'
    r'(?P<passed>\d+)\s+passed,\s+'
    r'(?P<failed>\d+)\s+failed\s*$'
)
_UNRECOGNIZED_MARKER = "Ergebnis nicht erkannt"
_SUMMARY_HEADER_MARKER = "ZUSAMMENFASSUNG"

# Optional extra gate: also treat a non-zero exit code of run_tests.ps1 as a
# red run, even when the summary block shows no failed suite (for example a
# pytest error that is reported as "0 failed"). Switch it on only if your
# run_tests.ps1 ends with a non-zero exit code whenever a suite failed or
# crashed; otherwise a harmless non-zero exit would abort every run.
CHECK_EXIT_CODE = False


class GeneratorAbort(Exception):
    """Controlled abort — docs/METRICS.md stays unchanged."""


# ── Step 1+2 — run the tests, read the log ───────────────────────────────────

def run_tests() -> int:
    if not RUN_TESTS_PS1.exists():
        raise GeneratorAbort(f"run_tests.ps1 not found: {RUN_TESTS_PS1}")

    print(f"→ running run_tests.ps1 (cwd={SRC_DIR}) ...")
    try:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(RUN_TESTS_PS1)],
            cwd=str(SRC_DIR),
            check=False,  # exit code is only evaluated if CHECK_EXIT_CODE is on — see docstring
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        raise GeneratorAbort("run_tests.ps1 exceeded the time limit (30 min)")
    except OSError as e:
        raise GeneratorAbort(f"run_tests.ps1 could not be started: {e}")
    return result.returncode


def parse_test_summary() -> list[dict]:
    """Reads the ZUSAMMENFASSUNG block from test_all_log.txt.

    Returns a list of {"label", "total", "passed", "failed"}.
    Raises GeneratorAbort on a red build, an unrecognized line or an empty log.
    """
    if not LOG_FILE.exists():
        raise GeneratorAbort(f"test_all_log.txt not found: {LOG_FILE}")

    text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    try:
        start = next(i for i, l in enumerate(lines) if _SUMMARY_HEADER_MARKER in l)
    except StopIteration:
        raise GeneratorAbort(
            "No ZUSAMMENFASSUNG block found in test_all_log.txt — "
            "log incomplete or the format has changed."
        )

    suites: list[dict] = []
    for line in lines[start + 1:]:
        if _UNRECOGNIZED_MARKER in line:
            # the suite label precedes the marker on the same line
            raise GeneratorAbort(f"Unrecognized test result in log line: {line.strip()!r}")

        m = _SUITE_LINE_RE.match(line)
        if m:
            suites.append({
                "label":  m.group("label").strip(),
                "total":  int(m.group("total")),
                "passed": int(m.group("passed")),
                "failed": int(m.group("failed")),
            })

    if not suites:
        raise GeneratorAbort(
            "No suite line recognized in the ZUSAMMENFASSUNG block — "
            "log format checked? (see _SUITE_LINE_RE)"
        )

    red = [s for s in suites if s["failed"] > 0]
    if red:
        labels = ", ".join(f"{s['label']} ({s['failed']} failed)" for s in red)
        raise GeneratorAbort(f"Red test run — METRICS.md not updated: {labels}")

    return suites


# ── Step 4 — read build_manifest.py + version.py ──────────────────────────

def read_shared_scripts() -> list[str]:
    if not BUILD_MANIFEST.exists():
        raise GeneratorAbort(f"build_manifest.py not found: {BUILD_MANIFEST}")

    source = BUILD_MANIFEST.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BUILD_MANIFEST))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SHARED_SCRIPTS":
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError) as e:
                        raise GeneratorAbort(f"SHARED_SCRIPTS cannot be evaluated as a literal: {e}")
                    if not isinstance(value, list):
                        raise GeneratorAbort("SHARED_SCRIPTS is not a list — format checked?")
                    return value

    raise GeneratorAbort("SHARED_SCRIPTS not found in build_manifest.py")


def read_app_version() -> str:
    if not VERSION_FILE.exists():
        raise GeneratorAbort(f"version.py not found: {VERSION_FILE}")

    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'''APP_VERSION\s*=\s*['"]([^'"]+)['"]''', text)
    if not m:
        raise GeneratorAbort("APP_VERSION not found in version.py — format checked?")
    return m.group(1)


# ── Step 5 — write docs/METRICS.md atomically ──────────────────────────────

def render_metrics_md(suites: list[dict], modules: list[str], version: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_checks = sum(s["total"] for s in suites)

    lines = [
        "<!-- generated by tools/generate_metrics.py — do not edit by hand -->",
        f"<!-- Other docs should link here instead of restating these numbers -->",
        "",
        "# METRICS",
        "",
        f"Generated: {now} · Version: {version}",
        "",
        "## Test Counts",
        "",
        "| Suite | Checks | Passed | Failed |",
        "|---|---|---|---|",
    ]
    for s in suites:
        lines.append(f"| {s['label']} | {s['total']} | {s['passed']} | {s['failed']} |")
    lines += [
        f"| **Total** | **{total_checks}** | **{total_checks}** | **0** |",
        "",
        "## Modules",
        "",
        f"Total: {len(modules)} (from `SHARED_SCRIPTS` in `build_manifest.py`)",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_metrics_md(content: str) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=str(DOCS_DIR), prefix=".metrics_", suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        # Atomic rename — no intermediate state in which METRICS.md would be
        # half-written or empty.
        Path(tmp_path).replace(OUTPUT_FILE)
    except OSError:
        Path(tmp_path).unlink(missing_ok=True)
        raise


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        returncode = run_tests()
        suites = parse_test_summary()
        if CHECK_EXIT_CODE and returncode != 0:
            raise GeneratorAbort(
                f"run_tests.ps1 reported an error (exit code {returncode}) despite a "
                f"green ZUSAMMENFASSUNG block — see test_all_log.txt"
            )
        modules = read_shared_scripts()
        version = read_app_version()

        content = render_metrics_md(suites, modules, version)
        write_metrics_md(content)

    except GeneratorAbort as e:
        print(f"\n✗ Aborted — {OUTPUT_FILE.name} stays unchanged.", file=sys.stderr)
        print(f"  Reason: {e}", file=sys.stderr)
        return 1

    print(f"\n✓ {OUTPUT_FILE} updated.")
    print(f"  {sum(s['total'] for s in suites)} checks, all green · {len(modules)} modules · v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
