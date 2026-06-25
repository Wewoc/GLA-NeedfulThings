"""
scan_critical_deps.py — needfull things
Scans the project for critical dependencies and shadow copies.

Process:
  0. Delete scan_config.py if it exists
  1. Find newest scan_config_v*.py → copy to scan_config.py
  2. Load scan_config.py
  3. Static scan of all SCAN_TARGETS across project files
  4. Ollama classification per match (cached by file+line+hash)
  5. Generate DEPS_CRITICAL.md
  6. Archive:
       DEPS_CRITICAL.md        → scan_output/DEPS_CRITICAL_[config_id].md
       scan_config.py          → scan_configs/[original_name]

Usage: python scan_critical_deps.py
Config: scan_config_v*.py (newest in the same directory)
Output: DEPS_CRITICAL.md → scan_output/
"""

from pathlib import Path
from datetime import datetime
import importlib.util
import hashlib
import json
import re
import shutil
import sys
import urllib.request

# ── Paths ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent.resolve()
CACHE_FILE  = SCRIPT_DIR / ".scan_cache.json"
OUTPUT_MD   = SCRIPT_DIR / "DEPS_CRITICAL.md"
SCAN_OUT    = SCRIPT_DIR / "scan_output"
SCAN_ARCH   = SCRIPT_DIR / "scan_configs"
CONFIG_FILE = SCRIPT_DIR / "scan_config.py"

# ── Cache ──────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    except Exception as e:
        print(f"  ⚠  Cache could not be saved: {e}")

def _cache_key(target_id: str, file_rel: str, lineno: int, line: str) -> str:
    raw = f"{target_id}|{file_rel}|{lineno}|{line}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

# ── Config laden ──────────────────────────────────────────────────────────────

