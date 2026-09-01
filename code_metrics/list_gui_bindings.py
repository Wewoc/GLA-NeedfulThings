"""
list_gui_bindings.py — code_metrics
Finds all Qt-style signal bindings (.connect(...)) across the project and
assigns them a handler where statically resolvable.

Project-wide recursive scan — any .py file containing a `.connect(...)`
call is included. There is no fixed file scope; if a project's GUI code
lives in identifiable files/folders only, narrow EXCLUDE_DIRS below or
point PROJECT_ROOT at the relevant subfolder instead.

Output: GUI_BINDINGS.md

Usage:  python list_gui_bindings.py [PROJECT_ROOT]
        PROJECT_ROOT default = "."
"""

import ast
import os
from datetime import datetime

# --- Configuration ---
from metrics_config import PROJECT_ROOT as ROOT, OUTPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT = os.path.join(OUTPUT_DIR, "GUI_BINDINGS.md")

EXCLUDE_DIRS = {
    "__pycache__", ".git", "build", "dist",
    ".pytest_cache", ".mypy_cache", "venv", ".venv",
    "node_modules"
}

EXCLUDE_FILES = {
    "list_gui_bindings.py",   # don't scan ourselves
}

# Signal names considered "widget-like" (for classification in the
# output). Anything outside this list that still calls .connect() is
# marked as "custom signal" instead of "widget".
WIDGET_SIGNAL_NAMES = {
    "clicked", "toggled", "triggered",
    "currentIndexChanged", "currentTextChanged",
    "valueChanged", "textChanged", "returnPressed",
    "cellDoubleClicked", "cellClicked", "itemClicked",
}


class BindingEntry:
    def __init__(self, lineno, signal_expr, signal_name, handler_repr, handler_kind, class_ctx):
        self.lineno       = lineno
        self.signal_expr  = signal_expr   # e.g. "self._start_btn.clicked"
        self.signal_name  = signal_name   # e.g. "clicked"
        self.handler_repr = handler_repr  # readable representation of the handler
        self.handler_kind = handler_kind  # "method" | "local_func" | "lambda" | "dynamic" | "unresolved"
        self.class_ctx    = class_ctx     # enclosing class, if any


def _expr_to_str(node):
    """Best-effort string representation of an Attribute/Name expression
    (e.g. self._start_btn.clicked) without full unparse overhead."""
    try:
        return ast.unparse(node)
    except Exception:
        return "<unresolved>"


def _classify_handler(arg_node):
    """
    Classifies the argument of a .connect(...) call.
    Returns: (handler_repr, handler_kind)
    """
    if isinstance(arg_node, ast.Lambda):
        try:
            body_repr = ast.unparse(arg_node.body)
        except Exception:
            body_repr = "<lambda body>"
        return f"lambda: {body_repr}", "lambda"

    if isinstance(arg_node, ast.Attribute):
        # self._on_ok, dlg.accept, dlg.reject etc.
        try:
            return ast.unparse(arg_node), "method"
        except Exception:
            return "<attribute>", "method"

    if isinstance(arg_node, ast.Name):
        # local function (_build, _save, ...) OR a parameter/variable
        # (e.g. "callback", "cmd") — both are syntactically
        # indistinguishable without data-flow analysis. We mark it as
        # "local_func_or_dynamic" and leave the distinction transparent
        # in the report text.
        return arg_node.id, "local_func_or_dynamic"

    if isinstance(arg_node, ast.Call):
        # e.g. functools.partial(...)
        try:
            return ast.unparse(arg_node), "call_expression"
        except Exception:
            return "<call>", "call_expression"

    try:
        return ast.unparse(arg_node), "unresolved"
    except Exception:
        return "<unresolved>", "unresolved"


