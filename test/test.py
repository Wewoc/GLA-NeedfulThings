"""
test/test.py — Quality test runner for LocalTranslate

Reads:    test/test_config.csv
Sources:  test/source/*.md
Writes:   test/results/DATUM_S1_S2_source_target_mindset.md

Each result file contains:
  - Run metadata
  - Relevant perf.csv rows (filtered by timestamp range)
  - Source text
  - S1 translation
  - S2 translation (if configured)

Requires LocalTranslate server running on http://127.0.0.1:8000
"""

import csv
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).resolve().parent
SOURCE_DIR  = SCRIPT_DIR / "source"
RESULTS_DIR = SCRIPT_DIR / "results"
CONFIG_FILE = SCRIPT_DIR / "test_config.csv"

# perf.csv is two levels up in logs/
PERF_LOG = SCRIPT_DIR.parent / "logs" / "perf.csv"

SERVER_URL  = "http://127.0.0.1:8000"

# ── Helpers ───────────────────────────────────────────────────────────────────

def check_server() -> bool:
    try:
        urllib.request.urlopen(f"{SERVER_URL}/config", timeout=3)
        return True
    except Exception:
        return False


def prepare_chunks(text: str) -> list[str]:
    """Ruft /translate/chunks/prepare auf — identisch mit dem UI."""
    payload = json.dumps({"text": text, "engine": "ollama"}).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/translate/chunks/prepare",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data.get("chunks", [text])


