"""
list_complexity.py — code_metrics
Two independent AST evaluations per file:

  1. Nesting depth — maximum depth of if/for/while/try/with nested
     inside each other, per function, aggregated per file (max + average).
     Reliable within a single function — no call-graph, no cross-module
     resolution (see limitations below).

  2. Interfaces per file — inputs (what the file imports) and outputs
     (module-level def/class that other files might import — split into
     public/private by underscore convention). Purely syntactic: it is
     NOT checked whether an export is actually imported anywhere (that
     would be cross-module analysis, deliberately out of scope for this
     script — see the note on "real call-chain depth").

Output: COMPLEXITY_MAP.md

Usage:  python list_complexity.py
"""

import ast
import os
from datetime import datetime

from metrics_config import PROJECT_ROOT as ROOT, OUTPUT_DIR

os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT = os.path.join(OUTPUT_DIR, "COMPLEXITY_MAP.md")

EXCLUDE_DIRS = {
    "__pycache__", ".git", "build", "dist",
    ".pytest_cache", ".mypy_cache", "venv", ".venv",
    "node_modules"
}

EXCLUDE_FILES = {
    "list_complexity.py",
    "metrics_config.py",
    "count_project.py",
    "list_functions.py",
    "list_gui_bindings.py",
    "list_longest_functions.py",
    "build_profile.py",
}

DEPTH_WARN_THRESHOLD = 4  # "deeply nested" from here — common rule of thumb

# Node types that open up an additional nesting level.
NESTING_NODE_TYPES = (
    ast.If, ast.For, ast.AsyncFor, ast.While,
    ast.Try, ast.With, ast.AsyncWith,
)


class FunctionComplexity:
    def __init__(self, name, lineno, class_name, max_depth):
        self.name       = name
        self.lineno     = lineno
        self.class_name = class_name
        self.max_depth  = max_depth


def _measure_depth(node, current_depth=0):
    """
    Recursive depth measurement. Counts one level per NESTING_NODE_TYPES
    node. Returns the maximum depth reached anywhere below node.
    Nested function definitions (closures) are NOT counted here — they
    get their own separate measurement (see analyze_functions).
    """
    max_found = current_depth

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # own measurement, not part of the enclosing depth

        if isinstance(child, NESTING_NODE_TYPES):
            child_depth = _measure_depth(child, current_depth + 1)
        else:
            child_depth = _measure_depth(child, current_depth)

        max_found = max(max_found, child_depth)

    return max_found


def analyze_functions(tree):
    """
    Finds all functions/methods (including nested/local ones) and
    measures, for each, its maximum internal nesting depth independent
    of the enclosing function.
    """
    results = []

    def walk(node, class_ctx=None):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, class_ctx=child.name)
                continue

            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                depth = _measure_depth(child, current_depth=0)
                results.append(FunctionComplexity(
                    name=child.name,
                    lineno=child.lineno,
                    class_name=class_ctx,
                    max_depth=depth,
                ))
                walk(child, class_ctx=None)  # capture local defs inside
                continue

            walk(child, class_ctx=class_ctx)

    walk(tree, class_ctx=None)
    return results


def analyze_interfaces(tree):
    """
    Inputs: all import / from-import statements (module name or source
    plus imported names).
    Outputs: all module-level def/class (not nested inside a function or
    class), split into public (no leading underscore) and private
    (_prefix).
    """
    imports = []
    exports_public = []
    exports_private = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ("." * node.level)
            names = ", ".join(alias.name for alias in node.names)
            imports.append(f"{module} ({names})")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if name.startswith("_"):
                exports_private.append(name)
            else:
                exports_public.append(name)

    return imports, exports_public, exports_private


def analyze_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
    except Exception:
        return None

    functions = analyze_functions(tree)
    imports, exports_public, exports_private = analyze_interfaces(tree)

    return {
        "functions": functions,
        "imports": imports,
        "exports_public": exports_public,
        "exports_private": exports_private,
    }


# --- Scan ---
per_file_results = {}   # rel_path -> analyze_file() result
parse_errors = []

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

    for filename in filenames:
        if filename in EXCLUDE_FILES or not filename.endswith(".py"):
            continue

        filepath = os.path.join(dirpath, filename)
        rel_path = os.path.relpath(filepath, ROOT).replace(os.sep, "/")

        result = analyze_file(filepath)
        if result is None:
            parse_errors.append(rel_path)
            continue

        per_file_results[rel_path] = result

# --- Aggregation: nesting depth ---
all_func_depths = []  # (rel_path, FunctionComplexity)
for rel_path, result in per_file_results.items():
    for fc in result["functions"]:
        all_func_depths.append((rel_path, fc))

over_threshold = [(p, fc) for p, fc in all_func_depths if fc.max_depth >= DEPTH_WARN_THRESHOLD]
over_threshold.sort(key=lambda item: item[1].max_depth, reverse=True)

