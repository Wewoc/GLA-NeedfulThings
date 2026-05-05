#!/usr/bin/env python3
"""
Step 2 — summarize_chats.py
Reads sorted chat JSON files, summarizes each via Ollama,
and writes a single navigable Markdown file.

Resume-safe: already processed files are detected from the output file and skipped.
On interruption: just run again — already done chats are skipped.

Usage:
  1. Make sure Ollama is running (ollama serve)
  2. Configure MODEL in config.py
  3. Run: python "Step 2 - summarize_chats.py"

Output: chat_summaries.md — one section per chat, chronologically ordered.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from config import SORTED_DIR, SUMMARIES_FILE, OLLAMA_URL, MODEL, MAX_MESSAGES, OLLAMA_TIMEOUT, PROJECT_CONTEXT, PROMPT_LANGUAGE

# ── Prompt ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are analyzing chat histories.
Project context: {PROJECT_CONTEXT}

Summarize the chat in 5-8 sentences. Cover:
- What was the main topic or task?
- What decision was made (if any)?
- Was there a turning point, problem, or surprise?
- Which version or module was affected (if identifiable)?

Reply ONLY with the summary. No preamble, no intro, no "Here is the summary:".
Write in the language of the chat ({PROMPT_LANGUAGE})."""

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_already_done() -> set:
    done = set()
    if not SUMMARIES_FILE.exists():
        return done
    for line in SUMMARIES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("*Datei: `") and "`" in line[9:]:
            try:
                done.add(line.split("`")[1])
            except IndexError:
                pass
    return done


def ensure_header():
    if not SUMMARIES_FILE.exists():
        SUMMARIES_FILE.write_text(
            f"# Chat Summaries\n\n"
            f"*Generiert: {datetime.now().strftime('%d.%m.%Y %H:%M')}*  \n"
            f"*Modell: {MODEL}*\n\n---\n\n",
            encoding="utf-8"
        )


def append_section(section: str):
    with SUMMARIES_FILE.open("a", encoding="utf-8") as f:
        f.write(section)


def extract_messages(data: dict) -> list:
    messages = data.get("chat_messages") or data.get("messages") or data.get("conversation") or []
    return messages if isinstance(messages, list) else []


def format_ts(ts) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(ts)


def messages_to_text(messages: list) -> str:
    if not messages:
        return ""
    if MAX_MESSAGES and len(messages) > MAX_MESSAGES:
        half    = MAX_MESSAGES // 2
        trimmed = messages[:half] + messages[-half:]
        prefix  = f"[Chat truncated: {len(messages)} messages → first {half} + last {half} shown]\n\n"
    else:
        trimmed = messages
        prefix  = ""

    lines = [prefix] if prefix else []
    for msg in trimmed:
        role    = str(msg.get("sender") or msg.get("role") or "").lower()
        content = str(msg.get("text") or msg.get("content") or "").strip()
        if not content:
            continue
        speaker = "USER" if any(x in role for x in ["human", "user", "mensch"]) else "ASSISTANT"
        if len(content) > 2000:
            content = content[:2000] + "\n[... gekürzt ...]"
        lines.append(f"{speaker}: {content}\n")
    return "\n".join(lines)


def call_ollama(chat_text: str, title: str) -> str:
    prompt  = f"{SYSTEM_PROMPT}\n\n---\nChat title: {title}\n\n{chat_text}\n---\n\nSummary:"
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.3, "num_predict": 800}
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            text = json.loads(resp.read().decode("utf-8")).get("response", "").strip()
            if "<think>" in text and "</think>" in text:
                text = text[text.find("</think>") + len("</think>"):].strip()
            return text
    except urllib.error.URLError as e:
        return f"[Ollama not reachable: {e}]"
    except Exception as e:
        return f"[Error: {e}]"

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    json_files = sorted([f for f in SORTED_DIR.glob("*.json") if f.name != "merged_chats.json"])

    if not json_files:
        print(f"✗ No JSON files found in: {SORTED_DIR.resolve()}")
        return

    try:
        urllib.request.urlopen("http://localhost:11434", timeout=3)
    except Exception:
        print("✗ Ollama is not running — start it first (ollama serve)")
        return

    already_done = load_already_done()
    ensure_header()
    todo = [f for f in json_files if f.name not in already_done]

    print("Chat Summarizer")
    print("=" * 40)
    print(f"  Model           : {MODEL}")
    print(f"  Input           : {SORTED_DIR.resolve()}")
    print(f"  Output          : {SUMMARIES_FILE.resolve()}")
    print(f"  Total           : {len(json_files)}")
    print(f"  Already done    : {len(already_done)}")
    print(f"  Remaining       : {len(todo)}")
    print()

    if not todo:
        print("  ✓ All chats already summarized.")
        return

    done = errors = skipped = 0

    for i, path in enumerate(todo, start=1):
        try:
            data     = json.loads(path.read_text(encoding="utf-8"))
            title    = data.get("name") or data.get("title") or path.stem
            messages = extract_messages(data)

            if not messages:
                print(f"  – [{i:03d}/{len(todo)}] Skip (empty): {path.name}")
                skipped += 1
                continue

            first_ts   = messages[0].get("created_at") or messages[0].get("timestamp") or ""
            global_idx = len(already_done) + done + 1
            print(f"  ⏳ [{i:03d}/{len(todo)}] #{global_idx:03d} {title[:55]}", end="", flush=True)

            summary = call_ollama(messages_to_text(messages), title)
            ts_str  = format_ts(first_ts) if first_ts else ""

            append_section(
                f"## {global_idx:03d} — {title}\n\n"
                f"*Datei: `{path.name}`*"
                + (f" · *{ts_str}*" if ts_str else "")
                + f" · *{len(messages)} Nachrichten*\n\n"
                f"{summary}\n\n---\n\n"
            )
            done += 1
            print(" ✓")

        except Exception as e:
            print(f" ✗ Fehler: {e}")
            errors += 1

    print()
    print("=" * 40)
    print(f"  Summarized : {done}")
    if skipped: print(f"  Skipped    : {skipped}")
    if errors:  print(f"  Errors     : {errors}")
    print(f"  Output     : {SUMMARIES_FILE.resolve()}")


if __name__ == "__main__":
    main()