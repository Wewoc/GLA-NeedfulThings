#!/usr/bin/env python3
"""
Step 3 — sort_summaries.py
Reads chat_summaries.md, sorts all sections chronologically by timestamp,
and writes chat_summaries_sorted.md. The original file is not modified.

Usage:
  python "Step 3 - sort_summaries.py"
"""

import re
from datetime import datetime
from config import SUMMARIES_FILE, SORTED_FILE

def parse_sections(text):
    first = text.find("\n## ")
    if first == -1:
        return text, []
    header = text[:first + 1]
    sections = []
    for raw in re.split(r"\n(?=## )", text[first + 1:]):
        raw = raw.strip()
        if not raw:
            continue
        ts = None
        m = re.search(r"\*(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\*", raw)
        if m:
            try:
                ts = datetime.strptime(m.group(1), "%d.%m.%Y %H:%M")
            except ValueError:
                pass
        title_m = re.match(r"## \d+ — (.+)", raw)
        sections.append({"title": title_m.group(1).strip() if title_m else "", "timestamp": ts, "raw": raw})
    return header, sections

def main():
    if not SUMMARIES_FILE.exists():
        print(f"✗ Datei nicht gefunden: {SUMMARIES_FILE.resolve()}")
        return

    print("Garmin Local Archive — Summary Sorter")
    print("=" * 40)
    text = SUMMARIES_FILE.read_text(encoding="utf-8")
    header, sections = parse_sections(text)
    print(f"  Sections gefunden : {len(sections)}")

    with_ts    = sorted([s for s in sections if s["timestamp"]], key=lambda s: s["timestamp"])
    without_ts = [s for s in sections if not s["timestamp"]]
    if without_ts:
        print(f"  Ohne Timestamp    : {len(without_ts)} — werden ans Ende gestellt")

    lines = [header.rstrip(), ""]
    for i, s in enumerate(with_ts + without_ts, start=1):
        raw = re.sub(r"^## \d+ — ", f"## {i:03d} — ", s["raw"], count=1)
        lines += [raw, ""]

    # Insert sort note into header
    header_lines = header.splitlines()
    insert_at = max((j for j, l in enumerate(header_lines) if l.startswith("*")), default=0)
    header_lines.insert(insert_at + 1, f"*Chronologisch sortiert: {datetime.now().strftime('%d.%m.%Y %H:%M')}*  ")
    lines[0] = "\n".join(header_lines)

    SORTED_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✓ Output          : {SORTED_FILE.resolve()}")

if __name__ == "__main__":
    main()
