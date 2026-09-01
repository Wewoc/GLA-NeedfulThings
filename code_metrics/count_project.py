"""
count_project.py — code_metrics
Recursively counts lines / words / characters starting from the project
root.

Output: project_stats.md
"""

import os
from collections import defaultdict
from datetime import datetime

# --- Configuration ---
from metrics_config import PROJECT_ROOT as ROOT, OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT = os.path.join(OUTPUT_DIR, "project_stats.md")

EXCLUDE_DIRS = {
    "__pycache__", ".git", "build", "dist",
    ".pytest_cache", ".mypy_cache", "venv", ".venv",
    "node_modules"
}

EXCLUDE_FILES = {
    "project_stats.md",   # don't count our own output
    "count_project.py",   # don't count ourselves
}

# Binary / assets — skipped entirely
EXCLUDE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp", ".webp",  # images
    ".drawio",                                                          # diagrams
    ".exe", ".dll", ".pyd", ".so",                                      # binaries
    ".zip", ".tar", ".gz",                                              # archives
    ".pyc",                                                             # python cache
}

# File types that get counted individually — everything else lands in "Other"
KNOWN_TYPES = {
    ".py":   "Python",
    ".md":   "Markdown",
    ".json": "JSON",
    ".bat":  "Batch",
    ".txt":  "Text",
    ".html": "HTML",
    ".css":  "CSS",
    ".js":   "JavaScript",
    ".xml":  "XML",
    ".ini":  "INI / Config",
    ".cfg":  "INI / Config",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml":  "YAML",
    ".spec": "PyInstaller Spec",
}

# --- Data structures ---
class Stats:
    def __init__(self):
        self.files = 0
        self.lines = 0
        self.words = 0
        self.chars = 0

    def add(self, lines, words, chars):
        self.files += 1
        self.lines += lines
        self.words += words
        self.chars += chars

# Python files only: code vs. prose lines (comments + docstrings)
class PyStats:
    def __init__(self):
        self.code_lines  = 0
        self.prose_lines = 0

    def add(self, code_lines, prose_lines):
        self.code_lines  += code_lines
        self.prose_lines += prose_lines

def count_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        words = len(content.split())
        chars = len(content)
        return lines, words, chars
    except Exception:
        return 0, 0, 0

def analyze_python_file(path):
    """
    Line-by-line heuristic separating code from prose (comments +
    docstrings).
    - Blank lines count toward neither.
    - Pure comment lines (start with '#' after strip()) -> prose.
    - Lines inside a docstring block (''' or \"\"\") -> prose.
    - Inline comments after code (x = 1  # comment) -> code
      (the line contains code, so it counts as a code line).
    Not an AST parser — multi-line string literals using \"\"\"/''' in
    actual code (e.g. SQL strings) will be misdetected as
    docstring/prose. Accepted trade-off for a rough-order metric.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except Exception:
        return 0, 0

    code_lines  = 0
    prose_lines = 0
    in_docstring = False
    docstring_delim = None

    for raw_line in raw_lines:
        stripped = raw_line.strip()

        if not stripped:
            continue  # blank line — counts toward neither

        if in_docstring:
            prose_lines += 1
            if docstring_delim in stripped:
                in_docstring = False
                docstring_delim = None
            continue

        if stripped.startswith("#"):
            prose_lines += 1
            continue

        # Detect docstring start (line begins with """ or ''')
        for delim in ('"""', "'''"):
            if stripped.startswith(delim):
                prose_lines += 1
                rest = stripped[len(delim):]
                # Single-line docstring: """text""" complete on one line
                if delim in rest:
                    break
                in_docstring = True
                docstring_delim = delim
                break
        else:
            code_lines += 1

    return code_lines, prose_lines

# --- Scan ---
by_type = defaultdict(Stats)   # grouped by display label
total   = Stats()
py_total = PyStats()           # code/prose split, Python only

for dirpath, dirnames, filenames in os.walk(ROOT):
    # Skip excluded dirs in-place so os.walk doesn't descend into them
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

    for filename in filenames:
        if filename in EXCLUDE_FILES:
            continue

        filepath = os.path.join(dirpath, filename)
        ext = os.path.splitext(filename)[1].lower()

        # Skip binaries/assets and extensionless files
        if not ext or ext in EXCLUDE_EXTENSIONS:
            continue

        label = KNOWN_TYPES.get(ext, f"Other ({ext})")

        lines, words, chars = count_file(filepath)
        by_type[label].add(lines, words, chars)
        total.add(lines, words, chars)

        if ext == ".py":
            code_lines, prose_lines = analyze_python_file(filepath)
            py_total.add(code_lines, prose_lines)

# --- Output ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

lines_out = []
lines_out.append(f"# Project Statistics")
lines_out.append(f"")
lines_out.append(f"*Generated: {now}*")
lines_out.append(f"")
lines_out.append(f"---")
lines_out.append(f"")

# Table by file type — sorted by character count, descending
lines_out.append(f"## By File Type")
lines_out.append(f"")
lines_out.append(f"| Type | Files | Lines | Words | Characters |")
lines_out.append(f"|---|---:|---:|---:|---:|")

for label in sorted(by_type, key=lambda k: by_type[k].chars, reverse=True):
    s = by_type[label]
    lines_out.append(
        f"| {label} | {s.files:,} | {s.lines:,} | {s.words:,} | {s.chars:,} |"
    )

lines_out.append(f"")

# Extra table, Python only — code vs. prose (comments + docstrings)
py_relevant_lines = py_total.code_lines + py_total.prose_lines
prose_pct = (py_total.prose_lines / py_relevant_lines * 100) if py_relevant_lines else 0.0

lines_out.append(f"## Python — Code vs. Prose")
lines_out.append(f"")
lines_out.append(f"| | Lines | Share |")
lines_out.append(f"|---|---:|---:|")
lines_out.append(f"| Code lines | {py_total.code_lines:,} | {100 - prose_pct:.1f}% |")
lines_out.append(f"| Comments/Docstrings | {py_total.prose_lines:,} | {prose_pct:.1f}% |")
lines_out.append(f"")
lines_out.append(f"*Heuristic: blank lines excluded, base = code + comments/docstrings. Inline comments count as code lines.*")
lines_out.append(f"")

lines_out.append(f"---")
lines_out.append(f"")
lines_out.append(f"## Totals")
lines_out.append(f"")
lines_out.append(f"| | Value |")
lines_out.append(f"|---|---:|")
lines_out.append(f"| Files | {total.files:,} |")
lines_out.append(f"| Lines | {total.lines:,} |")
lines_out.append(f"| Words | {total.words:,} |")
lines_out.append(f"| Characters | {total.chars:,} |")
lines_out.append(f"")

output_text = "\n".join(lines_out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Done — {OUTPUT} written.")
print(f"  Files:      {total.files:,}")
print(f"  Lines:      {total.lines:,}")
print(f"  Words:      {total.words:,}")
print(f"  Characters: {total.chars:,}")
