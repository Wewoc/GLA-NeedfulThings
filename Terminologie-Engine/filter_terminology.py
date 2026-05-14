"""
filter_terminology.py — Nachfilter für bereits gebaute Terminologielisten

Drei unabhängige Pässe — einzeln oder kombiniert ausführbar:

  Pass 1 — Blocklist (default, immer aktiv)
    Entfernt Fragmente, Alltagswörter, Großbuchstaben-Artefakte.

  Pass 2 — Ollama-Filter (--filter)
    Ollama bewertet: "Ist das ein echter Fachbegriff für diese Domäne?"
    Empfohlen: mistral oder qwen2.5:7b

  Pass 3 — Validierung (--validate)
    aya-expanse bewertet: "Ist die DE->EN Übersetzung korrekt?"
    Prüft Übersetzungsqualität der Paare, nicht nur ob es ein Fachbegriff ist.
    Empfohlen: aya-expanse:latest (mehrsprachig, kennt DE/EN Terminologie)

Backup wird vor jedem Schreibvorgang angelegt (terminology/{mindset}/backup/).

Aufruf:
  python filter_terminology.py --dir ../terminology
  python filter_terminology.py --dir ../terminology --dry-run
  python filter_terminology.py --dir ../terminology --filter --model mistral
  python filter_terminology.py --dir ../terminology --validate --model aya-expanse:latest
  python filter_terminology.py --dir ../terminology --filter --validate --model aya-expanse:latest
  python filter_terminology.py --dir ../terminology --mindset technical legal
"""

import argparse
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

# ── Konfiguration ─────────────────────────────────────────────────────────────
#
# Verschärfte Blocklist gegenüber build_terminology.py:
#
#   r"^\w{1,4}$"          zu kurz (1-4 Zeichen)
#                         fängt: ping, ring, fore, sire, rent, thin, time, task
#
#   r"^\d+"               beginnt mit Ziffer
#
#   r"^\(.*\)$"           komplett in Klammern
#
#   r"^[A-ZÄÖÜ]{2,}$"    nur Großbuchstaben (NICHT, ODER, REICH, LARGE, FAST, MODE)
#                         Ausnahme: ACRONYM_ALLOWLIST
#
#   r"^[a-z]{1,5}$"       kurze Kleinbuchstaben-Fragmente aus IATE-Parsing
#                         fängt: adit, cant, fore, quire, fines, mounts
#
#   r"^[A-Z][a-z]{1,4}$"  kurze kapitalisierte Wörter (Here, More, Other, Excel)
#
#   r"^(ja|nein|...)$"    Alltagswörter
BLOCKLIST_PATTERNS = [
    r"^\w{1,4}$",
    r"^\d+",
    r"^\(.*\)$",
    r"^[A-ZÄÖÜ]{2,}$",
    r"^[a-z]{1,5}$",
    r"^[A-Z][a-z]{1,4}$",
    r"^(ja|nein|ok|ok\.|gut|neu|alt|gross|klein|alle|jede[rs]?|bzw|usw|etc|ggf|inkl|exkl|ca|max|min)$",
    r"^(Eiche|Sonde|Frist|Sache|Spiel|Dauer|Dichte|Boden|Welle|Stein|Kraft)$",
]

# Akronyme die trotz Großbuchstaben behalten werden
ACRONYM_ALLOWLIST = {
    "VRAM", "API", "CPU", "GPU", "RAM", "ROM", "SQL", "XML", "JSON", "HTTP",
    "HTTPS", "FTP", "SSH", "TCP", "UDP", "DNS", "URL", "URI", "HTML", "CSS",
    "REST", "SOAP", "PDF", "CSV", "ZIP", "VPN", "LAN", "WAN", "SSD", "HDD",
    "BIOS", "UEFI", "USB", "PCIe", "HDMI", "RGB", "LED", "LCD", "OLED",
}

ALL_MINDSETS = ["general", "technical", "legal", "medical",
                "editorial", "academic", "marketing", "political"]

# ── Ollama-Hilfsfunktion ──────────────────────────────────────────────────────

