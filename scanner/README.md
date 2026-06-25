# scanner — Critical Dependency Scanner

Statically scans a Python project for configurable patterns, classifies matches via a local Ollama model, and produces a Markdown report.

Use cases:
- Dependency audits ("where is module X still imported directly?")
- Shadow-copy detection (duplicated logic across file boundaries)
- Preparation for refactorings

## How it works

1. Finds the newest `scan_config_v*.py` in the directory and copies it to `scan_config.py`
2. Loads the config (project path, scan targets, Ollama model)
3. Static scan: searches all configured regex patterns across every `.py` file in the project
4. Ollama classification: each match is rated by a local LLM (`relevant` / `unsure` / `not_relevant`). Results are cached in `.scan_cache.json`
5. Writes `DEPS_CRITICAL.md` and archives the config and report under `scan_output/` and `scan_configs/`

## Setup

### 1. Prepare Ollama

The scanner requires Ollama running at `http://localhost:11434`. Default model: `qwen2.5-coder:14b`.

```bash
ollama pull qwen2.5-coder:14b
```

### 2. Create a scan config

Create a file named `scan_config_v1.py` (version number is free to choose):

```python
"""scan_config_v1.py — My Project · Scan Configuration"""

CONFIG_ID    = "v1"
SESSION_NOTE = "Initial scan"

PROJECT_ROOT = "../my_project"            # relative to scanner/
OLLAMA_MODEL = "qwen2.5-coder:14b"
OLLAMA_URL   = "http://localhost:11434"

SCAN_TARGETS = [
    {
        "id":          "db_direct",
        "description": "Direct database access outside of db_layer.py",
        "file_exclude": ["src/db_layer.py"],
        "patterns": [
            r"sqlite3\.connect\(",
            r"psycopg2\.connect\(",
        ],
        "ollama_prompt": (
            "This line of code may be accessing the database directly, "
            "bypassing the intended abstraction layer. "
            "Is this a critical direct access (relevant), unclear (unsure), "
            "or harmless (not_relevant)? Reply with one word."
        ),
    },
]
```

A fully commented template is included as `scan_config_v1_template.py`.

### 3. Directory layout

```
needfull_things/
└── scanner/
    ├── scan_critical_deps.py
    ├── run_scan.bat
    ├── scan_config_v1.py        ← place your config here
    ├── scan_configs/            ← created automatically
    ├── scan_output/             ← created automatically
    └── .scan_cache.json         ← created automatically
```

## Usage

### Via batch file (Windows)

```
run_scan.bat
```

### Directly

```bash
python scan_critical_deps.py
```

## Configuration fields

| Field | Type | Description |
|-------|------|-------------|
| `CONFIG_ID` | str | ID used for archiving (e.g. `"v1"`) |
| `SESSION_NOTE` | str | Optional note shown in the report header |
| `PROJECT_ROOT` | str | Relative path to the project root |
| `OLLAMA_MODEL` | str | Ollama model (default: `qwen2.5-coder:14b`) |
| `OLLAMA_URL` | str | Ollama endpoint (default: `http://localhost:11434`) |
| `SCAN_TARGETS` | list | List of target dicts (see below) |

### Target dict fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique identifier |
| `description` | str | Description shown in the report header |
| `patterns` | list[str] | Regex patterns — one match per line is enough |
| `file_include` | list[str] | Glob filter (default: `["**/*.py"]`) |
| `file_exclude` | list[str] | Files/paths to exclude |
| `ollama_prompt` | str | Context prompt for LLM classification |

## Output

- `DEPS_CRITICAL.md` — main report with verdict tables per target
- `scan_output/DEPS_CRITICAL_<config_id>.md` — archived copy
- `scan_configs/<original_config_name>` — archived config
- `.scan_cache.json` — LLM cache (file + line + hash → verdict)

## Dependencies

- Python stdlib (`pathlib`, `re`, `json`, `hashlib`, `shutil`, `importlib`, `urllib`)
- Ollama (local, for classification)
