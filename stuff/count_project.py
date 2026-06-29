"""
count_project.py — Garmin Local Archive
Zählt Zeilen / Wörter / Zeichen rekursiv ab Projektroot.
Ausgabe: project_stats.md
"""

import os
from collections import defaultdict
from datetime import datetime

# --- Konfiguration ---
import sys as _sys
ROOT   = _sys.argv[1] if len(_sys.argv) > 1 else "."
OUTPUT = os.path.join(ROOT, "project_stats.md")

EXCLUDE_DIRS = {
    "__pycache__", ".git", "build", "dist",
    ".pytest_cache", ".mypy_cache", "venv", ".venv",
    "node_modules"
}

EXCLUDE_FILES = {
    "project_stats.md",  # eigene Ausgabe nicht zählen
    "count_project.py",  # sich selbst nicht zählen
}

# Binär / Assets — werden komplett übersprungen
EXCLUDE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp", ".webp",  # Bilder
    ".drawio",                                                           # Diagramme
    ".exe", ".dll", ".pyd", ".so",                                       # Binaries
    ".zip", ".tar", ".gz",                                               # Archive
    ".pyc",                                                              # Python Cache
}

# Dateitypen die gezählt werden — alles andere landet in "Sonstige"
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

# --- Datenstruktur ---
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
by_type = defaultdict(Stats)   # gruppiert nach Anzeigebezeichnung
total   = Stats()

for dirpath, dirnames, filenames in os.walk(ROOT):
    # Ausgeschlossene Ordner überspringen (in-place damit os.walk nicht reingeht)
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

    for filename in filenames:
        if filename in EXCLUDE_FILES:
            continue

        filepath = os.path.join(dirpath, filename)
        ext = os.path.splitext(filename)[1].lower()

        # Binär / Assets und Dateien ohne Extension überspringen
        if not ext or ext in EXCLUDE_EXTENSIONS:
            continue

        label = KNOWN_TYPES.get(ext, f"Sonstige ({ext})")

        lines, words, chars = count_file(filepath)
        by_type[label].add(lines, words, chars)
        total.add(lines, words, chars)

# --- Ausgabe ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

lines_out = []
lines_out.append(f"# Projektstatistik")
lines_out.append(f"")
lines_out.append(f"*Generiert: {now}*")
lines_out.append(f"")
lines_out.append(f"---")
lines_out.append(f"")

# Tabelle nach Dateityp — sortiert nach Zeichen absteigend
lines_out.append(f"## Nach Dateityp")
lines_out.append(f"")
lines_out.append(f"| Typ | Dateien | Zeilen | Wörter | Zeichen |")
lines_out.append(f"|---|---:|---:|---:|---:|")

for label in sorted(by_type, key=lambda k: by_type[k].chars, reverse=True):
    s = by_type[label]
    lines_out.append(
        f"| {label} | {s.files:,} | {s.lines:,} | {s.words:,} | {s.chars:,} |"
    )

lines_out.append(f"")
lines_out.append(f"---")
lines_out.append(f"")
lines_out.append(f"## Gesamt")
lines_out.append(f"")
lines_out.append(f"| | Wert |")
lines_out.append(f"|---|---:|")
lines_out.append(f"| Dateien | {total.files:,} |")
lines_out.append(f"| Zeilen  | {total.lines:,} |")
lines_out.append(f"| Wörter  | {total.words:,} |")
lines_out.append(f"| Zeichen | {total.chars:,} |")
lines_out.append(f"")

output_text = "\n".join(lines_out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Fertig — {OUTPUT} geschrieben.")
print(f"  Dateien: {total.files:,}")
print(f"  Zeilen:  {total.lines:,}")
print(f"  Wörter:  {total.words:,}")
print(f"  Zeichen: {total.chars:,}")
