#!/usr/bin/env python3
"""
sort_gemini_chats.py

Sorts exported Gemini MD files chronologically based on the export
timestamp in the filename. Gemini exports chats top-to-bottom
(newest first) — the highest timestamp = last exported = oldest chat.

Duplicates (same title, slightly different timestamp due to format
variation) are detected and only copied once.

Output: gemini_001_Title.md, gemini_002_Title.md ...

Usage:
    python sort_gemini_chats.py
    python sort_gemini_chats.py --source ./gemini_gla_export --dest ./gemini_sorted --dry-run
"""

import argparse
import re
import shutil
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

_HERE          = Path(__file__).parent
DEFAULT_SOURCE = str(_HERE / "gemini_gla_export")
DEFAULT_DEST   = str(_HERE / "gemini_sorted")


def parse_args():
    p = argparse.ArgumentParser(description="Sort Gemini chats chronologically.")
    p.add_argument("--source",  default=DEFAULT_SOURCE)
    p.add_argument("--dest",    default=DEFAULT_DEST)
    p.add_argument("--dry-run", action="store_true", help="Preview only, do not copy")
    return p.parse_args()


# Extract timestamp from filename.
# Supports: 20260531_140428 and 2026-05-31_140428
TS_RE = re.compile(r'(\d{4}-?\d{2}-?\d{2})_(\d{6})')


def get_timestamp(fname: str) -> str:
    m = TS_RE.search(fname)
    if m:
        date = m.group(1).replace('-', '')
        time = m.group(2)
        return f"{date}_{time}"
    return "99999999_999999"


def extract_title(fname: str) -> str:
    """Extract title from filename (everything before '_-_Google_Gemini')."""
    name = Path(fname).stem
    name = name.replace('_', ' ')
    for sep in [' -  Google Gemini', ' - Google Gemini']:
        if sep in name:
            name = name[:name.index(sep)]
            break
    return name.strip()


def safe_filename(title: str) -> str:
    """Convert title into a safe filename."""
    title = re.sub(r'[\\/:*?"<>|]', '_', title)
    title = re.sub(r'[\s_]+', '_', title)
    title = title.strip('._')
    return title[:80] if title else 'unknown'


def normalize_for_dedup(title: str) -> str:
    """Normalize title for duplicate detection."""
    t = title.lower()
    t = re.sub(r'[\s_\-]+', ' ', t)
    t = re.sub(r'[^\w\s]', '', t, flags=re.UNICODE)
    return t.strip()


def main():
    args = parse_args()
    source_dir = Path(args.source)
    dest_dir   = Path(args.dest)

    print("=" * 60)
    print("Gemini Chat Sorter (timestamp-based)")
    print(f"  Source  : {source_dir}")
    print(f"  Dest    : {dest_dir}")
    print(f"  Dry-run : {args.dry_run}")
    print("=" * 60)

    if not source_dir.exists():
        print(f"[x] Source folder not found: {source_dir}")
        return

    md_files = list(source_dir.glob("*.md"))
    print(f"\n[1] {len(md_files)} MD files found")

    # Higher timestamp = exported later = oldest chat → sort descending
    file_data = []
    for f in md_files:
        ts    = get_timestamp(f.name)
        title = extract_title(f.name)
        file_data.append((ts, title, f))

    file_data.sort(key=lambda x: x[0], reverse=True)

    # Duplicate detection (same normalized title)
    print("\n[2] Duplicate detection...")
    seen_titles = {}
    skipped = []

    for ts, title, fpath in file_data:
        norm = normalize_for_dedup(title)
        if norm in seen_titles:
            prev_ts = seen_titles[norm][0]
            if ts > prev_ts:
                skipped.append(seen_titles[norm])
                seen_titles[norm] = (ts, title, fpath)
            else:
                skipped.append((ts, title, fpath))
        else:
            seen_titles[norm] = (ts, title, fpath)

    deduped = sorted(seen_titles.values(), key=lambda x: x[0], reverse=True)

    print(f"    Original  : {len(file_data)}")
    print(f"    Duplicates: {len(skipped)}")
    print(f"    Remaining : {len(deduped)}")

    if skipped:
        print("\n    Skipped duplicates:")
        for ts, title, _ in skipped:
            print(f"      [{ts}] {title}")

    if not args.dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[3] Chronological order (oldest first):")
    print("-" * 60)

    for i, (ts, title, src_file) in enumerate(deduped, 1):
        safe = safe_filename(title)
        new_name  = f"gemini_{i:03d}_{safe}.md"
        dest_file = dest_dir / new_name

        print(f"  {i:3d}. [{ts}] {title[:52]}")
        print(f"       → {new_name}")

        if not args.dry_run:
            shutil.copy2(src_file, dest_file)

    print("\n" + "=" * 60)
    action = "Dry-run — nothing copied" if args.dry_run else f"Copied to {dest_dir}"
    print(f"Done: {len(deduped)} files | {action}")


if __name__ == "__main__":
    main()