def _ollama_call(prompt: str, model: str, host: str, timeout: int = 120) -> str:
    """Führt einen einzelnen Ollama-Call aus. Gibt Response-Text zurück."""
    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": False
    }).encode()
    req = urllib.request.Request(
        f"{host}/api/generate", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("response", "").strip()


def _parse_number_list(response: str, batch_len: int) -> set:
    """Parst eine kommagetrennte Nummernliste aus einer Ollama-Antwort."""
    indices = set()
    if response.lower() == "none":
        return indices
    for p in response.split(","):
        p = p.strip()
        if p.isdigit():
            idx = int(p) - 1
            if 0 <= idx < batch_len:
                indices.add(idx)
    return indices

# ── Pass 1: Blocklist ─────────────────────────────────────────────────────────

def is_trivial(term: str) -> bool:
    if term.strip() in ACRONYM_ALLOWLIST:
        return False
    for pattern in BLOCKLIST_PATTERNS:
        if re.match(pattern, term.strip(), re.IGNORECASE):
            return True
    return False


def filter_pair(de_term: str, en_term: str) -> bool:
    if is_trivial(de_term) or is_trivial(en_term):
        return True
    if de_term.lower() == en_term.lower():
        return True
    return False

# ── Pass 2: Ollama-Fachbegriff-Filter ────────────────────────────────────────

def ollama_filter_batch(
    pairs: list[tuple],
    mindset: str,
    model: str,
    host: str,
    batch_size: int = 30,
) -> list[tuple]:
    """
    Pass 2 — Fachbegriff-Filter.
    Frage: "Ist das ein echter Fachbegriff für diese Domäne?"
    """
    CONTEXT = {
        "general":   "general-purpose reference",
        "technical": "software and IT documentation",
        "legal":     "contracts and legislation",
        "medical":   "clinical and research texts",
        "editorial": "journalism and prose",
        "academic":  "scholarly publications",
        "marketing": "advertising and business",
        "political": "policy and government",
    }
    context = CONTEXT.get(mindset, "professional documents")

    # ── Checkpoint laden ──────────────────────────────────────────────────────
    checkpoint_path = Path(__file__).resolve().parent / f".filter2_checkpoint_{mindset}.json"
    start_batch = 0
    kept, skipped = [], 0

    if checkpoint_path.exists():
        try:
            cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if cp.get("model") == model and cp.get("total_pairs") == len(pairs):
                start_batch = cp["completed_batches"]
                kept_codes  = set(cp["kept_codes"])
                kept        = [p for p in pairs if p[0] in kept_codes]
                skipped     = cp["skipped"]
                print(f"    Resume ab Batch {start_batch + 1} ({len(kept)} bereits behalten)")
            else:
                print(f"    Checkpoint veraltet — starte neu")
                checkpoint_path.unlink()
        except Exception:
            print(f"    Checkpoint unlesbar — starte neu")
            checkpoint_path.unlink()

    print(f"    Pass 2 Fachbegriff-Filter [{mindset}]: {len(pairs)} Paare ...")
    total = (len(pairs) + batch_size - 1) // batch_size

    for i in range(start_batch * batch_size, len(pairs), batch_size):
        batch = pairs[i: i + batch_size]
        bn = i // batch_size + 1
        numbered = "\n".join(
            f"{j+1}. DE: {de} | EN: {en}"
            for j, (_, de, en) in enumerate(batch)
        )
        prompt = (
            f"Terminology filter for {context} documents.\n"
            "Return ONLY numbers of genuine domain-specific terms. "
            "Remove: everyday words, generic adjectives, word fragments, "
            "abbreviations of common words, proper nouns unrelated to the domain.\n"
            "Format: comma-separated numbers. Example: 1,3,5\n"
            "If none qualify: none\n\n"
            + numbered
        )
        try:
            rt = _ollama_call(prompt, model, host)
            indices = _parse_number_list(rt, len(batch))
            for idx in sorted(indices):
                kept.append(batch[idx])
            skipped += len(batch) - len(indices)
            print(f"      Batch {bn}/{total}: {len(indices)} behalten, "
                  f"{len(batch)-len(indices)} gefiltert")
            checkpoint_path.write_text(json.dumps({
                "mindset": mindset, "model": model,
                "total_pairs": len(pairs), "completed_batches": bn,
                "kept_codes": [p[0] for p in kept], "skipped": skipped,
            }, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.1)
        except Exception as ex:
            print(f"      [WARN] Batch {bn}: {ex} — unveraendert behalten")
            kept.extend(batch)

    if checkpoint_path.exists():
        checkpoint_path.unlink()
    print(f"    -> {len(kept)} behalten, {skipped} gefiltert")
    return kept

# ── Pass 3: Übersetzungsvalidierung ──────────────────────────────────────────

def ollama_validate_batch(
    pairs: list[tuple],
    mindset: str,
    model: str,
    host: str,
    batch_size: int = 20,
) -> list[tuple]:
    """
    Pass 3 — Übersetzungsqualität.
    Frage: "Ist die DE->EN Übersetzung korrekt und natürlich?"

    Kleinere Batches (20 statt 30) weil die Aufgabe schwieriger ist
    und aya-expanse beide Sprachen gleichzeitig beurteilen muss.
    """
    DOMAIN = {
        "general":   "general professional",
        "technical": "software, IT, and engineering",
        "legal":     "legal and regulatory",
        "medical":   "medical and clinical",
        "editorial": "journalism and publishing",
        "academic":  "academic and scientific",
        "marketing": "business and marketing",
        "political": "political and governmental",
    }
    domain = DOMAIN.get(mindset, "professional")

    # ── Checkpoint laden ──────────────────────────────────────────────────────
    checkpoint_path = Path(__file__).resolve().parent / f".filter3_checkpoint_{mindset}.json"
    start_batch = 0
    kept, rejected = [], 0

    if checkpoint_path.exists():
        try:
            cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if cp.get("model") == model and cp.get("total_pairs") == len(pairs):
                start_batch = cp["completed_batches"]
                kept_codes  = set(cp["kept_codes"])
                kept        = [p for p in pairs if p[0] in kept_codes]
                rejected    = cp["rejected"]
                print(f"    Resume ab Batch {start_batch + 1} ({len(kept)} bereits behalten)")
            else:
                print(f"    Checkpoint veraltet — starte neu")
                checkpoint_path.unlink()
        except Exception:
            print(f"    Checkpoint unlesbar — starte neu")
            checkpoint_path.unlink()

    print(f"    Pass 3 Uebersetzungsvalidierung [{mindset}]: {len(pairs)} Paare ...")
    total = (len(pairs) + batch_size - 1) // batch_size

    for i in range(start_batch * batch_size, len(pairs), batch_size):
        batch = pairs[i: i + batch_size]
        bn = i // batch_size + 1
        numbered = "\n".join(
            f"{j+1}. DE: {de} → EN: {en}"
            for j, (_, de, en) in enumerate(batch)
        )
        prompt = (
            f"You are a bilingual DE/EN terminology validator for {domain} texts.\n"
            "Below are German-English term pairs.\n"
            "Return ONLY the numbers of pairs where the English term is a correct, "
            "natural, and domain-appropriate translation of the German term.\n"
            "Reject if: wrong meaning, outdated usage, nonsensical, or the EN term "
            "is unrelated to the DE term.\n"
            "Format: comma-separated numbers only. Example: 1,3,5\n"
            "If none are correct: none\n\n"
            + numbered
        )
        try:
            rt = _ollama_call(prompt, model, host, timeout=180)
            indices = _parse_number_list(rt, len(batch))
            for idx in sorted(indices):
                kept.append(batch[idx])
            rejected += len(batch) - len(indices)
            print(f"      Batch {bn}/{total}: {len(indices)} behalten, "
                  f"{len(batch)-len(indices)} abgelehnt")
            checkpoint_path.write_text(json.dumps({
                "mindset": mindset, "model": model,
                "total_pairs": len(pairs), "completed_batches": bn,
                "kept_codes": [p[0] for p in kept], "rejected": rejected,
            }, ensure_ascii=False), encoding="utf-8")
            time.sleep(0.1)
        except Exception as ex:
            print(f"      [WARN] Batch {bn}: {ex} — unveraendert behalten")
            kept.extend(batch)

    if checkpoint_path.exists():
        checkpoint_path.unlink()
    print(f"    -> {len(kept)} behalten, {rejected} abgelehnt")
    return kept

# ── Hauptfunktion pro Mindset ─────────────────────────────────────────────────

def filter_mindset(
    mindset_dir: Path,
    mindset: str,
    use_filter: bool,
    use_validate: bool,
    ollama_model: str,
    ollama_host: str,
    dry_run: bool,
) -> dict:
    de_path = mindset_dir / "de.json"
    en_path = mindset_dir / "en.json"

    if not de_path.exists() or not en_path.exists():
        print(f"  [{mindset}] SKIP — de.json oder en.json fehlt")
        return {}

    de_data = json.loads(de_path.read_text(encoding="utf-8"))
    en_data = json.loads(en_path.read_text(encoding="utf-8"))

    if not de_data:
        print(f"  [{mindset}] SKIP — leer")
        return {}

    print(f"  [{mindset}] {len(de_data)} Eintraege")

    # ── Pass 1: Blocklist ─────────────────────────────────────────────────────
    pairs_in = [(code, de_data[code], en_data.get(code, ""))
                for code in de_data if code in en_data]
    pairs_ok = [(code, de, en) for code, de, en in pairs_in
                if not filter_pair(de, en)]
    removed_blocklist = len(pairs_in) - len(pairs_ok)
    print(f"    Pass 1 Blocklist: {removed_blocklist} entfernt, {len(pairs_ok)} verbleiben")

    # ── Pass 2: Fachbegriff-Filter ────────────────────────────────────────────
    if use_filter and pairs_ok:
        pairs_ok = ollama_filter_batch(
            pairs_ok, mindset, ollama_model, ollama_host
        )

    # ── Pass 3: Übersetzungsvalidierung ──────────────────────────────────────
    if use_validate and pairs_ok:
        pairs_ok = ollama_validate_batch(
            pairs_ok, mindset, ollama_model, ollama_host
        )

    # ── Backup + Schreiben ────────────────────────────────────────────────────
    total_removed = len(pairs_in) - len(pairs_ok)

    if dry_run:
        print(f"    DRY RUN — wuerde {total_removed} Eintraege entfernen "
              f"({len(pairs_ok)} verbleiben)")
        return {"before": len(pairs_in), "after": len(pairs_ok), "removed": total_removed}

    backup_dir = mindset_dir / "backup"
    backup_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(de_path, backup_dir / f"de_{ts}.json")
    shutil.copy2(en_path, backup_dir / f"en_{ts}.json")

    new_de = {code: de for code, de, _ in pairs_ok}
    new_en = {code: en for code, _, en in pairs_ok}

    de_path.write_text(json.dumps(new_de, ensure_ascii=False, indent=2), encoding="utf-8")
    en_path.write_text(json.dumps(new_en, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"    -> {len(new_de)} Eintraege geschrieben "
          f"({total_removed} entfernt, Backup in backup/)")

    return {"before": len(pairs_in), "after": len(new_de), "removed": total_removed}

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Nachfilter fuer bereits gebaute Terminologielisten (3 Paesse)"
    )
    parser.add_argument("--dir",      type=Path, required=True,
                        help="Pfad zum terminology-Ordner")
    parser.add_argument("--mindset",  nargs="*", default=ALL_MINDSETS,
                        help="Mindsets filtern (default: alle)")
    parser.add_argument("--filter",   action="store_true",
                        help="Pass 2: Ollama-Fachbegriff-Filter aktivieren")
    parser.add_argument("--validate", action="store_true",
                        help="Pass 3: Uebersetzungsvalidierung via aya-expanse aktivieren")
    parser.add_argument("--model",    default="aya-expanse:latest",
                        help="Ollama-Modell (default: aya-expanse:latest)")
    parser.add_argument("--host",     default="http://localhost:11434",
                        help="Ollama-Host")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Nur anzeigen was entfernt wuerde, nichts schreiben")
    args = parser.parse_args()

    if not args.dir.exists():
        print(f"[FEHLER] Ordner nicht gefunden: {args.dir}")
        sys.exit(1)

    print()
    print("  filter_terminology — Nachfilter")
    passes = ["Pass 1: Blocklist"]
    if args.filter:   passes.append("Pass 2: Fachbegriff-Filter")
    if args.validate: passes.append("Pass 3: Uebersetzungsvalidierung")
    print(f"  Aktive Paesse: {' + '.join(passes)}")
    if args.validate or args.filter:
        print(f"  Modell: {args.model}")
    if args.dry_run:
        print("  DRY RUN — keine Dateien werden veraendert")
    print()

    total_stats = {}
    for mindset in args.mindset:
        mindset_dir = args.dir / mindset
        stats = filter_mindset(
            mindset_dir=mindset_dir,
            mindset=mindset,
            use_filter=args.filter,
            use_validate=args.validate,
            ollama_model=args.model,
            ollama_host=args.host,
            dry_run=args.dry_run,
        )
        if stats:
            total_stats[mindset] = stats
        print()

    if total_stats:
        print("  Zusammenfassung:")
        total_before  = sum(s["before"]  for s in total_stats.values())
        total_after   = sum(s["after"]   for s in total_stats.values())
        total_removed = total_before - total_after
        for mindset, s in total_stats.items():
            print(f"    {mindset:12} {s['before']:>6} -> {s['after']:>6} (-{s['removed']})")
        print(f"    {'GESAMT':12} {total_before:>6} -> {total_after:>6} (-{total_removed})")
    print()


if __name__ == "__main__":
    main()