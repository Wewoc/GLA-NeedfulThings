"""
scope_snapshot.py — Garmin Local Archive / GLA-NeedfulThings
Generates a symbol map (signatures, constants, class attributes) for a
confirmed file scope — preparation before the first build task of a session.

Not a replacement for reading the target file before an anchor. No logic
verification. Complements scan_critical_deps.py (module level) and
build_dep_map.py (structure level) with the missing symbol level.

Flow:
  0. Delete scope_snapshot_config.py if present
  1. Find newest scope_snapshot_config_v*.py -> copy to scope_snapshot_config.py
  2. Load scope_snapshot_config.py
  3. AST extraction per file in SCOPE_FILES:
       - Public/internal functions & methods
         (signature, return annotation if present, first docstring line)
       - Module-level constants (ALL_CAPS name + ast.Constant value)
       - Class attributes (class body + self.x assignments in __init__)
       - Facade detection: imported names without local usage (Call/Name) in
         the module body -> neighbor file is resolved and the real signature
         is loaded (re-export pattern, see garmin_quality.py)
       - Referenced import neighbors: imported names that are actually used
         via Call/Name in the module body -> signature added from the
         neighbor file, without pulling the whole neighbor file into scope
  4. Generate SCOPE_SNAPSHOT.md (compact signature list, fingerprint per file)
  5. Archiving:
       SCOPE_SNAPSHOT.md            -> scope_output/SCOPE_SNAPSHOT_[config_id].md
       scope_snapshot_config.py     -> scope_configs/[original_name]

Usage: python scope_snapshot.py
Config: scope_snapshot_config_v*.py (newest in the same folder)
Output: SCOPE_SNAPSHOT.md -> scope_output/

No cache: pure deterministic AST extraction, no Ollama step
(unlike scan_critical_deps.py — needed there because classification is
expensive).
"""

from pathlib import Path
from datetime import datetime
import ast
import importlib.util
import shutil
import sys

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent.resolve()
OUTPUT_MD   = SCRIPT_DIR / "SCOPE_SNAPSHOT.md"
SNAP_OUT    = SCRIPT_DIR / "scope_output"
SNAP_ARCH   = SCRIPT_DIR / "scope_configs"
CONFIG_FILE = SCRIPT_DIR / "scope_snapshot_config.py"

# ── Load config ───────────────────────────────────────────────────────────────

