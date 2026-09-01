"""
list_longest_functions.py — code_metrics
Reads FUNCTION_MAP.md and filters all functions/methods over the
refactor-warning threshold (line length). Pure text parsing of the
existing table — no new AST scan.

Guideline values (rules-of-thumb from style guides/static analysis
tools, not a strict standard):
  <= 50 lines    — unremarkable, not listed
  51-100 lines   — candidate for splitting
  > 100 lines    — clear refactoring candidate

Order matters: run list_functions.py first, then this script.

Output: LONGEST_FUNCTIONS.md

Usage:  python list_longest_functions.py
"""

import os
import re
from datetime import datetime

from metrics_config import OUTPUT_DIR

PATH_FUNCTION_MAP = os.path.join(OUTPUT_DIR, "FUNCTION_MAP.md")
OUTPUT             = os.path.join(OUTPUT_DIR, "LONGEST_FUNCTIONS.md")

WARN_THRESHOLD  = 50    # candidate from here
CRIT_THRESHOLD  = 100   # clear candidate from here

# Line format from FUNCTION_MAP.md:
# | 261 | method | PanelHome | _on_daily_sync | 14 |
ROW_PATTERN = re.compile(
    r'^\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*([^\|]*)\|\s*([^\|]+?)\s*\|\s*(\d+)\s*\|\s*$'
)
FILE_HEADER_PATTERN = re.compile(r'^### (.+)$')


def parse_function_map(content):
    """
    Parses FUNCTION_MAP.md line by line. Tracks the current file via the
    '### {path}' headers and assigns each table row to the most recently
    seen file.
    Returns a list of dicts: file, lineno, kind, class_name, name, line_count
    """
    entries = []
    current_file = None

    for line in content.splitlines():
        header_match = FILE_HEADER_PATTERN.match(line)
        if header_match:
            current_file = header_match.group(1).strip()
            continue

        row_match = ROW_PATTERN.match(line)
        if row_match and current_file:
            lineno, kind, class_name, name, line_count = row_match.groups()
            entries.append({
                "file": current_file,
                "lineno": int(lineno),
                "kind": kind.strip(),
                "class_name": class_name.strip(),
                "name": name.strip(),
                "line_count": int(line_count),
            })

    return entries


if not os.path.isfile(PATH_FUNCTION_MAP):
    print(f"ERROR: {PATH_FUNCTION_MAP} not found — run list_functions.py first.")
    raise SystemExit(1)

with open(PATH_FUNCTION_MAP, encoding="utf-8", errors="replace") as f:
    map_content = f.read()

all_entries = parse_function_map(map_content)

over_warn = [e for e in all_entries if e["line_count"] > WARN_THRESHOLD]
over_warn.sort(key=lambda e: e["line_count"], reverse=True)

count_warn = sum(1 for e in over_warn if WARN_THRESHOLD < e["line_count"] <= CRIT_THRESHOLD)
count_crit = sum(1 for e in over_warn if e["line_count"] > CRIT_THRESHOLD)

# --- Output ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

out = []
out.append("# Longest Functions")
out.append("")
out.append(f"*Generated: {now}*")
out.append("")
out.append(
    f"All functions/methods from FUNCTION_MAP.md over {WARN_THRESHOLD} lines, "
    "sorted descending. Guideline values from common style guides/static "
    "analysis tools (not a strict standard): "
    f"**{WARN_THRESHOLD+1}–{CRIT_THRESHOLD} lines** = candidate for splitting, "
    f"**>{CRIT_THRESHOLD} lines** = clear refactoring candidate. "
    "Raw line length alone is not a complete health metric — a long, "
    "linear function can be less problematic than a short one with deep "
    "nesting. Still useful as an outlier radar."
)
out.append("")
out.append("---")
out.append("")
out.append("## Summary")
out.append("")
out.append("| | Count |")
out.append("|---|---:|")
out.append(f"| Functions total | {len(all_entries):,} |")
out.append(f"| Over warning threshold ({WARN_THRESHOLD}+ lines) total | {len(over_warn):,} |")
out.append(f"| of which candidate ({WARN_THRESHOLD+1}-{CRIT_THRESHOLD} lines) | {count_warn:,} |")
out.append(f"| of which clear candidate (>{CRIT_THRESHOLD} lines) | {count_crit:,} |")
out.append("")

if over_warn:
    out.append("---")
    out.append("")
    out.append("## Details")
    out.append("")
    out.append("| Lines | Rating | File | Class | Name | Line |")
    out.append("|---:|---|---|---|---|---:|")
    for e in over_warn:
        rating = "clear candidate" if e["line_count"] > CRIT_THRESHOLD else "candidate"
        class_col = e["class_name"] if e["class_name"] else ""
        out.append(
            f"| {e['line_count']} | {rating} | {e['file']} | {class_col} | {e['name']} | {e['lineno']} |"
        )
    out.append("")
else:
    out.append(f"No function over {WARN_THRESHOLD} lines found.")
    out.append("")

output_text = "\n".join(out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Done — {OUTPUT} written.")
print(f"  Over warning threshold: {len(over_warn):,}")
print(f"    Candidate ({WARN_THRESHOLD+1}-{CRIT_THRESHOLD}): {count_warn:,}")
print(f"    Clear candidate (>{CRIT_THRESHOLD}): {count_crit:,}")
if over_warn:
    top = over_warn[0]
    print(f"  Longest function: {top['name']} ({top['line_count']} lines, {top['file']}:{top['lineno']})")
