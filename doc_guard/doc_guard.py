#!/usr/bin/env python3
"""
doc_guard.py — Needful Things

Read-only doc drift detection (class 2). Writes NOTHING to REFERENCE_*.md,
MAINTENANCE_*.md, README.md or build_manifest.py — it only reads them. The
only file this tool writes to is its own report:
src/docs/DOC_DRIFT_REPORT.md.

Scope (see analysis chat v1.6.5.5, "Weg 1" ("way 1") — no documentation rewrite beforehand):

  A) SCRIPT_SIGNATURES_BASE values against the real code (high precision)
     For every file in SCRIPT_SIGNATURES_BASE: does every listed
     signature ('def foo', 'class Bar', or a bare constant/fragment)
     still exist in the source code? test_build_output.py only checks the
     dict KEYS against the manifest — not the values against the real code.
     That is the gap this check closes.

  B) Module mention in REFERENCE_*.md (medium precision, deliberately coarse)
     For every module in SHARED_SCRIPTS: does the file name, the stem
     (without .py) or the full path appear as backtick text anywhere in
     any REFERENCE_*.md — headings AND table cells
     (e.g. plugin tables). No file assignment (maps/ is spread over three
     files anyway) — only "documented somewhere" vs. "mentioned
     nowhere". Finds missing documentation, not outdated documentation.

  C) Test counts MAINTENANCE_*.md against docs/METRICS.md (high precision)
     Confirmed format: "**Current count: N checks, M sections.**"

  D) Module mention in README.md (low precision)
     Pure substring test over the whole file.

Runs locally on the maintainer's machine — not part of SHARED_SCRIPTS, not part of the build.
Pure stdlib, no external dependencies.
"""

import ast
import re
import sys
import tempfile
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
# Same convention as apply_anchors.py and generate_metrics.py — path
# relative to the script location, no hard-coded absolute path.
SCRIPT_DIR   = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPT_DIR / "../my_project").resolve()   # adjust to your project
SRC_DIR      = PROJECT_ROOT / "src"
DOCS_DIR     = SRC_DIR / "docs"

BUILD_MANIFEST = SRC_DIR / "compiler" / "build_manifest.py"
METRICS_FILE   = DOCS_DIR / "METRICS.md"
README_FILE    = SRC_DIR.parent / "README.md"   # lives one level above src/ (v1.6.0.1)

REFERENCE_FILES = [
    DOCS_DIR / "REFERENCE_GARMIN.md",
    DOCS_DIR / "REFERENCE_CONTEXT.md",
    DOCS_DIR / "REFERENCE_DASHBOARD.md",
    DOCS_DIR / "REFERENCE_BROKER.md",
    DOCS_DIR / "REFERENCE_GLOBAL.md",
]

# MAINTENANCE file → which test_*.py suite(s) it documents
# (from FINAL_DOKU_PROMPT_v2.md step 6 — stable, documented convention)
MAINTENANCE_FILES = [
    DOCS_DIR / "MAINTENANCE_GARMIN.md",
    DOCS_DIR / "MAINTENANCE_CONTEXT.md",
    DOCS_DIR / "MAINTENANCE_DASHBOARD.md",
    DOCS_DIR / "MAINTENANCE_GLOBAL.md",
]

OUTPUT_FILE = DOCS_DIR / "DOC_DRIFT_REPORT.md"

_CURRENT_COUNT_RE = re.compile(
    r'\*\*Current count:\s*(\d+)\s*checks,\s*(\d+)\s*\w+\.\*\*'
)
_CHECK_COUNT_SPLIT_RE = re.compile(
    r'\*\*Check count:\s*(\d+)\*\*'
)
_ANY_COUNT_CLAIM_RE = re.compile(r'Current count|Check count')
_TEST_FILE_MENTION_RE = re.compile(r'test_\w+\.py')
_HEADING_RE = re.compile(r'^#{1,6}\s+(.*)$')
_BACKTICK_RE = re.compile(r'`([^`]+)`')


class GuardError(Exception):
    """Unexpected error while reading — the report is still written (finally)."""


# ── A) SCRIPT_SIGNATURES_BASE against real code ───────────────────────────────

