#!/usr/bin/env python3
"""
run_anonymize.py — needfull things / menu
Anonymizes all JSON files in the target folder.

Input:  target folder (sys.argv[1]) — all *.json files directly in it
Output: target/anonymized/         on first run
        target/anonymized_02/      if anonymized/ already exists
        target/anonymized_03/      etc.

Usage (context menu):
    python run_anonymize.py "D:\\some\\folder"

Usage (direct):
    python run_anonymize.py          → uses current working directory
"""

import json
import sys
from pathlib import Path


# ── Anonymizer (same logic as anonymize_json.py) ──────────────────────────────

def anonymize(obj):
    if isinstance(obj, dict):
        return {k: anonymize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        if not obj:
            return []
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


# ── Numbered output folder ────────────────────────────────────────────────────

def next_output_dir(target: Path) -> Path:
    base = target / "anonymized"
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = target / f"anonymized_{n:02d}"
        if not candidate.exists():
            return candidate
        n += 1


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    target = target.resolve()

    print()
    print("=================================================================")
    print("  Anonymize JSONs -- needfull things")
    print("=================================================================")
    print()
    print(f"  Folder : {target}")

    if not target.exists() or not target.is_dir():
        print(f"\n  ERROR: Folder not found: {target}")
        sys.exit(1)

    json_files = sorted(target.glob("*.json"))
    if not json_files:
        print("\n  No JSON files found in this folder.")
        print("  (Only files directly in the folder are processed, not subfolders.)")
        sys.exit(0)

    output_dir = next_output_dir(target)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Output : {output_dir}")
    print()

    ok = 0
    for input_path in json_files:
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

        size_in  = input_path.stat().st_size / 1024
        size_out = output_path.stat().st_size / 1024
        print(f"  ✓ {input_path.name}  ({size_in:.1f} KB → {size_out:.1f} KB)")
        ok += 1

    print()
    print(f"  Done. {ok}/{len(json_files)} files anonymized.")
    print(f"  Output: {output_dir}")
    print()
    print("=================================================================")


if __name__ == "__main__":
    main()