def analyze_gui_file(path):
    """
    Finds all .connect(...) calls via AST and extracts the signal
    expression + handler classification. Tracks class context while
    walking so each binding can be attributed to its enclosing class.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
    except Exception:
        return None

    bindings = []

    def walk(node, class_ctx=None):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, class_ctx=child.name)
                continue

            if isinstance(child, ast.Call):
                func = child.func
                if isinstance(func, ast.Attribute) and func.attr == "connect":
                    signal_expr = _expr_to_str(func.value)
                    # The actual signal name sits in the last .attr before
                    # .connect, i.e. in .attr of func.value (if it's an
                    # Attribute).
                    if isinstance(func.value, ast.Attribute):
                        signal_name = func.value.attr
                    else:
                        signal_name = "<unknown>"

                    if child.args:
                        handler_repr, handler_kind = _classify_handler(child.args[0])
                    else:
                        handler_repr, handler_kind = "<no argument>", "unresolved"

                    bindings.append(BindingEntry(
                        lineno=child.lineno,
                        signal_expr=signal_expr,
                        signal_name=signal_name,
                        handler_repr=handler_repr,
                        handler_kind=handler_kind,
                        class_ctx=class_ctx,
                    ))

            walk(child, class_ctx=class_ctx)

    walk(tree, class_ctx=None)
    return bindings


# --- Scan ---
all_bindings = []      # (rel_path, BindingEntry)
parse_errors = []

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

    for filename in filenames:
        if filename in EXCLUDE_FILES or not filename.endswith(".py"):
            continue

        filepath = os.path.join(dirpath, filename)
        rel_path = os.path.relpath(filepath, ROOT).replace(os.sep, "/")

        bindings = analyze_gui_file(filepath)
        if bindings is None:
            parse_errors.append(rel_path)
            continue

        for b in bindings:
            all_bindings.append((rel_path, b))

# --- Aggregation ---
count_total   = len(all_bindings)
count_widget  = sum(1 for _, b in all_bindings if b.signal_name in WIDGET_SIGNAL_NAMES)
count_custom  = count_total - count_widget

kind_counts = {}
for _, b in all_bindings:
    kind_counts[b.handler_kind] = kind_counts.get(b.handler_kind, 0) + 1

all_bindings.sort(key=lambda item: (item[0], item[1].lineno))

# --- Output ---
now = datetime.now().strftime("%Y-%m-%d %H:%M")

out = []
out.append("# GUI Bindings")
out.append("")
out.append(f"*Generated: {now}*")
out.append("")
out.append(
    "AST-based evaluation of all `.connect(...)` calls found anywhere in "
    "the project (recursive scan, see EXCLUDE_DIRS/EXCLUDE_FILES for what "
    "is skipped)."
)
out.append("")
out.append(
    "**Handler classification:** `method` = class method (e.g. "
    "`self._on_ok`), `local_func_or_dynamic` = either a locally defined "
    "function (closure) or a passed-through parameter (e.g. `callback`) — "
    "both are syntactically identical (a plain name) and cannot be "
    "reliably distinguished without data-flow analysis, so they are "
    "reported as one category. `lambda` = inline lambda. "
    "`call_expression` = e.g. `functools.partial(...)`."
)
out.append("")
out.append("---")
out.append("")
out.append("## Summary")
out.append("")
out.append("| | Count |")
out.append("|---|---:|")
out.append(f"| Bindings total | {count_total:,} |")
out.append(f"| of which widget signals (clicked/toggled/...) | {count_widget:,} |")
out.append(f"| of which other/custom signals | {count_custom:,} |")
for kind, n in sorted(kind_counts.items(), key=lambda kv: -kv[1]):
    out.append(f"| Handler type: {kind} | {n:,} |")
out.append("")

if parse_errors:
    out.append("### Unparseable Files")
    out.append("")
    for f in parse_errors:
        out.append(f"- `{f}`")
    out.append("")

out.append("---")
out.append("")
out.append("## Details by File")
out.append("")

if not all_bindings:
    out.append("No `.connect(...)` calls found.")
    out.append("")

current_file = None
for rel_path, b in all_bindings:
    if rel_path != current_file:
        if current_file is not None:
            out.append("")
        out.append(f"### {rel_path}")
        out.append("")
        out.append("| Line | Class | Signal | Handler | Handler Type |")
        out.append("|---:|---|---|---|---|")
        current_file = rel_path

    class_col = b.class_ctx if b.class_ctx else ""
    out.append(
        f"| {b.lineno} | {class_col} | {b.signal_expr} | {b.handler_repr} | {b.handler_kind} |"
    )

out.append("")

output_text = "\n".join(out)

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write(output_text)

print(f"Done — {OUTPUT} written.")
print(f"  Bindings total: {count_total:,}")
print(f"    Widget signals: {count_widget:,}")
print(f"    Custom/other:   {count_custom:,}")
for kind, n in sorted(kind_counts.items(), key=lambda kv: -kv[1]):
    print(f"    Handler type {kind}: {n:,}")
if parse_errors:
    print(f"  WARNING: {len(parse_errors)} file(s) unparseable.")