# Per file: max + average depth
file_depth_stats = {}  # rel_path -> (max_depth, avg_depth, func_count)
for rel_path, result in per_file_results.items():
    depths = [fc.max_depth for fc in result["functions"]]
    if depths:
        file_depth_stats[rel_path] = (
            max(depths),
            sum(depths) / len(depths),
            len(depths),
        )

files_by_max_depth = sorted(
    file_depth_stats.items(), key=lambda item: item[1][0], reverse=True
)

# --- Output ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

out = []
out.append("# Complexity Map")
out.append("")
out.append(f"*Generated: {now}*")
out.append("")
out.append(
    "Two independent AST evaluations: (1) nesting depth of "
    "if/for/while/try/with nested inside each other, measured per "
    "function — closures get their own measurement, independent of the "
    "enclosing function. (2) Interfaces per file — imports (inputs) and "
    "module-level def/class (outputs, public/private)."
)
out.append("")
out.append(
    "**Limitation:** this is not a call-chain analysis. Whether an "
    "\"output\" (export) is actually imported anywhere, or whether a "
    "deeply nested function calls other functions that are themselves "
    "deeply nested, is not checked here — that would require cross-module "
    "resolution and type inference, which aren't reliably possible anyway "
    "with dynamic calls (callbacks, `self._app.x()` chains)."
)
out.append("")
out.append("---")
out.append("")
out.append("## Summary — Nesting Depth")
out.append("")
out.append("| | Value |")
out.append("|---|---:|")
out.append(f"| Functions analyzed | {len(all_func_depths):,} |")
out.append(f"| Over warning threshold (depth {DEPTH_WARN_THRESHOLD}+) | {len(over_threshold):,} |")
if parse_errors:
    out.append(f"| Unparseable files | {len(parse_errors):,} |")
out.append("")

if parse_errors:
    out.append("### Unparseable Files")
    out.append("")
    for p in parse_errors:
        out.append(f"- `{p}`")
    out.append("")

out.append("---")
out.append("")
out.append(f"## Functions Over Nesting Warning Threshold (Depth {DEPTH_WARN_THRESHOLD}+)")
out.append("")
if over_threshold:
    out.append("| Depth | File | Class | Function | Line |")
    out.append("|---:|---|---|---|---:|")
    for rel_path, fc in over_threshold:
        class_col = fc.class_name if fc.class_name else ""
        out.append(f"| {fc.max_depth} | {rel_path} | {class_col} | {fc.name} | {fc.lineno} |")
else:
    out.append(f"No function with nesting depth {DEPTH_WARN_THRESHOLD}+ found.")
out.append("")

out.append("---")
out.append("")
out.append("## Nesting Depth per File (max / avg, sorted by max)")
out.append("")
out.append("| File | Max Depth | Avg Depth | Functions |")
out.append("|---|---:|---:|---:|")
for rel_path, (max_d, avg_d, count) in files_by_max_depth:
    out.append(f"| {rel_path} | {max_d} | {avg_d:.1f} | {count} |")
out.append("")

out.append("---")
out.append("")
out.append("## Interfaces per File")
out.append("")
out.append(
    "*Inputs = what the file imports. Outputs = module-level def/class "
    "(public = no leading underscore, private = `_prefix`). No statement "
    "about whether an export is actually used.*"
)
out.append("")

for rel_path in sorted(per_file_results.keys()):
    result = per_file_results[rel_path]
    out.append(f"### {rel_path}")
    out.append("")
    if result["imports"]:
        out.append("**Inputs (Imports):**")
        for imp in result["imports"]:
            out.append(f"- {imp}")
    else:
        out.append("**Inputs (Imports):** none")
    out.append("")
    if result["exports_public"]:
        out.append(f"**Outputs, public ({len(result['exports_public'])}):** "
                    + ", ".join(f"`{n}`" for n in result["exports_public"]))
    else:
        out.append("**Outputs, public:** none")
    if result["exports_private"]:
        out.append(f"**Outputs, private ({len(result['exports_private'])}):** "
                    + ", ".join(f"`{n}`" for n in result["exports_private"]))
    else:
        out.append("**Outputs, private:** none")
    out.append("")

output_text = "\n".join(out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Done — {OUTPUT} written.")
print(f"  Functions analyzed: {len(all_func_depths):,}")
print(f"  Over warning threshold (depth {DEPTH_WARN_THRESHOLD}+): {len(over_threshold):,}")
if over_threshold:
    top = over_threshold[0]
    print(f"  Deepest nesting: {top[1].name} (depth {top[1].max_depth}, {top[0]}:{top[1].lineno})")
if parse_errors:
    print(f"  WARNING: {len(parse_errors)} file(s) unparseable.")
