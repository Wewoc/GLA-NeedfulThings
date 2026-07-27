#!/usr/bin/env python3
"""
tools/generate_metrics.py — Garmin Local Archive

Erzeugt src/docs/METRICS.md — die einzige Datei, in die dieses Tool schreibt.
Alle anderen Doku-Dateien (README, MAINTENANCE_*, SESSION_BASE, Handbuch, ...)
verweisen künftig auf diese Datei statt Zahlen selbst zu tragen.

Ablauf (siehe Analyse-Chat v1.6.5.5):
    1. run_tests.ps1 ausführen (cwd = src/, damit relative Pfade im Skript stimmen)
    2. src/test_all_log.txt lesen — NICHT den Prozess-Exit-Code als alleinige
       Wahrheit nehmen. run_tests.ps1 läuft mit $ErrorActionPreference =
       "Continue" weiter, auch wenn eine Suite rot ist — die eigentliche
       Wahrheit steht im ZUSAMMENFASSUNG-Block der Log-Datei.
    3. Jede Suite-Zeile im ZUSAMMENFASSUNG-Block prüfen:
       - "Ergebnis nicht erkannt — siehe Log oben"  → Abbruch (kein Zahlenwert)
       - failed > 0 irgendeiner Suite                → Abbruch (roter Build)
       - keine einzige Suite-Zeile gefunden           → Abbruch (Log leer/kaputt)
    4. Nur bei vollständig grünem Ergebnis: build_manifest.py (SHARED_SCRIPTS,
       per AST — kein Import, kein exec) und version.py (APP_VERSION, per
       Regex) lesen.
    5. src/docs/METRICS.md atomar schreiben (temp-Datei → os.replace).

Bei jedem Fehler in 1–4: Abbruch, docs/METRICS.md bleibt unverändert stehen.
Lieber keine Datei als eine mit falschem oder veraltetem Zustand.

Läuft lokal bei Timo — kein Teil von SHARED_SCRIPTS, kein Teil des Builds.
Reines stdlib, keine externen Abhängigkeiten.
"""

import ast
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── Pfade ──────────────────────────────────────────────────────────────────────
# Gleiche Konvention wie apply_anchors.py — Pfad relativ zum Script-Standort,
# kein hart codierter absoluter Pfad. Voraussetzung: dieses Script liegt in
# einem NeedfulThings-Unterordner, dessen Parent-Ordner ein Geschwister von
# garmin_collector-1_work ist (identisch zu apply_anchors.py PROJECT_ROOT).
SCRIPT_DIR   = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPT_DIR / "../garmin_collector-1_work").resolve()
SRC_DIR      = PROJECT_ROOT / "src"

DOCS_DIR    = SRC_DIR / "docs"
OUTPUT_FILE = DOCS_DIR / "METRICS.md"

RUN_TESTS_PS1 = SRC_DIR / "run_tests.ps1"
LOG_FILE      = SRC_DIR / "test_all_log.txt"
BUILD_MANIFEST = SRC_DIR / "compiler" / "build_manifest.py"
VERSION_FILE   = SRC_DIR / "version.py"

# Zusammenfassungs-Zeilenformat aus run_tests.ps1 — identisch für "eigenes
# Format" und normalisiertes pytest-Format, da run_tests.ps1 beide auf
# dieselbe Zeile abbildet, bevor sie in SuiteSummaries landet.
_SUITE_LINE_RE = re.compile(
    r'^\s*(?P<label>\S.*?)\s{2,}'
    r'(?P<total>\d+)\s+checks?\s+—\s+'
    r'(?P<passed>\d+)\s+passed,\s+'
    r'(?P<failed>\d+)\s+failed\s*$'
)
_UNRECOGNIZED_MARKER = "Ergebnis nicht erkannt"
_SUMMARY_HEADER_MARKER = "ZUSAMMENFASSUNG"


class GeneratorAbort(Exception):
    """Kontrollierter Abbruch — docs/METRICS.md bleibt unverändert."""


# ── Schritt 1+2 — Tests ausführen, Log lesen ───────────────────────────────────

def run_tests() -> None:
    if not RUN_TESTS_PS1.exists():
        raise GeneratorAbort(f"run_tests.ps1 nicht gefunden: {RUN_TESTS_PS1}")

    print(f"→ führe run_tests.ps1 aus (cwd={SRC_DIR}) ...")
    try:
        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(RUN_TESTS_PS1)],
            cwd=str(SRC_DIR),
            check=False,  # Exit-Code ist kein verlässliches Signal — siehe Docstring
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        raise GeneratorAbort("run_tests.ps1 hat das Zeitlimit (30 min) überschritten")
    except OSError as e:
        raise GeneratorAbort(f"run_tests.ps1 konnte nicht gestartet werden: {e}")


