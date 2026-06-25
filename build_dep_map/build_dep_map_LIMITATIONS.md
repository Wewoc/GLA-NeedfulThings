# build_dep_map — Known Limitations & Interpretation Notes

Location: `build_dep_map/` — next to the script.
**Not** overwritten on every run. Update manually when new patterns are
discovered or new scanner capabilities are added.

Last updated: 2026-06-22

---

## What the scanner can do

### Import detection (`dep_map.md`, `dep_map.csv`)
- `import X` — direct module import
- `from X import func` — selective import with symbols
- Internal / external classification: internal = exists as `.py` in the project
- Inverse map: who imports this module (table 2 in `dep_map.md`)

### Dynamic imports (`dep_map_dynamic.md`)
- `importlib.import_module("x")` — when argument is a string literal
- `importlib.util.spec_from_file_location("n", path)`
- `importlib.util.find_spec("x")`
- `__import__("x")`

### File I/O (`dep_map_fileio.md`)
- `open()` with mode detection (read/write/read-write)
- `Path.write_text()`, `Path.read_text()`, `Path.read_bytes()`, `Path.write_bytes()`
- `json.dump()`, `json.dumps()`, `json.load()`, `json.loads()`
- `shutil.move()`, `shutil.copy()`, `shutil.copy2()`, `shutil.copytree()`
- `Path.rename()`, `Path.replace()`, `Path.unlink()`, `Path.mkdir()`
- `Path.glob()`, `Path.rglob()`, `Path.iterdir()`, `Path.stat()`
- `Path.exists()`, `Path.is_file()`, `Path.is_dir()`

### Caller analysis (`dep_map_callers_*.md`) — two scan paths

**Path 1 — Attribute calls:**
```python
import my_config
my_config.get_path()   # detected
```

**Path 2 — Direct calls after from-import:**
```python
from my_config import get_path
get_path()             # detected
```
Alias imports are handled:
```python
from my_config import get_path as gp
gp()                   # detected, original name "get_path" is logged
```

---

### Exception handler analysis (`dep_map_exceptions.md`)
- All `except` blocks via AST
- Risk classification: `critical` | `silent` | `broad` | `ok`
- `critical`: `pass` or `return None/False/empty` without log/reraise
- `silent`: only logs, no reraise, no raise — caller receives no signal
- `broad`: overly wide type (`Exception`, `BaseException`, bare `except`)
- `ok`: specific type or controlled reraise/raise

## What the scanner cannot do

### 1. Shadowing (path 2 — direct calls)

**Problem:** If an imported name is locally overridden, the scanner still
reports the local call as a match.

```python
from my_config import get_path

def my_func():
    get_path = lambda: "/local"   # local variable — SHADOWING
    get_path()                    # scanner reports match for my_config — WRONG
```

**Assessment:** Rare in practice. Well-structured code avoids import-name
shadowing. False positives are possible but unlikely.

**Detection tip:** If a match in `dep_map_callers_*.md` looks unexpected,
check the relevant file and line manually.

### 2. Dynamic module arguments

```python
module_name = "my_" + suffix
importlib.import_module(module_name)   # argument not resolvable
```
Output in `dep_map_dynamic.md`: `_(dynamic — not resolvable)_`

### 3. getattr calls

```python
func = getattr(my_config, "get_path")
func()   # not detected
```
No static scanner can cover this fully.

### 4. Callback patterns

```python
handlers = {"write": my_writer.write}
handlers["write"]()   # not detected
```

### 5. eval / exec

```python
eval("get_path()")          # not detected
exec("import my_config")    # not detected
```

### 6. Multi-line imports (in regex-based scanners)

Not relevant for this scanner — it uses AST, not regex.
Multi-line imports are handled correctly.

### 7. Circular imports

The scanner does not explicitly detect cycles. If A imports B and B imports A,
both appear in each other's importer lists — but no warning is generated.
Identify cycles manually in `dep_map.md` table 2.

---

## Interpretation notes

### Entry points in `dep_map.md`

"Not imported by any other module" does not necessarily mean unused code.
Common causes:

- Dynamically loaded (check `dep_map_dynamic.md` for the same file name)
- Top-level entry point (e.g. `app.py`, `main.py`, `daily_update.py`)
- Build/utility script (not part of the production pipeline)

### File I/O `replace` operations

`str.replace()` and `Path.replace()` are two different operations.
The scanner captures both as "write" because both use the `replace` function name.
`str.replace()` is not an actual disk write — check the context.

### Caller match volume

In large projects, highly-coupled modules (e.g. a config module with 30+
importers) can produce hundreds of caller matches. The summary table in
`dep_map_callers_*.md` gives a compact overview first — read detail sections
only when needed.

### Path 2 match quality

From-import matches are reliable as long as no shadowing is present.
For unexpected matches (module calls itself or an unrelated module?),
always look up the line in the source code.

---

## Extension notes

Add new file I/O operations to `_FILEIO_WRITE` / `_FILEIO_READ`
(around line ~620 in `build_dep_map.py`).

Add new dynamic import patterns to `_DYNAMIC_PATTERNS`
(around line ~124 in `build_dep_map.py`).

Add new dunder methods to `_DUNDER` if they appear as caller noise
(around line ~786 in `build_dep_map.py`).

Line numbers may shift — when in doubt use function names as anchors,
not line numbers.
