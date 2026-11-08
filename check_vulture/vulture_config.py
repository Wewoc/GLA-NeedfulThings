"""
vulture_config.py
Needful Things — Dead Code Finder · Configuration

Location: check_vulture/
Usage:    run_vulture_check.bat  (or: python check_vulture.py)
Output:   output/vulture.json   (path set below)

Every value below is a placeholder for an imaginary project — adjust SRC_ROOT.
"""

# ── Paths ──────────────────────────────────────────────────────────────────────
# Source root that Vulture scans. Relative to the location of this script
# (check_vulture/), or absolute. Vulture runs from this folder, so reported
# paths are relative to it.

SRC_ROOT = "../my_project/src"    # adjust!

# Name of the tests folder directly below SRC_ROOT. Run A (production) leaves it
# out, Run B (production + tests) scans it.
TESTS_DIR = "tests"

# Folders directly below SRC_ROOT that are scanned in NEITHER run: build-only
# tooling, standalone probe scripts, anything that is not shipped code.
EXCLUDED_ALWAYS = []              # example: ["build", "tools"]

# Vulture's minimum confidence for a finding (60 = unused functions, classes,
# methods, attributes, imports; 100 = unused imports and unreachable code only).
MIN_CONFIDENCE = 60

# ── Output ────────────────────────────────────────────────────────────────────
# Result file, relative to this folder. Holds scan time, versions, whitelist count
# and every finding — other tools can read it.

OUTPUT_FILE = "output/vulture.json"

# Optional: file that holds the project version, written into the result.
# None = no version recorded. VERSION_VARIABLE is the name of the assignment in it.
VERSION_FILE     = None           # example: "../my_project/src/version.py"
VERSION_VARIABLE = "APP_VERSION"

# ── Whitelist ──────────────────────────────────────────────────────────────────
# Confirmed false positives: {(file, name): "reason"}. Filtered AFTER the Vulture
# run, scoped by file — so a generic attribute name is only suppressed where it is
# a confirmed false positive, not wherever else that name appears.
#
# file: exactly as Vulture reports it, relative to SRC_ROOT. Backslashes and
#       forward slashes are treated alike when matching.
# Vulture cannot see code that is reached only by name or by decorator — GUI
# event handlers called by the framework, plugin or tool registration, attributes
# that a library reads internally. Those show up as "unused" although they are
# load-bearing.
#
# Build this from real findings, not preemptively. Keep entries narrow — one
# (file, name) pair per confirmed false positive, with a reason a future reader
# can verify without re-deriving it.

VULTURE_WHITELIST: dict[tuple[str, str], str] = {
    # ("ui/panel.py", "mousePressEvent"): "GUI event handler, called by the framework",
}
