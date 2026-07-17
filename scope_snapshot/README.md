# scope_snapshot — Symbol Scope Snapshot

Generates a symbol map (function/method signatures, module-level constants,
class attributes) for a confirmed set of files — a third pre-session source
next to the DEPS report and, when needed, the dependency map.

Not a replacement for reading the target file before writing an anchor.
No logic verification — signatures and constants only, no function bodies.

Use case: after `scanner/` produces a `DEPS_CRITICAL_[version].md` and its
`relevant` matches have been reviewed and confirmed, this tool turns those
confirmed matches into a compact signature reference for the files touched
in the upcoming build task — reducing the risk of wrong cross-file
assumptions about a function's parameters, return type, or a constant's
current value.

## How it works

1. Finds the newest `scope_snapshot_config_v*.py` in the directory and
   copies it to `scope_snapshot_config.py`
2. Loads the config (project path, session note, scope files)
3. AST extraction per file in `SCOPE_FILES`:
   - Public/internal functions & methods (signature, return annotation if
     present, first docstring line)
   - Module-level constants (`ALL_CAPS` name + literal value)
   - Class attributes (class body + `self.x` assignments in `__init__`)
   - Facade detection: if a module re-exports imported names without using
     them locally (e.g. a `garmin_quality.py`-style facade), the real
     signature is resolved from the neighbor file
   - Referenced import neighbors: imported names that *are* used locally
     (`Call`/`Name`) get their signature pulled in from the neighbor file,
     without adding the whole neighbor file to the scope
4. Writes `SCOPE_SNAPSHOT.md` (compact signature list, `mtime` fingerprint
   per file)
5. Archives the report to `scope_output/` and the config to `scope_configs/`

No cache — pure deterministic AST extraction, no LLM step (unlike
`scanner/`, where classification is expensive enough to warrant one).

## Setup

### 1. Create a scope config

Copy `scope_snapshot_config_MASTER_TEMPLATE.py` to
`scope_snapshot_config_v[version]_[nn].py` and fill in `SCOPE_FILES` with
the deduplicated file paths from the confirmed `relevant` matches of the
matching `DEPS_CRITICAL_[version].md` run:

```python
CONFIG_ID    = "v1_01"
SESSION_NOTE = "v1 — refactor of the quality module"
PROJECT_ROOT = "../my_project"

SCOPE_FILES = [
    "garmin/garmin_quality.py",
    "garmin/garmin_writer.py",
]
```

`SCOPE_FILES` is not guessed or pattern-matched — it is the deduplicated
list of file paths from an already-reviewed DEPS report.

### 2. Directory layout

```
GLA-NeedfulThings/
└── scope_snapshot/
    ├── scope_snapshot.py
    ├── run_scope_snapshot.bat
    ├── scope_snapshot_config_MASTER_TEMPLATE.py
    ├── scope_snapshot_config_v1_01.py   ← place your config here
    ├── scope_configs/                   ← created automatically
    └── scope_output/                    ← created automatically
```

## Usage

### Via batch file (Windows)

```
run_scope_snapshot.bat
```

### Directly

```bash
python scope_snapshot.py
```

## Configuration fields

| Field | Type | Description |
|-------|------|-------------|
| `CONFIG_ID` | str | ID used for archiving, shared with the matching `scan_config_v[version]_[nn].py` |
| `SESSION_NOTE` | str | Optional note shown in the report header |
| `PROJECT_ROOT` | str | Relative path from `scope_snapshot/` to the repo root |
| `SCOPE_FILES` | list[str] | Deduplicated file paths (relative to `PROJECT_ROOT`) from confirmed DEPS matches |

## Output

- `SCOPE_SNAPSHOT.md` — compact signature list per file, plus a summary
  table and an "Unresolved references" section for anything that couldn't
  be resolved automatically
- `scope_output/SCOPE_SNAPSHOT_<config_id>.md` — archived copy
- `scope_configs/<original_config_name>` — archived config

## Relation to the other session tools

| | `scanner/` | `build_dep_map/` | `scope_snapshot/` |
|---|---|---|---|
| Level | Pattern matches | Module/structure | Symbol/signature |
| Question | What's affected? | Who depends on whom? | What exactly is there? |
| Timing | Before the build task | Precondition at session end | Before the build task, after the DEPS report |
| Scope | `SCAN_TARGETS` | Project-wide | Confirmed `relevant` matches + referenced import neighbors |
| Replaces reading the file? | No | No | No |

## Dependencies

Python stdlib only (`pathlib`, `datetime`, `ast`, `importlib`, `shutil`,
`sys`). No installation required.
