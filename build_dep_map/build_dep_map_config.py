"""
build_dep_map_config.py
needfull things — Dependency Map Generator · Configuration

Location: build_dep_map/
Usage:    run_dep_map.bat  (or: python build_dep_map.py)
Output:   output/YYYY-MM-DD_Run-NN/dep_map.md
          output/YYYY-MM-DD_Run-NN/dep_map.csv
          output/YYYY-MM-DD_Run-NN/dep_map_records.json
          output/YYYY-MM-DD_Run-NN/delta/dep_map_delta.md  (if baseline present)
"""

# ── Paths ──────────────────────────────────────────────────────────────────────
# Relative to the location of this script (build_dep_map/)

SCAN_ROOT   = "../my_project/src"   # source root — adjust!
OUTPUT_BASE = "output"                            # output base directory

# ── Baseline / Delta ──────────────────────────────────────────────────────────
# Controls whether and how a baseline is used for delta comparison.
#
# "auto_last" — automatically use the last dep_map_records.json in the output
#               directory as baseline. Recommended: no manual intervention needed.
#               First run (no previous snapshot yet): delta step is skipped.
#
# "none"      — Disable delta entirely. Absolute output only, no comparison.
#
# CLI override: --baseline <path> always takes precedence over this setting.

BASELINE_MODE = "auto_last"

# ── Exclusions ───────────────────────────────────────────────────────────────
# Directory names (not paths) — applies at all levels

EXCLUDE_DIRS = [
    "tests",
    "docs",
    "screenshots",
    # "scheduler",      # example: exclude background job directories
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
]

# Individual file names to skip (regardless of directory)
EXCLUDE_FILES = [
    "conftest.py",
    "build_dep_map.py",     # don't scan itself
]

# ── External packages — display filter ───────────────────────────────────────
# Known external packages — marked as "(external)" in the MD,
# not counted as internal dependencies.
# Extend when new dependencies are added.

KNOWN_EXTERNAL = [
    # Stdlib (commonly used — list is not exhaustive; anything without a
    # matching .py in the project is automatically treated as external)
    "os", "sys", "re", "json", "csv", "logging", "pathlib", "datetime",
    "hashlib", "shutil", "time", "threading", "traceback", "importlib",
    "functools", "collections", "typing", "dataclasses", "contextlib",
    "io", "copy", "math", "enum", "abc", "warnings", "urllib", "http",
    "socket", "struct", "base64", "hmac", "secrets", "tempfile",
    "subprocess", "platform", "locale", "gc", "weakref", "inspect",
    # Third-party (examples — adjust to your project)
    "PyQt6", "PyQt5",
    "openpyxl",
    "plotly",
    "cryptography",
    "keyring",
    "requests",
    "aiohttp",
    "numpy",
    "pandas",
    "pytest",
    "ruff",
]
