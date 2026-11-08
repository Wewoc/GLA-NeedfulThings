"""
build_dep_map.py
Needful Things — Dependency Map Generator

Builds a complete import map of the project via AST analysis.

Process:
  1. Collect all .py files under SCAN_ROOT (EXCLUDE_DIRS / EXCLUDE_FILES)
  2. Per file: extract all imports via AST
  3. Classify as internal / external (internal = exists as .py in the project)
  4. Build inverse map (who imports this module?)
  5. Output: dep_map.md + dep_map.csv + dep_map_dynamic.md +
             dep_map_fileio.md + dep_map_callers_top8.md +
             dep_map_callers_all.md  in output/YYYY-MM-DD_Run-NN/

Usage:   run_dep_map.bat  (or: python build_dep_map.py)
Config:   build_dep_map_config.py (same directory)
"""

from __future__ import annotations

import argparse
import ast
import csv
import importlib.util
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

# ── Load config ─────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent.resolve()
CONFIG_FILE = SCRIPT_DIR / "build_dep_map_config.py"

def _load_config():
    if not CONFIG_FILE.exists():
        print(f"ERROR: build_dep_map_config.py not found in {SCRIPT_DIR}")
        sys.exit(1)
    spec   = importlib.util.spec_from_file_location("build_dep_map_config", CONFIG_FILE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"ERROR: Config could not be loaded: {e}")
        sys.exit(1)
    return module

# ── Output directory with run numbering ──────────────────────────────────────

def _next_run_dir(output_base: Path) -> Path:
    today     = date.today().strftime("%Y-%m-%d")
    existing  = sorted(output_base.glob(f"{today}_Run-*"))
    if existing:
        last_num = int(existing[-1].name.split("-")[-1])
        num      = last_num + 1
    else:
        num = 1
    run_dir = output_base / f"{today}_Run-{num:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir

# ── File collection ─────────────────────────────────────────────────────────

def _collect_files(scan_root: Path, exclude_dirs: list[str],
                   exclude_files: list[str]) -> list[Path]:
    result = []
    for py_file in sorted(scan_root.rglob("*.py")):
        # Directory exclusion: every path component is checked
        parts = py_file.parts
        if any(ex in parts for ex in exclude_dirs):
            continue
        # File exclusion
        if py_file.name in exclude_files:
            continue
        result.append(py_file)
    return result

# ── AST import extraction ────────────────────────────────────────────────────

