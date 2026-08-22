"""
build_dep_map.py
needfull things — Dependency Map Generator

Builds a complete import map of the project via AST analysis.

Process:
  1. Collect all .py files under SCAN_ROOT (EXCLUDE_DIRS / EXCLUDE_FILES)
  2. Per file: extract all imports via AST
  3. Classify as internalal / externalal (internalal = exists as .py in the project)
  4. Build inverse map (who imports this module?)
  5. Output: dep_map.md + dep_map.csv + dep_map_dynamic.md +
             dep_map_fileio.md + dep_map_callers_top8.md +
             dep_map_callers_all.md  in output/YYYY-MM-DD_Run-NN/

call:    run_dep_map.bat  (or: python build_dep_map.py)
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
        module  — importiertes module (obfirst Ebene, z.B. "garmin_api")
        full    — voller modulepfad (z.B. "garmin.garmin_api")
        symbols — Liste importierter Symbole (bei "from X import a, b")
        kind    — "import" | "from"
        lineno  — linennummer
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

# ── Dynamische Import-Erkennung ───────────────────────────────────────────────

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
        pattern  — erkanntes pattern (z.B. "import_module")
        arg      — first argument as string if literal, else None
        lineno   — linennummer
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

        # Direkt: __import__("x")
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


# ── Intern / Extern classify ────────────────────────────────────────────

def _build_module_index(all_files: list[Path], scan_root: Path) -> dict[str, Path]:
    """
    Baut einen Index: modulename (ohne .py) → absoluteer path.
    Considers all levels (e.g. "my_api" from pkg/my_api.py,
    as well as "my_api" directly if in the root).
    """
    index = {}
    for f in all_files:
        # Einfacher filename ohne Extension
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

def _is_internalal(module_name: str, full_name: str,
                 module_index: dict[str, Path]) -> bool:
    return (module_name in module_index) or (full_name in module_index)

def _resolve_internalal_path(module_name: str, full_name: str,
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

# ── Haupt-Analyse ─────────────────────────────────────────────────────────────

def analyse(scan_root: Path, all_files: list[Path]) -> dict:
    """
    Gibt dict back:
        by_file    — {rel_path: {"internalal": [...], "externalal": [...]}}
        importers  — {rel_path: [rel_path, ...]}  (inverse Map)
    """
    module_index = _build_module_index(all_files, scan_root)

    by_file  = {}
    importers = defaultdict(set)   # wer importiert dieses module

    for py_file in all_files:
        try:
            rel = str(py_file.relative_to(scan_root)).replace("\\", "/")
        except ValueError:
            rel = py_file.name

        raw_imports = _extract_imports(py_file)
        internalal    = []
        externalal    = []

        for imp in raw_imports:
            if _is_internalal(imp["module"], imp["full"], module_index):
                resolved = _resolve_internalal_path(
                    imp["module"], imp["full"], module_index, scan_root)
                entry = {
                    "module":   imp["full"],
                    "symbols":  imp["symbols"],
                    "kind":     imp["kind"],
                    "lineno":   imp["lineno"],
                    "resolved": resolved or imp["full"],
                }
                internalal.append(entry)
                if resolved:
                    importers[resolved].add(rel)
            else:
                externalal.append({
                    "module":  imp["full"],
                    "symbols": imp["symbols"],
                    "kind":    imp["kind"],
                    "lineno":  imp["lineno"],
                })

        by_file[rel] = {
            "internalal": internalal,
            "externalal": externalal,
        }

    # importers zu sortierten Listen
    importers_clean = {k: sorted(v) for k, v in importers.items()}

    return {
        "by_file":   by_file,
        "importers": importers_clean,
    }

# ── CSV-Output ────────────────────────────────────────────────────────────────

def write_csv(result: dict, out_path: Path) -> None:
    """
    columnn: file | type | imported_module | symbols | lineno | resolved_path
    """
    rows = []
    for rel, data in sorted(result["by_file"].items()):
        for imp in data["internalal"]:
            rows.append({
                "file":          rel,
                "type":          "internal",
                "imported_module": imp["module"],
                "symbols":       ", ".join(imp["symbols"]) if imp["symbols"] else "",
                "lineno":        imp["lineno"],
                "resolved_path": imp["resolved"],
            })
        for imp in data["externalal"]:
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

    # ── Summary-Daten ────────────────────────────────────────────────────────
    total_modules   = len(by_file)
    leaf_nodes      = []   # no internal imports
    entry_points    = []   # no importers (nobody imports them)
    high_coupling   = []   # 5+ Importeure

    for rel, data in sorted(by_file.items()):
        n_internalal  = len(data["internalal"])
        n_importers = len(importers.get(rel, []))

        if n_internalal == 0:
            leaf_nodes.append(rel)
        if n_importers == 0:
            entry_points.append(rel)
        if n_importers >= 5:
            high_coupling.append((rel, n_importers))

    high_coupling.sort(key=lambda x: -x[1])

    lines = []
    now   = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    lines += [
        "# Dependency Map — needfull things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Kennzahl | value |",
        f"|---|---|",
        f"| modules total | {total_modules} |",
        f"| Leaf nodes (no internal imports) | {len(leaf_nodes)} |",
        f"| Entry points (no importers) | {len(entry_points)} |",
        f"| Hoch gekoppelt (5+ Importeure) | {len(high_coupling)} |",
        "",
    ]

    # Leaf-Nodes
    lines += [
        "### Leaf-Nodes",
        "_Diese modules importieren nichts Internes — moegliche Utility-/ Config-modules._",
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

    # Hoch gekoppelte modules
    if high_coupling:
        lines += [
            "### Hoch gekoppelte modules (5+ Importeure)",
            "_Aenderungsrisiko: viele modules haengen davon ab._",
            "",
            "| module | Importeure |",
            "|---|---|",
        ]
        for rel, count in high_coupling:
            lines.append(f"| `{rel}` | {count} |")
        lines.append("")

    lines += ["---", ""]

    # ── table 1: file → importiert ────────────────────────────────────────
    lines += [
        "## table 1 — file → importiert",
        "",
        "| file | Typ | module / Symbol | line | Aufgeloester path |",
        "|---|---|---|---|---|",
    ]

    for rel, data in sorted(by_file.items()):
        all_imports = (
            [(i, "internal") for i in data["internalal"]] +
            [(i, "external") for i in data["externalal"]]
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

    # ── table 2: Wer importiert diese file ────────────────────────────────
    lines += [
        "## table 2 — Wer importiert dieses module (invers)",
        "",
        "| module | Imported by |",
        "|---|---|",
    ]

    for rel in sorted(by_file.keys()):
        imp_by = importers.get(rel, [])
        if not imp_by:
            lines.append(f"| `{rel}` | _(niemand)_ |")
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
    Generates dep_map_dynamic.md — separate file fuer dynamische Imports.
    Only files with matches are listed.
    """
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# Dynamic Import Map — needfull things",
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
        "Erkannte pattern:",
        "- `import_module(...)` — importlib.import_module",
        "- `spec_from_file_location(...)` — importlib.util.spec_from_file_location",
        "- `find_spec(...)` — importlib.util.find_spec",
        "- `__import__(...)` — direkter built-in Import",
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
            "Keine dynamischen Imports found.",
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
        f"| Kennzahl | value |",
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
        "| file | line | pattern | module-Argument |",
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
    "glob", "rglob", "iterdir",                  # directory-Scan
    "exists", "is_file", "is_dir", "stat",       # Existenz-Check
}

