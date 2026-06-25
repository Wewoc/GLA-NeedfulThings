"""
scan_config_v1_template.py — needfull things · Scanner Configuration
Rename to scan_config_v1.py (or higher) and adjust.

The scanner always picks the newest scan_config_v*.py (by mtime).
"""

# ── Meta ──────────────────────────────────────────────────────────────────────

CONFIG_ID    = "v1"                     # used in archive file names
SESSION_NOTE = "Initial scan"           # optional — shown in the report header

# ── Project ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = "../my_project"          # relative to scanner/ — adjust!
OLLAMA_MODEL = "qwen2.5-coder:14b"     # ollama pull qwen2.5-coder:14b
OLLAMA_URL   = "http://localhost:11434"

# ── Scan targets ─────────────────────────────────────────────────────────────
# Each target defines: what to search for, where, and how Ollama classifies it.
#
# Fields:
#   id            — unique identifier (string)
#   description   — describes what this target searches for (shown in report)
#   patterns      — list of regex patterns; one match per line is enough
#   file_include  — glob filter (default: all .py files)
#   file_exclude  — paths/files to exclude
#   ollama_prompt — context prompt for LLM classification

SCAN_TARGETS = [
    {
        "id":          "example_direct_access",
        "description": "Direct access to module X outside the intended abstraction layer",
        "file_exclude": [
            "src/x_layer.py",      # this is the permitted location
        ],
        "patterns": [
            r"import x_module",
            r"from x_module import",
        ],
        "ollama_prompt": (
            "This line of code may be importing a module directly, "
            "bypassing the intended abstraction layer. "
            "Is this a critical direct access (relevant), unclear (unsure), "
            "or harmless / a correct exception (not_relevant)? "
            "Reply with one word: relevant, unsure or not_relevant."
        ),
    },
    # Add another target:
    # {
    #     "id":          "...",
    #     "description": "...",
    #     "patterns":    [r"..."],
    #     "ollama_prompt": "...",
    # },
]
