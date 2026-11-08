# change_script — Anchor Applier

Automatically applies Claude-delivered anchor blocks (ALT/NEU diffs) to project files.

## How it works

Claude delivers code changes as an `anchor_delivery.md` with structured ALT/NEU blocks. Block boundaries use unique sentinel markers (`<<<ALT>>>`/`<<<ALT_END>>>`, `<<<NEU>>>`/`<<<NEU_END>>>`) rather than plain backtick fences — this avoids a bug where a nested code fence inside the NEU content (e.g. an embedded example in documentation) could be mistaken for the closing fence, silently truncating the block:

```markdown
## FILE: src/my_module.py

### ALT
<<<ALT>>>
old_code_here()
<<<ALT_END>>>
### NEU
<<<NEU>>>
new_code_here()
<<<NEU_END>>>
```

The marker content can optionally still be wrapped in backtick fences for nicer rendering when pasted into a chat — the parser only looks for the `<<<...>>>` markers and ignores any surrounding fence.

`apply_anchors.py` reads this file and applies all changes in **two passes**:

- **Pass 1** — locates every ALT block in the target file without writing anything. Checks: does the file exist, is the block found exactly once, are there any overlaps between anchors? An anchor whose NEU text is already present in the target file counts as already applied and is skipped (see *Re-runs* below).
- **Pass 2** — writes only if Pass 1 was 100% successful. No partial applies.

Also supports `#DELETE` as the NEU content to remove an ALT block without replacement.

### Re-runs (idempotence)

An anchor counts as already applied when its NEU text is present in the target file **and** either NEU contains ALT (a pure append: NEU = ALT + new lines) or ALT is gone. Pass 1 then reports `ALREADY APPLIED — skip`, Pass 2 leaves the anchor out, and the summary shows how many anchors were skipped. Running the same delivery twice therefore does not apply anything twice — in particular an append does not duplicate its addition.

While ALT is still in the file, an anchor is applied normally, even if its NEU text also occurs elsewhere or is a part of ALT (for example trimming the first or last lines of a block). `#DELETE` anchors are not checked this way: after a successful run their ALT is gone, so a second run reports `NOT FOUND`.

### Legacy format

Older `anchor_delivery.md` files that use plain backtick fences instead of the sentinel markers still work — the parser tries the markers first and falls back to fence-matching if none are found. New deliveries should use the marker format above, especially for blocks containing documentation with embedded code examples.

## Setup

### 1. Configure the project path

Set the path to your target project in `apply_anchors.py`. The shipped value is a placeholder (`../my_project`), so change it. Relative to `change_script/`:

```python
PROJECT_ROOT = (SCRIPT_DIR / "../my_project").resolve()
```

Or as an absolute path:

```python
PROJECT_ROOT = Path("C:/Users/me/projects/my_project")
```

### 2. Directory layout

```
GLA-NeedfulThings/
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
  apply_anchors.py — Needful Things
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
| `ALREADY APPLIED` | NEU text is already present — anchor skipped, not an error (see *Re-runs*) |

If any error occurs in Pass 1, **no files are written**.

## Dependencies

Python stdlib only (`pathlib`, `re`, `sys`). No installation required.