def find_newest_config() -> Path | None:
    """Finds the newest scan_config_v*.py in the script directory (by mtime)."""
    candidates = list(SCRIPT_DIR.glob("scan_config_v*.py"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None

def prepare_config() -> str | None:
    """
    Deletes scan_config.py, copies the newest scan_config_v*.py in its place.
    Returns the original file name (for archiving), or None on error.
    """
    newest = find_newest_config()
    if not newest:
        print("✗  No scan_config_v*.py found.")
        return None

    print(f"  Config gefunden : {newest.name}")

    # Delete old scan_config.py
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        print(f"  Old scan_config.py deleted.")

    # Neueste kopieren
    shutil.copy2(newest, CONFIG_FILE)
    print(f"  scan_config.py bereit.\n")
    return newest.name

def load_config() -> object | None:
    """Loads scan_config.py as a module."""
    spec   = importlib.util.spec_from_file_location("scan_config", CONFIG_FILE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print(f"✗  scan_config.py could not be loaded: {e}")
        return None

# ── Statischer Scan ───────────────────────────────────────────────────────────

def _file_matches_include(rel: str, include: list[str]) -> bool:
    from fnmatch import fnmatch
    return any(fnmatch(rel, pat) for pat in include)

def _file_matches_exclude(rel: str, exclude: list[str]) -> bool:
    return any(rel.startswith(ex) for ex in exclude)

def static_scan(project_root: Path, targets: list[dict]) -> dict[str, list[dict]]:
    """
    Scans all project files for patterns from SCAN_TARGETS.
    Returns dict {target_id: [hit, ...]}.

    Each hit:
        file    — relative path (str)
        lineno  — line number (1-based)
        line    — line content (stripped)
        pattern — matching pattern
    """
    results = {t["id"]: [] for t in targets}

    all_py = sorted(project_root.rglob("*.py"))

    for abs_path in all_py:
        try:
            rel = str(abs_path.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            continue

        for target in targets:
            tid     = target["id"]
            include = target.get("file_include", ["**/*.py"])
            exclude = target.get("file_exclude", [])

            if not _file_matches_include(rel, include):
                continue
            if _file_matches_exclude(rel, exclude):
                continue

            try:
                lines = abs_path.read_text(encoding="utf-8",
                                           errors="replace").splitlines()
            except Exception:
                continue

            patterns = target.get("patterns", [])
            for lineno, raw_line in enumerate(lines, start=1):
                line = raw_line.strip()
                for pat in patterns:
                    try:
                        if re.search(pat, line):
                            results[tid].append({
                                "file":    rel,
                                "lineno":  lineno,
                                "line":    line,
                                "pattern": pat,
                            })
                            break  # one match per line per target is enough
                    except re.error:
                        if pat in line:
                            results[tid].append({
                                "file":    rel,
                                "lineno":  lineno,
                                "line":    line,
                                "pattern": pat,
                            })
                            break

    return results

# ── Ollama-Klassifikation ─────────────────────────────────────────────────────

def _ollama_classify(hit: dict, target: dict,
                     model: str, url: str,
                     project_root: Path) -> str:
    """
    Asks Ollama whether the match is relevant.
    Returns 'relevant', 'not_relevant' or 'unsure'.
    On error: 'unsure'.
    """
    # Context: ±3 lines around the match
    abs_path = project_root / hit["file"]
    context_lines = []
    try:
        all_lines = abs_path.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
        lo = max(0, hit["lineno"] - 4)
        hi = min(len(all_lines), hit["lineno"] + 3)
        for i, l in enumerate(all_lines[lo:hi], start=lo + 1):
            marker = ">>>" if i == hit["lineno"] else "   "
            context_lines.append(f"{marker} {i:4d}  {l}")
    except Exception:
        context_lines = [hit["line"]]

    context = "\n".join(context_lines)
    prompt  = (
        f"File: {hit['file']}\n\n"
        f"Code context:\n{context}\n\n"
        f"{target['ollama_prompt']}"
    )

    payload = json.dumps({
        "model":  model,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data     = json.loads(resp.read().decode("utf-8"))
            response = data.get("response", "").strip().lower()

        if "not_relevant" in response:
            return "not_relevant"
        elif "relevant" in response:
            return "relevant"
        elif "unsure" in response:
            return "unsure"
        else:
            return "unsure"
    except Exception as e:
        return "unsure"

def classify_hits(hits_by_target: dict, targets: list[dict],
                  model: str, ollama_url: str,
                  project_root: Path, cache: dict) -> dict:
    """
    Classifies all matches via Ollama (with cache).
    Returns dict {target_id: [hit_with_verdict, ...]}.
    """
    # Ollama erreichbar?
    ollama_ok = False
    try:
        req = urllib.request.Request(ollama_url, method="GET")
        with urllib.request.urlopen(req, timeout=5):
            ollama_ok = True
    except Exception:
        print("  ⚠  Ollama not reachable — classification skipped (all matches: 'unsure')\n")

    targets_by_id = {t["id"]: t for t in targets}
    result = {}

    total_hits = sum(len(v) for v in hits_by_target.values())
    done       = 0

    for tid, hits in hits_by_target.items():
        target       = targets_by_id[tid]
        result[tid]  = []

        for hit in hits:
            done += 1
            key   = _cache_key(tid, hit["file"], hit["lineno"], hit["line"])

            if key in cache:
                verdict = cache[key]
                source  = "cache"
            elif not ollama_ok:
                verdict = "unsure"
                source  = "skip"
            else:
                print(f"  [{done}/{total_hits}] Ollama: {hit['file']}:{hit['lineno']} ...",
                      end=" ", flush=True)
                verdict = _ollama_classify(hit, target, model, ollama_url, project_root)
                cache[key] = verdict
                source     = "ollama"
                print(verdict)

            result[tid].append({**hit, "verdict": verdict, "source": source})

    return result

# ── MD-Generierung ────────────────────────────────────────────────────────────

def build_md(config, classified: dict, targets: list[dict],
             project_root: Path) -> str:
    """Builds the content of DEPS_CRITICAL.md."""

    now      = datetime.now().strftime("%Y-%m-%d %H:%M")
    cfg_id   = getattr(config, "CONFIG_ID",   "unknown")
    ses_note = getattr(config, "SESSION_NOTE", "")

    lines = []
    lines.append(f"# DEPS_CRITICAL — needfull things")
    lines.append(f"")
    lines.append(f"Generated : {now}")
    lines.append(f"Config    : {cfg_id}")
    if ses_note:
        lines.append(f"Session   : {ses_note}")
    lines.append(f"Project   : {project_root}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Legende")
    lines.append(f"")
    lines.append(f"| Verdict | Meaning |")
    lines.append(f"|---|---|")
    lines.append(f"| `relevant` | Confirmed critical dependency — review before refactoring |")
    lines.append(f"| `unsure`   | Ollama uncertain — manual review recommended |")
    lines.append(f"| `not_relevant` | Kein Bezug — ignorieren |")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    targets_by_id = {t["id"]: t for t in targets}
    has_relevant  = False

    # Zusammenfassung oben
    lines.append(f"## Zusammenfassung")
    lines.append(f"")
    lines.append(f"| Target | Relevant | Unsure | Not Relevant | Gesamt |")
    lines.append(f"|---|---|---|---|---|")

    summary_rows = []
    for tid, hits in classified.items():
        r = sum(1 for h in hits if h["verdict"] == "relevant")
        u = sum(1 for h in hits if h["verdict"] == "unsure")
        n = sum(1 for h in hits if h["verdict"] == "not_relevant")
        summary_rows.append((tid, r, u, n, len(hits)))
        if r > 0 or u > 0:
            has_relevant = True

    for tid, r, u, n, total in summary_rows:
        lines.append(f"| `{tid}` | {r} | {u} | {n} | {total} |")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # Detail-Sektionen — nur relevant + unsure
    lines.append(f"## Details — Relevant & Unsure")
    lines.append(f"")

    for tid, hits in classified.items():
        target    = targets_by_id.get(tid, {})
        desc      = target.get("description", tid)
        canonical = target.get("canonical_source", "—")

        show_hits = [h for h in hits
                     if h["verdict"] in ("relevant", "unsure")]

        if not show_hits:
            lines.append(f"### {tid}")
            lines.append(f"")
            lines.append(f"_{desc}_")
            lines.append(f"")
            lines.append(f"Canonical source: `{canonical}`")
            lines.append(f"")
            lines.append(f"✓ No relevant or unsure matches.")
            lines.append(f"")
            continue

        lines.append(f"### {tid}")
        lines.append(f"")
        lines.append(f"_{desc}_")
        lines.append(f"")
        lines.append(f"Canonical source: `{canonical}`")
        lines.append(f"")
        lines.append(f"| File | Line | Verdict | Code |")
        lines.append(f"|---|---|---|---|")

        for h in sorted(show_hits, key=lambda x: (x["verdict"], x["file"], x["lineno"])):
            verdict_badge = f"`{h['verdict']}`"
            code          = h["line"].replace("|", "\\|")[:80]
            lines.append(f"| `{h['file']}` | {h['lineno']} | {verdict_badge} | `{code}` |")

        lines.append(f"")

    # Not-relevant Anhang (kompakt)
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## Ausgeschlossen (not_relevant)")
    lines.append(f"")

    for tid, hits in classified.items():
        nr_hits = [h for h in hits if h["verdict"] == "not_relevant"]
        if not nr_hits:
            continue
        lines.append(f"**{tid}** ({len(nr_hits)} match ausgeschlossen):")
        lines.append(f"")
        for h in nr_hits:
            lines.append(f"- `{h['file']}:{h['lineno']}` — `{h['line'][:60]}`")
        lines.append(f"")

    return "\n".join(lines) + "\n"

# ── Archivierung ──────────────────────────────────────────────────────────────

def archive(config_id: str, original_config_name: str) -> None:
    """
    Verschiebt DEPS_CRITICAL.md → scan_output/DEPS_CRITICAL_[config_id].md
    Archives scan_config.py  → scan_configs/[original_config_name]
    """
    SCAN_OUT.mkdir(exist_ok=True)
    SCAN_ARCH.mkdir(exist_ok=True)

    # DEPS_CRITICAL.md archivieren
    dest_md = SCAN_OUT / f"DEPS_CRITICAL_{config_id}.md"
    if OUTPUT_MD.exists():
        shutil.move(str(OUTPUT_MD), str(dest_md))
        print(f"  ✓  {OUTPUT_MD.name} → scan_output/{dest_md.name}")

    # Archive scan_config.py
    dest_cfg = SCAN_ARCH / original_config_name
    if CONFIG_FILE.exists():
        shutil.move(str(CONFIG_FILE), str(dest_cfg))
        print(f"  ✓  scan_config.py → scan_configs/{original_config_name}")

# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  scan_critical_deps.py — needfull things")
    print("=" * 65)
    print()

    # 0+1 — Prepare config
    print("── Config ──────────────────────────────────────────────────")
    original_name = prepare_config()
    if not original_name:
        sys.exit(1)

    # 2 — Load config
    cfg = load_config()
    if cfg is None:
        sys.exit(1)

    config_id    = getattr(cfg, "CONFIG_ID",    "unknown")
    session_note = getattr(cfg, "SESSION_NOTE", "")
    ollama_model = getattr(cfg, "OLLAMA_MODEL", "qwen2.5-coder:14b")
    ollama_url   = getattr(cfg, "OLLAMA_URL",   "http://localhost:11434")
    proj_rel     = getattr(cfg, "PROJECT_ROOT", "../mein_projekt")
    targets      = getattr(cfg, "SCAN_TARGETS", [])

    project_root = (SCRIPT_DIR / proj_rel).resolve()

    print(f"  Config-ID  : {config_id}")
    if session_note:
        print(f"  Session    : {session_note}")
    print(f"  Project    : {project_root}")
    print(f"  Ollama     : {ollama_model} @ {ollama_url}")
    print(f"  Targets    : {len(targets)}")
    print()

    if not project_root.is_dir():
        print(f"✗  Project root not found: {project_root}")
        sys.exit(1)

    if not targets:
        print("✗  No SCAN_TARGETS defined in scan_config.py.")
        sys.exit(1)

    # 3 — Static scan
    print("── Static scan ─────────────────────────────────────────────")
    hits_by_target = static_scan(project_root, targets)
    total_hits     = sum(len(v) for v in hits_by_target.values())
    for tid, hits in hits_by_target.items():
        print(f"  {tid}: {len(hits)} matches")
    print(f"  Total: {total_hits} matches\n")

    # 4 — Ollama classification
    print("── Ollama classification ────────────────────────────────────")
    cache      = _load_cache()
    classified = classify_hits(hits_by_target, targets,
                               ollama_model, ollama_url,
                               project_root, cache)
    _save_cache(cache)
    print()

    # 5 — Generate MD
    print("── Output ──────────────────────────────────────────────────")
    md_content = build_md(cfg, classified, targets, project_root)
    OUTPUT_MD.write_text(md_content, encoding="utf-8")
    print(f"  ✓  {OUTPUT_MD} geschrieben\n")

    # 6 — Archive
    print("── Archiving ───────────────────────────────────────────────")
    archive(config_id, original_name)

    print()
    print("=" * 65)
    print(f"  Done — DEPS_CRITICAL_{config_id}.md in scan_output/")
    print("=" * 65)
    print()


if __name__ == "__main__":
    main()
