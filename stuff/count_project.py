"""
count_project.py — Needful Things
Counts lines / words / characters recursively from the project root.
Output: project_stats.md
"""

import os
from collections import defaultdict
from datetime import datetime

# --- Configuration ---
import sys as _sys
ROOT   = _sys.argv[1] if len(_sys.argv) > 1 else "."
OUTPUT = os.path.join(ROOT, "project_stats.md")

EXCLUDE_DIRS = {
    "__pycache__", ".git", "build", "dist",
    ".pytest_cache", ".mypy_cache", "venv", ".venv",
    "node_modules"
}

EXCLUDE_FILES = {
    "project_stats.md",  # don't count the own output
    "count_project.py",  # don't count itself
}

# Binary / assets — skipped completely
EXCLUDE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp", ".webp",  # images
    ".drawio",                                                           # diagrams
    ".exe", ".dll", ".pyd", ".so",                                       # Binaries
    ".zip", ".tar", ".gz",                                               # archives
    ".pyc",                                                              # Python cache
}

# File types that are counted — everything else goes to "Other"
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

# --- Data structure ---
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

# --- Scan ---
by_type = defaultdict(Stats)   # grouped by display label
total   = Stats()

for dirpath, dirnames, filenames in os.walk(ROOT):
    # Skip excluded folders (in place, so os.walk does not descend into them)
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

    for filename in filenames:
        if filename in EXCLUDE_FILES:
            continue

        filepath = os.path.join(dirpath, filename)
        ext = os.path.splitext(filename)[1].lower()

        # Skip binary / assets and files without an extension
        if not ext or ext in EXCLUDE_EXTENSIONS:
            continue

        label = KNOWN_TYPES.get(ext, f"Other ({ext})")

        lines, words, chars = count_file(filepath)
        by_type[label].add(lines, words, chars)
        total.add(lines, words, chars)

# --- Output ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

lines_out = []
lines_out.append(f"# Project statistics")
lines_out.append(f"")
lines_out.append(f"*Generated: {now}*")
lines_out.append(f"")
lines_out.append(f"---")
lines_out.append(f"")

# Table by file type — sorted by characters, descending
lines_out.append(f"## By file type")
lines_out.append(f"")
lines_out.append(f"| Type | Files | Lines | Words | Characters |")
lines_out.append(f"|---|---:|---:|---:|---:|")

for label in sorted(by_type, key=lambda k: by_type[k].chars, reverse=True):
    s = by_type[label]
    lines_out.append(
        f"| {label} | {s.files:,} | {s.lines:,} | {s.words:,} | {s.chars:,} |"
    )

lines_out.append(f"")
lines_out.append(f"---")
lines_out.append(f"")
lines_out.append(f"## Total")
lines_out.append(f"")
lines_out.append(f"| | Value |")
lines_out.append(f"|---|---:|")
lines_out.append(f"| Files | {total.files:,} |")
lines_out.append(f"| Lines  | {total.lines:,} |")
lines_out.append(f"| Words  | {total.words:,} |")
lines_out.append(f"| Characters | {total.chars:,} |")
lines_out.append(f"")

output_text = "\n".join(lines_out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Done — {OUTPUT} written.")
print(f"  Files:   {total.files:,}")
print(f"  Lines:  {total.lines:,}")
print(f"  Words:  {total.words:,}")
print(f"  Chars:  {total.chars:,}")
