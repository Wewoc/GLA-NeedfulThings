"""
apply_anchors.py — Needful Things
Applies Claude-delivered anchor blocks to project files automatically.

Flow:
  Pass 1 — locate every ALT block, run through all of them, collect errors
  Pass 2 — only if Pass 1 was 100% successful: apply all NEU blocks

Call:   python apply_anchors.py
Input:  anchor_delivery.md (in the same folder as this script)
Target: ../my_project/ (relative to the script location — set PROJECT_ROOT below)

v1.6.5.5 fix: the FENCE regex now requires the closing fence to have the
same number of backticks as the opening one (backreference \1) —
previously any triple-backtick sequence was accepted as the end, which
silently truncated NEU blocks that contained embedded ```python code
examples (no error, no notice — just a match that was too short). Cause +
reproduction: session v1.6.5.5, documentation automation.

v1.6.6 change: the v1.6.5.5 fix only protects when the outer wrapper
fence has more backticks than any fence inside the block content — that
had to be observed manually when writing the delivery and was regularly
overlooked for documentation blocks with embedded ``` examples (same
symptom as above: silently truncated or misassigned content, no error).
New, preferred way: unique sentinel markers <<<ALT>>>/<<<ALT_END>>> and
<<<NEU>>>/<<<NEU_END>>>, which can never collide with Markdown/code fences
in the content, because they are searched by exact string instead of by a
matching closing fence. Old, plain backtick-fence deliveries are still
supported as a fallback (backward compatibility) — markers are tried
first, the old FENCE logic only applies when none are present.
"""

from pathlib import Path
import re
import sys

# ── Pfade ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent.resolve()
PROJECT_ROOT = (SCRIPT_DIR / "../my_project").resolve()   # adjust to your project
DELIVERY_MD  = SCRIPT_DIR / "anchor_delivery.md"

DELETE_MARKER = "#DELETE"

# ── Parser ───────────────────────────────────────────────────────────────────

def parse_delivery(md_path: Path) -> list[dict] | str:
    """
    Reads anchor_delivery.md and returns a list of anchor dicts.
    On a parse error: a string with the error message.

    Each dict:
        file  — path relative to the project root (str)
        alt   — ALT block content (str, raw from the MD)
        neu   — NEU block content (str, raw) or DELETE_MARKER
        index — global index (1-based, set after parsing)
    """
    text = md_path.read_text(encoding="utf-8")

    # Fenced code block: (`{3,})optional_lang\n...\n<same number of backticks>
    # Backreference \1 enforces: closing fence length == opening fence length.
    # This allows nested code blocks in the NEU content (e.g. an
    # embedded ```python example), as long as the outer wrapper fence
    # is longer (e.g. ````) than any inner fence in the content.
    FENCE = re.compile(r"^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$", re.DOTALL | re.MULTILINE)

    # Marker-based extraction (preferred, see the v1.6.6 note above).
    # Exact sentinel lines instead of counting backticks — never collides with
    # nested fences in the block content.
    ALT_MARKER = re.compile(r"<<<ALT>>>[ \t]*\n(.*?)\n[ \t]*<<<ALT_END>>>", re.DOTALL)
    NEU_MARKER = re.compile(r"<<<NEU>>>[ \t]*\n(.*?)\n[ \t]*<<<NEU_END>>>", re.DOTALL)

    def extract_block(section_text, marker_re):
        """Get the block content — first via sentinel marker, otherwise fence fallback."""
        m = marker_re.search(section_text)
        if m:
            return m.group(1)
        m = FENCE.search(section_text)
        if m:
            return m.group(2)
        return None

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
            errors.append(f"  ✗  {file_path} — ALT/NEU count does not match")
            continue

        for alt_pos, neu_pos in zip(alt_positions, neu_positions):
            # Extract the ALT block
            alt_section = body[alt_pos:neu_pos]
            alt_content = extract_block(alt_section, ALT_MARKER)
            if alt_content is None:
                errors.append(f"  ✗  {file_path} — ALT block found without marker/fence")
                continue

            # Extract the NEU block (up to the next ## FILE: / ### ALT or the end)
            next_boundary = len(body)
            for pos in alt_positions:
                if pos > neu_pos:
                    next_boundary = pos
                    break
            neu_section = body[neu_pos:next_boundary]
            neu_content = extract_block(neu_section, NEU_MARKER)
            if neu_content is None:
                errors.append(f"  ✗  {file_path} — NEU block found without marker/fence")
                continue

            # Empty NEU block without #DELETE → error
            neu_stripped = neu_content.strip()
            if neu_stripped == "":
                errors.append(f"  ✗  {file_path} — NEU block is empty (use #DELETE for a deletion)")
                continue

            # Normalize #DELETE
            if neu_stripped == DELETE_MARKER:
                neu_content = DELETE_MARKER

            anchors.append({
                "file"  : file_path,
                "alt"   : alt_content,
                "neu"   : neu_content,
                "index" : 0,  # set below
            })

    if errors:
        return "Parsefehler:\n" + "\n".join(errors)

    # Global numbering
    for i, anchor in enumerate(anchors, start=1):
        anchor["index"] = i

    return anchors