def _extract_fileio(py_file: Path) -> list[dict]:
    """
    Searches for file I/O operations via AST.
    Returns a list of dicts:
        op       — Funktionsname
        mode     — "write" | "read" | "read/write"
        lineno   — linennummer
        arg      — first argument as string if literal, else None
    """
    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        tree   = ast.parse(source, filename=str(py_file))
    except Exception:
        return []

    findings = []
    seen     = set()   # (op, lineno) — Deduplizierung

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

        # Modus bestimmen
        if is_write and is_read:
            mode = "read/write"
        elif is_write:
            mode = "write"
        else:
            mode = "read"

        # open() — read mode from second argument if present
        if op == "open":
            mode = "read/write"   # Default
            # Zweites Argument (mode string) auswerten
            mode_arg = None
            if len(node.args) >= 2:
                a = node.args[1]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    mode_arg = a.value
            # Keyword-Argument "mode=..."
            if mode_arg is None:
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode_arg = kw.value.value
            if mode_arg:
                if "w" in mode_arg or "a" in mode_arg or "x" in mode_arg:
                    mode = "write"
                elif "r" in mode_arg:
                    mode = "read"

        # Erstes Argument als path-note
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

        # Funktionskontext nachtraeglich ergaenzen
        try:
            source  = py_file.read_text(encoding="utf-8", errors="replace")
            tree    = ast.parse(source, filename=str(py_file))
            parents = _build_parent_map(tree)
            # Lineno → finding index fuer schnellen Lookup
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

        # Fallback fuer Findings ohne Kontext
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
        "# File I/O Map — needfull things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "## note",
        "",
        "Erfasst: `open()`, `write_text()`, `read_text()`, `json.dump/load`,",
        "`shutil.move/copy`, `Path.rename/unlink/mkdir`, `glob/rglob`.",
        "Relevant fuer Sole-Write-Authority-Verifikation: Schreib-Operationen",
        "zeigen welches module actually auf Disk schreibt.",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Kennzahl | value |",
        f"|---|---|",
        f"| files with file I/O | {total_files} |",
        f"| Schreib-Operationen total | {total_write} |",
        f"| Lese-Operationen total | {total_read} |",
        "",
        "---",
        "",
        "## Details",
        "",
        "| file | line | Modus | Operation | path-Argument |",
        "|---|---|---|---|---|",
    ]

    for rel, hits in sorted(fileio.items()):
        first = True
        for hit in sorted(hits, key=lambda h: h["lineno"]):
            file_col = f"`{rel}`" if first else ""
            first    = False
            arg_col  = f"`{hit['arg']}`" if hit["arg"] else "_(variabel)_"
            lines.append(
                f"| {file_col} | {hit['lineno']} | {hit['mode']} "
                f"| `{hit['op']}` | {arg_col} |"
            )

    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ── Caller-Analyse ────────────────────────────────────────────────────────────