def set_model(model: str) -> None:
    payload = json.dumps({"model": model}).encode()
    req = urllib.request.Request(
        f"{SERVER_URL}/ollama/set_model",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def translate_chunk(
    text: str,
    src_lang: str,
    tgt_lang: str,
    mindset: str,
    s2_model: str,
    chunk_index: int = 0,
    context: str = "",
) -> dict:
    """
    Calls /translate/chunk directly — same path as the UI chunking loop.
    Returns {"translation": str} or raises on error.
    """
    payload = json.dumps({
        "text":        text,
        "source_lang": src_lang.upper(),
        "target_lang": tgt_lang.upper(),
        "engine":      "ollama",
        "context":     context,
        "mindset":     mindset,
        "s2_model":    s2_model if s2_model and s2_model != "—" else "",
        "chunk_index": chunk_index,
    }).encode()

    req = urllib.request.Request(
        f"{SERVER_URL}/translate/chunk",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def read_perf_rows(since: datetime, until: datetime) -> list[str]:
    """
    Reads perf.csv and returns rows whose timestamp falls within [since, until].
    Includes the header row.
    """
    if not PERF_LOG.exists():
        return []

    rows = []
    try:
        with open(PERF_LOG, encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            return []

        header = lines[0].rstrip()
        rows.append(header)

        for line in lines[1:]:
            line = line.rstrip()
            if not line:
                continue
            # First field is timestamp — sep can be ; or ,
            ts_str = line.split(line[19])[0] if len(line) > 19 else ""
            try:
                ts = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S")
                if since <= ts <= until:
                    rows.append(line)
            except ValueError:
                continue
    except Exception as e:
        rows.append(f"[perf.csv read error: {e}]")

    return rows


def safe_filename(s: str) -> str:
    """Strips characters unsafe for filenames."""
    return "".join(c for c in s if c.isalnum() or c in "-_.").rstrip(".")


def build_result_md(
    row: dict,
    source_text: str,
    s1_translation: str,
    s2_translation: str,
    perf_rows: list[str],
    time_s1: float,
    time_s2: float,
    run_ts: str,
) -> str:
    s2_model  = row["s2"] if row["s2"] and row["s2"] != "—" else "—"
    has_s2    = s2_model != "—" and s2_translation

    lines = [
        f"# Test — {run_ts}",
        "",
        "## Run",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Source | `{row['quelle']}` |",
        f"| S1 model | `{row['s1']}` |",
        f"| S2 model | `{s2_model}` |",
        f"| Source lang | `{row.get('source', 'DE').upper()}` |",
        f"| Target lang | `{row['target'].upper()}` |",
        f"| Mindset | `{row['mindset']}` |",
        f"| S1 time | {int(round(time_s1))}s |",
        f"| S2 time | {int(round(time_s2))}s |",
        "",
    ]

    # perf.csv rows for this run
    if len(perf_rows) > 1:
        lines += [
            "## Performance Log",
            "",
            "```",
        ] + perf_rows + [
            "```",
            "",
        ]
    else:
        lines += ["## Performance Log", "", "_No entries logged for this run._", ""]

    # Source
    lines += [
        "## Source",
        "",
        source_text,
        "",
    ]

    # S1
    lines += [
        f"## S1 — {row['s1']}",
        "",
        s1_translation,
        "",
    ]

    # S2
    if has_s2:
        lines += [
            f"## S2 — {s2_model}",
            "",
            s2_translation,
            "",
        ]

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("  LocalTranslate — Quality Test Runner")
    print()

    # Server check
    if not check_server():
        print("  [ERROR] LocalTranslate server not reachable at", SERVER_URL)
        print("  Start the server first, then re-run test.bat")
        sys.exit(1)
    print("  Server online.")

    # Config
    if not CONFIG_FILE.exists():
        print(f"  [ERROR] Config not found: {CONFIG_FILE}")
        sys.exit(1)

    rows = []
    with open(CONFIG_FILE, encoding="utf-8-sig", newline="") as f:
        # Auto-detect separator: Excel/DE saves as ";", standard CSV uses ","
        first = f.readline()
        sep = ";" if ";" in first else ","
        # Skip Excel sep= hint line if present, otherwise rewind
        if not first.startswith("sep="):
            f.seek(0)
        reader = csv.DictReader(f, delimiter=sep)
        # Normalize headers to lowercase
        for row in reader:
            rows.append({k.lower().strip(): v.strip() for k, v in row.items()})

    if not rows:
        print("  [ERROR] test_config.csv is empty.")
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  {len(rows)} test run(s) configured.")
    print()

    for i, row in enumerate(rows, 1):
        quelle  = row.get("quelle", "").strip()
        s1      = row.get("s1", "").strip()
        s2      = row.get("s2", "").strip()
        target  = row.get("target", "en").strip().lower()
        mindset = row.get("mindset", "general").strip().lower()
        source_lang = row.get("source", "de").strip().lower()

        if not quelle or not s1:
            print(f"  [SKIP] Row {i}: missing quelle or S1")
            continue

        source_path = SOURCE_DIR / quelle
        if not source_path.exists():
            print(f"  [SKIP] Row {i}: source not found: {source_path}")
            continue

        source_text = source_path.read_text(encoding="utf-8")
        run_ts      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_str    = datetime.now().strftime("%Y-%m-%d")
        t_start     = datetime.now()

        print(f"  [{i}/{len(rows)}] {quelle} | S1={s1} | S2={s2 or '—'} | {source_lang.upper()}→{target.upper()} | {mindset}")

        # S1 — mit Chunking
        try:
            set_model(s1)
            time.sleep(0.5)
            chunks = prepare_chunks(source_text)
            print(f"    {len(chunks)} chunk(s)")
            t0 = time.monotonic()
            s1_parts = []
            context = ""
            for idx, chunk in enumerate(chunks):
                data = translate_chunk(chunk, source_lang, target, mindset, s2, idx, context)
                part = data.get("translation", "")
                s1_parts.append(part)
                context = part[-300:] if part else ""
            time_s1 = time.monotonic() - t0
            s1_translation = "\n\n".join(s1_parts)
            print(f"    S1 done ({int(round(time_s1))}s, {len(s1_translation)} chars)")
        except Exception as e:
            print(f"    [ERROR] S1 failed: {e}")
            continue

        # S2
        s2_translation = ""
        time_s2 = 0.0
        if s2 and s2 != "—":
            try:
                set_model(s2)
                time.sleep(0.5)
                t0 = time.monotonic()
                data_s2 = translate_chunk(s1_translation, target, target, mindset, "")
                time_s2 = time.monotonic() - t0
                s2_translation = data_s2.get("translation", "")
                print(f"    S2 done ({int(round(time_s2))}s, {len(s2_translation)} chars)")
            except Exception as e:
                print(f"    [WARN] S2 failed: {e} — S1 result used")

        t_end = datetime.now()

        # perf.csv rows for this run
        perf_rows = read_perf_rows(t_start, t_end)

        # Build result
        result_md = build_result_md(
            row=row,
            source_text=source_text,
            s1_translation=s1_translation,
            s2_translation=s2_translation,
            perf_rows=perf_rows,
            time_s1=time_s1,
            time_s2=time_s2,
            run_ts=run_ts,
        )

        # Output filename
        s1_safe  = safe_filename(s1.replace(":", "-"))
        s2_safe  = safe_filename(s2.replace(":", "-")) if s2 and s2 != "—" else "noS2"
        src_safe = safe_filename(source_path.stem)
        out_name = f"{date_str}_{s1_safe}_{s2_safe}_{src_safe}_{target}_{mindset}.md"
        out_path = RESULTS_DIR / out_name

        out_path.write_text(result_md, encoding="utf-8")
        print(f"    -> {out_path.name}")
        print()

    print(f"  Done. Results in: {RESULTS_DIR}")
    print()


if __name__ == "__main__":
    main()