def parse_test_summary() -> list[dict]:
    """Liest den ZUSAMMENFASSUNG-Block aus test_all_log.txt.

    Gibt eine Liste von {"label", "total", "passed", "failed"} zurück.
    Wirft GeneratorAbort bei rotem Build, unerkannter Zeile oder leerem Log.
    """
    if not LOG_FILE.exists():
        raise GeneratorAbort(f"test_all_log.txt nicht gefunden: {LOG_FILE}")

    text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    try:
        start = next(i for i, l in enumerate(lines) if _SUMMARY_HEADER_MARKER in l)
    except StopIteration:
        raise GeneratorAbort(
            "Kein ZUSAMMENFASSUNG-Block in test_all_log.txt gefunden — "
            "Log unvollständig oder Format hat sich geändert."
        )

    suites: list[dict] = []
    for line in lines[start + 1:]:
        if _UNRECOGNIZED_MARKER in line:
            # Suite-Label steht vor dem Marker in derselben Zeile
            raise GeneratorAbort(f"Unerkanntes Testergebnis in Log-Zeile: {line.strip()!r}")

        m = _SUITE_LINE_RE.match(line)
        if m:
            suites.append({
                "label":  m.group("label").strip(),
                "total":  int(m.group("total")),
                "passed": int(m.group("passed")),
                "failed": int(m.group("failed")),
            })

    if not suites:
        raise GeneratorAbort(
            "Keine Suite-Zeile im ZUSAMMENFASSUNG-Block erkannt — "
            "Log-Format geprüft? (siehe _SUITE_LINE_RE)"
        )

    red = [s for s in suites if s["failed"] > 0]
    if red:
        labels = ", ".join(f"{s['label']} ({s['failed']} failed)" for s in red)
        raise GeneratorAbort(f"Roter Testlauf — kein Update von METRICS.md: {labels}")

    return suites


# ── Schritt 4 — build_manifest.py + version.py lesen ──────────────────────────

def read_shared_scripts() -> list[str]:
    if not BUILD_MANIFEST.exists():
        raise GeneratorAbort(f"build_manifest.py nicht gefunden: {BUILD_MANIFEST}")

    source = BUILD_MANIFEST.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BUILD_MANIFEST))

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SHARED_SCRIPTS":
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError) as e:
                        raise GeneratorAbort(f"SHARED_SCRIPTS nicht literal auswertbar: {e}")
                    if not isinstance(value, list):
                        raise GeneratorAbort("SHARED_SCRIPTS ist keine Liste — Format geprüft?")
                    return value

    raise GeneratorAbort("SHARED_SCRIPTS in build_manifest.py nicht gefunden")


def read_app_version() -> str:
    if not VERSION_FILE.exists():
        raise GeneratorAbort(f"version.py nicht gefunden: {VERSION_FILE}")

    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'''APP_VERSION\s*=\s*['"]([^'"]+)['"]''', text)
    if not m:
        raise GeneratorAbort("APP_VERSION in version.py nicht gefunden — Format geprüft?")
    return m.group(1)


# ── Schritt 5 — docs/METRICS.md atomar schreiben ──────────────────────────────

def render_metrics_md(suites: list[dict], modules: list[str], version: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_checks = sum(s["total"] for s in suites)

    lines = [
        "<!-- generated by tools/generate_metrics.py — do not edit by hand -->",
        f"<!-- Other docs should link here instead of restating these numbers -->",
        "",
        "# METRICS",
        "",
        f"Generated: {now} · Version: {version}",
        "",
        "## Test Counts",
        "",
        "| Suite | Checks | Passed | Failed |",
        "|---|---|---|---|",
    ]
    for s in suites:
        lines.append(f"| {s['label']} | {s['total']} | {s['passed']} | {s['failed']} |")
    lines += [
        f"| **Total** | **{total_checks}** | **{total_checks}** | **0** |",
        "",
        "## Modules",
        "",
        f"Total: {len(modules)} (from `SHARED_SCRIPTS` in `build_manifest.py`)",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_metrics_md(content: str) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=str(DOCS_DIR), prefix=".metrics_", suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        # Atomarer Rename — kein Zwischenzustand, in dem METRICS.md halb
        # geschrieben oder leer wäre.
        Path(tmp_path).replace(OUTPUT_FILE)
    except OSError:
        Path(tmp_path).unlink(missing_ok=True)
        raise


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        run_tests()
        suites = parse_test_summary()
        modules = read_shared_scripts()
        version = read_app_version()

        content = render_metrics_md(suites, modules, version)
        write_metrics_md(content)

    except GeneratorAbort as e:
        print(f"\n✗ Abbruch — {OUTPUT_FILE.name} bleibt unverändert.", file=sys.stderr)
        print(f"  Grund: {e}", file=sys.stderr)
        return 1

    print(f"\n✓ {OUTPUT_FILE} aktualisiert.")
    print(f"  {sum(s['total'] for s in suites)} checks, alle grün · {len(modules)} Module · v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