def analyse_callers(scan_root: Path, all_files: list[Path],
                    importers: dict[str, list[str]],
                    top_threshold: int = 5) -> dict:
    """
    Analysiert Funktionsaufrufe per AST — zwei Scan-paths:

    path 1 — Attribut-usages:  modul.funktion()
        Detects usages when the module is referenced as an object.

    path 2 — Direct usages after from-import:
        from my_config import get_path
        get_path()   ← now detected

        Method: collect all from-X-import-func statements per file
        (func_name → source_module), then check all ast.Name calls
        whether the name appears in that table.

        Bekannte Einschraenkung (dokumentiert in build_dep_map_LIMITATIONS.md):
        Shadowing is not detected. If an imported name is locally
        overridden, the call still counts as a match.
        Rarely seen in typical code — false positives possible.

    Gibt dict back:
        all     — {callee_rel: [{caller_file, func_name, lineno, via}, ...]}
        top8    — like all, but only modules with >= top_threshold importers
    """
    # module-Index build: stem → rel_path
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

    # Top-modules bestimmen (>= threshold Importeure)
    top_modules = {
        rel for rel, imp_list in importers.items()
        if len(imp_list) >= top_threshold
    }

    # Caller-Dict initialisieren
    all_callers: dict[str, list[dict]] = defaultdict(list)

    # Dunder-Methoden ausschliessen
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

        # ── path 2 Vorbereitung: from-Import-table pro file ──────────────
        # func_name → callee_rel  (nur internale modules)
        from_import_map: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module is None:
                continue
            top    = node.module.split(".")[0]
            full   = node.module
            # Internes module?
            callee = module_index.get(full) or module_index.get(top)
            if callee is None or callee == caller_rel:
                continue
            for alias in node.names:
                # Alias beruecksichtigen: from X import func as f → "f" tracken
                local_name = alias.asname if alias.asname else alias.name
                from_import_map[local_name] = (callee, alias.name)

        # ── Both paths: all ast.Call nodes ──────────────────────────────────
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            func = node.func

            # ── path 1: Attribut-call modul.funktion() ────────────────────
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

    # Top-8 herausfiltern
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
        f"# {title} — needfull things",
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
        f"| Kennzahl | value |",
        f"|---|---|",
        f"| Aufgerufene modules | {total_callees} |",
        f"| usages total | {total_calls} |",
        f"| Unique Caller-files | {total_callers} |",
        "",
    ]

    # Kompakte Uebersicht
    lines += [
        "## Uebersicht",
        "",
        "| module (callee) | usages | Unique Caller |",
        "|---|---|---|",
    ]
    for rel in sorted(callers.keys(),
                      key=lambda r: -len(callers[r])):
        hits    = callers[rel]
        n_calls = len(hits)
        n_caller = len({h["caller_file"] for h in hits})
        lines.append(f"| `{rel}` | {n_calls} | {n_caller} |")

    lines += ["", "---", ""]

    # Detail-Sektionen
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
        title="Caller Map — Top-modules (5+ Importeure)",
        subtitle="Only modules with 5 or more importers. "
                 "Shows which functions of highly-coupled modules are actually called.\n",
    )


