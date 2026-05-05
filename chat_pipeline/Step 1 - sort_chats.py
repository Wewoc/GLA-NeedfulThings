#!/usr/bin/env python3
"""
Step 1 — sort_chats.py
Sorts exported Claude chat JSON files by label prefix into a subfolder.

Usage:
  1. Set SEARCH_LABEL and INPUT_DIR in config.py
  2. Run: python "Step 1 - sort_chats.py"

Matching chats are copied to SORTED_DIR. Non-matching chats are not touched.
"""

import json
import shutil
from config import SEARCH_LABEL, INPUT_DIR, SORTED_DIR, _safe_name

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    json_files = list(INPUT_DIR.glob("*.json"))

    if not json_files:
        print(f"✗ No JSON files found in: {INPUT_DIR.resolve()}")
        return

    print(f"Garmin Local Archive — Chat Sorter")
    print(f"{'=' * 40}")
    print(f"  Search label : '{SEARCH_LABEL}'")
    print(f"  Input folder : {INPUT_DIR.resolve()}")
    print(f"  Output folder: {SORTED_DIR.resolve()}")
    print(f"  Files found  : {len(json_files)}")
    print()

    matched = skipped = errors = 0
    SORTED_DIR.mkdir(parents=True, exist_ok=True)

    for path in sorted(json_files):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))

            if isinstance(data, list):
                for i, chat in enumerate(data):
                    label = chat.get("name") or chat.get("title") or chat.get("chat_title") or ""
                    if label.startswith(SEARCH_LABEL):
                        safe_label = _safe_name(label[:60])
                        dest = SORTED_DIR / f"{i:04d}_{safe_label}.json"
                        dest.write_text(json.dumps(chat, indent=2, ensure_ascii=False), encoding="utf-8")
                        print(f"  ✓ Match : [{i:04d}] {label}")
                        matched += 1
                    else:
                        skipped += 1
                continue

            label = data.get("name") or data.get("title") or data.get("chat_title") or ""
            if label.startswith(SEARCH_LABEL):
                shutil.copy2(path, SORTED_DIR / path.name)
                print(f"  ✓ Match : {path.name} — {label}")
                matched += 1
            else:
                skipped += 1

        except Exception as e:
            print(f"  ✗ Error reading {path.name}: {e}")
            errors += 1

    print()
    print(f"{'=' * 40}")
    print(f"  Matched : {matched}")
    print(f"  Skipped : {skipped}")
    if errors:
        print(f"  Errors  : {errors}")
    print()
    if matched:
        print(f"  → Output: {SORTED_DIR.resolve()}")
    else:
        print(f"  → No matching chats found for label: '{SEARCH_LABEL}'")


if __name__ == "__main__":
    main()
