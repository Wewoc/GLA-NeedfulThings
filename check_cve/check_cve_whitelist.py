# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
check_cve_whitelist.py — CVE Relevance Filter
Needful Things · report tool · no project imports

Runs pip-audit against the requirements file set in cve_config.py, then
cross-references each finding against CVE_WHITELIST (cve_config.py) to
flag whether the vulnerable package's known-used functions are actually
plausibly affected.

This is a REPORT ONLY tool. It never blocks, never aborts a build, and
never asks for confirmation. Exit code is always 0. The decision whether
a finding matters stays with the developer — this script narrows the
list, it does not make the call.

Verdict per finding:
  relevant      — package is in the whitelist AND the CVE description
                  mentions a function/class name that appears in
                  used_functions. Worth a closer look.
  unsure        — package is in the whitelist but no keyword overlap was
                  found (pip-audit descriptions are free text, not
                  guaranteed to name the affected function explicitly).
                  Not dismissed — just not confirmed either way.
  not_relevant  — package is not in the whitelist at all, i.e. the project
                  has no recorded usage of it. Most likely a transitive
                  dependency never called directly.

Needs pip-audit in the interpreter that runs this script
(pip install pip-audit). Optionally asks a local Ollama model about
inconclusive findings (USE_OLLAMA in cve_config.py).

Run via run_cve_check.bat, or standalone:
    python check_cve_whitelist.py [--full]
