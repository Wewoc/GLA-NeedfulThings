"""
apply_anchors.py — Garmin Local Archive
Automatisiertes Einpflegen von Claude-gelieferten Anchor-Blöcken.

Ablauf:
  Pass 1 — Alle ALT-Blöcke suchen, vollständig durchlaufen, Fehler sammeln
  Pass 2 — Nur bei 100% Pass 1: alle NEU-Blöcke einpflegen

Aufruf: python apply_anchors.py
Eingabe: anchor_delivery.md (im selben Ordner wie dieses Script)
Ziel:    ../garmin_collector-1_work/ (relativ zum Script-Standort)

v1.6.5.5-fix: FENCE-Regex verlangt jetzt, dass die schließende Fence
dieselbe Backtick-Anzahl hat wie die öffnende (Backreference \1) —
vorher wurde jede beliebige Dreifach-Backtick-Folge als Ende akzeptiert,
was bei NEU-Blöcken mit eingebetteten ```python-Codebeispielen zu
stillschweigend abgeschnittenem Inhalt führte (kein Fehler, kein Hinweis
— einfach ein zu kurzer Treffer). Ursache + Reproduktion: Session
v1.6.5.5, Doku-Automatisierung.
"""

from pathlib import Path
import re
import sys

# ── Pfade ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPT_DIR / "../garmin_collector-1_work").resolve()
DELIVERY_MD  = SCRIPT_DIR / "anchor_delivery.md"

DELETE_MARKER = "#DELETE"

# ── Parser ───────────────────────────────────────────────────────────────────

