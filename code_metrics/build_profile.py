"""
build_profile.py — code_metrics
Reads the individual reports (project_stats.md, FUNCTION_MAP.md,
GUI_BINDINGS.md, LONGEST_FUNCTIONS.md) and aggregates their key figures
into one overall project profile.

Pure text parsing of the summary tables — no new scan.
Order matters: run count_project.py, list_functions.py,
list_gui_bindings.py and list_longest_functions.py first, then this
script.

Output: PROJECT_PROFILE.md

Usage:  python build_profile.py [PROJECT_ROOT]
        PROJECT_ROOT default = "."
"""

import os
import re
from datetime import datetime

from metrics_config import PROJECT_ROOT as ROOT, OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)

PATH_PROJECT_STATS = os.path.join(OUTPUT_DIR, "project_stats.md")
PATH_FUNCTION_MAP  = os.path.join(OUTPUT_DIR, "FUNCTION_MAP.md")
PATH_GUI_BINDINGS  = os.path.join(OUTPUT_DIR, "GUI_BINDINGS.md")
OUTPUT              = os.path.join(OUTPUT_DIR, "PROJECT_PROFILE.md")


def read_file_safe(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def extract_table_value(content, row_label):
    """
    Searches a markdown table for a row starting with '| {row_label}'
    (whitespace-tolerant) and returns the FIRST numerically parseable
    column after it. Tables have either 1 or 2 data columns depending on
    the report (e.g. "Lines | Share") — so instead of a fixed column
    index, this returns the first cell that parses as a number (percent
    columns with '%' are skipped, since they could otherwise be confused
    with absolute values).
    Commas in numbers are stripped (1,234 -> 1234).
    Returns None if not found or no column is numeric.
    """
    if content is None:
        return None

    pattern = re.compile(
        r'^\|\s*' + re.escape(row_label) + r'\s*\|(.+)\|\s*$',
        re.MULTILINE
    )
    match = pattern.search(content)
    if not match:
        return None

    cols = [c.strip() for c in match.group(1).split("|")]

    for col in cols:
        if col.endswith("%"):
            continue  # skip percent columns — absolute number preferred
        raw = col.replace(",", "").strip()
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            continue

    return None


# --- Read individual reports ---
stats_content    = read_file_safe(PATH_PROJECT_STATS)
functions_content = read_file_safe(PATH_FUNCTION_MAP)
gui_content       = read_file_safe(PATH_GUI_BINDINGS)

missing_reports = []
if stats_content is None:
    missing_reports.append("project_stats.md")
if functions_content is None:
    missing_reports.append("FUNCTION_MAP.md")
if gui_content is None:
    missing_reports.append("GUI_BINDINGS.md")

# --- Extract values ---
total_files = extract_table_value(stats_content, "Files")
total_lines = extract_table_value(stats_content, "Lines")
total_words = extract_table_value(stats_content, "Words")
total_chars = extract_table_value(stats_content, "Characters")

py_code_lines  = extract_table_value(stats_content, "Code lines")
py_prose_lines = extract_table_value(stats_content, "Comments/Docstrings")

func_total  = extract_table_value(functions_content, "Functions total")
func_module = extract_table_value(functions_content, "of which module functions")
func_method = extract_table_value(functions_content, "of which methods")
func_local  = extract_table_value(functions_content, "of which local functions/closures")
class_total = extract_table_value(functions_content, "Classes")

gui_total  = extract_table_value(gui_content, "Bindings total")
gui_widget = extract_table_value(gui_content, "of which widget signals (clicked/toggled/...)")
gui_custom = extract_table_value(gui_content, "of which other/custom signals")

PATH_LONGEST_FUNCTIONS = os.path.join(OUTPUT_DIR, "LONGEST_FUNCTIONS.md")
longest_content = read_file_safe(PATH_LONGEST_FUNCTIONS)
if longest_content is None:
    missing_reports.append("LONGEST_FUNCTIONS.md")

longest_over_warn = extract_table_value(longest_content, "Over warning threshold (50+ lines) total")
longest_candidate = extract_table_value(longest_content, "of which candidate (51-100 lines)")
longest_critical  = extract_table_value(longest_content, "of which clear candidate (>100 lines)")

# Extract the single longest function from the details table (first data
# row after the header — the list is already sorted descending).
longest_name = None
longest_lines = None
longest_file = None
if longest_content:
    detail_match = re.search(
        r'\|\s*(\d+)\s*\|\s*[^\|]*\|\s*([^\|]+?)\s*\|[^\|]*\|\s*([^\|]+?)\s*\|\s*\d+\s*\|',
        longest_content
    )
    if detail_match:
        longest_lines = int(detail_match.group(1))
        longest_file  = detail_match.group(2).strip()
        longest_name  = detail_match.group(3).strip()

# --- Output ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

out = []
out.append("# Project Profile")
out.append("")
out.append(f"*Generated: {now}*")
out.append("")
out.append(
    "Aggregation from project_stats.md, FUNCTION_MAP.md and "
    "GUI_BINDINGS.md. All values are derived heuristically (line-counting "
    "heuristic or AST parse) — see the individual reports for details and "
    "limitations."
)
out.append("")

if missing_reports:
    out.append("> **Warning:** the following reports were missing during "
                "aggregation — affected values are blank:")
    for r in missing_reports:
        out.append(f"> - `{r}`")
    out.append("")

out.append("---")
out.append("")
out.append("## Scope")
out.append("")
out.append("| | Value |")
out.append("|---|---:|")
out.append(f"| Files total | {total_files if total_files is not None else '—':,} |" if isinstance(total_files, int) else f"| Files total | — |")
out.append(f"| Lines total | {total_lines:,} |" if isinstance(total_lines, int) else "| Lines total | — |")
out.append(f"| Words total | {total_words:,} |" if isinstance(total_words, int) else "| Words total | — |")
out.append(f"| Characters total | {total_chars:,} |" if isinstance(total_chars, int) else "| Characters total | — |")
out.append("")

out.append("## Python — Code vs. Prose")
out.append("")
out.append("| | Lines |")
out.append("|---|---:|")
out.append(f"| Functional code | {py_code_lines:,} |" if isinstance(py_code_lines, int) else "| Functional code | — |")
out.append(f"| Comments/Docstrings | {py_prose_lines:,} |" if isinstance(py_prose_lines, int) else "| Comments/Docstrings | — |")
out.append("")

out.append("## Functions & Classes")
out.append("")
out.append("| | Count |")
out.append("|---|---:|")
out.append(f"| Functions total | {func_total:,} |" if isinstance(func_total, int) else "| Functions total | — |")
out.append(f"| of which module functions | {func_module:,} |" if isinstance(func_module, int) else "| of which module functions | — |")
out.append(f"| of which methods | {func_method:,} |" if isinstance(func_method, int) else "| of which methods | — |")
out.append(f"| of which local functions/closures | {func_local:,} |" if isinstance(func_local, int) else "| of which local functions/closures | — |")
out.append(f"| Classes | {class_total:,} |" if isinstance(class_total, int) else "| Classes | — |")
out.append("")

out.append("## GUI Bindings")
out.append("")
out.append(
    "*Recursive project-wide scan — see GUI_BINDINGS.md for scope details "
    "if EXCLUDE_DIRS/EXCLUDE_FILES were customized.*"
)
out.append("")
out.append("| | Count |")
out.append("|---|---:|")
out.append(f"| Bindings total | {gui_total:,} |" if isinstance(gui_total, int) else "| Bindings total | — |")
out.append(f"| of which widget signals | {gui_widget:,} |" if isinstance(gui_widget, int) else "| of which widget signals | — |")
out.append(f"| of which other/custom signals | {gui_custom:,} |" if isinstance(gui_custom, int) else "| of which other/custom signals | — |")
out.append("")

out.append("## Refactoring Candidates")
out.append("")
out.append(
    "*Basis: LONGEST_FUNCTIONS.md — functions over 50 lines. Raw line "
    "length is an outlier radar, not a complete health metric — see the "
    "individual report for details.*"
)
out.append("")
out.append("| | Value |")
out.append("|---|---:|")
out.append(f"| Over warning threshold (50+ lines) | {longest_over_warn:,} |" if isinstance(longest_over_warn, int) else "| Over warning threshold (50+ lines) | — |")
out.append(f"| of which candidate (51-100 lines) | {longest_candidate:,} |" if isinstance(longest_candidate, int) else "| of which candidate (51-100 lines) | — |")
out.append(f"| of which clear candidate (>100 lines) | {longest_critical:,} |" if isinstance(longest_critical, int) else "| of which clear candidate (>100 lines) | — |")
if longest_name:
    out.append(f"| Longest function | {longest_name} ({longest_lines} lines, {longest_file}) |")
else:
    out.append("| Longest function | — |")
out.append("")

output_text = "\n".join(out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Done — {OUTPUT} written.")
if missing_reports:
    print(f"  WARNING: missing reports: {', '.join(missing_reports)}")