# ── Normalization for comparison ──────────────────────────────────────────────

def normalize_for_match(text: str) -> str:
    """
    For comparison only — the original stays untouched.
    - CRLF → LF
    - Strip trailing whitespace per line
    - Strip leading/trailing blank lines
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    # Remove leading blank lines
    while lines and lines[0] == "":
        lines.pop(0)
    # Remove trailing blank lines
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)

# ── Detect line endings ───────────────────────────────────────────────────

def detect_line_ending(raw: str) -> str:
    """Returns '\r\n' or '\n' — whichever dominates in the file."""
    crlf = raw.count("\r\n")
    lf   = raw.count("\n") - crlf
    return "\r\n" if crlf >= lf else "\n"

# ── Pass 1 — Search ───────────────────────────────────────────────────────────

def pass1(anchors: list[dict], total: int) -> list[dict]:
    """
    Searches every ALT block in the target file.
    Returns the list of errors (empty = 100% OK).
    Sets anchor['status'] for every anchor.
    """
    # Collect file paths for the header
    files = sorted(set(a["file"] for a in anchors))
    print(f"\nPass 1 — Searching {total} anchors in {len(files)} files ...\n")

    errors = []

    for anchor in anchors:
        idx       = anchor["index"]
        rel_path  = anchor["file"]
        abs_path  = PROJECT_ROOT / rel_path
        label     = f"  [{idx}/{total}]"
        col_path  = rel_path.ljust(55)

        # Does the file exist?
        if not abs_path.is_file():
            msg = f"  ✗  {col_path} {label} FILE NOT FOUND"
            print(msg)
            errors.append(msg)
            anchor["status"] = "FILE_NOT_FOUND"
            continue

        # Read the file
        raw = abs_path.read_text(encoding="utf-8", errors="replace")

        # Normalize for comparison
        norm_file = normalize_for_match(raw)
        norm_alt  = normalize_for_match(anchor["alt"])

        # ── Idempotence check ─────────────────────────────────────────────
        # If NEU (not #DELETE) is already completely present in the document,
        # this anchor was applied before — e.g. because NEU = ALT + appended
        # text and a second run would otherwise duplicate the addition. Not an
        # error, but a skip: the anchor is taken out of the overlap check and
        # out of Pass 2.
        if anchor["neu"] != DELETE_MARKER:
            norm_neu = normalize_for_match(anchor["neu"])
            neu_present = bool(norm_neu) and norm_file.count(norm_neu) > 0
            # If NEU contains ALT (pure append), NEU being present in the
            # document is enough. Otherwise ALT must be gone as well: while ALT
            # is still there, NEU is only a part of ALT (trimming) or happens to
            # occur elsewhere — the anchor has not been applied yet.
            if neu_present and (norm_alt in norm_neu or norm_file.count(norm_alt) == 0):
                msg = f"  ⏭  {col_path} {label} ALREADY APPLIED — skip"
                print(msg)
                anchor["status"] = "ALREADY_APPLIED"
                continue

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
            # Determine the position via sliding window — for the overlap check
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

    # ── Overlap check — check all OK anchors per file for overlaps ──
    from itertools import combinations
    files_in_delivery = sorted(set(a["file"] for a in anchors))
    for file_path in files_in_delivery:
        ok_anchors = [a for a in anchors if a["file"] == file_path and a.get("status") == "OK"]
        for a, b in combinations(ok_anchors, 2):
            # Overlap if: start_a < end_b AND start_b < end_a
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
    Applies every anchor to the target file.
    Re-reads the file after every replace — also with several anchors per file.
    """
    print(f"\nPass 2 — Applying ...\n")

    for anchor in anchors:
        idx      = anchor["index"]
        rel_path = anchor["file"]
        abs_path = PROJECT_ROOT / rel_path
        label    = f"  [{idx}/{total}]"
        col_path = rel_path.ljust(55)

        if anchor.get("status") == "ALREADY_APPLIED":
            print(f"  ⏭  {col_path} {label} skipped (already applied)")
            continue

        # Read fresh (newline='' to preserve the raw line endings)
        with open(abs_path, encoding="utf-8", errors="replace", newline="") as fh:
            raw = fh.read()
        line_end = detect_line_ending(raw)

        # Normalize for the search
        norm_file = normalize_for_match(raw)
        norm_alt  = normalize_for_match(anchor["alt"])

        # Find the position in the normalized text → map back to the original
        # Strategy: find the ALT block in the original by stepwise comparison
        # Reliable way: normalize the original line by line and search for the block

        alt_lines  = norm_alt.split("\n")
        file_lines_raw  = raw.splitlines(keepends=True)
        file_lines_norm = [l.rstrip("\r\n").rstrip() for l in file_lines_raw]

        # Sliding window over the normalized lines
        start_idx = None
        for i in range(len(file_lines_norm) - len(alt_lines) + 1):
            window = file_lines_norm[i:i + len(alt_lines)]
            if window == alt_lines:
                start_idx = i
                break

        if start_idx is None:
            # Should have been ruled out by Pass 1
            print(f"  ✗  {col_path} {label} ERROR (not found in Pass 2 — skip)")
            continue

        end_idx = start_idx + len(alt_lines)

        # Prepare the NEU block
        if anchor["neu"] == DELETE_MARKER:
            new_lines = []
        else:
            # Normalize the NEU block to the target file's line endings
            neu_normalized = anchor["neu"].replace("\r\n", "\n").replace("\r", "\n")
            neu_line_list  = neu_normalized.split("\n")
            # Remove the trailing empty line from the fenced block
            if neu_line_list and neu_line_list[-1] == "":
                neu_line_list = neu_line_list[:-1]
            new_lines = [l + line_end for l in neu_line_list]

        # Assemble
        result_lines = file_lines_raw[:start_idx] + new_lines + file_lines_raw[end_idx:]
        result       = "".join(result_lines)

        abs_path.write_text(result, encoding="utf-8", newline="")
        print(f"  ✓  {col_path} {label} applied")