def parse_delivery(md_path: Path) -> list[dict] | str:
    """
    Liest anchor_delivery.md und gibt eine Liste von Anchor-Dicts zurück.
    Bei Parsefehler: String mit Fehlermeldung.

    Jedes Dict:
        file  — relativer Pfad ab Projektroot (str)
        alt   — ALT-Block Inhalt (str, roh aus MD)
        neu   — NEU-Block Inhalt (str, roh) oder DELETE_MARKER
        index — globaler Index (1-basiert, wird nach Parse gesetzt)
    """
    text = md_path.read_text(encoding="utf-8")

    # Fenced code block: (`{3,})optional_lang\n...\n<dieselbe Backtick-Anzahl>
    # Backreference \1 erzwingt: schließende Fence == öffnende Fence-Länge.
    # Das erlaubt verschachtelte Codeblöcke im NEU-Inhalt (z.B. ein
    # eingebettetes ```python-Beispiel), solange die äußere Wrapper-Fence
    # länger ist (z.B. ````) als jede innere Fence im Inhalt.
    FENCE = re.compile(r"^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$", re.DOTALL | re.MULTILINE)

    anchors = []
    errors  = []

    # Aufteilen nach ## FILE: Sektionen
    sections = re.split(r"^## FILE:\s*", text, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue

        lines     = section.splitlines(keepends=True)
        file_path = lines[0].strip()
        body      = "".join(lines[1:])

        # ALT / NEU Blöcke innerhalb der Sektion finden
        # Mehrere ALT/NEU-Paare pro Datei erlaubt
        alt_positions = [m.start() for m in re.finditer(r"^### ALT", body, re.MULTILINE)]
        neu_positions = [m.start() for m in re.finditer(r"^### NEU", body, re.MULTILINE)]

        if len(alt_positions) != len(neu_positions):
            errors.append(f"  ✗  {file_path} — ALT/NEU Anzahl stimmt nicht überein")
            continue

        for alt_pos, neu_pos in zip(alt_positions, neu_positions):
            # ALT-Block extrahieren
            alt_section = body[alt_pos:neu_pos]
            alt_match   = FENCE.search(alt_section)
            if not alt_match:
                errors.append(f"  ✗  {file_path} — ALT-Block ohne Code-Fence gefunden")
                continue
            alt_content = alt_match.group(2)

            # NEU-Block extrahieren (bis nächsten ## FILE: / ### ALT oder Ende)
            next_boundary = len(body)
            for pos in alt_positions:
                if pos > neu_pos:
                    next_boundary = pos
                    break
            neu_section = body[neu_pos:next_boundary]
            neu_match   = FENCE.search(neu_section)
            if not neu_match:
                errors.append(f"  ✗  {file_path} — NEU-Block ohne Code-Fence gefunden")
                continue
            neu_content = neu_match.group(2)

            # Leerer NEU-Block ohne #DELETE → Fehler
            neu_stripped = neu_content.strip()
            if neu_stripped == "":
                errors.append(f"  ✗  {file_path} — NEU-Block ist leer (für Löschung: #DELETE verwenden)")
                continue

            # #DELETE normalisieren
            if neu_stripped == DELETE_MARKER:
                neu_content = DELETE_MARKER

            anchors.append({
                "file"  : file_path,
                "alt"   : alt_content,
                "neu"   : neu_content,
                "index" : 0,  # wird unten gesetzt
            })

    if errors:
        return "Parsefehler:\n" + "\n".join(errors)

    # Globale Nummerierung
    for i, anchor in enumerate(anchors, start=1):
        anchor["index"] = i

    return anchors

# ── Normalisierung für Vergleich ──────────────────────────────────────────────

def normalize_for_match(text: str) -> str:
    """
    Nur für den Vergleich — Original bleibt unberührt.
    - CRLF → LF
    - Trailing whitespace pro Zeile entfernen
    - Leading/trailing Leerzeilen entfernen
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    # Leading Leerzeilen entfernen
    while lines and lines[0] == "":
        lines.pop(0)
    # Trailing Leerzeilen entfernen
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)

# ── Zeilenenden detektieren ───────────────────────────────────────────────────

def detect_line_ending(raw: str) -> str:
    """Gibt '\r\n' oder '\n' zurück — je nachdem was in der Datei dominiert."""
    crlf = raw.count("\r\n")
    lf   = raw.count("\n") - crlf
    return "\r\n" if crlf >= lf else "\n"

# ── Pass 1 — Suche ───────────────────────────────────────────────────────────

def pass1(anchors: list[dict], total: int) -> list[dict]:
    """
    Sucht jeden ALT-Block in der Zieldatei.
    Gibt Liste der Fehler zurück (leer = 100% OK).
    Setzt anchor['status'] für jeden Anchor.
    """
    # Dateipfade für Kopfzeile sammeln
    files = sorted(set(a["file"] for a in anchors))
    print(f"\nPass 1 — Searching {total} anchors in {len(files)} files ...\n")

    errors = []

    for anchor in anchors:
        idx       = anchor["index"]
        rel_path  = anchor["file"]
        abs_path  = PROJECT_ROOT / rel_path
        label     = f"  [{idx}/{total}]"
        col_path  = rel_path.ljust(55)

        # Datei existiert?
        if not abs_path.is_file():
            msg = f"  ✗  {col_path} {label} FILE NOT FOUND"
            print(msg)
            errors.append(msg)
            anchor["status"] = "FILE_NOT_FOUND"
            continue

        # Datei lesen
        raw = abs_path.read_text(encoding="utf-8", errors="replace")

        # Normalisieren für Vergleich
        norm_file = normalize_for_match(raw)
        norm_alt  = normalize_for_match(anchor["alt"])

        count = norm_file.count(norm_alt)

        if count == 0:
            msg = f"  ✗  {col_path} {label} NOT FOUND"
            print(msg)
            errors.append(msg)
            anchor["status"] = "NOT_FOUND"
        elif count > 1:
            msg = f"  ✗  {col_path} {label} AMBIGUOUS ({count}x)"
            print(msg)
            errors.append(msg)
            anchor["status"] = "AMBIGUOUS"
        else:
            # Position per Sliding Window ermitteln — für Overlap-Check
            alt_lines       = normalize_for_match(anchor["alt"]).split("\n")
            file_lines_norm = [l.rstrip("\r\n").rstrip() for l in raw.splitlines(keepends=True)]
            line_start = None
            for i in range(len(file_lines_norm) - len(alt_lines) + 1):
                if file_lines_norm[i:i + len(alt_lines)] == alt_lines:
                    line_start = i
                    break
            anchor["line_start"] = line_start
            anchor["line_end"]   = line_start + len(alt_lines) if line_start is not None else None
            print(f"  ✓  {col_path} {label} located")
            anchor["status"] = "OK"

    # ── Overlap-Check — pro Datei alle OK-Anchors auf Überschneidung prüfen ──
    from itertools import combinations
    files_in_delivery = sorted(set(a["file"] for a in anchors))
    for file_path in files_in_delivery:
        ok_anchors = [a for a in anchors if a["file"] == file_path and a.get("status") == "OK"]
        for a, b in combinations(ok_anchors, 2):
            # Overlap wenn: start_a < end_b AND start_b < end_a
            if (a["line_start"] is not None and b["line_start"] is not None
                    and a["line_start"] < b["line_end"]
                    and b["line_start"] < a["line_end"]):
                msg = (f"  ✗  {file_path.ljust(55)}"
                       f"  [{a['index']}/{total}] ↔ [{b['index']}/{total}] OVERLAP")
                print(msg)
                errors.append(msg)
                a["status"] = "OVERLAP"
                b["status"] = "OVERLAP"

    return errors

# ── Pass 2 — Replace ─────────────────────────────────────────────────────────

def pass2(anchors: list[dict], total: int) -> None:
    """
    Pflegt jeden Anchor in die Zieldatei ein.
    Liest Datei nach jedem Replace neu — auch bei mehreren Anchors pro Datei.
    """
    print(f"\nPass 2 — Applying ...\n")

    for anchor in anchors:
        idx      = anchor["index"]
        rel_path = anchor["file"]
        abs_path = PROJECT_ROOT / rel_path
        label    = f"  [{idx}/{total}]"
        col_path = rel_path.ljust(55)

        # Frisch lesen (newline='' um rohe Zeilenenden zu erhalten)
        with open(abs_path, encoding="utf-8", errors="replace", newline="") as fh:
            raw = fh.read()
        line_end = detect_line_ending(raw)

        # Für Suche normalisieren
        norm_file = normalize_for_match(raw)
        norm_alt  = normalize_for_match(anchor["alt"])

        # Position im normalisierten Text finden → auf Original zurückrechnen
        # Strategie: ALT-Block im Original durch schrittweisen Vergleich finden
        # Zuverlässiger Weg: Original zeilenweise normalisieren und Block suchen

        alt_lines  = norm_alt.split("\n")
        file_lines_raw  = raw.splitlines(keepends=True)
        file_lines_norm = [l.rstrip("\r\n").rstrip() for l in file_lines_raw]

        # Sliding window über die normalisierten Zeilen
        start_idx = None
        for i in range(len(file_lines_norm) - len(alt_lines) + 1):
            window = file_lines_norm[i:i + len(alt_lines)]
            if window == alt_lines:
                start_idx = i
                break

        if start_idx is None:
            # Sollte durch Pass 1 ausgeschlossen sein
            print(f"  ✗  {col_path} {label} ERROR (not found in Pass 2 — skip)")
            continue

        end_idx = start_idx + len(alt_lines)

        # NEU-Block vorbereiten
        if anchor["neu"] == DELETE_MARKER:
            new_lines = []
        else:
            # NEU-Block auf Zeilenenden der Zieldatei normalisieren
            neu_normalized = anchor["neu"].replace("\r\n", "\n").replace("\r", "\n")
            neu_line_list  = neu_normalized.split("\n")
            # Trailing leere Zeile aus dem Fenced Block entfernen
            if neu_line_list and neu_line_list[-1] == "":
                neu_line_list = neu_line_list[:-1]
            new_lines = [l + line_end for l in neu_line_list]

        # Zusammenbauen
        result_lines = file_lines_raw[:start_idx] + new_lines + file_lines_raw[end_idx:]
        result       = "".join(result_lines)

        abs_path.write_text(result, encoding="utf-8", newline="")
        print(f"  ✓  {col_path} {label} applied")

# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  apply_anchors.py — Garmin Local Archive")
    print("=" * 65)
    print(f"\n  Delivery : {DELIVERY_MD}")
    print(f"  Target   : {PROJECT_ROOT}\n")

    # Prüfen ob anchor_delivery.md existiert
    if not DELIVERY_MD.is_file():
        print(f"✗  anchor_delivery.md nicht gefunden: {DELIVERY_MD}")
        sys.exit(1)

    # Prüfen ob Projektroot existiert
    if not PROJECT_ROOT.is_dir():
        print(f"✗  Projektroot nicht gefunden: {PROJECT_ROOT}")
        sys.exit(1)

    # MD parsen
    result = parse_delivery(DELIVERY_MD)
    if isinstance(result, str):
        print(result)
        sys.exit(1)

    anchors = result
    total   = len(anchors)

    if total == 0:
        print("✗  Keine Anchors in anchor_delivery.md gefunden.")
        sys.exit(1)

    # Pass 1
    errors = pass1(anchors, total)

    if errors:
        print(f"\nPass 1 FAILED — {len(errors)} error(s). No files written.\n")
        sys.exit(1)

    print(f"\nPass 1 complete — all {total} anchors located. Starting Pass 2 ...\n")
    print("-" * 65)

    # Pass 2
    pass2(anchors, total)

    print(f"\n{'=' * 65}")
    print(f"  Done — {total}/{total} anchors applied.")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
