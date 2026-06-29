#!/usr/bin/env python3
"""
summarize_gemini_chats.py

Reads sorted Gemini chat MD files, summarizes each chat via Ollama,
and writes a navigable Markdown file.

Short chats (≤ CHUNK_SIZE chars): summarized directly in one step.
Long chats: Map-Reduce — chunks individually, then merge.

Resume-safe: already processed files are skipped on restart.

Usage:
  1. ollama serve
  2. python summarize_gemini_chats.py
  3. If interrupted: just restart
"""

import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────────

INPUT_DIR   = Path(__file__).parent / "gemini_sorted"
OUTPUT_FILE = Path(__file__).parent / "chat_summaries_gemini.md"

OLLAMA_URL   = "http://localhost:11434/api/generate"
CHUNK_MODEL  = "qwen2.5:7b"      # For individual chunks — fast
MERGE_MODEL  = "deepseek-r1:14b" # For final merge — stronger model
DIRECT_MODEL = "phi4:14b"        # For short chats directly

# Characters per chunk. Safe up to ~8000 for phi4:14b.
CHUNK_SIZE  = 8000

# Overlap between chunks to avoid context gaps
CHUNK_OVERLAP = 400

# ── Prompts ────────────────────────────────────────────────────────────────────

CONTEXT = """You are analyzing chats with Gemini (Google AI) from the context of the project
"Garmin Local Archive" — a local Python tool for archiving Garmin Connect health data.
Built by Timo (non-programmer) with Claude as the primary coding partner.
Gemini was used for reviews, concept evaluations, and peer feedback."""

CHUNK_PROMPT = """{context}

You are receiving PART {chunk_nr} of {total_chunks} of a longer chat.
Summarize this part in 3-5 sentences:
- What topics, questions, or problems appear?
- What decisions or insights are made?
- Which module or version is involved (if recognizable)?

Reply ONLY with the summary. No preamble.
Write in the language of the chat (German or English).

---
Chat title: {title}
Part {chunk_nr}/{total_chunks}

{chunk_text}
---

Summary part {chunk_nr}:"""

MERGE_PROMPT = """{context}

You are receiving partial summaries of a chat in chronological order.
Create a single coherent overall summary in 5-8 sentences:
- What was the main topic or task?
- What decision was made (if any)?
- Was there a turning point, problem, or surprise?
- Which module, version, or concept was involved?

Reply ONLY with the summary. No preamble.
Write in the language of the partial summaries (German or English).

---
Chat title: {title}

{partial_summaries}
---

Overall summary:"""

DIRECT_PROMPT = """{context}

Summarize the following chat in 5-8 sentences:
- What was the main topic or task?
- What decision was made (if any)?
- Was there a turning point, problem, or surprise?
- Which module, version, or concept was involved?

Reply ONLY with the summary. No preamble.
Write in the language of the chat (German or English).

---
Chat title: {title}

{chat_text}
---

Summary:"""

# ── Chunking ───────────────────────────────────────────────────────────────────

