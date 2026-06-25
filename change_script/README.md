# change_script — Anchor Applier

Automatically applies Claude-delivered anchor blocks (ALT/NEU diffs) to project files.

## How it works

Claude delivers code changes as an `anchor_delivery.md` with structured ALT/NEU blocks:

```markdown
## FILE: src/my_module.py

### ALT
\```python
old_code_here()
\```

### NEU
\```python
new_code_here()
\```
```

`apply_anchors.py` reads this file and applies all changes in **two passes**:

- **Pass 1** — locates every ALT block in the target file without writing anything. Checks: does the file exist, is the block found exactly once, are there any overlaps between anchors?
- **Pass 2** — writes only if Pass 1 was 100% successful. No partial applies.

Also supports `#DELETE` as the NEU content to remove an ALT block without replacement.

## Setup

### 1. Configure the project path

Set the relative path to your target project in `apply_anchors.py`:

```python
PROJECT_REL_PATH = "../my_project"   # relative to change_script/
```

Or as an absolute path:

```python
PROJECT_ROOT = Path("C:/Users/me/projects/my_project")
```

### 2. Directory layout

```
needfull_things/
└── change_script/
    ├── apply_anchors.py
    ├── run_anchors.bat
    └── anchor_delivery_2026-06-25.md   ← drop Claude's delivery here
```

## Usage

### Via batch file (Windows)

```
run_anchors.bat
```

The batch file:
1. Deletes any existing `anchor_delivery.md`
2. Finds the newest `anchor_delivery_*.md` (by file date) and copies it to `anchor_delivery.md`
3. Runs `apply_anchors.py`

### Directly

```bash
python apply_anchors.py
```

Expects `anchor_delivery.md` in the same directory.

## Output

```
=================================================================
  apply_anchors.py — needfull things
=================================================================

  Delivery : C:\...\anchor_delivery.md
  Target   : C:\...\my_project

Pass 1 — Searching 5 anchors in 3 files ...

  ✓  src/my_module.py                           [1/5] located
  ✓  src/config.py                              [2/5] located
  ...

Pass 1 complete — all 5 anchors located. Starting Pass 2 ...

  ✓  src/my_module.py                           [1/5] applied
  ...

=================================================================
  Done — 5/5 anchors applied.
=================================================================
```

## Error handling

| Error | Meaning |
|-------|---------|
| `FILE NOT FOUND` | Path in `## FILE:` does not exist under the project root |
| `NOT FOUND` | ALT block not found in the file (content changed?) |
| `AMBIGUOUS (Nx)` | ALT block appears more than once — too unspecific |
| `OVERLAP` | Two anchors overlap in line range |

If any error occurs in Pass 1, **no files are written**.

## Dependencies

Python stdlib only (`pathlib`, `re`, `sys`). No installation required.