# ── Main program ─────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  apply_anchors.py — Needful Things")
    print("=" * 65)
    print(f"\n  Delivery : {DELIVERY_MD}")
    print(f"  Target   : {PROJECT_ROOT}\n")

    # Check that anchor_delivery.md exists
    if not DELIVERY_MD.is_file():
        print(f"✗  anchor_delivery.md not found: {DELIVERY_MD}")
        sys.exit(1)

    # Check that the project root exists
    if not PROJECT_ROOT.is_dir():
        print(f"✗  Project root not found: {PROJECT_ROOT}")
        sys.exit(1)

    # Parse the MD
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

    skipped = sum(1 for a in anchors if a.get("status") == "ALREADY_APPLIED")
    to_apply = total - skipped

    if skipped:
        print(f"\nPass 1 complete — {to_apply}/{total} anchors to apply, "
              f"{skipped} already applied (skip). Starting Pass 2 ...\n")
    else:
        print(f"\nPass 1 complete — all {total} anchors located. Starting Pass 2 ...\n")
    print("-" * 65)

    # Pass 2
    pass2(anchors, total)

    print(f"\n{'=' * 65}")
    if skipped:
        print(f"  Done — {to_apply}/{total} anchors applied, {skipped} skipped (already applied).")
    else:
        print(f"  Done — {total}/{total} anchors applied.")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