def _extract_imports(py_file: Path) -> list[dict]:
    """
    Returns a list of dicts:
        module  — imported module (top level, e.g. "garmin_api")
        full    — full module path (e.g. "garmin.garmin_api")
        symbols — list of imported symbols (for "from X import a, b")
        kind    — "import" | "from"
        lineno  — line number
    """
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree   = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return []
    except Exception:
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                imports.append({
                    "module":  top,
                    "full":    alias.name,
                    "symbols": [],
                    "kind":    "import",
                    "lineno":  node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            top     = node.module.split(".")[0]
            symbols = [a.name for a in node.names] if node.names else []
            imports.append({
                "module":  top,
                "full":    node.module,
                "symbols": symbols,
                "kind":    "from",
                "lineno":  node.lineno,
            })
    return imports

# ── Dynamic import detection ───────────────────────────────────────────────

# Function names that trigger a dynamic import
_DYNAMIC_PATTERNS = {
    "import_module",            # importlib.import_module("x")
    "spec_from_file_location",  # importlib.util.spec_from_file_location("n", path)
    "__import__",               # __import__("x")
    "find_spec",                # importlib.util.find_spec("x")
}

def _extract_dynamic_imports(py_file: Path) -> list[dict]:
    """
    Searches for dynamic import usages via AST:
      importlib.import_module(...)
      importlib.util.spec_from_file_location(...)
      __import__(...)
      importlib.util.find_spec(...)

    Returns a list of dicts:
        pattern  — detected pattern (e.g. "import_module")
        arg      — first argument as string if literal, else None
        lineno   — line number
        call_str — simplified representation of the call
    """
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree   = ast.parse(source, filename=str(py_file))
    except Exception:
        return []

    findings = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        func_name = None

        # Direct: __import__("x")
        if isinstance(func, ast.Name):
            func_name = func.id

        # Attribute call: importlib.import_module(...) or importlib.util.spec_from_file_location(...)
        elif isinstance(func, ast.Attribute):
            func_name = func.attr

        if func_name not in _DYNAMIC_PATTERNS:
            continue

        # Read first argument — only if string literal
        arg_value = None
        if node.args:
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                arg_value = first_arg.value

        # Human-readable usage string for the report
        if arg_value:
            call_str = f'{func_name}("{arg_value}", ...)'
        else:
            call_str = f"{func_name}(...)"

        findings.append({
            "pattern":  func_name,
            "arg":      arg_value,
            "lineno":   node.lineno,
            "call_str": call_str,
        })

    return findings


def analyse_dynamic(scan_root: Path, all_files: list[Path]) -> dict[str, list[dict]]:
    """
    Runs dynamic import analysis for all files.
    Returns dict {rel_path: [finding, ...]} — only files with matches.
    """
    result = {}
    for py_file in all_files:
        try:
            rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        except ValueError:
            rel = py_file.name

        findings = _extract_dynamic_imports(py_file)
        if findings:
            result[rel] = findings

    return result


# ── Internal / external classification ────────────────────────────────────────────

def _build_module_index(all_files: list[Path], scan_root: Path) -> dict[str, Path]:
    """
    Builds an index: module name (without .py) → absolute path.
    Considers all levels (e.g. "my_api" from pkg/my_api.py,
    as well as "my_api" directly if in the root).
    """
    index = {}
    for f in all_files:
        # Simple file name without extension
        stem = f.stem
        index[stem] = f
        # Also register the relative dotted path
        # e.g. pkg/my_api.py → "pkg.my_api"
        try:
            rel  = f.relative_to(scan_root)
            dotted = ".".join(rel.with_suffix("").parts)
            index[dotted] = f
        except ValueError:
            pass
    return index

def _is_internal(module_name: str, full_name: str,
                 module_index: dict[str, Path]) -> bool:
    return (module_name in module_index) or (full_name in module_index)

def _resolve_internal_path(module_name: str, full_name: str,
                            module_index: dict[str, Path],
                            scan_root: Path) -> str | None:
    """Returns relative path (relative to scan_root) or None."""
    for key in (full_name, module_name):
        if key in module_index:
            try:
                return str(module_index[key].relative_to(scan_root)).replace("\\", "/")
            except ValueError:
                return str(module_index[key]).replace("\\", "/")
    return None

# ── Main analysis ─────────────────────────────────────────────────────────────

def analyse(scan_root: Path, all_files: list[Path]) -> dict:
    """
    Returns dict:
        by_file    — {rel_path: {"internal": [...], "external": [...]}}
        importers  — {rel_path: [rel_path, ...]}  (inverse map)
    """
    module_index = _build_module_index(all_files, scan_root)

    by_file  = {}
    importers = defaultdict(set)   # who imports this module

    for py_file in all_files:
        try:
            rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        except ValueError:
            rel = py_file.name

        raw_imports = _extract_imports(py_file)
        internal    = []
        external    = []

        for imp in raw_imports:
            if _is_internal(imp["module"], imp["full"], module_index):
                resolved = _resolve_internal_path(
                    imp["module"], imp["full"], module_index, scan_root)
                entry = {
                    "module":   imp["full"],
                    "symbols":  imp["symbols"],
                    "kind":     imp["kind"],
                    "lineno":   imp["lineno"],
                    "resolved": resolved or imp["full"],
                }
                internal.append(entry)
                if resolved:
                    importers[resolved].add(rel)
            else:
                external.append({
                    "module":  imp["full"],
                    "symbols": imp["symbols"],
                    "kind":    imp["kind"],
                    "lineno":  imp["lineno"],
                })

        by_file[rel] = {
            "internal": internal,
            "external": external,
        }

    # importers to sorted lists
    importers_clean = {k: sorted(v) for k, v in importers.items()}

    return {
        "by_file":   by_file,
        "importers": importers_clean,
    }

# ── CSV-Output ────────────────────────────────────────────────────────────────

def write_csv(result: dict, out_path: Path) -> None:
    """
    columns: file | type | imported_module | symbols | lineno | resolved_path
    """
    rows = []
    for rel, data in sorted(result["by_file"].items()):
        for imp in data["internal"]:
            rows.append({
                "file":          rel,
                "type":          "internal",
                "imported_module": imp["module"],
                "symbols":       ", ".join(imp["symbols"]) if imp["symbols"] else "",
                "lineno":        imp["lineno"],
                "resolved_path": imp["resolved"],
            })
        for imp in data["external"]:
            rows.append({
                "file":          rel,
                "type":          "external",
                "imported_module": imp["module"],
                "symbols":       ", ".join(imp["symbols"]) if imp["symbols"] else "",
                "lineno":        imp["lineno"],
                "resolved_path": "",
            })

    fieldnames = ["file", "type", "imported_module", "symbols", "lineno", "resolved_path"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

# ── MD-Output ─────────────────────────────────────────────────────────────────

def write_md(result: dict, scan_root: Path, run_dir: Path,
             all_files: list[Path], out_path: Path) -> None:

    by_file   = result["by_file"]
    importers = result["importers"]

    # ── Summary data ────────────────────────────────────────────────────────
    total_modules   = len(by_file)
    leaf_nodes      = []   # no internal imports
    entry_points    = []   # no importers (nobody imports them)
    high_coupling   = []   # 5+ importers

    for rel, data in sorted(by_file.items()):
        n_internal  = len(data["internal"])
        n_importers = len(importers.get(rel, []))

        if n_internal == 0:
            leaf_nodes.append(rel)
        if n_importers == 0:
            entry_points.append(rel)
        if n_importers >= 5:
            high_coupling.append((rel, n_importers))

    high_coupling.sort(key=lambda x: -x[1])

    lines = []
    now   = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    lines += [
        "# Dependency Map — Needful Things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | value |",
        f"|---|---|",
        f"| modules total | {total_modules} |",
        f"| Leaf nodes (no internal imports) | {len(leaf_nodes)} |",
        f"| Entry points (no importers) | {len(entry_points)} |",
        f"| Highly coupled (5+ importers) | {len(high_coupling)} |",
        "",
    ]

    # Leaf-Nodes
    lines += [
        "### Leaf-Nodes",
        "_These modules import nothing internal — possible utility / config modules._",
        "",
    ]
    for rel in sorted(leaf_nodes):
        lines.append(f"- `{rel}`")
    lines.append("")

    # Entry-Points
    lines += [
        "### Entry-Points",
        "_Not imported by any other module — possible top-level entry points._",
        "",
    ]
    for rel in sorted(entry_points):
        lines.append(f"- `{rel}`")
    lines.append("")

    # Highly coupled modules
    if high_coupling:
        lines += [
            "### Highly coupled modules (5+ importers)",
            "_Change risk: many modules depend on these._",
            "",
            "| module | Importers |",
            "|---|---|",
        ]
        for rel, count in high_coupling:
            lines.append(f"| `{rel}` | {count} |")
        lines.append("")

    lines += ["---", ""]

    # ── table 1: file → imports ────────────────────────────────────────
    lines += [
        "## table 1 — file → imports",
        "",
        "| file | Type | module / symbol | line | Resolved path |",
        "|---|---|---|---|---|",
    ]

    for rel, data in sorted(by_file.items()):
        all_imports = (
            [(i, "internal") for i in data["internal"]] +
            [(i, "external") for i in data["external"]]
        )
        if not all_imports:
            lines.append(f"| `{rel}` | — | _(no imports)_ | | |")
            continue
        first = True
        for imp, itype in all_imports:
            file_col     = f"`{rel}`" if first else ""
            first        = False
            symbols_str  = f" → `{', '.join(imp['symbols'])}`" if imp["symbols"] else ""
            module_col   = f"`{imp['module']}`{symbols_str}"
            resolved_col = f"`{imp.get('resolved', '')}`" if itype == "internal" else ""
            lines.append(
                f"| {file_col} | {itype} | {module_col} | {imp['lineno']} | {resolved_col} |"
            )

    lines += ["", "---", ""]

    # ── table 2: who imports this file ────────────────────────────────
    lines += [
        "## table 2 — Who imports this module (inverse)",
        "",
        "| module | Imported by |",
        "|---|---|",
    ]

    for rel in sorted(by_file.keys()):
        imp_by = importers.get(rel, [])
        if not imp_by:
            lines.append(f"| `{rel}` | _(nobody)_ |")
        else:
            first = True
            for importer in sorted(imp_by):
                mod_col = f"`{rel}`" if first else ""
                first   = False
                lines.append(f"| {mod_col} | `{importer}` |")

    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

# ── Dynamic-MD-Output ────────────────────────────────────────────────────────

def write_dynamic_md(dynamic: dict[str, list[dict]], scan_root: Path,
                     run_dir: Path, out_path: Path) -> None:
    """
    Generates dep_map_dynamic.md — separate file for dynamic imports.
    Only files with matches are listed.
    """
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# Dynamic Import Map — Needful Things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "## note",
        "",
        "This file captures dynamic imports that the static AST scan",
        "does **not** see as a dependency in `dep_map.md`.",
        "",
        "Detected patterns:",
        "- `import_module(...)` — importlib.import_module",
        "- `spec_from_file_location(...)` — importlib.util.spec_from_file_location",
        "- `find_spec(...)` — importlib.util.find_spec",
        "- `__import__(...)` — direct built-in import",
        "",
        "column **module argument**: string literal if resolvable by AST,",
        "else `(dynamic — value not resolvable)` if variable or expression.",
        "",
        "---",
        "",
    ]

    if not dynamic:
        lines += [
            "## result",
            "",
            "No dynamic imports found.",
            "",
        ]
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return

    # Summary
    total_files   = len(dynamic)
    total_hits    = sum(len(v) for v in dynamic.values())
    resolvable    = sum(
        1 for hits in dynamic.values()
        for h in hits if h["arg"] is not None
    )
    unresolvable  = total_hits - resolvable

    lines += [
        "## Summary",
        "",
        f"| Metric | value |",
        f"|---|---|",
        f"| files with dynamic imports | {total_files} |",
        f"| match total | {total_hits} |",
        f"| module argument resolvable (string literal) | {resolvable} |",
        f"| Not resolvable (variable / expression) | {unresolvable} |",
        "",
        "---",
        "",
        "## match",
        "",
        "| file | line | pattern | module argument |",
        "|---|---|---|---|",
    ]

    for rel, hits in sorted(dynamic.items()):
        first = True
        for hit in sorted(hits, key=lambda h: h["lineno"]):
            file_col = f"`{rel}`" if first else ""
            first    = False
            arg_col  = f"`{hit['arg']}`" if hit["arg"] else "_(dynamic — not resolvable)_"
            lines.append(
                f"| {file_col} | {hit['lineno']} | `{hit['pattern']}` | {arg_col} |"
            )

    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ── File I/O Analyse ─────────────────────────────────────────────────────────

# Function names that indicate file I/O
_FILEIO_WRITE = {
    "write_text", "write_bytes", "open",        # Path.write_text, open()
    "dump", "dumps",                             # json.dump
    "move", "copy", "copy2", "copytree",         # shutil
    "rename", "replace", "unlink", "rmdir",      # Path ops
    "mkdir",                                     # Path.mkdir
}
_FILEIO_READ = {
    "read_text", "read_bytes",                   # Path.read_text
    "load", "loads",                             # json.load
    "open",                                      # open() — including reads
    "glob", "rglob", "iterdir",                  # directory scan
    "exists", "is_file", "is_dir", "stat",       # existence check
}

def _extract_fileio(py_file: Path) -> list[dict]:
    """
    Searches for file I/O operations via AST.
    Returns a list of dicts:
        op       — function name
        mode     — "write" | "read" | "read/write"
        lineno   — line number
        arg      — first argument as string if literal, else None
    """
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree   = ast.parse(source, filename=str(py_file))
    except Exception:
        return []

    findings = []
    seen     = set()   # (op, lineno) — deduplication

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        op   = None

        if isinstance(func, ast.Name):
            op = func.id
        elif isinstance(func, ast.Attribute):
            op = func.attr

        if op is None:
            continue

        is_write = op in _FILEIO_WRITE
        is_read  = op in _FILEIO_READ

        if not (is_write or is_read):
            continue

        key = (op, node.lineno)
        if key in seen:
            continue
        seen.add(key)

        # Determine the mode
        if is_write and is_read:
            mode = "read/write"
        elif is_write:
            mode = "write"
        else:
            mode = "read"

        # open() — read mode from second argument if present
        if op == "open":
            mode = "read/write"   # Default
            # Evaluate the second argument (mode string)
            mode_arg = None
            if len(node.args) >= 2:
                a = node.args[1]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    mode_arg = a.value
            # Keyword argument "mode=..."
            if mode_arg is None:
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode_arg = kw.value.value
            if mode_arg:
                if "w" in mode_arg or "a" in mode_arg or "x" in mode_arg:
                    mode = "write"
                elif "r" in mode_arg:
                    mode = "read"

        # First argument as a path note
        arg_val = None
        if node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                arg_val = a.value

        findings.append({
            "op":     op,
            "mode":   mode,
            "lineno": node.lineno,
            "arg":    arg_val,
        })

    return findings


def analyse_fileio(scan_root: Path, all_files: list[Path]) -> dict[str, list[dict]]:
    """
    Returns dict {rel_path: [finding, ...]} — only files with matches.
    Each finding now also contains "function" — the enclosing function name.
    """
    result = {}
    for py_file in all_files:
        try:
            rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        except ValueError:
            rel = py_file.name

        findings = _extract_fileio(py_file)
        if not findings:
            continue

        # Add the function context afterwards
        try:
            source  = py_file.read_text(encoding="utf-8", errors="replace")
            tree    = ast.parse(source, filename=str(py_file))
            parents = _build_parent_map(tree)
            # Lineno → finding index for fast lookup
            lineno_map: dict[int, list[dict]] = defaultdict(list)
            for f in findings:
                lineno_map[f["lineno"]].append(f)
            # Tag all call nodes on matching lines with function context
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and node.lineno in lineno_map:
                    func_name = _enclosing_function(node, parents)
                    for f in lineno_map[node.lineno]:
                        if "function" not in f:
                            f["function"] = func_name
        except Exception:
            pass

        # Fallback for findings without context
        for f in findings:
            if "function" not in f:
                f["function"] = "<module>"

        result[rel] = findings
    return result


def write_fileio_md(fileio: dict[str, list[dict]], scan_root: Path,
                    run_dir: Path, out_path: Path) -> None:
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    total_files = len(fileio)
    total_write = sum(1 for hits in fileio.values()
                      for h in hits if h["mode"] in ("write", "read/write"))
    total_read  = sum(1 for hits in fileio.values()
                      for h in hits if h["mode"] in ("read", "read/write"))

    lines = [
        "# File I/O Map — Needful Things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "## note",
        "",
        "Captures: `open()`, `write_text()`, `read_text()`, `json.dump/load`,",
        "`shutil.move/copy`, `Path.rename/unlink/mkdir`, `glob/rglob`.",
        "Relevant for sole-write-authority verification: write operations",
        "show which module actually writes to disk.",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | value |",
        f"|---|---|",
        f"| files with file I/O | {total_files} |",
        f"| Write operations total | {total_write} |",
        f"| Read operations total | {total_read} |",
        "",
        "---",
        "",
        "## Details",
        "",
        "| file | line | Mode | Operation | path argument |",
        "|---|---|---|---|---|",
    ]

    for rel, hits in sorted(fileio.items()):
        first = True
        for hit in sorted(hits, key=lambda h: h["lineno"]):
            file_col = f"`{rel}`" if first else ""
            first    = False
            arg_col  = f"`{hit['arg']}`" if hit["arg"] else "_(variable)_"
            lines.append(
                f"| {file_col} | {hit['lineno']} | {hit['mode']} "
                f"| `{hit['op']}` | {arg_col} |"
            )

    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ── Caller analysis ────────────────────────────────────────────────────────────

def analyse_callers(scan_root: Path, all_files: list[Path],
                    importers: dict[str, list[str]],
                    top_threshold: int = 5) -> dict:
    """
    Analyzes function calls via AST — two scan paths:

    path 1 — attribute usages:  module.function()
        Detects usages when the module is referenced as an object.

    path 2 — Direct usages after from-import:
        from my_config import get_path
        get_path()   ← now detected

        Method: collect all from-X-import-func statements per file
        (func_name → source_module), then check all ast.Name calls
        whether the name appears in that table.

        Known limitation (documented in build_dep_map_LIMITATIONS.md):
        Shadowing is not detected. If an imported name is locally
        overridden, the call still counts as a match.
        Rarely seen in typical code — false positives possible.

    Returns dict:
        all     — {callee_rel: [{caller_file, func_name, lineno, via}, ...]}
        top8    — like all, but only modules with >= top_threshold importers
    """
    # Build the module index: stem → rel_path
    module_index: dict[str, str] = {}
    for py_file in all_files:
        try:
            rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        except ValueError:
            rel = py_file.name
        module_index[py_file.stem] = rel
        try:
            dotted = ".".join(
                py_file.relative_to(scan_root).with_suffix("").parts
            )
            module_index[dotted] = rel
        except ValueError:
            pass

    # Determine top modules (>= threshold importers)
    top_modules = {
        rel for rel, imp_list in importers.items()
        if len(imp_list) >= top_threshold
    }

    # Initialize the caller dict
    all_callers: dict[str, list[dict]] = defaultdict(list)

    # Exclude dunder methods
    _DUNDER = {"__init__", "__str__", "__repr__", "__len__", "__eq__",
               "__hash__", "__enter__", "__exit__", "__iter__", "__next__",
               "__getitem__", "__setitem__", "__delitem__", "__contains__"}

    for py_file in all_files:
        try:
            caller_rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        except ValueError:
            caller_rel = py_file.name

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree   = ast.parse(source, filename=str(py_file))
        except Exception:
            continue

        # ── path 2 preparation: from-import table per file ──────────────
        # func_name → callee_rel  (internal modules only)
        from_import_map: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module is None:
                continue
            top    = node.module.split(".")[0]
            full   = node.module
            # Internal module?
            callee = module_index.get(full) or module_index.get(top)
            if callee is None or callee == caller_rel:
                continue
            for alias in node.names:
                # Consider aliases: from X import func as f → track "f"
                local_name = alias.asname if alias.asname else alias.name
                from_import_map[local_name] = (callee, alias.name)

        # ── Both paths: all ast.Call nodes ──────────────────────────────────
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func

            # ── path 1: attribute call module.function() ────────────────────
            if isinstance(func, ast.Attribute):
                func_name = func.attr
                if func_name in _DUNDER:
                    continue
                receiver   = func.value
                callee_rel = None
                if isinstance(receiver, ast.Name):
                    callee_rel = module_index.get(receiver.id)
                elif isinstance(receiver, ast.Attribute):
                    callee_rel = module_index.get(receiver.attr)
                if callee_rel and callee_rel != caller_rel:
                    all_callers[callee_rel].append({
                        "caller_file": caller_rel,
                        "func_name":   func_name,
                        "lineno":      node.lineno,
                        "via":         "attribute",
                    })

            # ── path 2: direct call func() after from-import ─────────────────
            elif isinstance(func, ast.Name):
                local_name = func.id
                if local_name in _DUNDER:
                    continue
                if local_name not in from_import_map:
                    continue
                callee_rel, orig_name = from_import_map[local_name]
                if callee_rel == caller_rel:
                    continue
                all_callers[callee_rel].append({
                    "caller_file": caller_rel,
                    "func_name":   orig_name,
                    "lineno":      node.lineno,
                    "via":         "from-import",
                })

    # Filter out the top 8
    top_callers = {
        rel: hits for rel, hits in all_callers.items()
        if rel in top_modules
    }

    return {
        "all":  dict(all_callers),
        "top8": top_callers,
    }


def _write_callers_md(callers: dict[str, list[dict]], scan_root: Path,
                      run_dir: Path, out_path: Path,
                      title: str, subtitle: str) -> None:
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    total_callees = len(callers)
    total_calls   = sum(len(v) for v in callers.values())
    total_callers = len({
        h["caller_file"] for hits in callers.values() for h in hits
    })

    lines = [
        f"# {title} — Needful Things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "## note",
        "",
        subtitle,
        "Two scan paths: attribute calls (`module.function()`) and",
        "direct calls after from-import (`from X import func` → `func()`).",
        "Dunder methods are filtered out. Column **via** shows the detection path.",
        "Known limitation: shadowing not detected — see `build_dep_map_LIMITATIONS.md`.",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Metric | value |",
        f"|---|---|",
        f"| Called modules | {total_callees} |",
        f"| usages total | {total_calls} |",
        f"| Unique caller files | {total_callers} |",
        "",
    ]

    # Compact overview
    lines += [
        "## Overview",
        "",
        "| module (callee) | usages | Unique callers |",
        "|---|---|---|",
    ]
    for rel in sorted(callers.keys(),
                      key=lambda r: -len(callers[r])):
        hits    = callers[rel]
        n_calls = len(hits)
        n_caller = len({h["caller_file"] for h in hits})
        lines.append(f"| `{rel}` | {n_calls} | {n_caller} |")

    lines += ["", "---", ""]

    # Detail sections
    lines.append("## Details")
    lines.append("")

    for rel in sorted(callers.keys()):
        hits = callers[rel]
        lines += [
            f"### `{rel}`",
            "",
            f"| Called by | Function | Line | Via |",
            f"|---|---|---|---|",
        ]
        for hit in sorted(hits, key=lambda h: (h["caller_file"], h["lineno"])):
            via = hit.get("via", "attribute")
            lines.append(
                f"| `{hit['caller_file']}` | `{hit['func_name']}` | {hit['lineno']} | {via} |"
            )
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_callers_top8_md(callers: dict, scan_root: Path,
                           run_dir: Path, out_path: Path) -> None:
    _write_callers_md(
        callers["top8"], scan_root, run_dir, out_path,
        title="Caller Map — Top modules (5+ importers)",
        subtitle="Only modules with 5 or more importers. "
                 "Shows which functions of highly-coupled modules are actually called.\n",
    )


def write_callers_all_md(callers: dict, scan_root: Path,
                          run_dir: Path, out_path: Path) -> None:
    _write_callers_md(
        callers["all"], scan_root, run_dir, out_path,
        title="Caller Map — whole project",
        subtitle="All attribute usages between internal modules. "
                 "Full picture of call connections in the project.\n",
    )


# ── AST context helpers ────────────────────────────────────────────────────────

def _build_parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    """Builds an id(node) → parent map for the full AST."""
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> str:
    """
    Returns the qualified function name enclosing an AST node.
    Accounts for nested classes and functions:
        "MyClass.my_method", "outer.<locals>.inner", "<module>"
    """
    parts = []
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(current.name)
        elif isinstance(current, ast.ClassDef):
            parts.append(current.name)
        current = parents.get(id(current))
    if not parts:
        return "<module>"
    return ".".join(reversed(parts))


# ── Exception handler analysis ─────────────────────────────────────────────────

# Risk classification:
#   critical — handler swallows the error completely (pass, return None/False/"")
#   silent   — handler only logs, no reraising, no raise
#   broad    — exception type too broad (Exception, BaseException, bare except)
#   ok       — specific type + reraising or controlled raise

_BROAD_TYPES = {"Exception", "BaseException"}

def _classify_handler(handler: ast.ExceptHandler) -> dict:
    """
    Classifies a single except block.
    Returns dict:
        exc_type  — type as string or "bare" (no type specified)
        risk      — "critical" | "silent" | "broad" | "ok"
        body_desc — short description of what happens in the body
        lineno    — line number of the except statement
    """
    # Determine the exception type
    if handler.type is None:
        exc_type = "bare"
        is_broad = True
    elif isinstance(handler.type, ast.Name):
        exc_type = handler.type.id
        is_broad = exc_type in _BROAD_TYPES
    elif isinstance(handler.type, ast.Attribute):
        exc_type = f"{ast.unparse(handler.type)}"
        is_broad = handler.type.attr in _BROAD_TYPES
    elif isinstance(handler.type, ast.Tuple):
        parts    = [ast.unparse(e) for e in handler.type.elts]
        exc_type = f"({', '.join(parts)})"
        is_broad = any(
            (isinstance(e, ast.Name) and e.id in _BROAD_TYPES)
            for e in handler.type.elts
        )
    else:
        exc_type = "unknown"
        is_broad = False

    body = handler.body

    # Body analysis
    has_pass    = any(isinstance(n, ast.Pass) for n in body)
    has_reraise = any(
        isinstance(n, ast.Raise) and n.exc is None
        for n in ast.walk(ast.Module(body=body, type_ignores=[]))
    )
    has_raise   = any(
        isinstance(n, ast.Raise) and n.exc is not None
        for n in ast.walk(ast.Module(body=body, type_ignores=[]))
    )
    has_log     = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("error", "warning", "exception", "critical",
                            "debug", "info", "log")
        for n in ast.walk(ast.Module(body=body, type_ignores=[]))
    )

    # Only a return with None/False/empty string/0?
    silent_returns = False
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Return):
            v = node.value
            if v is None:
                silent_returns = True
            elif isinstance(v, ast.Constant) and v.value in (None, False, "", 0, []):
                silent_returns = True

    # Body description
    parts = []
    if has_pass:        parts.append("pass")
    if silent_returns:  parts.append("return None/False/empty")
    if has_log:         parts.append("log")
    if has_reraise:     parts.append("reraise")
    if has_raise:       parts.append("raise")
    if not parts:       parts.append("other handling")
    body_desc = " + ".join(parts)

    # Determine the risk
    if has_pass and not has_reraise and not has_raise:
        risk = "critical"
    elif silent_returns and not has_reraise and not has_raise:
        risk = "critical"
    elif is_broad and not has_reraise and not has_raise:
        risk = "silent" if has_log else "broad"
    elif not has_reraise and not has_raise and has_log:
        risk = "silent"
    else:
        risk = "ok"

    return {
        "exc_type":  exc_type,
        "risk":      risk,
        "body_desc": body_desc,
        "lineno":    handler.lineno,
    }


