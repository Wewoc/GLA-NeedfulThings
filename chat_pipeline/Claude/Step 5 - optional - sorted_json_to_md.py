#!/usr/bin/env python3
"""
Step 5 (optional) — sorted_json_to_md.py
Converts sorted chat JSON files to individual Markdown files.

Usage:
  python "Step 5 - optional - sorted_json_to_md.py"
"""

import json
from datetime import datetime
from config import SORTED_DIR, MD_EXPORT_DIR

def format_ts(ts):
    if not ts: return ""
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except:
        return str(ts)

def convert(path):
    try:
        data     = json.loads(path.read_text(encoding="utf-8"))
        title    = data.get("title") or data.get("name") or path.stem
        messages = data.get("messages") or data.get("chat_messages") or data.get("conversation")
        if not messages or not isinstance(messages, list):
            return False
        lines = [f"# {title}\n", f"*Datei: {path.name}*\n", "---\n"]
        for msg in messages:
            role    = str(msg.get("sender") or msg.get("role") or "").lower()
            ts_str  = f" *({format_ts(msg.get('created_at') or msg.get('timestamp'))})*" if msg.get("created_at") or msg.get("timestamp") else ""
            content = str(msg.get("text") or msg.get("content") or "")
            prefix  = f"### 👤 Du{ts_str}" if any(x in role for x in ["human","user","mensch"]) else f"### 🤖 Assistant{ts_str}"
            lines  += [f"{prefix}\n\n{content}\n", "\n> ---\n"]
        (MD_EXPORT_DIR / f"{path.stem}.md").write_text("\n".join(lines), encoding="utf-8")
        return True
    except Exception as e:
        print(f"  ✗ {path.name}: {e}")
        return False

def main():
    MD_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_files = sorted([f for f in SORTED_DIR.glob("*.json") if f.name != "merged_chats.json"])
    print(f"Garmin Local Archive — JSON → Markdown")
    print(f"  {len(json_files)} Dateien gefunden")
    done = sum(1 for f in json_files if convert(f) and print(f"  ✓ {f.name}") is None)
    print(f"\n  ✓ {done} Markdown-Dateien erstellt in: {MD_EXPORT_DIR.resolve()}")

if __name__ == "__main__":
    main()