def make_chunks(text: str, size: int, overlap: int) -> list[str]:
    """
    Split text into overlapping chunks.
    Cuts at line breaks where possible.
    """
    chunks = []
    start  = 0
    length = len(text)

    while start < length:
        end = min(start + size, length)

        if end < length:
            newline = text.rfind('\n', start + size // 2, end)
            if newline != -1:
                end = newline + 1

        chunks.append(text[start:end])

        if end >= length:
            break
        start = end - overlap

    return chunks

# ── Ollama ─────────────────────────────────────────────────────────────────────

def call_ollama(prompt: str, model: str) -> str:
    payload = json.dumps({
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 800,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            text   = result.get("response", "").strip()
            if "<think>" in text and "</think>" in text:
                start = text.find("</think>")
                text  = text[start + len("</think>"):].strip()
            return text
    except urllib.error.URLError as e:
        return f"[Ollama not reachable: {e}]"
    except Exception as e:
        return f"[Error: {e}]"


def summarize_chat(content: str, title: str, global_idx: int) -> tuple[str, str]:
    """
    Create a summary for one chat.
    Returns (summary, mode).
    For map-reduce: intermediate results are written to the output file immediately.
    """
    if len(content) <= CHUNK_SIZE:
        prompt  = DIRECT_PROMPT.format(
            context=CONTEXT, title=title, chat_text=content
        )
        summary = call_ollama(prompt, DIRECT_MODEL)
        return summary, "direct"

    # Long chat — Map-Reduce
    chunks   = make_chunks(content, CHUNK_SIZE, CHUNK_OVERLAP)
    n        = len(chunks)
    partials = []

    # Write interim header immediately
    interim_header = (
        f"## {global_idx:03d} — {title}\n\n"
        f"*File: `__IN_PROGRESS__`*"
        f" · *{len(content):,} chars*"
        f" · *map-reduce ({n} chunks) — running...*\n\n"
        f"### Chunk intermediates\n\n"
    )
    append_section(interim_header)

    for idx, chunk in enumerate(chunks, 1):
        print(f"\n      Chunk {idx}/{n}", end="", flush=True)
        prompt  = CHUNK_PROMPT.format(
            context=CONTEXT,
            chunk_nr=idx,
            total_chunks=n,
            title=title,
            chunk_text=chunk,
        )
        partial = call_ollama(prompt, CHUNK_MODEL)
        partials.append(f"Part {idx}/{n}:\n{partial}")

        append_section(f"**Part {idx}/{n}:** {partial}\n\n")
        print(" ✓", end="", flush=True)

    # Merge
    print(f"\n      Merge", end="", flush=True)
    combined = "\n\n".join(partials)
    prompt   = MERGE_PROMPT.format(
        context=CONTEXT, title=title, partial_summaries=combined
    )
    summary = call_ollama(prompt, MERGE_MODEL)

    append_section(f"### Overall Summary\n\n{summary}\n\n---\n\n")
    print(" ✓", end="", flush=True)

    return summary, f"map-reduce ({n} chunks)"

# ── Resume / Output ────────────────────────────────────────────────────────────

def load_already_done() -> set:
    done = set()
    if not OUTPUT_FILE.exists():
        return done
    for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("*File: `") and "`" in line[8:]:
            try:
                fname = line.split("`")[1]
                done.add(fname)
            except IndexError:
                pass
    return done


def ensure_header():
    if not OUTPUT_FILE.exists():
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"# Garmin Local Archive — Gemini Chat Summaries\n\n"
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*  \n"
            f"*Chunk model: {CHUNK_MODEL} / Merge model: {MERGE_MODEL} / Direct model: {DIRECT_MODEL}*  \n"
            f"*Chunk size: {CHUNK_SIZE} chars*\n\n"
            f"---\n\n"
        )
        OUTPUT_FILE.write_text(header, encoding="utf-8")


def append_section(section: str):
    with OUTPUT_FILE.open("a", encoding="utf-8") as f:
        f.write(section)


def extract_title(fname: str) -> str:
    stem = Path(fname).stem
    stem = re.sub(r'^gemini_\d+_', '', stem)
    return stem.replace('_', ' ').strip()

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    md_files = sorted(INPUT_DIR.glob("gemini_*.md"))

    if not md_files:
        print(f"✗ No gemini_*.md files in: {INPUT_DIR.resolve()}")
        return

    try:
        urllib.request.urlopen("http://localhost:11434", timeout=3)
    except Exception:
        print("✗ Ollama is not running — start with: ollama serve")
        return

    already_done = load_already_done()
    ensure_header()
    todo = [f for f in md_files if f.name not in already_done]

    print("Gemini Chat Summarizer — Map-Reduce")
    print("=" * 50)
    print(f"  Chunk model      : {CHUNK_MODEL}")
    print(f"  Merge model      : {MERGE_MODEL}")
    print(f"  Direct model     : {DIRECT_MODEL}")
    print(f"  Chunk size       : {CHUNK_SIZE} chars (+{CHUNK_OVERLAP} overlap)")
    print(f"  Input            : {INPUT_DIR.resolve()}")
    print(f"  Output           : {OUTPUT_FILE.resolve()}")
    print(f"  Total            : {len(md_files)}")
    print(f"  Already done     : {len(already_done)}")
    print(f"  Remaining        : {len(todo)}")
    print()

    if not todo:
        print("  ✓ All chats already summarized.")
        return

    done = errors = skipped = 0

    for i, path in enumerate(todo, start=1):
        try:
            content = path.read_text(encoding="utf-8", errors="replace").strip()

            if not content:
                print(f"  – [{i:03d}/{len(todo)}] Skip (empty): {path.name}")
                skipped += 1
                continue

            title      = extract_title(path.name)
            global_idx = len(already_done) + done + 1
            char_count = len(content)

            print(
                f"  ⏳ [{i:03d}/{len(todo)}] #{global_idx:03d} "
                f"{title[:45]} ({char_count:,} chars)",
                end="", flush=True
            )

            summary, mode = summarize_chat(content, title, global_idx)

            # For map-reduce: already written inline
            # For direct: write now
            if not mode.startswith("map-reduce"):
                section = (
                    f"## {global_idx:03d} — {title}\n\n"
                    f"*File: `{path.name}`*"
                    f" · *{char_count:,} chars*"
                    f" · *{mode}*\n\n"
                    f"{summary}\n\n"
                    f"---\n\n"
                )
                append_section(section)
            done += 1
            print(f" ✓ [{mode}]")

        except Exception as e:
            print(f" ✗ Error: {e}")
            errors += 1

    print()
    print("=" * 50)
    print(f"  Newly summarized : {done}")
    if skipped: print(f"  Skipped          : {skipped}")
    if errors:  print(f"  Errors           : {errors}")
    print(f"  Output           : {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