"""

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import importlib.util

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "cve_config.py"


def load_config():
    """Import cve_config.py from next to this script; stop with a clear message if it is unusable."""
    if not CONFIG_FILE.exists():
        sys.exit(f"config not found: {CONFIG_FILE}")
    spec = importlib.util.spec_from_file_location("cve_config", CONFIG_FILE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # any error inside the config is reported the same way
        sys.exit(f"cannot load {CONFIG_FILE.name}: {exc!r}")
    missing = [n for n in ("REQUIREMENTS_FILE", "CVE_WHITELIST") if not hasattr(module, n)]
    if missing:
        sys.exit(f"{CONFIG_FILE.name}: missing setting(s): {', '.join(missing)}")
    if not isinstance(module.CVE_WHITELIST, dict):
        sys.exit(f"{CONFIG_FILE.name}: CVE_WHITELIST must be a dict {{package: {{used_functions, note}}}}")
    for pkg, entry in module.CVE_WHITELIST.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("used_functions"), list):
            sys.exit(f"{CONFIG_FILE.name}: entry '{pkg}' needs a list under 'used_functions' (may be empty)")
    return module


CFG = load_config()
REQUIREMENTS_FILE = (HERE / CFG.REQUIREMENTS_FILE).resolve()
CVE_WHITELIST = CFG.CVE_WHITELIST
USE_OLLAMA = getattr(CFG, "USE_OLLAMA", True)
OLLAMA_MODEL = getattr(CFG, "OLLAMA_MODEL", "phi4:14b")
OLLAMA_URL = getattr(CFG, "OLLAMA_URL", "http://localhost:11434")

# ─── pip-audit invocation ───────────────────────────────────────────────────


def run_pip_audit() -> list[dict] | None:
    """
    Runs `pip-audit -r <requirements file> -f json` — scoped to the packages
    the project actually declares (plus their resolved transitive
    dependencies), not the entire active Python environment. Without -r,
    pip-audit reports on every package installed in the current
    interpreter, including unrelated dev tools — a real test run produced
    ~70 irrelevant findings that way.

    Returns the parsed dependency list, or None if pip-audit itself
    failed to run (not installed, requirements file missing, network
    error, etc.) — this is reported as a finding, never raised as an
    exception that could disrupt a build.
    """
    requirements_path = REQUIREMENTS_FILE
    if not requirements_path.exists():
        return None

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pip_audit",
                "-r", str(requirements_path),
                "-f", "json",
                "--progress-spinner", "off",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None

    # pip-audit exits 1 when vulnerabilities are found — this is expected,
    # not an error. Only a missing/unparsable stdout is treated as failure.
    if not result.stdout.strip():
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    return data.get("dependencies", [])


# ─── Whitelist cross-reference ──────────────────────────────────────────────


def _normalize(text: str) -> str:
    return text.lower().replace("_", "").replace(".", "").replace(" ", "")


def classify_finding(pkg_name: str, description: str) -> tuple[str, str]:
    """
    Returns (verdict, matched_function_or_empty).

    First tries a direct string match against used_functions (cheap, no
    network call). If that's inconclusive and the package IS in the
    whitelist, falls back to an Ollama text-comparison check — only for
    that case, never for not_relevant findings (a package outside the
    whitelist is a different question: "is the whitelist complete?", not
    "does this description match a known function?").
    """
    entry = CVE_WHITELIST.get(pkg_name)
    if entry is None:
        return "not_relevant", ""

    desc_norm = _normalize(description)
    # Check longest names first — same reasoning as in
    # _ollama_check_unsure(): "AESGCM.encrypt" must win over the shorter
    # "AESGCM" when both are whitelist entries for the same package,
    # since the normalized short form is itself a substring of the long
    # form's normalized text and would otherwise always match first.
    for func in sorted(entry["used_functions"], key=len, reverse=True):
        func_norm = _normalize(func)
        if func_norm and func_norm in desc_norm:
            return "relevant", func

    ollama_verdict, ollama_func = _ollama_check_unsure(
        description, entry["used_functions"]
    )
    if ollama_verdict == "relevant":
        return "relevant", f"{ollama_func} (via Ollama)"

    return "unsure", ""


def _ollama_check_unsure(description: str, used_functions: list[str]) -> tuple[str, str]:
    """
    Asks a local Ollama model whether the CVE description plausibly refers
    to one of the listed functions, even without an exact string match
    (e.g. "the encryption routine" vs. "AESGCM.encrypt"). Same network
    call pattern as scan_critical_deps.py's _ollama_classify() — plain
    urllib POST to /api/generate, no extra dependency.

    Returns (verdict, matched_function_or_empty). Any failure (Ollama not
    running, timeout, malformed response) falls back to "unsure" — never
    raises, never blocks the report.

    An empty used_functions list is short-circuited to "unsure" before
    the call: with nothing to compare against, Ollama has been observed
    to still answer "relevant" (confirmed live run, 2026-09-28 — anyio/
    pydantic-settings/starlette entries), which would produce a
    "relevant" verdict with no matched function at all — the one thing
    "relevant" is supposed to guarantee.
    """
    if not USE_OLLAMA or not used_functions:
        return "unsure", ""

    func_list = ", ".join(used_functions)
    prompt = (
        f"A security advisory describes a vulnerability with this "
        f"description:\n\n{description}\n\n"
        f"Here is a list of functions/classes actually used by a "
        f"software project: {func_list}\n\n"
        f"Does the vulnerability description plausibly refer to the "
        f"behavior of one of these specific functions/classes? Answer "
        f"with exactly one word: 'relevant' if yes and name which one in "
        f"a second line, 'not_relevant' if the description is clearly "
        f"about something else, or 'unsure' if you cannot tell. Answer "
        f"with one of these three words first."
    )

    payload = json.dumps({
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data     = json.loads(resp.read().decode("utf-8"))
            response = data.get("response", "").strip().lower()
    except Exception:
        return "unsure", ""

    # Check "not_relevant" before "relevant" — the substring "relevant"
    # appears inside "not_relevant" too (same ordering as
    # scan_critical_deps.py._ollama_classify()).
    if "not_relevant" in response:
        return "not_relevant", ""
    elif "relevant" in response:
        # Try to find which function it named, on a best-effort basis.
        # Check longest names first — "AESGCM.encrypt" must win over the
        # shorter "AESGCM" when both are whitelist entries, since
        # "aesgcm" (normalized) is itself a substring of
        # "aesgcmencrypt" and would otherwise match first regardless of
        # which one the response actually names.
        for func in sorted(used_functions, key=len, reverse=True):
            if _normalize(func) in _normalize(response):
                return "relevant", func
        return "relevant", used_functions[0] if used_functions else ""
    else:
        return "unsure", ""


def build_findings(dependencies: list[dict]) -> list[dict]:
    findings = []
    for dep in dependencies:
        pkg_name = dep.get("name", "")
        vulns = dep.get("vulns", [])
        if not vulns:
            continue

        for vuln in vulns:
            vuln_id = vuln.get("id", "?")
            description = vuln.get("description", "") or ""
            fix_versions = vuln.get("fix_versions", [])

            verdict, matched_func = classify_finding(pkg_name, description)

            findings.append({
                "package":      pkg_name,
                "version":      dep.get("version", "?"),
                "id":           vuln_id,
                "verdict":      verdict,
                "matched_func": matched_func,
                "fix_versions": fix_versions,
                "description":  description,
            })

    return findings


# ─── Report ──────────────────────────────────────────────────────────────────

_VERDICT_ORDER = ["relevant", "unsure", "not_relevant"]

_VERDICT_LABELS = {
    "relevant":     "⚠ CRITICAL — whitelisted function name found in description",
    "unsure":       "UNSURE — package is used by the project, no function match confirmed",
    "not_relevant": "NOT RELEVANT — package not in the project's used-function whitelist",
}


def build_report(findings: list[dict], full: bool = False) -> str:
    """
    full=False (default): only the "relevant" group is printed in detail —
    "unsure"/"not_relevant" collapse to a single count line, so the one
    verdict backed by an actual keyword match doesn't get buried. Pass
    full=True (main(): --full) for the complete per-finding report.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("CVE WHITELIST CHECK — pip-audit findings cross-referenced")
    lines.append("against CVE_WHITELIST in cve_config.py (known-used functions per package)")
    lines.append("=" * 70)
    lines.append("")

    if not findings:
        lines.append("✓ No known vulnerabilities found in installed packages.")
        lines.append("")
        return "\n".join(lines)

    by_verdict: dict[str, list[dict]] = {v: [] for v in _VERDICT_ORDER}
    for f in findings:
        by_verdict[f["verdict"]].append(f)

    for verdict in _VERDICT_ORDER:
        group = by_verdict[verdict]
        if not group:
            continue

        lines.append("-" * 70)
        lines.append(_VERDICT_LABELS[verdict])
        lines.append("-" * 70)
        lines.append("")

        if verdict != "relevant" and not full:
            lines.append(
                f"  {len(group)} finding(s) — run with --full to see details."
            )
            lines.append("")
            continue

        for f in group:
            fix = ", ".join(f["fix_versions"]) if f["fix_versions"] else "none published"
            lines.append(f"  • {f['id']} — {f['package']} {f['version']}")
            if f["matched_func"]:
                lines.append(f"      matched function: {f['matched_func']}")
            lines.append(f"      fix versions: {fix}")
            desc = f["description"].strip()
            if desc:
                snippet = (desc[:200] + "…") if len(desc) > 200 else desc
                lines.append(f"      {snippet}")

            if verdict == "relevant":
                rec = (
                    f"      → Recommendation: review {f['id']} — the "
                    f"description names a function the project actually calls "
                    f"({f['matched_func']})."
                )
            elif verdict == "unsure":
                rec = (
                    f"      → Recommendation: {f['package']} is used by "
                    f"the project, but the description doesn't name a specific "
                    f"function — worth a quick look if time allows."
                )
            else:  # not_relevant
                rec = (
                    f"      → No action expected: {f['package']} is not "
                    f"in CVE_WHITELIST — likely an unused transitive "
                    f"dependency. Update the whitelist if this changes."
                )
            lines.append(rec)
            lines.append("")

    lines.append("-" * 70)
    lines.append(
        f"Summary: {len(by_verdict['relevant'])} relevant, "
        f"{len(by_verdict['unsure'])} unsure, "
        f"{len(by_verdict['not_relevant'])} not relevant — "
        f"{len(findings)} total findings."
    )
    lines.append(
        "This is an informational report only — nothing was blocked. "
        "Review 'relevant' entries first, then 'unsure' if time allows."
    )
    lines.append("")

    return "\n".join(lines)


# ─── Main ────────────────────────────────────────────────────────────────────


def main() -> int:
    print("check_cve_whitelist — CVE relevance filter")
    print()

    requirements_path = REQUIREMENTS_FILE
    if not requirements_path.exists():
        print(f"⚠ requirements file not found at {requirements_path}")
        print("  This is informational only — build is not affected.")
        print()
        return 0

    dependencies = run_pip_audit()

    if dependencies is None:
        print("⚠ pip-audit could not be run (not installed, or no output).")
        print("  Install with: pip install pip-audit")
        print("  This is informational only — build is not affected.")
        print()
        return 0

    full = "--full" in sys.argv[1:]

    findings = build_findings(dependencies)
    print(build_report(findings, full=full))

    return 0


if __name__ == "__main__":
    sys.exit(main())