def load_build_manifest() -> tuple[list[str], dict[str, list[str]]]:
    if not BUILD_MANIFEST.exists():
        raise GuardError(f"build_manifest.py not found: {BUILD_MANIFEST}")

    source = BUILD_MANIFEST.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BUILD_MANIFEST))

    shared_scripts: list[str] | None = None
    signatures: dict[str, list[str]] | None = None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "SHARED_SCRIPTS":
                try:
                    shared_scripts = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
            elif target.id == "SCRIPT_SIGNATURES_BASE":
                try:
                    signatures = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass

    if shared_scripts is None:
        raise GuardError("SHARED_SCRIPTS not found / not evaluable as a literal")
    if signatures is None:
        raise GuardError("SCRIPT_SIGNATURES_BASE not found / not evaluable as a literal")

    return shared_scripts, signatures


def _extract_def_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _extract_class_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
    return names


def check_signatures(signatures: dict[str, list[str]]) -> list[dict]:
    """Checks every signature string against the real source code.

    Returns: list of {"module", "signature", "status", "detail"}.
    status: "ok" | "missing" | "file_missing"
    """
    results = []

    for module_path, sig_list in signatures.items():
        file_path = SRC_DIR / module_path
        if not file_path.exists():
            for sig in sig_list:
                results.append({
                    "module": module_path, "signature": sig,
                    "status": "file_missing", "detail": "File does not exist",
                })
            continue

        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(raw_text, filename=str(file_path))
            def_names = _extract_def_names(tree)
            class_names = _extract_class_names(tree)
            parse_ok = True
        except SyntaxError as e:
            def_names, class_names = set(), set()
            parse_ok = False
            parse_error = str(e)

        for sig in sig_list:
            sig_stripped = sig.strip()

            if not parse_ok:
                results.append({
                    "module": module_path, "signature": sig,
                    "status": "missing",
                    "detail": f"File not parsable (SyntaxError: {parse_error})",
                })
                continue

            if sig_stripped.startswith("def "):
                name = sig_stripped[4:].split("(")[0].strip()
                ok = name in def_names
            elif sig_stripped.startswith("class "):
                name = sig_stripped[6:].split("(")[0].split(":")[0].strip()
                ok = name in class_names
            else:
                # Constants / fragments (e.g. 'QUALITY_LOCK', 'GARMIN_EMAIL',
                # 'from quality._maint import') — simple substring fallback.
                ok = sig_stripped in raw_text

            results.append({
                "module": module_path, "signature": sig,
                "status": "ok" if ok else "missing",
                "detail": "" if ok else "Signature not found in the source code",
            })

    return results


# ── B) Module mention in REFERENCE_*.md ───────────────────────────────────────

def collect_reference_mentions() -> set[str]:
    """Collects all backtick tokens from REFERENCE_*.md — not only from
    headings, but from the whole file (table cells
    included, e.g. plugin tables as in REFERENCE_CONTEXT.md).
    Deliberately broader than a pure heading search — 'documented somewhere',
    not 'has its own section'."""
    tokens: set[str] = set()
    for ref_file in REFERENCE_FILES:
        if not ref_file.exists():
            continue
        for line in ref_file.read_text(encoding="utf-8", errors="replace").splitlines():
            for bt in _BACKTICK_RE.findall(line):
                tokens.add(bt.strip())
    return tokens


def check_reference_coverage(shared_scripts: list[str]) -> tuple[list[dict], list[str]]:
    mentions = collect_reference_mentions()
    missing_files = [f.name for f in REFERENCE_FILES if not f.exists()]

    results = []
    for module_path in shared_scripts:
        filename = Path(module_path).name          # e.g. "garmin_utils.py"
        if filename == "__init__.py":
            continue   # structural marker file, not documented individually anywhere
        stem = Path(module_path).stem               # e.g. "garmin_utils"
        # Additionally check the full path — covers cases like
        # '## `layouts/reference_ranges.py`' where the folder is part of the
        # heading text and the file name/stem alone do not match.
        found = (
            filename in mentions
            or stem in mentions
            or module_path in mentions
        )
        results.append({
            "module": module_path,
            "status": "ok" if found else "missing",
        })

    return results, missing_files


# ── C) Test counts MAINTENANCE_*.md against docs/METRICS.md ─────────────────────

def load_metrics_counts() -> dict[str, int]:
    """Reads the suite totals from docs/METRICS.md (own, known format)."""
    if not METRICS_FILE.exists():
        return {}

    counts: dict[str, int] = {}
    row_re = re.compile(r'^\|\s*(test_\w+\.py)\s*\|\s*(\d+)\s*\|')
    for line in METRICS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        m = row_re.match(line.strip())
        if m:
            counts[m.group(1)] = int(m.group(2))
    return counts


