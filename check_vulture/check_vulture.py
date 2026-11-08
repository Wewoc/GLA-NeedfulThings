# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
check_vulture.py — Dead Code Finder
Needful Things · report tool · no project imports

Runs Vulture twice against the source folder set in vulture_config.py:
  Run A ("production")       — everything except the tests folder and the
                                folders in EXCLUDED_ALWAYS (build-only or
                                standalone tooling that is not shipped code)
  Run B ("production+tests") — Run A's scope plus the tests folder

Run B's scope is a superset of Run A's, so Run B can only ever find a
subset of what Run A finds (more references, never fewer). That means
Run A alone is the complete list of dead-code candidates — Run B is used
only to label each Run A finding, not as a second independent check:
  dead_everywhere — still unused even counting tests (Run B finds it too)
  test_only       — only a test references it; production never calls it

Both runs are filtered against VULTURE_WHITELIST (vulture_config.py)
AFTER parsing — not fed to Vulture as a scan path. Vulture's own
whitelist mechanism matches by name only, with no way to scope an entry
to one file; a (file, name) filter here avoids a generic attribute name
(e.g. "alignment") suppressing a genuinely dead one elsewhere just
because it shares a name with a confirmed false positive.

This tool never blocks a build or a test run by itself. It is meant to be
read by a human (run_vulture_check.bat), for example as a check before a
release or a documentation round. It writes the result to OUTPUT_FILE
(vulture.json), which other tools can read.

Exit code: 0 only if Run A found nothing (after whitelist) — i.e. both
runs are clean, since Run B can't find more than Run A. Non-zero
otherwise. This is a signal for the human running it, not a build gate.

Needs Vulture in the interpreter that runs this script (pip install vulture).

Run via run_vulture_check.bat, or standalone:
    python check_vulture.py [--target-version vX.Y.Z]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import importlib.util

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "vulture_config.py"


