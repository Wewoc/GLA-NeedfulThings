"""
count_chats.py — Chat Statistics Counter
Zählt Zeilen / Wörter / Zeichen in Chat-Exporten, aufgeteilt nach User / KI.

Unterstützte Formate:
  - Claude JSON  (.json)  — sender: human / assistant
  - Claude MD    (.md)    — ### 👤 Du  /  ### 🤖 Assistant
  - Gemini MD    (.md)    — ## 👤 You  /  ## 🤖 Gemini

Ausgabe: chat_stats.md
"""

import os
import json
import re
from collections import defaultdict
from datetime import datetime

# ─── Konfiguration ────────────────────────────────────────────────────────────

ROOT   = "."
OUTPUT = "chat_stats.md"

EXCLUDE_DIRS = {
    "__pycache__", ".git", "build", "dist",
    ".pytest_cache", ".mypy_cache", "venv", ".venv", "node_modules"
}

EXCLUDE_FILES = {
    OUTPUT,
    "count_chats.py",
    "count_project.py",
    "chat_stats.md",
    "project_stats.md",
}


# ─── Datenstruktur ────────────────────────────────────────────────────────────

class TurnStats:
    """Zähler für eine Seite (User oder KI)."""
    def __init__(self):
        self.turns  = 0    # Anzahl Nachrichten / Turns
        self.words  = 0
        self.chars  = 0

    def add_text(self, text: str):
        self.turns += 1
        self.words += len(text.split())
        self.chars += len(text)

class FileStats:
    """Zähler pro Datei."""
    def __init__(self, source_format: str):
        self.fmt   = source_format
        self.user  = TurnStats()
        self.ai    = TurnStats()

    @property
    def total_turns(self):
        return self.user.turns + self.ai.turns


# ─── Parser ───────────────────────────────────────────────────────────────────

# Claude MD: ### 👤 Du  oder  ### 🤖 Assistant
_CLAUDE_MD_USER = re.compile(r"^### 👤 Du\b")
_CLAUDE_MD_AI   = re.compile(r"^### 🤖 Assistant\b")

# Gemini MD: ## 👤 You  oder  ## 🤖 Gemini
_GEMINI_MD_USER = re.compile(r"^## 👤 You\b")
_GEMINI_MD_AI   = re.compile(r"^## 🤖 Gemini\b")

# Jeder MD-Separator / Metadaten-Zeile (wird nicht zum Text gezählt)
_MD_META = re.compile(r"^(---|\*[^*].*\*|#[^#].*Export.*|>.*---)\s*$")


def _is_section_header(line: str) -> bool:
    return bool(
        _CLAUDE_MD_USER.match(line) or _CLAUDE_MD_AI.match(line) or
        _GEMINI_MD_USER.match(line) or _GEMINI_MD_AI.match(line)
    )


def parse_md(path: str) -> FileStats | None:
    """Parst Claude-MD und Gemini-MD Exporte."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return None

    # Format erkennen
    content = "".join(lines)
    if "### 👤 Du" in content or "### 🤖 Assistant" in content:
        fmt = "Claude MD"
        re_user = _CLAUDE_MD_USER
        re_ai   = _CLAUDE_MD_AI
    elif "## 👤 You" in content or "## 🤖 Gemini" in content:
        fmt = "Gemini MD"
        re_user = _GEMINI_MD_USER
        re_ai   = _GEMINI_MD_AI
    else:
        return None   # kein bekanntes Chat-MD Format

    stats   = FileStats(fmt)
    current = None   # "user" | "ai" | None
    buf     = []

    def flush():
        nonlocal buf, current
        if current and buf:
            text = " ".join(" ".join(buf).split())   # Whitespace normalisieren
            if text:
                if current == "user":
                    stats.user.add_text(text)
                else:
                    stats.ai.add_text(text)
        buf = []

    for line in lines:
        stripped = line.rstrip("\n")

        if re_user.match(stripped):
            flush()
            current = "user"
            continue
        if re_ai.match(stripped):
            flush()
            current = "ai"
            continue

        # Header-Zeilen und Meta überspringen
        if _is_section_header(stripped) or _MD_META.match(stripped):
            continue

        # Metazeile direkt nach einem Turn-Header (Datum etc.) überspringen
        if stripped.startswith("> ---"):
            continue

        if current:
            buf.append(stripped)

    flush()
    return stats if stats.total_turns > 0 else None


def parse_json(path: str) -> FileStats | None:
    """Parst Claude JSON Exporte."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    messages = data.get("chat_messages")
    if not isinstance(messages, list):
        return None

    stats = FileStats("Claude JSON")

    for msg in messages:
        sender = msg.get("sender", "")
        if sender not in ("human", "assistant"):
            continue

        # Text aus content-Blöcken sammeln (nur type=text)
        parts = []
        for block in msg.get("content", []):
            if block.get("type") == "text":
                t = block.get("text", "").strip()
                if t:
                    parts.append(t)

        # Fallback: top-level "text" Feld
        if not parts:
            t = msg.get("text", "").strip()
            if t:
                parts.append(t)

        text = " ".join(parts)
        if not text:
            continue

        if sender == "human":
            stats.user.add_text(text)
        else:
            stats.ai.add_text(text)

    return stats if stats.total_turns > 0 else None


# ─── Scan ─────────────────────────────────────────────────────────────────────

# Gesamtstatistik pro Format
format_totals: dict[str, FileStats] = {}   # fmt → aggregierter FileStats
all_files: list[tuple[str, FileStats]] = []  # (rel_path, stats)

grand_user = TurnStats()
grand_ai   = TurnStats()

