"""
apply_checkpoint.py — Wendet einen vorhandenen Checkpoint direkt auf die JSON-Dateien an.

Liest:  .filter3_checkpoint_{mindset}.json
Schreibt: terminology/{mindset}/de.json + en.json (gefiltert)
Backup wird vorher angelegt.

Aufruf (aus dem Terminologie-Engine Ordner):
  python apply_checkpoint.py --mindset technical --dir ..\terminology
"""

import argparse
import json
import shutil
import time
from pathlib import Path

def apply(mindset: str, terminology_dir: Path, script_dir: Path) -> None:
    checkpoint_path = script_dir / f".filter3_checkpoint_{mindset}.json"

    if not checkpoint_path.exists():
        print(f"[FEHLER] Checkpoint nicht gefunden: {checkpoint_path}")
        return

    cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    kept_codes = set(cp["kept_codes"])
    completed  = cp["completed_batches"]
    total      = cp["total_pairs"]

    print(f"[{mindset}] Checkpoint geladen:")
    print(f"  Abgeschlossene Batches: {completed}")
    print(f"  Gesamtpaare:            {total}")
    print(f"  Behalten (kept_codes):  {len(kept_codes)}")

    de_path = terminology_dir / mindset / "de.json"
    en_path = terminology_dir / mindset / "en.json"

    if not de_path.exists() or not en_path.exists():
        print(f"[FEHLER] JSON-Dateien nicht gefunden: {de_path}")
        return

    de_data = json.loads(de_path.read_text(encoding="utf-8"))
    en_data = json.loads(en_path.read_text(encoding="utf-8"))

    print(f"  Eintraege vor Filter:   {len(de_data)}")

    # Backup
    backup_dir = terminology_dir / mindset / "backup"
    backup_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(de_path, backup_dir / f"de_{ts}.json")
    shutil.copy2(en_path, backup_dir / f"en_{ts}.json")
    print(f"  Backup angelegt in backup/")

    # Filter — nur kept_codes behalten
    new_de = {code: term for code, term in de_data.items() if code in kept_codes}
    new_en = {code: term for code, term in en_data.items() if code in kept_codes}

    de_path.write_text(json.dumps(new_de, ensure_ascii=False, indent=2), encoding="utf-8")
    en_path.write_text(json.dumps(new_en, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  Eintraege nach Filter:  {len(new_de)} (−{len(de_data) - len(new_de)})")
    print(f"  Hinweis: Checkpoint enthielt {completed} von {(total + 19) // 20} Batches")

    if completed < (total + 19) // 20:
        remaining = (total + 19) // 20 - completed
        print(f"  WARNUNG: {remaining} Batches wurden nicht validiert — ")
        print(f"  diese Eintraege fehlen in kept_codes und wurden entfernt.")
        print(f"  Empfehlung: restliche Batches mit validate.bat nachholen.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mindset", required=True)
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    apply(args.mindset, args.dir.resolve(), script_dir)
