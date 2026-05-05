#!/usr/bin/env python3
"""
Step 4 (optional) — merge_chats.py
Merges all sorted chat JSON files into a single file for upload.

Usage:
  python "Step 4 - optional - merge_chats.py"
"""

import json
from config import SORTED_DIR, MERGED_FILE

def main():
    json_files = sorted([f for f in SORTED_DIR.glob("*.json") if f.name != "merged_chats.json"])
    if not json_files:
        print(f"✗ No JSON files found in: {SORTED_DIR.resolve()}")
        return

    print("Garmin Local Archive — Chat Merger")
    print("=" * 40)
    chats = errors = 0

    merged = []
    for path in json_files:
        try:
            data     = json.loads(path.read_text(encoding="utf-8"))
            messages = data.get("chat_messages") or data.get("messages") or data.get("conversation") or []
            if not messages:
                print(f"  – Skip (empty): {path.name}")
                continue
            merged.append({"source_file": path.name, "title": data.get("name") or data.get("title") or path.stem, "messages": messages})
            print(f"  ✓ Merged: {path.name} ({len(messages)} messages)")
            chats += 1
        except Exception as e:
            print(f"  ✗ Error: {path.name}: {e}")
            errors += 1

    MERGED_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    size_kb = MERGED_FILE.stat().st_size / 1024
    print(f"\n{'=' * 40}")
    print(f"  Chats merged : {chats}")
    if errors: print(f"  Errors       : {errors}")
    print(f"  Output size  : {size_kb:.0f} KB")
    print(f"  Output       : {MERGED_FILE.resolve()}")
    if size_kb > 30000:
        print(f"  ⚠ File is large — may need splitting for upload.")

if __name__ == "__main__":
    main()
