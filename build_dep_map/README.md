# build_dep_map — Dependency Map Generator

Builds a complete import map of a Python project via AST analysis. No runtime tracing — purely static.

## What gets analyzed

| Output file | Content |
|---|---|
| `dep_map.md` | Import map (who imports whom) + inverse map (who is imported by whom) |
| `dep_map.csv` | Same data, machine-readable |
| `dep_map_records.json` | Full snapshot for delta comparisons |
| `dep_map_dynamic.md` | Dynamic imports (`importlib`, `__import__`) |
| `dep_map_fileio.md` | File I/O operations (`open()`, `Path.write_text()`, `json.dump()` …) |
| `dep_map_callers_top8.md` | The 8 most-imported modules and who calls them |
| `dep_map_callers_all.md` | Full caller analysis |
| `dep_map_delta.md` | Changes compared to the previous run (optional) |

All output lands in `output/YYYY-MM-DD_Run-NN/`.

## Setup

### 1. Edit `build_dep_map_config.py`

```python
SCAN_ROOT   = "../my_project/src"   # path to source code — relative to build_dep_map/
OUTPUT_BASE = "output"
```

Additional optional settings:

```python
BASELINE_MODE = "auto_last"   # "auto_last" or "none"

EXCLUDE_DIRS  = ["tests", "docs", "__pycache__", ".ruff_cache"]
EXCLUDE_FILES = ["conftest.py", "build_dep_map.py"]

KNOWN_EXTERNAL = [
    "os", "sys", "re", "json", ...   # mark these as "(external)" in the report
]
```

### 2. Directory layout

```
needfull_things/
└── build_dep_map/
    ├── build_dep_map.py
    ├── build_dep_map_config.py      ← edit this
    ├── build_dep_map_LIMITATIONS.md
    ├── run_dep_map.bat
    └── output/                      ← created automatically
        └── 2026-06-25_Run-01/
            ├── dep_map.md
            ├── dep_map.csv
            ├── dep_map_records.json
            └── ...
```

## Usage

### Via batch file (Windows)

```
run_dep_map.bat
```

### Directly

```bash
python build_dep_map.py
```

### With an explicit baseline for delta

```bash
python build_dep_map.py --baseline output/2026-06-20_Run-01/dep_map_records.json
```

`BASELINE_MODE = "auto_last"` in the config picks up the last snapshot automatically — the `--baseline` CLI argument always takes precedence.

## Delta mode

When a baseline is available (manual or `auto_last`), an additional `dep_map_delta.md` is produced showing newly added and removed dependencies side by side.

On the first run (no `output/` directory yet), the delta step is skipped automatically.

## Known limitations

See [`build_dep_map_LIMITATIONS.md`](build_dep_map_LIMITATIONS.md) for the boundaries of static analysis, known false positives, and interpretation notes.

## Dependencies

Python stdlib only (`ast`, `pathlib`, `csv`, `json`, `importlib`, `argparse`). No installation required.