def check_test_counts(metrics_counts: dict[str, int]) -> list[dict]:
    """For every MAINTENANCE_*.md: finds 'Current count' lines, assigns them
    to the nearest preceding test_*.py mention, compares against
    METRICS.md."""
    results = []

    for maint_file in MAINTENANCE_FILES:
        if not maint_file.exists():
            results.append({
                "file": maint_file.name, "test_file": None,
                "status": "file_missing", "detail": "File does not exist",
            })
            continue

        raw_text = maint_file.read_text(encoding="utf-8", errors="replace")
        lines = raw_text.splitlines()
        last_test_file = None
        matches_in_file = 0

        for line in lines:
            # Check the count match first against the PREVIOUS last_test_file —
            # not against a possible incidental test-file mention in
            # the same line (e.g. "... Does NOT duplicate `test_app_logic.py`"
            # inside the count line for ANOTHER file).
            cm = _CURRENT_COUNT_RE.search(line)
            sm = _CHECK_COUNT_SPLIT_RE.search(line)
            match = cm or sm

            if match and last_test_file:
                matches_in_file += 1
                documented_count = int(match.group(1))
                metrics_count = metrics_counts.get(last_test_file)

                if metrics_count is None:
                    results.append({
                        "file": maint_file.name, "test_file": last_test_file,
                        "status": "no_metrics_data",
                        "detail": f"docs/METRICS.md has no entry for {last_test_file}",
                    })
                elif documented_count == metrics_count:
                    results.append({
                        "file": maint_file.name, "test_file": last_test_file,
                        "status": "ok",
                        "detail": f"{documented_count} checks — matches",
                    })
                else:
                    results.append({
                        "file": maint_file.name, "test_file": last_test_file,
                        "status": "drift",
                        "detail": f"Docs: {documented_count}, METRICS.md: {metrics_count}",
                    })

            # Update last_test_file only AFTER the count evaluation of this line
            # — so it only affects subsequent lines.
            tm = _TEST_FILE_MENTION_RE.search(line)
            if tm:
                last_test_file = tm.group(0)

        if matches_in_file == 0:
            # Distinction: is there a count claim in the file at all
            # (then the format is merely unrecognized — a real warning), or is
            # no number claimed at all (then there is nothing to check — the
            # file implicitly refers to docs/METRICS.md as its source, no
            # drift risk, no warning needed)?
            if _ANY_COUNT_CLAIM_RE.search(raw_text):
                results.append({
                    "file": maint_file.name, "test_file": None,
                    "status": "no_match_found",
                    "detail": (
                        "File contains 'Current count'/'Check count', but no "
                        "known format could assign it to a test_*.py file. "
                        "New format? NOT checked, not 'clean'."
                    ),
                })
            else:
                results.append({
                    "file": maint_file.name, "test_file": None,
                    "status": "no_count_claimed",
                    "detail": (
                        "File claims no test count number — nothing to check, "
                        "no drift risk. docs/METRICS.md is the source."
                    ),
                })

    return results


# ── D) Module mention in README.md ────────────────────────────────────────────

def check_readme_coverage(shared_scripts: list[str]) -> tuple[list[dict], bool]:
    if not README_FILE.exists():
        return [], False

    text = README_FILE.read_text(encoding="utf-8", errors="replace")
    results = []
    for module_path in shared_scripts:
        filename = Path(module_path).name
        if filename == "__init__.py":
            continue   # structural marker file, not documented individually anywhere
        stem = Path(module_path).stem
        found = filename in text or stem in text
        results.append({
            "module": module_path,
            "status": "ok" if found else "missing",
        })
    return results, True


# ── Report ─────────────────────────────────────────────────────────────────────