def write_callers_all_md(callers: dict, scan_root: Path,
                          run_dir: Path, out_path: Path) -> None:
    _write_callers_md(
        callers["all"], scan_root, run_dir, out_path,
        title="Caller Map — Totalprojekt",
        subtitle="Alle Attribut-usages zwischen internal modulesn. "
                 "Full picture of call connections in the project.\n",
    )


# ── AST-Kontext-Helfer ────────────────────────────────────────────────────────

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


# ── Exception-Handler-Analyse ─────────────────────────────────────────────────

# Risiko-Classification:
#   critical — Handler verschluckt error komplett (pass, return None/False/"")
#   silent   — handler only logs, no reraising, no raise
#   broad    — Exception-Typ zu weit (Exception, BaseException, bare except)
#   ok       — specific type + reraising or controlled raise

_BROAD_TYPES = {"Exception", "BaseException"}

def _classify_handler(handler: ast.ExceptHandler) -> dict:
    """
    Klassifiziert einen einzelnen except-Block.
    Gibt dict back:
        exc_type  — type as string or "bare" (no type specified)
        risk      — "critical" | "silent" | "broad" | "ok"
        body_desc — kurze Beschreibung was im Body passiert
        lineno    — line number of the except statement
    """
    # Exception-Typ bestimmen
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

    # Body-Analyse
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

    # Body-Beschreibung
    parts = []
    if has_pass:        parts.append("pass")
    if silent_returns:  parts.append("return None/False/empty")
    if has_log:         parts.append("log")
    if has_reraise:     parts.append("reraise")
    if has_raise:       parts.append("raise")
    if not parts:       parts.append("andere Behandlung")
    body_desc = " + ".join(parts)

    # Risiko bestimmen
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

    # Total-Statistik
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
        "# Exception Handler Map — needfull things",
        "",
        f"Generated : {now}",
        f"Scan root : `{scan_root}`",
        f"Run dir   : `{run_dir.name}`",
        "",
        "## note",
        "",
        "Captures all `except` blocks via AST. Risk classification:",
        "",
        "| Risiko | Bedeutung |",
        "|---|---|",
        "| `critical` | Handler silently swallows the error (`pass`, `return None/False`) — no log, no reraise |",
        "| `silent` | error is logged but not propagated — caller receives no signal |",
        "| `broad` | Zu weiter Exception-Typ (`Exception`, `BaseException`, bare `except`) ohne Reraise |",
        "| `ok` | Specific type or controlled reraise / raise |",
        "",
        "**Primary lens for phase 2:** `critical` and `silent` are candidates for",
        "silent failure — the caller receives no signal that something went wrong.",
        "Relevant fuer ein Archivierungstool wo unbemerkte error Datenverlust bedeuten.",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"| Risiko | count |",
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
        "| file | line | Exception-Typ | Risiko | Body |",
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



