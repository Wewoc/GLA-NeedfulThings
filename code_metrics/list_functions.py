"""
list_functions.py — code_metrics
Lists all functions, methods and classes in the project via AST parsing
(no regex, no line-counting heuristics — a real Python syntax tree).

Output: FUNCTION_MAP.md

Usage:  python list_functions.py [PROJECT_ROOT]
        PROJECT_ROOT default = "."
"""

import ast
import os
from datetime import datetime

# --- Configuration ---
from metrics_config import PROJECT_ROOT as ROOT, OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT = os.path.join(OUTPUT_DIR, "FUNCTION_MAP.md")

EXCLUDE_DIRS = {
    "__pycache__", ".git", "build", "dist",
    ".pytest_cache", ".mypy_cache", "venv", ".venv",
    "node_modules"
}

EXCLUDE_FILES = {
    "list_functions.py",   # don't count ourselves
}


# --- Data structure for a found function/method entry ---
class FuncEntry:
    def __init__(self, name, kind, lineno, end_lineno, class_name=None):
        self.name        = name         # function name
        self.kind        = kind         # "module" | "method" | "local"
        self.lineno      = lineno       # start line (1-indexed)
        self.end_lineno  = end_lineno   # end line — for line count
        self.class_name  = class_name   # for kind="method": class name, else None

    @property
    def line_count(self):
        if self.end_lineno is None:
            return 0
        return self.end_lineno - self.lineno + 1


def analyze_python_file(path):
    """
    Parses a Python file via ast and extracts:
      - module-level functions (def at top level)
      - methods (def inside a class)
      - class names
      - local functions (def inside another function — closures)

    kind classification:
      "module" — def directly in module scope
      "method" — def directly in class scope
      "local"  — def inside a function/method (closure/helper)

    Returns (funcs, classes), or (None, None) on parse failure
    (syntax error in file — noted as a warning in the report, not a crash).
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return None, None  # signals "parse failed"
    except Exception:
        return None, None

    funcs = []
    classes = []

    def walk(node, class_ctx=None, depth=0):
        """
        class_ctx: name of the enclosing class, if directly nested under one.
        depth: 0 = module level, 1 = one level deeper (class OR function), ...
        Classification:
          - depth==0 and no class_ctx        -> "module"
          - directly under a class (depth==1 relative to the class) -> "method"
          - anything else (nested deeper) -> "local"
        """
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                classes.append((child.name, child.lineno))
                walk(child, class_ctx=child.name, depth=0)

            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if class_ctx is not None and depth == 0:
                    kind = "method"
                elif class_ctx is None and depth == 0:
                    kind = "module"
                else:
                    kind = "local"

                end_line = getattr(child, "end_lineno", None)
                funcs.append(FuncEntry(
                    name=child.name,
                    kind=kind,
                    lineno=child.lineno,
                    end_lineno=end_line,
                    class_name=class_ctx if kind == "method" else None,
                ))
                # Defs found inside a function are always "local",
                # regardless of whether we were inside a method.
                walk(child, class_ctx=None, depth=1)

            else:
                # Other nodes (if/for/with/try/...) — not scope-forming
                # for our purposes, but may contain further defs
                # (e.g. a def inside an if-block at module level).
                walk(child, class_ctx=class_ctx, depth=depth)

    walk(tree, class_ctx=None, depth=0)
    return funcs, classes


# --- Scan ---
all_entries = []       # list of (filepath, FuncEntry)
all_classes = []        # list of (filepath, class_name, lineno)
parse_errors = []       # files that could not be parsed

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

    for filename in filenames:
        if filename in EXCLUDE_FILES:
            continue
        if not filename.endswith(".py"):
            continue

        filepath = os.path.join(dirpath, filename)
        rel_path = os.path.relpath(filepath, ROOT).replace(os.sep, "/")

        funcs, classes = analyze_python_file(filepath)

        if funcs is None:
            parse_errors.append(rel_path)
            continue

        for entry in funcs:
            all_entries.append((rel_path, entry))
        for class_name, lineno in classes:
            all_classes.append((rel_path, class_name, lineno))

# --- Aggregation ---
count_module = sum(1 for _, e in all_entries if e.kind == "module")
count_method = sum(1 for _, e in all_entries if e.kind == "method")
count_local  = sum(1 for _, e in all_entries if e.kind == "local")
count_total  = len(all_entries)
count_classes = len(all_classes)

# Sort: by file, then by line
all_entries.sort(key=lambda item: (item[0], item[1].lineno))

# --- Output ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

out = []
out.append("# Function Map")
out.append("")
out.append(f"*Generated: {now}*")
out.append("")
out.append(
    "AST-based inventory of all functions, methods and classes. "
    "`module` = top-level function, `method` = class method, "
    "`local` = local function/closure inside another function."
)
out.append("")
out.append("---")
out.append("")
out.append("## Summary")
out.append("")
out.append("| | Count |")
out.append("|---|---:|")
out.append(f"| Functions total | {count_total:,} |")
out.append(f"| of which module functions | {count_module:,} |")
out.append(f"| of which methods | {count_method:,} |")
out.append(f"| of which local functions/closures | {count_local:,} |")
out.append(f"| Classes | {count_classes:,} |")
if parse_errors:
    out.append(f"| Unparseable files | {len(parse_errors):,} |")
out.append("")

if parse_errors:
    out.append("### Unparseable Files (Syntax Errors)")
    out.append("")
    for p in parse_errors:
        out.append(f"- `{p}`")
    out.append("")

out.append("---")
out.append("")
out.append("## Details by File")
out.append("")

current_file = None
for rel_path, entry in all_entries:
    if rel_path != current_file:
        if current_file is not None:
            out.append("")
        out.append(f"### {rel_path}")
        out.append("")
        out.append("| Line | Type | Class | Name | Lines |")
        out.append("|---:|---|---|---|---:|")
        current_file = rel_path

    class_col = entry.class_name if entry.class_name else ""
    out.append(
        f"| {entry.lineno} | {entry.kind} | {class_col} | {entry.name} | {entry.line_count} |"
    )

out.append("")

output_text = "\n".join(out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Done — {OUTPUT} written.")
print(f"  Functions total: {count_total:,}")
print(f"    Module functions: {count_module:,}")
print(f"    Methods:          {count_method:,}")
print(f"    Local/closures:   {count_local:,}")
print(f"  Classes: {count_classes:,}")
if parse_errors:
    print(f"  WARNING: {len(parse_errors)} file(s) unparseable — see report.")