def render_report(
    sig_results: list[dict],
    ref_results: list[dict],
    ref_missing_files: list[str],
    count_results: list[dict],
    readme_results: list[dict],
    readme_available: bool,
) -> str:
    lines = [
        "<!-- generated by tools/doc_guard.py — do not edit by hand -->",
        "<!-- Read-only report. This tool never modifies REFERENCE_*/MAINTENANCE_*/README/build_manifest. -->",
        "",
        "# DOC_DRIFT_REPORT",
        "",
    ]

    # A) Signatures
    sig_missing = [r for r in sig_results if r["status"] != "ok"]
    lines += [
        "## A) SCRIPT_SIGNATURES_BASE vs. real code",
        "",
        f"{len(sig_results) - len(sig_missing)} / {len(sig_results)} signatures confirmed.",
        "",
    ]
    if sig_missing:
        lines += ["| Module | Signature | Status | Detail |", "|---|---|---|---|"]
        for r in sig_missing:
            lines.append(f"| `{r['module']}` | `{r['signature']}` | {r['status']} | {r['detail']} |")
    else:
        lines.append("No drift found.")
    lines.append("")

    # B) Reference coverage
    ref_missing = [r for r in ref_results if r["status"] != "ok"]
    lines += [
        "## B) Module mentioned in REFERENCE_*.md (headings + table cells, coarse)",
        "",
    ]
    if ref_missing_files:
        lines.append(f"⚠ Files not found, skipped: {', '.join(ref_missing_files)}")
        lines.append("")
    lines.append(f"{len(ref_results) - len(ref_missing)} / {len(ref_results)} modules found.")
    lines.append("")
    if ref_missing:
        lines += ["| Module | Status |", "|---|---|"]
        for r in ref_missing:
            lines.append(f"| `{r['module']}` | not mentioned in any REFERENCE_*.md heading |")
    else:
        lines.append("No drift found.")
    lines.append("")

    # C) Test counts
    count_drift = [r for r in count_results if r["status"] not in ("ok",)]
    lines += [
        "## C) Test counts — MAINTENANCE_*.md vs. docs/METRICS.md",
        "",
    ]
    if count_results:
        lines += ["| File | Test file | Status | Detail |", "|---|---|---|---|"]
        for r in count_results:
            lines.append(f"| {r['file']} | {r.get('test_file') or '—'} | {r['status']} | {r['detail']} |")
    else:
        lines.append("No 'Current count' lines found in any MAINTENANCE_*.md.")
    lines.append("")

    # D) README coverage
    lines += ["## D) Module mentioned in README.md (substring only)", ""]
    if not readme_available:
        lines.append(f"⚠ README.md not found at {README_FILE} — skipped.")
    else:
        readme_missing = [r for r in readme_results if r["status"] != "ok"]
        lines.append(f"{len(readme_results) - len(readme_missing)} / {len(readme_results)} modules found.")
        lines.append("")
        if readme_missing:
            lines += ["| Module | Status |", "|---|---|"]
            for r in readme_missing:
                lines.append(f"| `{r['module']}` | not found anywhere in README.md |")
        else:
            lines.append("No drift found.")
    lines.append("")

    return "\n".join(lines) + "\n"


def write_report(content: str) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(DOCS_DIR), prefix=".drift_", suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        Path(tmp_path).replace(OUTPUT_FILE)
    except OSError:
        Path(tmp_path).unlink(missing_ok=True)
        raise


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    any_drift = False
    content = "<!-- doc_guard.py aborted before producing a full report -->\n"

    try:
        shared_scripts, signatures = load_build_manifest()

        sig_results = check_signatures(signatures)
        ref_results, ref_missing_files = check_reference_coverage(shared_scripts)
        metrics_counts = load_metrics_counts()
        count_results = check_test_counts(metrics_counts)
        readme_results, readme_available = check_readme_coverage(shared_scripts)

        content = render_report(
            sig_results, ref_results, ref_missing_files,
            count_results, readme_results, readme_available,
        )

        any_drift = (
            any(r["status"] != "ok" for r in sig_results)
            or any(r["status"] != "ok" for r in ref_results)
            or any(r["status"] not in ("ok", "no_count_claimed") for r in count_results)
            or (readme_available and any(r["status"] != "ok" for r in readme_results))
        )

    except GuardError as e:
        content = f"<!-- doc_guard.py aborted: {e} -->\n\n# DOC_DRIFT_REPORT\n\nAborted: {e}\n"
        print(f"✗ Guard error: {e}", file=sys.stderr)
        return 1

    finally:
        # try/finally analogous to the test_critical_archive concept — the report is
        # written in every case, even on an unexpected error above.
        write_report(content)

    print(f"✓ {OUTPUT_FILE} written.")
    print("  Drift found." if any_drift else "  No drift found.")
    return 1 if any_drift else 0


if __name__ == "__main__":
    sys.exit(main())
