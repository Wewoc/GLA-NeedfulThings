"""
apply_anchors.py — needfull things
Automated application of Claude-delivered anchor blocks.

Process:
  Pass 1 — Search all ALT blocks, run completely, collect errors
  Pass 2 — Only if Pass 1 is 100% successful: apply all NEU blocks

Usage: python apply_anchors.py
Input:  anchor_delivery.md (same directory as this script)
Target: PROJECT_ROOT (see configuration below)
"""

from pathlib import Path
import re
import sys

# ── Configuration ───────────────────────────────────────────────────────────────
#
# Path to the target project directory — relative to the location of this script.
# Examples:
#   "../my_project"          → sibling folder next to change_script/
#   "../../src/my_project"   → two levels up, then into src/
#
# Alternatively, PROJECT_ROOT can be set as an absolute path:
#   PROJECT_ROOT = Path("C:/Users/me/projects/my_project")

PROJECT_REL_PATH = "../my_project"   # ← adjust this

# ── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPT_DIR / PROJECT_REL_PATH).resolve()
DELIVERY_MD  = SCRIPT_DIR / "anchor_delivery.md"

DELETE_MARKER = "#DELETE"


# ── Parser ───────────────────────────────────────────────────────────────────

def parse_delivery(md_path: Path) -> list[dict] | str:
    """
    Reads anchor_delivery.md and returns a list of anchor dicts.
    On parse error: returns a string with the error message.

    Each dict:
        file  — relative path from project root (str)
        alt   — ALT block content (str, raw from MD)
        neu   — NEU block content (str, raw) or DELETE_MARKER
        index — global index (1-based, set after parsing)
    """
    text = md_path.read_text(encoding="utf-8")

    # Fenced code block: ```optional_lang\n...\n```
    FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

    anchors = []
    errors  = []

    # Split into ## FILE: sections
    sections = re.split(r"^## FILE:\s*", text, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue

        lines     = section.splitlines(keepends=True)
        file_path = lines[0].strip()
        body      = "".join(lines[1:])

        # Find ALT / NEU blocks within the section
        # Multiple ALT/NEU pairs per file are allowed
        alt_positions = [m.start() for m in re.finditer(r"^### ALT", body, re.MULTILINE)]
        neu_positions = [m.start() for m in re.finditer(r"^### NEU", body, re.MULTILINE)]

        if len(alt_positions) != len(neu_positions):
            errors.append(f"  ✗  {file_path} — ALT/NEU count mismatch")
            continue

        for alt_pos, neu_pos in zip(alt_positions, neu_positions):
            # Extract ALT block
            alt_section = body[alt_pos:neu_pos]
            alt_match   = FENCE.search(alt_section)
            if not alt_match:
                errors.append(f"  ✗  {file_path} — ALT block missing code fence")
                continue
            alt_content = alt_match.group(1)

            # Extract NEU block (up to next ## FILE: / ### ALT or end of body)
            next_boundary = len(body)
            for pos in alt_positions:
                if pos > neu_pos:
                    next_boundary = pos
                    break
            neu_section = body[neu_pos:next_boundary]
            neu_match   = FENCE.search(neu_section)
            if not neu_match:
                errors.append(f"  ✗  {file_path} — NEU block missing code fence")
                continue
            neu_content = neu_match.group(1)

            # Empty NEU block without #DELETE → error
            neu_stripped = neu_content.strip()
            if neu_stripped == "":
                errors.append(f"  ✗  {file_path} — NEU block is empty (use #DELETE to remove a block)")
                continue

            # Normalise #DELETE
            if neu_stripped == DELETE_MARKER:
                neu_content = DELETE_MARKER

            anchors.append({
                "file"  : file_path,
                "alt"   : alt_content,
                "neu"   : neu_content,
                "index" : 0,  # set below
            })

    if errors:
        return "Parse errors:\n" + "\n".join(errors)

    # Global numbering
    for i, anchor in enumerate(anchors, start=1):
        anchor["index"] = i

    return anchors

# ── Normalisation for comparison ────────────────────────────────────────────

def normalize_for_match(text: str) -> str:
    """
    For comparison only — original remains untouched.
    - CRLF → LF
    - Strip trailing whitespace per line
    - Strip leading/trailing blank lines
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    # Strip leading blank lines
    while lines and lines[0] == "":
        lines.pop(0)
    # Strip trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)

# ── Line ending detection ────────────────────────────────────────────────────

def detect_line_ending(raw: str) -> str:
    """Returns '\r\n' or '\n' — whichever dominates in the file."""
    crlf = raw.count("\r\n")
    lf   = raw.count("\n") - crlf
    return "\r\n" if crlf >= lf else "\n"

# ── Pass 1 — Search ─────────────────────────────────────────────────────────

def pass1(anchors: list[dict], total: int) -> list[dict]:
    """
    Locates every ALT block in the target file.
    Returns a list of errors (empty = 100% OK).
    Sets anchor['status'] for each anchor.
    """
    # Collect file paths for header
    files = sorted(set(a["file"] for a in anchors))
    print(f"\nPass 1 — Searching {total} anchors in {len(files)} files ...\n")

    errors = []

    for anchor in anchors:
        idx       = anchor["index"]
        rel_path  = anchor["file"]
        abs_path  = PROJECT_ROOT / rel_path
        label     = f"  [{idx}/{total}]"
        col_path  = rel_path.ljust(55)

        # File exists?
        if not abs_path.is_file():
            msg = f"  ✗  {col_path} {label} FILE NOT FOUND"
            print(msg)
            errors.append(msg)
            anchor["status"] = "FILE_NOT_FOUND"
            continue

        # Read file
        raw = abs_path.read_text(encoding="utf-8", errors="replace")

        # Normalise for comparison
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
            # Determine position via sliding window — for overlap check
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

    # ── Overlap check — verify no OK anchors overlap within the same file ──
    from itertools import combinations
    files_in_delivery = sorted(set(a["file"] for a in anchors))
    for file_path in files_in_delivery:
        ok_anchors = [a for a in anchors if a["file"] == file_path and a.get("status") == "OK"]
        for a, b in combinations(ok_anchors, 2):
            # Overlap when: start_a < end_b AND start_b < end_a
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

# ── Pass 2 — Replace ────────────────────────────────────────────────────────

def pass2(anchors: list[dict], total: int) -> None:
    """
    Applies every anchor to the target file.
    Re-reads the file after each replace — even when multiple anchors target the same file.
    """
    print(f"\nPass 2 — Applying ...\n")

    for anchor in anchors:
        idx      = anchor["index"]
        rel_path = anchor["file"]
        abs_path = PROJECT_ROOT / rel_path
        label    = f"  [{idx}/{total}]"
        col_path = rel_path.ljust(55)

        # Fresh read (newline='' to preserve raw line endings)
        with open(abs_path, encoding="utf-8", errors="replace", newline="") as fh:
            raw = fh.read()
        line_end = detect_line_ending(raw)

        # Normalise for search
        norm_file = normalize_for_match(raw)
        norm_alt  = normalize_for_match(anchor["alt"])

        # Find position in normalised text → map back to original
        # Strategy: locate ALT block in original via line-by-line comparison
        # Reliable approach: normalise original line by line and search for the block

        alt_lines  = norm_alt.split("\n")
        file_lines_raw  = raw.splitlines(keepends=True)
        file_lines_norm = [l.rstrip("\r\n").rstrip() for l in file_lines_raw]

        # Sliding window over normalised lines
        start_idx = None
        for i in range(len(file_lines_norm) - len(alt_lines) + 1):
            window = file_lines_norm[i:i + len(alt_lines)]
            if window == alt_lines:
                start_idx = i
                break

        if start_idx is None:
            # Should have been caught by Pass 1
            print(f"  ✗  {col_path} {label} ERROR (not found in Pass 2 — skip)")
            continue

        end_idx = start_idx + len(alt_lines)

        # Prepare NEU block
        if anchor["neu"] == DELETE_MARKER:
            new_lines = []
        else:
            # Normalise NEU block to target file's line endings
            neu_normalized = anchor["neu"].replace("\r\n", "\n").replace("\r", "\n")
            neu_line_list  = neu_normalized.split("\n")
            # Remove trailing blank line from fenced block
            if neu_line_list and neu_line_list[-1] == "":
                neu_line_list = neu_line_list[:-1]
            new_lines = [l + line_end for l in neu_line_list]

        # Reassemble
        result_lines = file_lines_raw[:start_idx] + new_lines + file_lines_raw[end_idx:]
        result       = "".join(result_lines)

        abs_path.write_text(result, encoding="utf-8", newline="")
        print(f"  ✓  {col_path} {label} applied")

# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  apply_anchors.py — needfull things")
    print("=" * 65)
    print(f"\n  Delivery : {DELIVERY_MD}")
    print(f"  Target   : {PROJECT_ROOT}\n")

    # Check anchor_delivery.md exists
    if not DELIVERY_MD.is_file():
        print(f"✗  anchor_delivery.md not found: {DELIVERY_MD}")
        sys.exit(1)

    # Check project root exists
    if not PROJECT_ROOT.is_dir():
        print(f"✗  Project root not found: {PROJECT_ROOT}")
        sys.exit(1)

    # Parse delivery MD
    result = parse_delivery(DELIVERY_MD)
    if isinstance(result, str):
        print(result)
        sys.exit(1)

    anchors = result
    total   = len(anchors)

    if total == 0:
        print("✗  No anchors found in anchor_delivery.md.")
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