def analyse_exceptions(scan_root: Path, all_files: list[Path]) -> dict[str, list[dict]]:
    """
    Scans all except blocks via AST.
    Returns dict {rel_path: [finding, ...]} — all handlers, sorted by risk.
    Each finding now also contains "function" — the enclosing function name.
    """
    result = {}

    for py_file in all_files:
        try:
            rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        except ValueError:
            rel = py_file.name

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree   = ast.parse(source, filename=str(py_file))
        except Exception:
            continue

        parents  = _build_parent_map(tree)
        findings = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                finding           = _classify_handler(node)
                finding["lineno"] = node.lineno
                finding["function"] = _enclosing_function(node, parents)
                findings.append(finding)

        if findings:
            _risk_order = {"critical": 0, "silent": 1, "broad": 2, "ok": 3}
            findings.sort(key=lambda f: (_risk_order.get(f["risk"], 9), f["lineno"]))
            result[rel] = findings

    return result


def write_exceptions_md(exceptions: dict[str, list[dict]], scan_root: Path,
                        run_dir: Path, out_path: Path) -> None:
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    # Total statistics
    total_handlers = sum(len(v) for v in exceptions.values())
    by_risk: dict[str, int] = {"critical": 0, "silent": 0, "broad": 0, "ok": 0}
    for hits in exceptions.values():
        for h in hits:
            by_risk[h["risk"]] = by_risk.get(h["risk"], 0) + 1

    # Sort files by highest risk
    def _file_risk(hits):
        order = {"critical": 0, "silent": 1, "broad": 2, "ok": 3}
        return min(order.get(h["risk"], 9) for h in hits)

    lines = [
        "# Exception Handler Map — Needful Things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "## note",
        "",
        "Captures all `except` blocks via AST. Risk classification:",
        "",
        "| Risk | Meaning |",
        "|---|---|",
        "| `critical` | Handler silently swallows the error (`pass`, `return None/False`) — no log, no reraise |",
        "| `silent` | error is logged but not propagated — caller receives no signal |",
        "| `broad` | Exception type too broad (`Exception`, `BaseException`, bare `except`) without reraise |",
        "| `ok` | Specific type or controlled reraise / raise |",
        "",
        "**Primary lens for phase 2:** `critical` and `silent` are candidates for",
        "silent failure — the caller receives no signal that something went wrong.",
        "Relevant for an archiving tool, where unnoticed errors mean data loss.",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Risk | count |",
        f"|---|---|",
        f"| critical | {by_risk['critical']} |",
        f"| silent | {by_risk['silent']} |",
        f"| broad | {by_risk['broad']} |",
        f"| ok | {by_risk['ok']} |",
        f"| **total** | **{total_handlers}** |",
        "",
        "---",
        "",
        "## Details",
        "",
        "| file | line | Exception type | Risk | Body |",
        "|---|---|---|---|---|",
    ]

    for rel in sorted(exceptions.keys(), key=lambda r: _file_risk(exceptions[r])):
        hits  = exceptions[rel]
        first = True
        for hit in hits:
            file_col = f"`{rel}`" if first else ""
            first    = False
            risk_col = f"**{hit['risk']}**" if hit["risk"] in ("critical", "silent") else hit["risk"]
            lines.append(
                f"| {file_col} | {hit['lineno']} "
                f"| `{hit['exc_type']}` | {risk_col} | {hit['body_desc']} |"
            )

    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")