def load_config():
    """Import vulture_config.py from next to this script; stop with a clear message if it is unusable."""
    if not CONFIG_FILE.exists():
        sys.exit(f"config not found: {CONFIG_FILE}")
    spec = importlib.util.spec_from_file_location("vulture_config", CONFIG_FILE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # any error inside the config is reported the same way
        sys.exit(f"cannot load {CONFIG_FILE.name}: {exc!r}")
    missing = [n for n in ("SRC_ROOT", "VULTURE_WHITELIST") if not hasattr(module, n)]
    if missing:
        sys.exit(f"{CONFIG_FILE.name}: missing setting(s): {', '.join(missing)}")
    if not isinstance(module.VULTURE_WHITELIST, dict):
        sys.exit(f"{CONFIG_FILE.name}: VULTURE_WHITELIST must be a dict {{(file, name): reason}}")
    return module


CFG = load_config()
SRC_DIR = (HERE / CFG.SRC_ROOT).resolve()
VERSION_FILE = (HERE / CFG.VERSION_FILE).resolve() if getattr(CFG, "VERSION_FILE", None) else None
VERSION_VARIABLE = getattr(CFG, "VERSION_VARIABLE", "APP_VERSION")
OUTPUT_FILE = (HERE / getattr(CFG, "OUTPUT_FILE", "output/vulture.json")).resolve()
TESTS_DIR = getattr(CFG, "TESTS_DIR", "tests")
MIN_CONFIDENCE = getattr(CFG, "MIN_CONFIDENCE", 60)
VULTURE_WHITELIST = CFG.VULTURE_WHITELIST

# Relative to SRC_DIR. Excluded from BOTH runs — not project source
# (build-only tooling, standalone probe scripts, ...). Set in vulture_config.py.
EXCLUDED_ALWAYS = list(getattr(CFG, "EXCLUDED_ALWAYS", []))

_REPORT_LINE_RE = re.compile(
    r"^(?P<file>.+):(?P<line>\d+): (?P<kind>unused \S+) '(?P<name>[^']+)' "
    r"\((?P<confidence>\d+)% confidence\)$"
)


# ─── Vulture invocation ──────────────────────────────────────────────────────


def _scan_paths(include_tests: bool) -> list[str]:
    excluded = set(EXCLUDED_ALWAYS)
    if not include_tests:
        excluded.add(TESTS_DIR)

    paths = [
        p.name for p in SRC_DIR.iterdir()
        if p.name not in excluded
    ]
    return paths


def run_vulture(include_tests: bool) -> list[dict] | None:
    """
    Runs `python -m vulture <scan paths>` from SRC_DIR, so reported paths
    are relative and identical between both runs (needed to match findings
    across Run A / Run B by file+line+name). Whitelist filtering happens
    afterward, in filter_whitelisted() — not passed to Vulture here.

    Returns parsed findings, or None if Vulture itself could not be run
    (not installed, etc.) — reported as a finding, never raised.
    """
    paths = _scan_paths(include_tests)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "vulture", *paths,
             "--min-confidence", str(MIN_CONFIDENCE)],
            cwd=str(SRC_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None

    findings = []
    for line in result.stdout.splitlines():
        m = _REPORT_LINE_RE.match(line.strip())
        if m:
            findings.append({
                "file":       m.group("file"),
                "line":       int(m.group("line")),
                "kind":       m.group("kind"),
                "name":       m.group("name"),
                "confidence": int(m.group("confidence")),
            })
    return findings


# ─── Whitelist filtering ─────────────────────────────────────────────────────


def filter_whitelisted(findings: list[dict]) -> tuple[list[dict], int]:
    """
    Drops findings whose (file, name) pair is a confirmed false positive in
    VULTURE_WHITELIST (vulture_config.py). Scoped by file, not by name alone —
    see check_vulture.py's module docstring for why.

    File paths are compared with backslashes normalized to forward slashes
    on both sides: whitelist keys written from a Windows run use
    backslashes, while Vulture on Linux reports forward slashes — without
    normalizing, every whitelist entry with a subdirectory silently fails
    to match.

    Returns (remaining findings, count filtered out).
    """
    whitelist = {
        (file.replace("\\", "/"), name): reason
        for (file, name), reason in VULTURE_WHITELIST.items()
    }
    remaining = [
        f for f in findings
        if (f["file"].replace("\\", "/"), f["name"]) not in whitelist
    ]
    return remaining, len(findings) - len(remaining)


# ─── Delta labeling ──────────────────────────────────────────────────────────


def label_findings(findings_a: list[dict], findings_b: list[dict]) -> list[dict]:
    keys_b = {(f["file"], f["line"], f["name"]) for f in findings_b}
    labeled = []
    for f in findings_a:
        key = (f["file"], f["line"], f["name"])
        status = "dead_everywhere" if key in keys_b else "test_only"
        labeled.append({**f, "status": status})
    return labeled


# ─── version.py lookup ───────────────────────────────────────────────────────


def read_current_version() -> str | None:
    if VERSION_FILE is None or not VERSION_FILE.exists():
        return None
    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(re.escape(VERSION_VARIABLE) + r'''\s*=\s*['"]([^'"]+)['"]''', text)
    return m.group(1) if m else None


# ─── vulture.json ────────────────────────────────────────────────────────────


def write_result_json(findings: list[dict], target_version: str | None, whitelisted: int) -> None:
    content = {
        "scanned_at":         datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "current_version":    read_current_version(),
        "target_version":     target_version,
        "whitelisted_count":  whitelisted,
        "total_findings":     len(findings),
        "findings":           findings,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ─── Report ──────────────────────────────────────────────────────────────────


def build_report(findings: list[dict]) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("VULTURE DEAD CODE CHECK")
    lines.append("=" * 70)
    lines.append("")

    if not findings:
        lines.append("OK - no unused code found (production + test-only both clean).")
        lines.append("")
        return "\n".join(lines)

    dead_everywhere = [f for f in findings if f["status"] == "dead_everywhere"]
    test_only = [f for f in findings if f["status"] == "test_only"]

    for label, group in [
        ("DEAD EVERYWHERE - unused in production AND in tests", dead_everywhere),
        ("TEST-ONLY - production never calls this, a test still does", test_only),
    ]:
        if not group:
            continue
        lines.append("-" * 70)
        lines.append(label)
        lines.append("-" * 70)
        for f in group:
            lines.append(
                f"  {f['file']}:{f['line']}: {f['kind']} '{f['name']}' "
                f"({f['confidence']}% confidence)"
            )
        lines.append("")

    lines.append("-" * 70)
    lines.append(
        f"Summary: {len(dead_everywhere)} dead everywhere, "
        f"{len(test_only)} test-only - {len(findings)} total findings."
    )
    lines.append(
        "Confirmed false positive? Add it to VULTURE_WHITELIST in vulture_config.py, not here."
    )
    lines.append("")

    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-version", default=None)
    args = parser.parse_args()

    print("check_vulture - dead code finder")
    print()

    if not SRC_DIR.is_dir():
        print(f"Source folder not found: {SRC_DIR}")
        print("  Check SRC_ROOT in vulture_config.py.")
        return 1

    findings_a = run_vulture(include_tests=False)
    if findings_a is None:
        print("Vulture could not be run (not installed?).")
        print("  Install with: pip install vulture")
        return 1

    findings_b = run_vulture(include_tests=True)
    if findings_b is None:
        print("Vulture could not be run (not installed?).")
        print("  Install with: pip install vulture")
        return 1

    findings_a, whitelisted_a = filter_whitelisted(findings_a)
    findings_b, _ = filter_whitelisted(findings_b)

    labeled = label_findings(findings_a, findings_b)
    print(build_report(labeled))
    if whitelisted_a:
        print(f"({whitelisted_a} finding(s) suppressed via VULTURE_WHITELIST)")
        print()

    write_result_json(labeled, args.target_version, whitelisted_a)
    print(f"Result written to {OUTPUT_FILE}")

    return 1 if labeled else 0


if __name__ == "__main__":
    sys.exit(main())
