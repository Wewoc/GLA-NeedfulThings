#!/usr/bin/env python3
"""
anonymize_json.py

Liest alle JSON-Dateien aus dem Unterordner ./json und ersetzt alle Werte
durch Platzhalter. Struktur und Feldnamen bleiben erhalten.
Ausgabe: ./json/export/

Verwendung:
    python anonymize_json.py
"""

import json
import sys
from pathlib import Path


def anonymize(obj):
    """Ersetzt alle Werte rekursiv durch Platzhalter."""
    if isinstance(obj, dict):
        return {k: anonymize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        if not obj:
            return []
        # Nur erstes Element anonymisieren — Struktur erkennbar, Datei klein
        return [anonymize(obj[0])]
    elif isinstance(obj, bool):
        return False
    elif isinstance(obj, (int, float)):
        return 0
    elif isinstance(obj, str):
        return "..."
    elif obj is None:
        return None
    return obj


def main():
    input_dir  = Path(__file__).parent / "json"
    output_dir = input_dir / "export"

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Fehler: Ordner nicht gefunden: {input_dir}")
        sys.exit(1)

    output_dir.mkdir(exist_ok=True)

    json_files = list(input_dir.glob("*.json"))
    if not json_files:
        print("Keine JSON-Dateien gefunden.")
        sys.exit(0)

    for input_path in sorted(json_files):
        output_path = output_dir / input_path.name
        try:
            with open(input_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  ✗ {input_path.name}: {e}")
            continue

        anonymized = anonymize(data)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(anonymized, f, ensure_ascii=False, indent=2)

        print(f"  ✓ {input_path.name} ({input_path.stat().st_size / 1024:.1f} KB → {output_path.stat().st_size / 1024:.1f} KB)")

    print(f"\nFertig. {len(json_files)} Dateien → {output_dir}")


if __name__ == "__main__":
    main()