# ── Records-snapshot (Serialisierung) ────────────────────────────────────────

_RECORDS_VERSION = 1
_RISK_RANK = {"ok": 0, "broad": 1, "silent": 2, "critical": 3}


def _build_records(exceptions: dict[str, list[dict]],
                   fileio:     dict[str, list[dict]]) -> list[dict]:
    """
    Builds the deterministically sorted records snapshot.
    Schluessel fuer Exception: (kind, module, function, exception_type, risk_class)
    Schluessel fuer FileIO:    (kind, module, function, operation)
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

    # Deterministisch sortieren — linennummer NICHT im Sort-Key
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


# ── delta-Vergleich ───────────────────────────────────────────────────────────

def _exc_key_full(r: dict) -> tuple:
    """Voller Schluessel inkl. risk_class — fuer NEU/WEG."""
    return (r["module"], r["function"], r["exception_type"], r["risk_class"])


def _exc_key_reduced(r: dict) -> tuple:
    """Reduzierter Schluessel ohne risk_class — fuer GEKIPPT-Erkennung."""
    return (r["module"], r["function"], r["exception_type"])


def _fio_key(r: dict) -> tuple:
    return (r["module"], r["function"], r["operation"], r["detail"])


def compare_records(baseline: dict, current: dict) -> dict:
    """
    Semantischer Vergleich baseline vs. current.
    Gibt dict back:
        neu_exc      — list[dict]
        weg_exc      — list[dict]
        gekippt_exc  — list[dict]  {baseline_rec, current_rec, direction}
        neu_fio      — list[dict]
        weg_fio      — list[dict]
    """
    b_recs = baseline.get("records", [])
    c_recs = current.get("records",  [])

    b_exc = [r for r in b_recs if r["kind"] == "exception"]
    c_exc = [r for r in c_recs if r["kind"] == "exception"]
    b_fio = [r for r in b_recs if r["kind"] == "fileio"]
    c_fio = [r for r in c_recs if r["kind"] == "fileio"]

    # ── Exception-delta ───────────────────────────────────────────────────────
    b_exc_full = {_exc_key_full(r): r for r in b_exc}
    c_exc_full = {_exc_key_full(r): r for r in c_exc}

    # Kandidaten fuer GEKIPPT: gleicher reduzierter Schluessel, andere risk_class
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
        # Einfachster Fall: je genau einer auf beiden Seiten, risk_class verschieden
        if len(b_list) == 1 and len(c_list) == 1:
            br, cr = b_list[0], c_list[0]
            if br["risk_class"] != cr["risk_class"]:
                b_rank = _RISK_RANK.get(br["risk_class"], 0)
                c_rank = _RISK_RANK.get(cr["risk_class"], 0)
                direction = "regression" if c_rank > b_rank else "improvement"
                gekippt_exc.append({
                    "baseline": br,
                    "current":  cr,
                    "direction": direction,
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


# ── delta-Render ──────────────────────────────────────────────────────────────

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

    n_regression   = sum(1 for g in gek_exc if g["direction"] == "regression")
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
        "| Kategorie | exceptions | fileio |",
        "|---|---|---|",
        f"| NEU | {len(neu_exc)} | {len(neu_fio)} |",
        f"| WEG | {len(weg_exc)} | {len(weg_fio)} |",
        f"| GEKIPPT-Regression | {n_regression} | — |",
        f"| GEKIPPT-Verbesserung | {n_improvement} | — |",
        "",
    ]

    # ── GEKIPPT Regression (zuerst — Audit-Trigger) ───────────────────────────
    regressions = [g for g in gek_exc if g["direction"] == "regression"]
    if regressions:
        lines += [
            "## ⚠ GEKIPPT — Regression (zuerst auditieren)",
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

    # ── NEU ───────────────────────────────────────────────────────────────────
    lines += ["## NEU", ""]
    if neu_exc or neu_fio:
        lines += [
            "| Kind | module | Funktion | Typ / Operation | Risk |",
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
            "| Kind | module | Funktion | Typ / Operation | Risk |",
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

    # ── Fussnote ──────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "*fileio-note: `write-replace` may be `str.replace()` (L-1 limitation)"
        " — gegen Code verifizieren.*",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # stdout-Zusammenfassung
    return (
        f"DELTA vs {b_run} ({b_ts}): "
        f"{len(neu_exc)+len(neu_fio)} NEU · "
        f"{len(weg_exc)+len(weg_fio)} WEG · "
        f"{n_regression} GEKIPPT-Regression · "
        f"{n_improvement} GEKIPPT-Verbesserung"
    )


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main() -> None:
    # ── CLI ───────────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="build_dep_map.py — needfull things · Dependency Map Generator"
    )
    parser.add_argument(
        "--baseline",
        metavar="PATH",
        help="path zu dep_map_records.json eines frueheren Runs (fuer delta-Vergleich)",
        default=None,
    )
    args = parser.parse_args()

    print("=" * 65)
    print("  build_dep_map.py — needfull things")
    print("=" * 65)
    print()

    # Config laden
    cfg = _load_config()

    scan_root     = (SCRIPT_DIR / cfg.SCAN_ROOT).resolve()
    output_base   = (SCRIPT_DIR / cfg.OUTPUT_BASE).resolve()
    exclude_dirs  = getattr(cfg, "EXCLUDE_DIRS",   [])
    exclude_files = getattr(cfg, "EXCLUDE_FILES",  [])
    baseline_mode = getattr(cfg, "BASELINE_MODE",  "auto_last")

    # baseline-path bestimmen:
    # 1. Expliziter --baseline CLI-Parameter hat Vorrang
    # 2. BASELINE_MODE = "auto_last" → last snapshot im output-directory suchen
    # 3. BASELINE_MODE = "none"      → no delta
    def _find_last_snapshot(base: Path) -> Path | None:
        candidates = sorted(base.glob("*_Run-*/dep_map_records.json"))
        return candidates[-1] if candidates else None

    effective_baseline: Path | None = None
    if args.baseline:
        effective_baseline = Path(args.baseline)
    elif baseline_mode == "auto_last":
        effective_baseline = _find_last_snapshot(output_base)

    print(f"  Scan-Root  : {scan_root}")
    print(f"  Output     : {output_base}")
    if effective_baseline:
        print(f"  baseline   : {effective_baseline}")
    else:
        if baseline_mode == "auto_last":
            print(f"  baseline   : (no previous run found — first run)")
        else:
            print(f"  baseline   : (BASELINE_MODE=none — delta deaktiviert)")
    print()

    if not scan_root.is_dir():
        print(f"ERROR: SCAN_ROOT not found: {scan_root}")
        sys.exit(1)

    # baseline laden
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

    # files collecting
    print("── files collecting ──────────────────────────────────────")
    all_files = _collect_files(scan_root, exclude_dirs, exclude_files)
    print(f"  {len(all_files)} Python-files found\n")

    if not all_files:
        print("FEHLER: Keine files found — EXCLUDE_DIRS check.")
        sys.exit(1)

    # Analyse
    print("── AST-Analyse ─────────────────────────────────────────────")
    result = analyse(scan_root, all_files)
    total_internalal = sum(len(d["internalal"]) for d in result["by_file"].values())
    total_externalal = sum(len(d["externalal"]) for d in result["by_file"].values())
    print(f"  Interne Imports         : {total_internalal}")
    print(f"  Externe Imports         : {total_externalal}")

    dynamic = analyse_dynamic(scan_root, all_files)
    total_dynamic = sum(len(v) for v in dynamic.values())
    print(f"  Dynamische Imports      : {total_dynamic} in {len(dynamic)} files")

    fileio = analyse_fileio(scan_root, all_files)
    total_fileio = sum(len(v) for v in fileio.values())
    print(f"  File I/O Operationen    : {total_fileio} in {len(fileio)} files")

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
    print(f"  Exception-Handler       : {total_exc} ({total_critical} critical, {total_silent} silent)")
    print()

    # Output-directory
    run_dir = _next_run_dir(output_base)
    print(f"── Output ──────────────────────────────────────────────────")
    print(f"  Run-directory : {run_dir.name}")

    # CSV
    csv_path = run_dir / "dep_map.csv"
    write_csv(result, csv_path)
    print(f"  dep_map.csv                 geschrieben")

    # MD
    md_path = run_dir / "dep_map.md"
    write_md(result, scan_root, run_dir, all_files, md_path)
    print(f"  dep_map.md                  geschrieben")

    # Dynamic MD
    dyn_path = run_dir / "dep_map_dynamic.md"
    write_dynamic_md(dynamic, scan_root, run_dir, dyn_path)
    print(f"  dep_map_dynamic.md          geschrieben")

    # File I/O MD
    fileio_path = run_dir / "dep_map_fileio.md"
    write_fileio_md(fileio, scan_root, run_dir, fileio_path)
    print(f"  dep_map_fileio.md           geschrieben")

    # Callers Top-8 MD
    cal_top_path = run_dir / "dep_map_callers_top8.md"
    write_callers_top8_md(callers, scan_root, run_dir, cal_top_path)
    print(f"  dep_map_callers_top8.md     geschrieben")

    # Callers All MD
    cal_all_path = run_dir / "dep_map_callers_all.md"
    write_callers_all_md(callers, scan_root, run_dir, cal_all_path)
    print(f"  dep_map_callers_all.md      geschrieben")

    # Exception Handler MD
    exc_path = run_dir / "dep_map_exceptions.md"
    write_exceptions_md(exceptions, scan_root, run_dir, exc_path)
    print(f"  dep_map_exceptions.md       geschrieben")

    # Records JSON (immer schreiben)
    records      = _build_records(exceptions, fileio)
    rec_path     = run_dir / "dep_map_records.json"
    current_snap = write_records_json(records, run_dir, rec_path)
    print(f"  dep_map_records.json        geschrieben")

    # delta (only if baseline is present and compatible)
    print()
    if baseline_snapshot is not None:
        delta_dir  = run_dir / "delta"
        delta_dir.mkdir(exist_ok=True)
        delta      = compare_records(baseline_snapshot, current_snap)
        delta_path = delta_dir / "dep_map_delta.md"
        stdout_line = write_delta_md(delta, baseline_snapshot, current_snap, delta_path)
        print(f"  delta/dep_map_delta.md      geschrieben")
        print()
        print("=" * 65)
        print(f"  {stdout_line}")
        print("=" * 65)
    else:
        print("  delta: skipped (no previous run or BASELINE_MODE=none)")
        print()
        print("=" * 65)
        print(f"  Fertig — {run_dir.name}")
        print("=" * 65)
    print()


if __name__ == "__main__":
    main()