# ── Records snapshot (serialization) ────────────────────────────────────────

_RECORDS_VERSION = 1
_RISK_RANK = {"ok": 0, "broad": 1, "silent": 2, "critical": 3}


def _build_records(exceptions: dict[str, list[dict]],
                   fileio:     dict[str, list[dict]]) -> list[dict]:
    """
    Builds the deterministically sorted records snapshot.
    Key for exception: (kind, module, function, exception_type, risk_class)
    Key for FileIO:    (kind, module, function, operation)
    Line number is metadata only — never part of the key.
    """
    records: list[dict] = []

    for module, hits in exceptions.items():
        for h in hits:
            records.append({
                "kind":           "exception",
                "module":         module,
                "function":       h.get("function", "<module>"),
                "exception_type": h["exc_type"],
                "risk_class":     h["risk"],
                "line":           h["lineno"],
            })

    for module, hits in fileio.items():
        for h in hits:
            records.append({
                "kind":      "fileio",
                "module":    module,
                "function":  h.get("function", "<module>"),
                "operation": h["mode"],
                "detail":    h["op"],
                "line":      h["lineno"],
            })

    # Sort deterministically — line number NOT in the sort key
    def _sort_key(r: dict) -> tuple:
        if r["kind"] == "exception":
            return (r["kind"], r["module"], r["function"],
                    r["exception_type"], r["risk_class"])
        return (r["kind"], r["module"], r["function"],
                r["operation"], r["detail"])

    records.sort(key=_sort_key)
    return records


