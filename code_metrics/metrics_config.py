"""
metrics_config.py — code_metrics
Central configuration for all metric scripts in this folder.
Single place where PROJECT_ROOT and OUTPUT_DIR are maintained —
count_project.py, list_functions.py, list_gui_bindings.py,
list_longest_functions.py, list_complexity.py and build_profile.py
all import from here instead of expecting their own command-line
arguments.

Must live in the same folder as the other scripts (relative import).
"""

import os

# Path to the repo root to scan, relative to this folder (code_metrics/).
# This is the source of the metrics, but it is NOT used as the report
# output location — see OUTPUT_DIR below.
PROJECT_ROOT = "../your_project"

# Folder where all reports are written — project_stats.md, FUNCTION_MAP.md,
# GUI_BINDINGS.md, LONGEST_FUNCTIONS.md, COMPLEXITY_MAP.md, PROJECT_PROFILE.md.
# Lives next to the scripts (code_metrics/output/), not inside the scanned
# project. Created automatically by the scripts if it doesn't exist.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")