def find_newest_config() -> Path | None:
    """Finds the newest scope_snapshot_config_v*.py in the script directory (by mtime)."""
    candidates = list(SCRIPT_DIR.glob("scope_snapshot_config_v*.py"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

def prepare_config() -> str | None:
    """
    Deletes scope_snapshot_config.py, copies the newest
    scope_snapshot_config_v*.py there.
    Returns the original name (for archiving), or None on error.
    """
    newest = find_newest_config()
    if not newest:
        print("✗  No scope_snapshot_config_v*.py found.")
        return None

    print(f"  Config found     : {newest.name}")

    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        print(f"  Old scope_snapshot_config.py deleted.")

    shutil.copy2(newest, CONFIG_FILE)
    print(f"  scope_snapshot_config.py ready.\n")
    return newest.name

def load_config() -> object | None:
    """Loads scope_snapshot_config.py as a module."""
    spec   = importlib.util.spec_from_file_location("scope_snapshot_config", CONFIG_FILE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print(f"✗  scope_snapshot_config.py could not be loaded: {e}")
        return None

# ── AST helper functions ─────────────────────────────────────────────────────

def _is_const_name(name: str) -> bool:
    """ALL-CAPS convention. str.isupper() correctly ignores underscores/digits."""
    return name.isupper()

def _first_docstring_line(node) -> str | None:
    doc = ast.get_docstring(node, clean=True)
    if not doc:
        return None
    return doc.strip().splitlines()[0].strip()

def _format_signature(node) -> str:
    """Builds 'def name(args) -> ret' or 'async def ...' from a FunctionDef node."""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    try:
        args_str = ast.unparse(node.args)
    except Exception:
        args_str = "..."
    ret = ""
    if node.returns is not None:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            ret = ""
    return f"{prefix} {node.name}({args_str}){ret}"

def _extract_module_functions(tree: ast.Module) -> list[dict]:
    """Top-level functions (not nested inside classes)."""
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append({
                "signature": _format_signature(node),
                "name":      node.name,
                "doc":       _first_docstring_line(node),
                "internal":  node.name.startswith("_"),
            })
    return out

def _extract_module_constants(tree: ast.Module) -> list[dict]:
    """
    Module-level constants: ALL-CAPS name + ast.Constant value.
    Deliberately conservative (v1): dict/list literals (e.g. QUALITY_RANK) are
    NOT captured — complex expressions are excluded per the concept.
    """
    out = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and _is_const_name(target.id):
                if isinstance(node.value, ast.Constant):
                    try:
                        val = ast.unparse(node.value)
                    except Exception:
                        val = repr(node.value.value)
                    out.append({"name": target.id, "value": val})
    return out

def _extract_classes(tree: ast.Module) -> list[dict]:
    """Classes with class-level attributes, self.x from __init__, and methods."""
    out = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        attrs = []
        methods = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        attrs.append(t.id)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append({
                    "signature": _format_signature(item),
                    "name":      item.name,
                    "doc":       _first_docstring_line(item),
                    "internal":  item.name.startswith("_"),
                })
                if item.name == "__init__":
                    for sub in ast.walk(item):
                        if (isinstance(sub, ast.Assign)
                                and len(sub.targets) == 1
                                and isinstance(sub.targets[0], ast.Attribute)
                                and isinstance(sub.targets[0].value, ast.Name)
                                and sub.targets[0].value.id == "self"):
                            attrs.append(f"self.{sub.targets[0].attr}")
        out.append({"name": node.name, "attrs": sorted(set(attrs)), "methods": methods})
    return out

def _imported_names(tree: ast.Module) -> dict[str, tuple[str, int, str]]:
    """
    {local_name: (module, level, original_name)} for all ImportFrom
    statements at module level. Plain 'import x' statements are ignored
    (no re-export or neighbor case in this project's style).
    """
    result = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                result[local] = (node.module, node.level or 0, alias.name)
    return result

def _used_names_outside_imports(tree: ast.Module) -> set[str]:
    """All ast.Name ids in the tree, excluding the import statements themselves."""
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Name):
            used.add(node.id)
    return used

def _resolve_module_file(importing_file: Path, module: str, level: int,
                          project_root: Path) -> Path | None:
    """
    Resolves 'from quality._io import x' etc. to a file.
    GLA convention: garmin/, context/, maps/, dashboards/ sit directly on
    sys.path -> sub-packages are resolved relative to the importing file's
    folder (level=0), or relative upward for level>0.
    """
    rel_path = Path(*module.split("."))
    candidates = []
    if level == 0:
        candidates.append(importing_file.parent / rel_path)
        candidates.append(project_root / rel_path)
    else:
        base = importing_file.parent
        for _ in range(level - 1):
            base = base.parent
        candidates.append(base / rel_path)

    for cand in candidates:
        py_file = cand.with_suffix(".py")
        if py_file.is_file():
            return py_file
        init_file = cand / "__init__.py"
        if init_file.is_file():
            return init_file
    return None

def _find_symbol_in_file(target_file: Path, symbol_name: str) -> dict | None:
    """Searches for a top-level function or constant with the given name."""
    try:
        tree = ast.parse(target_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol_name:
            return {
                "kind":      "function",
                "signature": _format_signature(node),
                "doc":       _first_docstring_line(node),
            }
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == symbol_name:
                    try:
                        val = ast.unparse(node.value) if isinstance(node.value, ast.Constant) else "..."
                    except Exception:
                        val = "..."
                    return {"kind": "constant", "value": val}
    return None

def extract_import_relations(tree: ast.Module, file_path: Path,
                              project_root: Path) -> dict:
    """
    Splits imported names into:
      - facade_exports: imported, never referenced locally (re-export pattern)
      - referenced_neighbors: imported AND actually referenced locally via
        Name/Call

    Heuristic for 'facade': at least 3 unreferenced ImportFrom names AND
    more than 60% of all ImportFrom names are unreferenced. Otherwise
    unreferenced imports are treated as ordinary (possibly dead) imports and
    ignored — no scope bloat from individual cases.
    """
    imported = _imported_names(tree)
    if not imported:
        return {"facade_exports": [], "referenced_neighbors": [], "unresolved": []}

    used = _used_names_outside_imports(tree)
    unreferenced = [n for n in imported if n not in used]
    referenced   = [n for n in imported if n in used]

    is_facade = (len(unreferenced) >= 3
                 and len(unreferenced) / len(imported) > 0.6)

    facade_exports, referenced_neighbors, unresolved = [], [], []

    names_to_resolve = unreferenced if is_facade else []
    names_to_resolve += referenced

    for local_name in names_to_resolve:
        module, level, original_name = imported[local_name]
        target_file = _resolve_module_file(file_path, module, level, project_root)
        if target_file is None:
            unresolved.append(f"{module}.{original_name}  (from {file_path.name})")
            continue
        symbol = _find_symbol_in_file(target_file, original_name)
        if symbol is None:
            unresolved.append(f"{module}.{original_name}  (symbol not found in {target_file.name})")
            continue
        entry = {"local_name": local_name, "source_file": target_file.name, **symbol}
        if local_name in unreferenced:
            facade_exports.append(entry)
        else:
            referenced_neighbors.append(entry)

    return {
        "facade_exports":       facade_exports,
        "referenced_neighbors": referenced_neighbors,
        "unresolved":           unresolved,
        "is_facade":            is_facade,
    }

# ── File processing ──────────────────────────────────────────────────────────

def process_file(rel_path: str, project_root: Path) -> dict | None:
    """Extracts all symbols of a single file in the scope."""
    abs_path = (project_root / rel_path).resolve()
    if not abs_path.is_file():
        print(f"  ✗  not found: {rel_path}")
        return None

    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
        tree   = ast.parse(source, filename=str(abs_path))
    except SyntaxError as e:
        print(f"  ✗  syntax error in {rel_path}: {e}")
        return None

    mtime = datetime.fromtimestamp(abs_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

    return {
        "rel_path":  rel_path,
        "mtime":     mtime,
        "functions": _extract_module_functions(tree),
        "constants": _extract_module_constants(tree),
        "classes":   _extract_classes(tree),
        "imports":   extract_import_relations(tree, abs_path, project_root),
    }

# ── Markdown generation ───────────────────────────────────────────────────────

def _fmt_func_line(f: dict) -> list[str]:
    lines = [f["signature"]]
    if f.get("doc"):
        lines.append(f'    """{f["doc"]}"""')
    return lines

def build_md(config, results: list[dict], project_root: Path) -> str:
    now      = datetime.now().strftime("%Y-%m-%d %H:%M")
    cfg_id   = getattr(config, "CONFIG_ID",    "unknown")
    ses_note = getattr(config, "SESSION_NOTE", "")

    lines = []
    lines.append("# SCOPE_SNAPSHOT — Garmin Local Archive")
    lines.append("")
    lines.append(f"Generated : {now}")
    lines.append(f"Config    : {cfg_id}")
    if ses_note:
        lines.append(f"Session   : {ses_note}")
    lines.append(f"Project   : {project_root}")
    lines.append("")
    lines.append("Symbol map of the confirmed scope — not a replacement for")
    lines.append("reading the target file before an anchor. No logic verification.")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary
    total_public   = sum(len([f for f in r["functions"] if not f["internal"]]) for r in results)
    total_internal = sum(len([f for f in r["functions"] if f["internal"]])     for r in results)
    total_const    = sum(len(r["constants"]) for r in results)
    total_classes  = sum(len(r["classes"])   for r in results)
    total_unresolved = sum(len(r["imports"]["unresolved"]) for r in results)

    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Files | Public | Internal | Constants | Classes | Unresolved |")
    lines.append(f"|---|---|---|---|---|---|")
    lines.append(f"| {len(results)} | {total_public} | {total_internal} | {total_const} | {total_classes} | {total_unresolved} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    all_unresolved = []

    for r in results:
        lines.append(f"## {r['rel_path']} · mtime: {r['mtime']}")
        lines.append("")

        public_funcs   = [f for f in r["functions"] if not f["internal"]]
        internal_funcs = [f for f in r["functions"] if f["internal"]]

        if public_funcs:
            lines.append("### Public")
            for f in public_funcs:
                lines.extend(_fmt_func_line(f))
            lines.append("")

        if internal_funcs:
            lines.append("### Internal")
            for f in internal_funcs:
                lines.extend(_fmt_func_line(f))
            lines.append("")

        if r["classes"]:
            lines.append("### Classes")
            for c in r["classes"]:
                lines.append(f"class {c['name']}:")
                for a in c["attrs"]:
                    lines.append(f"    {a}")
                for m in c["methods"]:
                    lines.append(f"    {m['signature']}")
                lines.append("")

        if r["constants"]:
            lines.append("### Constants")
            for c in r["constants"]:
                lines.append(f"{c['name']} = {c['value']}")
            lines.append("")

        imp = r["imports"]
        if imp["facade_exports"]:
            lines.append(f"### Re-exports (facade detected — {r['rel_path']})")
            for e in imp["facade_exports"]:
                if e["kind"] == "function":
                    lines.append(f"{e['signature']}   [from {e['source_file']}]")
                    if e.get("doc"):
                        lines.append(f'    """{e["doc"]}"""')
                else:
                    lines.append(f"{e['local_name']} = {e.get('value', '...')}   [from {e['source_file']}]")
            lines.append("")

        if imp["referenced_neighbors"]:
            lines.append("### Referenced import neighbors")
            for e in imp["referenced_neighbors"]:
                if e["kind"] == "function":
                    lines.append(f"{e['signature']}   [from {e['source_file']}]")
                else:
                    lines.append(f"{e['local_name']} = {e.get('value', '...')}   [from {e['source_file']}]")
            lines.append("")

        all_unresolved.extend(imp["unresolved"])
        lines.append("---")
        lines.append("")

    if all_unresolved:
        lines.append("## Unresolved references")
        lines.append("")
        lines.append("Check manually — the module path convention doesn't apply cleanly here:")
        lines.append("")
        for u in all_unresolved:
            lines.append(f"- {u}")
        lines.append("")

    return "\n".join(lines) + "\n"

# ── Archiving ─────────────────────────────────────────────────────────────────

def archive(config_id: str, original_config_name: str) -> None:
    """
    Moves SCOPE_SNAPSHOT.md        -> scope_output/SCOPE_SNAPSHOT_[config_id].md
    Moves scope_snapshot_config.py -> scope_configs/[original_config_name]
    """
    SNAP_OUT.mkdir(exist_ok=True)
    SNAP_ARCH.mkdir(exist_ok=True)

    dest_md = SNAP_OUT / f"SCOPE_SNAPSHOT_{config_id}.md"
    if OUTPUT_MD.exists():
        shutil.move(str(OUTPUT_MD), str(dest_md))
        print(f"  ✓  {OUTPUT_MD.name} → scope_output/{dest_md.name}")

    dest_cfg = SNAP_ARCH / original_config_name
    if CONFIG_FILE.exists():
        shutil.move(str(CONFIG_FILE), str(dest_cfg))
        print(f"  ✓  scope_snapshot_config.py → scope_configs/{original_config_name}")

# ── Main program ─────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  scope_snapshot.py — Garmin Local Archive")
    print("=" * 65)
    print()

    print("── Config ──────────────────────────────────────────────────")
    original_name = prepare_config()
    if not original_name:
        sys.exit(1)

    cfg = load_config()
    if cfg is None:
        sys.exit(1)

    config_id    = getattr(cfg, "CONFIG_ID",    "unknown")
    session_note = getattr(cfg, "SESSION_NOTE", "")
    proj_rel     = getattr(cfg, "PROJECT_ROOT", "../garmin_collector-1_work")
    scope_files  = getattr(cfg, "SCOPE_FILES",  [])

    project_root = (SCRIPT_DIR / proj_rel).resolve()

    print(f"  Config-ID  : {config_id}")
    if session_note:
        print(f"  Session    : {session_note}")
    print(f"  Project    : {project_root}")
    print(f"  Scope      : {len(scope_files)} file(s)")
    print()

    if not project_root.is_dir():
        print(f"✗  Project root not found: {project_root}")
        sys.exit(1)

    if not scope_files:
        print("✗  No SCOPE_FILES defined in scope_snapshot_config.py.")
        sys.exit(1)

    print("── AST extraction ─────────────────────────────────────────")
    results = []
    for rel_path in scope_files:
        r = process_file(rel_path, project_root)
        if r:
            n_pub = len([f for f in r["functions"] if not f["internal"]])
            n_int = len([f for f in r["functions"] if f["internal"]])
            print(f"  ✓  {rel_path}: {n_pub} public, {n_int} internal, "
                  f"{len(r['constants'])} const, {len(r['classes'])} class(es)")
            results.append(r)
    print()

    if not results:
        print("✗  No file could be processed.")
        sys.exit(1)

    print("── Output ──────────────────────────────────────────────────")
    md_content = build_md(cfg, results, project_root)
    OUTPUT_MD.write_text(md_content, encoding="utf-8")
    print(f"  ✓  {OUTPUT_MD} written\n")

    print("── Archiving ───────────────────────────────────────────────")
    archive(config_id, original_name)

    print()
    print("=" * 65)
    print(f"  Done — SCOPE_SNAPSHOT_{config_id}.md in scope_output/")
    print("=" * 65)
    print()


if __name__ == "__main__":
    main()