def write_records_json(records: list[dict], run_dir: Path,
                       out_path: Path) -> dict:
    """
    Writes dep_map_records.json. Returns the complete snapshot dict
    (used directly as the current baseline for delta comparison).
    """
    now = datetime.now().isoformat(timespec="seconds")
    snapshot = {
        "version":      _RECORDS_VERSION,
        "generated_at": now,
        "map_basis":    f"build_dep_map.py {run_dir.name}",
        "records":      records,
    }
    out_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return snapshot


# ── delta comparison ───────────────────────────────────────────────────────────

def _exc_key_full(r: dict) -> tuple:
    """Full key incl. risk_class — for NEU/WEG."""
    return (r["module"], r["function"], r["exception_type"], r["risk_class"])


def _exc_key_reduced(r: dict) -> tuple:
    """Reduced key without risk_class — for GEKIPPT detection."""
    return (r["module"], r["function"], r["exception_type"])


def _fio_key(r: dict) -> tuple:
    return (r["module"], r["function"], r["operation"], r["detail"])


def compare_records(baseline: dict, current: dict,
                    accepted_transitions: list | None = None) -> dict:
    """
    Semantic comparison baseline vs. current.

    accepted_transitions : list[tuple] | None — from
        build_dep_map_config.ACCEPTED_GEKIPPT. Each entry is
        (module, function, exception_type, reason). A GEKIPPT regression
        whose (module, function, exception_type) appears here is marked
        "accepted" — it stays visible in gekippt_exc/dep_map_delta.md, but
        does not count towards the blocker total.

    Returns dict:
        neu_exc      — list[dict]
        weg_exc      — list[dict]
        gekippt_exc  — list[dict]  {baseline_rec, current_rec, direction,
                                     accepted, accepted_reason}
        neu_fio      — list[dict]
        weg_fio      — list[dict]
    """
    accepted_transitions = accepted_transitions or []
    accepted_set    = {(m, f, t) for (m, f, t, _reason) in accepted_transitions}
    accepted_reason = {(m, f, t): _reason for (m, f, t, _reason) in accepted_transitions}

    b_recs = baseline.get("records", [])
    c_recs = current.get("records",  [])

    b_exc = [r for r in b_recs if r["kind"] == "exception"]
    c_exc = [r for r in c_recs if r["kind"] == "exception"]
    b_fio = [r for r in b_recs if r["kind"] == "fileio"]
    c_fio = [r for r in c_recs if r["kind"] == "fileio"]

    # ── Exception delta ───────────────────────────────────────────────────────
    b_exc_full = {_exc_key_full(r): r for r in b_exc}
    c_exc_full = {_exc_key_full(r): r for r in c_exc}

    # Candidates for GEKIPPT: same reduced key, different risk_class
    b_exc_red = {}
    for r in b_exc:
        k = _exc_key_reduced(r)
        b_exc_red.setdefault(k, []).append(r)
    c_exc_red = {}
    for r in c_exc:
        k = _exc_key_reduced(r)
        c_exc_red.setdefault(k, []).append(r)

    gekippt_exc: list[dict] = []
    gekippt_full_keys: set  = set()   # do not count these keys as NEW/REMOVED

    for red_key in set(b_exc_red) & set(c_exc_red):
        b_list = b_exc_red[red_key]
        c_list = c_exc_red[red_key]
        # Simplest case: exactly one on each side, risk_class differs
        if len(b_list) == 1 and len(c_list) == 1:
            br, cr = b_list[0], c_list[0]
            if br["risk_class"] != cr["risk_class"]:
                b_rank = _RISK_RANK.get(br["risk_class"], 0)
                c_rank = _RISK_RANK.get(cr["risk_class"], 0)
                direction = "regression" if c_rank > b_rank else "improvement"
                is_accepted = direction == "regression" and red_key in accepted_set
                gekippt_exc.append({
                    "baseline": br,
                    "current":  cr,
                    "direction": direction,
                    "accepted": is_accepted,
                    "accepted_reason": accepted_reason.get(red_key, "") if is_accepted else "",
                })
                gekippt_full_keys.add(_exc_key_full(br))
                gekippt_full_keys.add(_exc_key_full(cr))

    neu_exc = [
        r for k, r in c_exc_full.items()
        if k not in b_exc_full and k not in gekippt_full_keys
    ]
    weg_exc = [
        r for k, r in b_exc_full.items()
        if k not in c_exc_full and k not in gekippt_full_keys
    ]

    # ── FileIO-delta ──────────────────────────────────────────────────────────
    b_fio_map = {_fio_key(r): r for r in b_fio}
    c_fio_map = {_fio_key(r): r for r in c_fio}

    neu_fio = [r for k, r in c_fio_map.items() if k not in b_fio_map]
    weg_fio = [r for k, r in b_fio_map.items() if k not in c_fio_map]

    return {
        "neu_exc":     sorted(neu_exc,     key=_exc_key_full),
        "weg_exc":     sorted(weg_exc,     key=_exc_key_full),
        "gekippt_exc": sorted(
            gekippt_exc,
            key=lambda x: (
                0 if x["direction"] == "regression" else 1,
                _exc_key_reduced(x["current"]),
            )
        ),
        "neu_fio":     sorted(neu_fio, key=_fio_key),
        "weg_fio":     sorted(weg_fio, key=_fio_key),
    }