def merge_into(target: FileStats, src: FileStats):
    """Addiert src-Werte in target."""
    target.user.turns += src.user.turns
    target.user.words += src.user.words
    target.user.chars += src.user.chars
    target.ai.turns   += src.ai.turns
    target.ai.words   += src.ai.words
    target.ai.chars   += src.ai.chars


for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

    for filename in filenames:
        if filename in EXCLUDE_FILES:
            continue

        filepath = os.path.join(dirpath, filename)
        rel_path = os.path.relpath(filepath, ROOT)
        ext = os.path.splitext(filename)[1].lower()

        stats: FileStats | None = None

        if ext == ".json":
            stats = parse_json(filepath)
        elif ext == ".md":
            stats = parse_md(filepath)

        if stats is None:
            continue

        all_files.append((rel_path, stats))

        # In Formatgruppe aggregieren
        if stats.fmt not in format_totals:
            format_totals[stats.fmt] = FileStats(stats.fmt)
        merge_into(format_totals[stats.fmt], stats)

        # Gesamtsumme
        grand_user.turns += stats.user.turns
        grand_user.words += stats.user.words
        grand_user.chars += stats.user.chars
        grand_ai.turns   += stats.ai.turns
        grand_ai.words   += stats.ai.words
        grand_ai.chars   += stats.ai.chars


# ─── Ausgabe ──────────────────────────────────────────────────────────────────

now = datetime.now().strftime("%Y-%m-%d %H:%M")

def fmt_row(label, u: TurnStats, a: TurnStats) -> str:
    u_ratio = u.words / (u.words + a.words) * 100 if (u.words + a.words) else 0
    a_ratio = 100 - u_ratio
    return (
        f"| {label} "
        f"| {u.turns:,} | {u.words:,} | {u.chars:,} "
        f"| {a.turns:,} | {a.words:,} | {a.chars:,} "
        f"| {u_ratio:.0f}% / {a_ratio:.0f}% |"
    )

lines_out = []
lines_out.append(f"# Chat-Statistik")
lines_out.append(f"")
lines_out.append(f"*Generiert: {now}*")
lines_out.append(f"")
lines_out.append(f"---")
lines_out.append(f"")

# ── Gesamt ────────────────────────────────────────────────────────────────────
total_files = len(all_files)
total_turns = grand_user.turns + grand_ai.turns

lines_out.append(f"## Gesamt")
lines_out.append(f"")
lines_out.append(f"| | Wert |")
lines_out.append(f"|---|---:|")
lines_out.append(f"| Dateien          | {total_files:,} |")
lines_out.append(f"| Turns gesamt     | {total_turns:,} |")
lines_out.append(f"| — User-Turns     | {grand_user.turns:,} |")
lines_out.append(f"| — KI-Turns       | {grand_ai.turns:,} |")
lines_out.append(f"| Wörter gesamt    | {grand_user.words + grand_ai.words:,} |")
lines_out.append(f"| — User-Wörter    | {grand_user.words:,} |")
lines_out.append(f"| — KI-Wörter      | {grand_ai.words:,} |")
lines_out.append(f"| Zeichen gesamt   | {grand_user.chars + grand_ai.chars:,} |")
lines_out.append(f"| — User-Zeichen   | {grand_user.chars:,} |")
lines_out.append(f"| — KI-Zeichen     | {grand_ai.chars:,} |")
lines_out.append(f"")

# ── Nach Format ───────────────────────────────────────────────────────────────
lines_out.append(f"---")
lines_out.append(f"")
lines_out.append(f"## Nach Format")
lines_out.append(f"")
lines_out.append(f"| Format | User-Turns | User-Wörter | User-Zeichen | KI-Turns | KI-Wörter | KI-Zeichen | Wort-Split (U/KI) |")
lines_out.append(f"|---|---:|---:|---:|---:|---:|---:|---:|")

for fmt in sorted(format_totals):
    s = format_totals[fmt]
    lines_out.append(fmt_row(fmt, s.user, s.ai))

lines_out.append(f"")

# ── Nach Datei ────────────────────────────────────────────────────────────────
lines_out.append(f"---")
lines_out.append(f"")
lines_out.append(f"## Nach Datei")
lines_out.append(f"")
lines_out.append(f"| Datei | Fmt | User-Turns | User-Wörter | KI-Turns | KI-Wörter | Wort-Split (U/KI) |")
lines_out.append(f"|---|---|---:|---:|---:|---:|---:|")

# Sortiert nach KI-Wörter absteigend
for rel_path, s in sorted(all_files, key=lambda x: x[1].ai.words, reverse=True):
    u, a = s.user, s.ai
    u_ratio = u.words / (u.words + a.words) * 100 if (u.words + a.words) else 0
    a_ratio = 100 - u_ratio
    name = os.path.basename(rel_path)
    lines_out.append(
        f"| {name} | {s.fmt} "
        f"| {u.turns:,} | {u.words:,} "
        f"| {a.turns:,} | {a.words:,} "
        f"| {u_ratio:.0f}% / {a_ratio:.0f}% |"
    )

lines_out.append(f"")

output_text = "\n".join(lines_out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Fertig — {OUTPUT} geschrieben.")
print(f"  Dateien:    {total_files:,}")
print(f"  Turns:      {total_turns:,}  (User: {grand_user.turns:,} / KI: {grand_ai.turns:,})")
print(f"  Wörter:     {grand_user.words + grand_ai.words:,}  (User: {grand_user.words:,} / KI: {grand_ai.words:,})")
print(f"  Zeichen:    {grand_user.chars + grand_ai.chars:,}  (User: {grand_user.chars:,} / KI: {grand_ai.chars:,})")
