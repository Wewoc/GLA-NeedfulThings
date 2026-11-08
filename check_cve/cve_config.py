"""
cve_config.py
Needful Things — CVE Relevance Filter · Configuration

Location: check_cve/
Usage:    run_cve_check.bat  (or: python check_cve_whitelist.py)
Output:   report on the console only; nothing is written

Every value below is a placeholder for an imaginary project — adjust
REQUIREMENTS_FILE and fill CVE_WHITELIST from your own code.
"""

# ── Paths ──────────────────────────────────────────────────────────────────────
# Requirements file that pip-audit checks (pip-audit -r). Relative to the location
# of this script (check_cve/), or absolute. Scoping to this file keeps unrelated
# tools in the active environment out of the report.

REQUIREMENTS_FILE = "../my_project/requirements.txt"    # adjust!

# ── Ollama (optional) ─────────────────────────────────────────────────────────
# For a package that IS in the whitelist but whose advisory text names none of the
# listed functions, the checker can ask a local Ollama model whether the text
# plausibly refers to one of them. Any failure (Ollama not running, timeout,
# unclear answer) falls back to "unsure" — it never blocks the report.
# Nothing leaves your machine. Set USE_OLLAMA = False to skip the call.

USE_OLLAMA   = True
OLLAMA_MODEL = "phi4:14b"
OLLAMA_URL   = "http://localhost:11434"

# ── Whitelist ──────────────────────────────────────────────────────────────────
# Known-used functions per package. pip-audit reports vulnerabilities at the package
# level, not the function level; this list lets the checker tell "this package has
# a known vulnerability" from "the vulnerable function is part of our call graph" —
# without claiming certainty either way.
#
# Format: {"package": {"used_functions": [...], "note": "..."}}
#   used_functions  the functions/classes your code actually calls — narrow, not the
#                   whole package surface. Matching ignores case, "_", "." and spaces.
#   note            where it is used, so a later reader can verify the entry.
# An EMPTY used_functions list is allowed: the package counts as "used" (verdict at
# most "unsure", never "not_relevant"), e.g. for a transitive dependency that no code
# of yours calls directly but that the application needs at runtime.
#
# Edit this file whenever the project starts or stops using a specific function.
# A package that is not listed at all gets the verdict "not_relevant".

CVE_WHITELIST = {
    "requests": {
        "used_functions": [
            "requests.get",
            "requests.Session",
        ],
        "note": "HTTP calls — api_client.py (example entry, replace)",
    },
    "some-transitive-dependency": {
        "used_functions": [],
        "note": "Pulled in by another package, not called directly (example entry, replace)",
    },
}