# ── delta rendering ──────────────────────────────────────────────────────────────

def write_delta_md(delta: dict, baseline_snapshot: dict,
                   current_snapshot: dict, out_path: Path) -> str:
    """
    Writes dep_map_delta.md. Returns the stdout summary.
    """
    b_ts  = baseline_snapshot.get("generated_at", "?")
    b_run = baseline_snapshot.get("map_basis",    "?")
    c_ts  = current_snapshot.get("generated_at",  "?")
    c_run = current_snapshot.get("map_basis",     "?")

    neu_exc     = delta["neu_exc"]
    weg_exc     = delta["weg_exc"]
    gek_exc     = delta["gekippt_exc"]
    neu_fio     = delta["neu_fio"]
    weg_fio     = delta["weg_fio"]

    n_regression   = sum(1 for g in gek_exc
                         if g["direction"] == "regression" and not g.get("accepted"))
    n_regression_accepted = sum(1 for g in gek_exc
                                if g["direction"] == "regression" and g.get("accepted"))
    n_improvement  = sum(1 for g in gek_exc if g["direction"] == "improvement")

    lines = [
        "# Dependency Map — delta",
        "",
        f"Current  : {c_run} ({c_ts})",
        f"baseline : {b_run} ({b_ts})",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Category | exceptions | fileio |",
        "|---|---|---|",
        f"| NEU | {len(neu_exc)} | {len(neu_fio)} |",
        f"| WEG | {len(weg_exc)} | {len(weg_fio)} |",
        f"| GEKIPPT-Regression | {n_regression} | — |",
        f"| GEKIPPT-Regression (accepted) | {n_regression_accepted} | — |",
        f"| GEKIPPT-Verbesserung | {n_improvement} | — |",
        "",
    ]

    # ── GEKIPPT Regression (first — audit trigger) ───────────────────────────
    # Only non-accepted regressions count as blockers.
    regressions          = [g for g in gek_exc
                            if g["direction"] == "regression" and not g.get("accepted")]
    accepted_regressions = [g for g in gek_exc
                            if g["direction"] == "regression" and g.get("accepted")]
    if regressions:
        lines += [
            "## ⚠ GEKIPPT — Regression (audit first)",
            "",
            "| module | Function | Exception type | from → to |",
            "|---|---|---|---|",
        ]
        for g in regressions:
            b, c = g["baseline"], g["current"]
            lines.append(
                f"| `{c['module']}` | `{c['function']}` "
                f"| `{c['exception_type']}` "
                f"| {b['risk_class']} → **{c['risk_class']}** |"
            )
        lines.append("")
    else:
        lines += ["## ⚠ FLIPPED — Regression", "", "_(none)_", ""]

    # ── GEKIPPT Regression, accepted (informational, not a blocker) ──────────
    if accepted_regressions:
        lines += [
            "## GEKIPPT — Regression (accepted)",
            "",
            "_Deliberately chosen pattern — the error is passed on through a structured_",
            "_return value instead of raise/reraise, verified end to end._",
            "_See ACCEPTED_GEKIPPT in build_dep_map_config.py._",
            "",
            "| module | Function | Exception type | from → to | Reason |",
            "|---|---|---|---|---|",
        ]
        for g in accepted_regressions:
            b, c = g["baseline"], g["current"]
            lines.append(
                f"| `{c['module']}` | `{c['function']}` "
                f"| `{c['exception_type']}` "
                f"| {b['risk_class']} → {c['risk_class']} "
                f"| {g['accepted_reason']} |"
            )
        lines.append("")

    # ── NEU ───────────────────────────────────────────────────────────────────
    lines += ["## NEU", ""]
    if neu_exc or neu_fio:
        lines += [
            "| Kind | module | Function | Type / operation | Risk |",
            "|---|---|---|---|---|",
        ]
        for r in neu_exc:
            lines.append(
                f"| exception | `{r['module']}` | `{r['function']}` "
                f"| `{r['exception_type']}` | **{r['risk_class']}** |"
            )
        for r in neu_fio:
            lines.append(
                f"| fileio | `{r['module']}` | `{r['function']}` "
                f"| `{r['operation']}` / `{r['detail']}` | — |"
            )
        lines.append("")
    else:
        lines += ["_(none)_", ""]

    # ── WEG ───────────────────────────────────────────────────────────────────
    lines += ["## WEG", ""]
    if weg_exc or weg_fio:
        lines += [
            "| Kind | module | Function | Type / operation | Risk |",
            "|---|---|---|---|---|",
        ]
        for r in weg_exc:
            lines.append(
                f"| exception | `{r['module']}` | `{r['function']}` "
                f"| `{r['exception_type']}` | {r['risk_class']} |"
            )
        for r in weg_fio:
            lines.append(
                f"| fileio | `{r['module']}` | `{r['function']}` "
                f"| `{r['operation']}` / `{r['detail']}` | — |"
            )
        lines.append("")
    else:
        lines += ["_(none)_", ""]

    # ── GEKIPPT Verbesserung ──────────────────────────────────────────────────
    improvements = [g for g in gek_exc if g["direction"] == "improvement"]
    lines += ["## GEKIPPT — Verbesserung", ""]
    if improvements:
        lines += [
            "| module | Function | Exception type | from → to |",
            "|---|---|---|---|",
        ]
        for g in improvements:
            b, c = g["baseline"], g["current"]
            lines.append(
                f"| `{c['module']}` | `{c['function']}` "
                f"| `{c['exception_type']}` "
                f"| {b['risk_class']} → {c['risk_class']} |"
            )
        lines.append("")
    else:
        lines += ["_(none)_", ""]

    # ── Footnote ──────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "*fileio-note: `write-replace` may be `str.replace()` (L-1 limitation)"
        " — verify against the code.*",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # stdout summary
    return (
        f"DELTA vs {b_run} ({b_ts}): "
        f"{len(neu_exc)+len(neu_fio)} NEU · "
        f"{len(weg_exc)+len(weg_fio)} WEG · "
        f"{n_regression} GEKIPPT-Regression · "
        f"{n_improvement} GEKIPPT-Verbesserung"
    )


