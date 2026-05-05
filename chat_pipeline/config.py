#!/usr/bin/env python3
"""
config.py — chat_pipeline
Reads configuration from environment variables (set by run.bat).
Falls back to defaults when run directly without the batch file.

To run a step manually with custom settings:
    set SEARCH_LABEL=DCS && python "Step 1 - sort_chats.py"
"""

import os
import re
from pathlib import Path

# ── Pipeline settings ──────────────────────────────────────────────────────────
# Set by run.bat as environment variables. Edit defaults here for manual runs.

SEARCH_LABEL   = os.getenv("SEARCH_LABEL",    "Garmin")
INPUT_DIR      = Path(os.getenv("INPUT_DIR",  "."))
MODEL          = os.getenv("MODEL",           "qwen2.5-coder:14b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))

# ── Derived paths (not user-editable) ─────────────────────────────────────────

SORTED_DIR      = INPUT_DIR / "sorted" / SEARCH_LABEL
SUMMARIES_FILE  = SORTED_DIR / "chat_summaries.md"
SORTED_FILE     = SORTED_DIR / "chat_summaries_sorted.md"
MERGED_FILE     = SORTED_DIR / "merged_chats.json"
MD_EXPORT_DIR   = SORTED_DIR / "Markdown_Export"
WORD_EXPORT_DIR = SORTED_DIR / "Word_Export"

# ── Ollama ─────────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/generate"

# ── Summarization ──────────────────────────────────────────────────────────────

MAX_MESSAGES    = 60
PROJECT_CONTEXT = f"This is a chat export related to the '{SEARCH_LABEL}' project."
PROMPT_LANGUAGE = "the same language as the chat"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", s).strip()