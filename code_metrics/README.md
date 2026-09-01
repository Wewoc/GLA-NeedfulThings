# code_metrics

Six small, dependency-free Python scripts that inventory a Python
codebase: size, function/class structure, GUI signal bindings (PyQt/PySide
`.connect()` style), line-length outliers, and nesting-depth outliers.
Each script does one thing, writes one Markdown report, and can be run on
its own. A batch runner chains all six and a final aggregator rolls the
individual reports into one profile.

No third-party dependencies — standard library only (`ast`, `os`, `re`,
`datetime`).

## What it produces

Running the full chain against a project writes six files to
`code_metrics/output/`:

| Script | Output | What it shows |
|---|---|---|
| `count_project.py` | `project_stats.md` | Files/lines/words/chars by file type; Python code-vs-prose split |
| `list_functions.py` | `FUNCTION_MAP.md` | Every function, method, closure and class, with line count, via AST |
| `list_gui_bindings.py` | `GUI_BINDINGS.md` | Every `.connect(...)` call found project-wide, with signal name and handler classification |
| `list_longest_functions.py` | `LONGEST_FUNCTIONS.md` | Functions/methods over a line-length threshold, read back out of `FUNCTION_MAP.md` |
| `list_complexity.py` | `COMPLEXITY_MAP.md` | Per-function nesting depth (if/for/while/try/with), plus per-file import/export interfaces |
| `build_profile.py` | `PROJECT_PROFILE.md` | One aggregated summary pulling key figures from all of the above |

## Setup

1. Copy the whole `code_metrics/` folder next to (not inside) the project
   you want to scan.
2. Open `metrics_config.py` and set `PROJECT_ROOT` to a relative path
   pointing at that project's root, e.g.:
   ```python
   PROJECT_ROOT = "../my_project"
   ```
   `OUTPUT_DIR` defaults to `code_metrics/output/` and is created
   automatically — reports never land inside the scanned project.

## Usage

Run everything in the correct order with the batch runner (Windows):

```
run_all_checks.bat
```

Or run scripts individually. Order matters for two of them:

```
python count_project.py
python list_functions.py
python list_gui_bindings.py
python list_longest_functions.py   # needs FUNCTION_MAP.md
python list_complexity.py          # independent, own scan
python build_profile.py            # needs all of the above
```

## Notes and known limitations

- **Line-length metric is an outlier radar, not a health metric.** A
  long, linear function (e.g. straightforward UI construction or HTML
  string assembly) can be far less problematic than a short, deeply
  nested one. Cross-check any long-function finding against the nesting
  depth report before treating it as a real problem, and read the actual
  code before acting on it.
- **`list_gui_bindings.py` does a project-wide recursive scan** for any
  `.connect(...)` call, regardless of file location. If your GUI code
  lives in specific files or folders, you can either point `PROJECT_ROOT`
  at that subfolder, or add other paths to `EXCLUDE_DIRS`/`EXCLUDE_FILES`
  inside the script to narrow the scope.
- **`local_func_or_dynamic` handler classification** is a deliberate
  ambiguity: a bare name passed to `.connect(...)` is syntactically
  identical whether it's a local closure or a parameter/variable passed
  through from elsewhere. Telling them apart needs data-flow analysis,
  which this tool doesn't do.
- **No cross-module analysis anywhere.** `list_complexity.py`'s
  "exports" are not checked against actual usage elsewhere in the
  project; `list_functions.py`/`list_gui_bindings.py` don't resolve
  dynamic dispatch, `getattr`-based calls, or metaprogramming. All
  figures come from static, per-file AST parsing.
- **The Python code-vs-prose split in `count_project.py` is a line-based
  heuristic, not an AST parse** — a multi-line string literal that
  happens to use `"""`/`'''` inside real code (e.g. an embedded SQL
  query) will be miscounted as a docstring. Accepted trade-off for a
  quick, rough metric.
- Reports are plain Markdown text, meant to be read directly or fed back
  into an LLM session as project context.