# ── Main program ─────────────────────────────────────────────────────────────

def main() -> None:
    # ── CLI ───────────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="build_dep_map.py — Needful Things · Dependency Map Generator"
    )
    parser.add_argument(
        "--baseline",
        metavar="PATH",
        help="path to dep_map_records.json of an earlier run (for delta comparison)",
        default=None,
    )
    args = parser.parse_args()

    print("=" * 65)
    print("  build_dep_map.py — Needful Things")
    print("=" * 65)
    print()

    # Load config
    cfg = _load_config()

    scan_root     = (SCRIPT_DIR / cfg.SCAN_ROOT).resolve()
    output_base   = (SCRIPT_DIR / cfg.OUTPUT_BASE).resolve()
    exclude_dirs  = getattr(cfg, "EXCLUDE_DIRS",   [])
    exclude_files = getattr(cfg, "EXCLUDE_FILES",  [])
    baseline_mode = getattr(cfg, "BASELINE_MODE",  "auto_last")

    # Determine the baseline path:
    # 1. An explicit --baseline CLI parameter takes precedence
    # 2. BASELINE_MODE = "auto_last" → look for the last snapshot in the output directory
    # 3. BASELINE_MODE = "none"      → no delta
    def _find_last_snapshot(base: Path) -> Path | None:
        candidates = sorted(base.glob("*_Run-*/dep_map_records.json"))
        return candidates[-1] if candidates else None

    effective_baseline: Path | None = None
    if args.baseline:
        effective_baseline = Path(args.baseline)
    elif baseline_mode == "auto_last":
        effective_baseline = _find_last_snapshot(output_base)

    print(f"  Scan root  : {scan_root}")
    print(f"  Output     : {output_base}")
    if effective_baseline:
        print(f"  baseline   : {effective_baseline}")
    else:
        if baseline_mode == "auto_last":
            print(f"  baseline   : (no previous run found — first run)")
        else:
            print(f"  baseline   : (BASELINE_MODE=none — delta disabled)")
    print()

    if not scan_root.is_dir():
        print(f"ERROR: SCAN_ROOT not found: {scan_root}")
        sys.exit(1)

    # Load the baseline
    baseline_snapshot: dict | None = None
    if effective_baseline is not None:
        if not effective_baseline.exists():
            print(f"WARNING: baseline not found: {effective_baseline} — skipping delta")
        else:
            try:
                baseline_snapshot = json.loads(
                    effective_baseline.read_text(encoding="utf-8")
                )
                b_ver = baseline_snapshot.get("version", "?")
                if b_ver != _RECORDS_VERSION:
                    print(f"WARNING: baseline version {b_ver} != {_RECORDS_VERSION} — skipping delta")
                    baseline_snapshot = None
            except Exception as e:
                print(f"WARNING: baseline could not be loaded: {e} — skipping delta")

    # Collect files
    print("── collecting files ──────────────────────────────────────")
    all_files = _collect_files(scan_root, exclude_dirs, exclude_files)
    print(f"  {len(all_files)} Python files found\n")

    if not all_files:
        print("ERROR: No files found — check EXCLUDE_DIRS.")
        sys.exit(1)

    # Analysis
    print("── AST analysis ─────────────────────────────────────────────")
    result = analyse(scan_root, all_files)
    total_internal = sum(len(d["internal"]) for d in result["by_file"].values())
    total_external = sum(len(d["external"]) for d in result["by_file"].values())
    print(f"  Internal imports        : {total_internal}")
    print(f"  External imports        : {total_external}")

    dynamic = analyse_dynamic(scan_root, all_files)
    total_dynamic = sum(len(v) for v in dynamic.values())
    print(f"  Dynamic imports         : {total_dynamic} in {len(dynamic)} files")

    fileio = analyse_fileio(scan_root, all_files)
    total_fileio = sum(len(v) for v in fileio.values())
    print(f"  File I/O operations     : {total_fileio} in {len(fileio)} files")

    callers = analyse_callers(scan_root, all_files, result["importers"])
    total_callers_all  = sum(len(v) for v in callers["all"].values())
    total_callers_top8 = sum(len(v) for v in callers["top8"].values())
    print(f"  Caller-usages total   : {total_callers_all}")
    print(f"  Caller-usages Top-8    : {total_callers_top8}")

    exceptions = analyse_exceptions(scan_root, all_files)
    total_exc      = sum(len(v) for v in exceptions.values())
    total_critical = sum(1 for hits in exceptions.values()
                         for h in hits if h["risk"] == "critical")
    total_silent   = sum(1 for hits in exceptions.values()
                         for h in hits if h["risk"] == "silent")
    print(f"  Exception handlers      : {total_exc} ({total_critical} critical, {total_silent} silent)")
    print()

    # Output directory
    run_dir = _next_run_dir(output_base)
    print(f"── Output ──────────────────────────────────────────────────")
    print(f"  Run directory : {run_dir.name}")

    # CSV
    csv_path = run_dir / "dep_map.csv"
    write_csv(result, csv_path)
    print(f"  dep_map.csv                 written")

    # MD
    md_path = run_dir / "dep_map.md"
    write_md(result, scan_root, run_dir, all_files, md_path)
    print(f"  dep_map.md                  written")

    # Dynamic MD
    dyn_path = run_dir / "dep_map_dynamic.md"
    write_dynamic_md(dynamic, scan_root, run_dir, dyn_path)
    print(f"  dep_map_dynamic.md          written")

    # File I/O MD
    fileio_path = run_dir / "dep_map_fileio.md"
    write_fileio_md(fileio, scan_root, run_dir, fileio_path)
    print(f"  dep_map_fileio.md           written")

    # Callers Top-8 MD
    cal_top_path = run_dir / "dep_map_callers_top8.md"
    write_callers_top8_md(callers, scan_root, run_dir, cal_top_path)
    print(f"  dep_map_callers_top8.md     written")

    # Callers All MD
    cal_all_path = run_dir / "dep_map_callers_all.md"
    write_callers_all_md(callers, scan_root, run_dir, cal_all_path)
    print(f"  dep_map_callers_all.md      written")

    # Exception Handler MD
    exc_path = run_dir / "dep_map_exceptions.md"
    write_exceptions_md(exceptions, scan_root, run_dir, exc_path)
    print(f"  dep_map_exceptions.md       written")

    # Records JSON (always write)
    records      = _build_records(exceptions, fileio)
    rec_path     = run_dir / "dep_map_records.json"
    current_snap = write_records_json(records, run_dir, rec_path)
    print(f"  dep_map_records.json        written")

    # delta (only if baseline is present and compatible)
    print()
    if baseline_snapshot is not None:
        delta_dir  = run_dir / "delta"
        delta_dir.mkdir(exist_ok=True)
        delta      = compare_records(
            baseline_snapshot, current_snap,
            accepted_transitions=getattr(cfg, "ACCEPTED_GEKIPPT", []),
        )
        delta_path = delta_dir / "dep_map_delta.md"
        stdout_line = write_delta_md(delta, baseline_snapshot, current_snap, delta_path)
        print(f"  delta/dep_map_delta.md      written")
        print()
        print("=" * 65)
        print(f"  {stdout_line}")
        print("=" * 65)
    else:
        print("  delta: skipped (no previous run or BASELINE_MODE=none)")
        print()
        print("=" * 65)
        print(f"  Done — {run_dir.name}")
        print("=" * 65)
    print()


if __name__ == "__main__":
    main()

