"""
count_chats.py — Chat Statistics Counter
Counts lines / words / characters in chat exports, split by user / AI.

Supported formats:
  - Claude JSON  (.json)  — sender: human / assistant
  - Claude MD    (.md)    — ### 👤 Du  /  ### 🤖 Assistant   ("Du" = German export UI)
  - Gemini MD    (.md)    — ## 👤 You  /  ## 🤖 Gemini

Output: chat_stats.md
"""

import os
import json
import re
from collections import defaultdict
from datetime import datetime

# ─── Configuration ────────────────────────────────────────────────────────────

import sys as _sys
ROOT   = _sys.argv[1] if len(_sys.argv) > 1 else "."
OUTPUT = os.path.join(ROOT, "chat_stats.md")

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


# ─── Data structure ────────────────────────────────────────────────────────────

class TurnStats:
    """Counter for one side (user or AI)."""
    def __init__(self):
        self.turns  = 0    # number of messages / turns
        self.words  = 0
        self.chars  = 0

    def add_text(self, text: str):
        self.turns += 1
        self.words += len(text.split())
        self.chars += len(text)

class FileStats:
    """Counter per file."""
    def __init__(self, source_format: str):
        self.fmt   = source_format
        self.user  = TurnStats()
        self.ai    = TurnStats()

    @property
    def total_turns(self):
        return self.user.turns + self.ai.turns


# ─── Parser ───────────────────────────────────────────────────────────────────

# Claude MD: ### 👤 Du  or  ### 🤖 Assistant
_CLAUDE_MD_USER = re.compile(r"^### 👤 Du\b")
_CLAUDE_MD_AI   = re.compile(r"^### 🤖 Assistant\b")

# Gemini MD: ## 👤 You  or  ## 🤖 Gemini
_GEMINI_MD_USER = re.compile(r"^## 👤 You\b")
_GEMINI_MD_AI   = re.compile(r"^## 🤖 Gemini\b")

# Any MD separator / metadata line (not counted as text)
_MD_META = re.compile(r"^(---|\*[^*].*\*|#[^#].*Export.*|>.*---)\s*$")


def _is_section_header(line: str) -> bool:
    return bool(
        _CLAUDE_MD_USER.match(line) or _CLAUDE_MD_AI.match(line) or
        _GEMINI_MD_USER.match(line) or _GEMINI_MD_AI.match(line)
    )


def parse_md(path: str) -> FileStats | None:
    """Parses Claude MD and Gemini MD exports."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return None

    # Detect the format
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
        return None   # no known chat MD format

    stats   = FileStats(fmt)
    current = None   # "user" | "ai" | None
    buf     = []

    def flush():
        nonlocal buf, current
        if current and buf:
            text = " ".join(" ".join(buf).split())   # normalize whitespace
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

        # Skip header lines and meta
        if _is_section_header(stripped) or _MD_META.match(stripped):
            continue

        # Skip the meta line directly after a turn header (date etc.)
        if stripped.startswith("> ---"):
            continue

        if current:
            buf.append(stripped)

    flush()
    return stats if stats.total_turns > 0 else None


def parse_json(path: str) -> FileStats | None:
    """Parses Claude JSON exports."""
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

        # Collect text from content blocks (type=text only)
        parts = []
        for block in msg.get("content", []):
            if block.get("type") == "text":
                t = block.get("text", "").strip()
                if t:
                    parts.append(t)

        # Fallback: top-level "text" field
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

# Overall statistics per format
format_totals: dict[str, FileStats] = {}   # fmt → aggregated FileStats
all_files: list[tuple[str, FileStats]] = []  # (rel_path, stats)

grand_user = TurnStats()
grand_ai   = TurnStats()

def merge_into(target: FileStats, src: FileStats):
    """Adds src values into target."""
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

        # Aggregate into the format group
        if stats.fmt not in format_totals:
            format_totals[stats.fmt] = FileStats(stats.fmt)
        merge_into(format_totals[stats.fmt], stats)

        # Grand total
        grand_user.turns += stats.user.turns
        grand_user.words += stats.user.words
        grand_user.chars += stats.user.chars
        grand_ai.turns   += stats.ai.turns
        grand_ai.words   += stats.ai.words
        grand_ai.chars   += stats.ai.chars


# ─── Output ──────────────────────────────────────────────────────────────────

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
lines_out.append(f"# Chat statistics")
lines_out.append(f"")
lines_out.append(f"*Generated: {now}*")
lines_out.append(f"")
lines_out.append(f"---")
lines_out.append(f"")

# ── Total ────────────────────────────────────────────────────────────────────
total_files = len(all_files)
total_turns = grand_user.turns + grand_ai.turns

lines_out.append(f"## Total")
lines_out.append(f"")
lines_out.append(f"| | Value |")
lines_out.append(f"|---|---:|")
lines_out.append(f"| Files          | {total_files:,} |")
lines_out.append(f"| Turns total     | {total_turns:,} |")
lines_out.append(f"| — User turns     | {grand_user.turns:,} |")
lines_out.append(f"| — AI turns       | {grand_ai.turns:,} |")
lines_out.append(f"| Words total    | {grand_user.words + grand_ai.words:,} |")
lines_out.append(f"| — User words    | {grand_user.words:,} |")
lines_out.append(f"| — AI words      | {grand_ai.words:,} |")
lines_out.append(f"| Characters total   | {grand_user.chars + grand_ai.chars:,} |")
lines_out.append(f"| — User characters   | {grand_user.chars:,} |")
lines_out.append(f"| — AI characters     | {grand_ai.chars:,} |")
lines_out.append(f"")

# ── By format ───────────────────────────────────────────────────────────────
lines_out.append(f"---")
lines_out.append(f"")
lines_out.append(f"## By format")
lines_out.append(f"")
lines_out.append(f"| Format | User turns | User words | User characters | AI turns | AI words | AI characters | Word split (U/AI) |")
lines_out.append(f"|---|---:|---:|---:|---:|---:|---:|---:|")

for fmt in sorted(format_totals):
    s = format_totals[fmt]
    lines_out.append(fmt_row(fmt, s.user, s.ai))

lines_out.append(f"")

# ── By file ────────────────────────────────────────────────────────────────
lines_out.append(f"---")
lines_out.append(f"")
lines_out.append(f"## By file")
lines_out.append(f"")
lines_out.append(f"| File | Fmt | User turns | User words | AI turns | AI words | Word split (U/AI) |")
lines_out.append(f"|---|---|---:|---:|---:|---:|---:|")

# Sorted by AI words, descending
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

print(f"Done — {OUTPUT} written.")
print(f"  Files:      {total_files:,}")
print(f"  Turns:      {total_turns:,}  (User: {grand_user.turns:,} / AI: {grand_ai.turns:,})")
print(f"  Words:      {grand_user.words + grand_ai.words:,}  (User: {grand_user.words:,} / AI: {grand_ai.words:,})")
print(f"  Chars:      {grand_user.chars + grand_ai.chars:,}  (User: {grand_user.chars:,} / AI: {grand_ai.chars:,})")
