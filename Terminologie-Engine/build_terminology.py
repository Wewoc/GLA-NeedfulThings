"""
build_terminology.py — One-time build step (local only, not in repo)

Reads:
  - Any TBX terminology file (e.g. a language-specific export from a glossary collection)
  - Any pipe-separated CSV with columns E_ID, E_DOMAINS, L_CODE, T_TERM, T_RELIABILITY

Writes one subfolder per mindset with two language lists:
  terminology/
    technical/
      de.json     {"§Txxxxxxxx§": "Betriebssystem", ...}
      en.json     {"§Txxxxxxxx§": "Operating System", ...}
    legal/
      de.json
      en.json
    ... (general, medical, editorial, academic, marketing, political)
    build_report.txt

Codes are hash-based and build-stable — same DE term always gets the same code.
Adding a new target language: place a new fr.json in each mindset folder, no code changes needed.

Usage:
  python build_terminology.py --mtc path/to/GERMAN.tbx --out ../terminology
  python build_terminology.py --iate path/to/export.csv --out ../terminology
  python build_terminology.py --mtc path/to/GERMAN.tbx --iate path/to/export.csv --out ../terminology
  python build_terminology.py --mtc path/to/GERMAN.tbx --iate path/to/export.csv --out ../terminology --filter
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path

try:
    from lxml import etree
except ImportError:
    print("[FEHLER] lxml nicht installiert. Bitte: pip install lxml")
    sys.exit(1)

# ── Konfiguration ─────────────────────────────────────────────────────────────

# BLOCKLIST_PATTERNS — auf DE- UND EN-Term geprüft, Eintrag fliegt raus bei Treffer.
#   r"^\w{1,3}$"    zu kurz. Auf r"^\w{1,2}$" kürzen um API/CPU/SQL zu behalten.
#   r"^\d+"         beginnt mit Ziffer
#   r"^\(.*\)$"     komplett in Klammern, z.B. "( Intellekt )" — kein echter Term
#   r"^(...)$"      Alltagswörter die durch das Längen-Muster rutschen
BLOCKLIST_PATTERNS = [
    r"^\w{1,3}$",
    r"^\d+",
    r"^\(.*\)$",
    r"^(ja|nein|ok|ok\.|gut|neu|alt|gross|klein|alle|jede[rs]?|bzw|usw|etc|ggf|inkl|exkl|ca|max|min)$",
]

# IATE_MIN_RELIABILITY
#   "Very reliable"              -> 4  (EU-Rechtsakte, offiziell validiert)
#   "Reliable"                   -> 3  (von Experten geprüft)  <- Standard
#   "Minimum reliability"        -> 1  (eingereicht, nicht geprüft)
#   "Reliability not verified"   -> 0
IATE_MIN_RELIABILITY = 3

# GENERAL_MIN_DOMAINS — Wie viele Mindset-Domains ein Begriff abdecken muss
# um als domänenübergreifend (general.json) zu gelten statt in Einzellisten.
GENERAL_MIN_DOMAINS = 3

# ── Domain -> Mindset Mapping ─────────────────────────────────────────────────

DOMAIN_TO_MINDSET = [
    ("information technology", "technical"),
    ("computing",              "technical"),
    ("electronics",            "technical"),
    ("telecommunications",     "technical"),
    ("software",               "technical"),
    ("data processing",        "technical"),
    ("technology",             "technical"),
    ("engineering",            "technical"),
    ("law",                    "legal"),
    ("legal",                  "legal"),
    ("judicial",               "legal"),
    ("legislation",            "legal"),
    ("contract",               "legal"),
    ("justice",                "legal"),
    ("civil law",              "legal"),
    ("criminal law",           "legal"),
    ("intellectual property",  "legal"),
    ("medicine",               "medical"),
    ("health",                 "medical"),
    ("pharmacology",           "medical"),
    ("biology",                "medical"),
    ("chemistry",              "medical"),
    ("clinical",               "medical"),
    ("nutrition",              "medical"),
    ("disease",                "medical"),
    ("media",                  "editorial"),
    ("journalism",             "editorial"),
    ("publishing",             "editorial"),
    ("culture",                "editorial"),
    ("arts",                   "editorial"),
    ("communication",          "editorial"),
    ("language",               "editorial"),
    ("education",              "academic"),
    ("research",               "academic"),
    ("science",                "academic"),
    ("university",             "academic"),
    ("statistics",             "academic"),
    ("mathematics",            "academic"),
    ("physics",                "academic"),
    ("trade",                  "marketing"),
    ("commerce",               "marketing"),
    ("finance",                "marketing"),
    ("economics",              "marketing"),
    ("advertising",            "marketing"),
    ("marketing",              "marketing"),
    ("business",               "marketing"),
    ("accounting",             "marketing"),
    ("industry",               "marketing"),
    ("politics",               "political"),
    ("government",             "political"),
    ("international relations","political"),
    ("defence",                "political"),
    ("military",               "political"),
    ("public administration",  "political"),
    ("diplomacy",              "political"),
    ("european union",         "political"),
    ("international agreement","political"),
]

ALL_MINDSETS = ["general", "technical", "legal", "medical",
                "editorial", "academic", "marketing", "political"]

# ── Code-Generierung ──────────────────────────────────────────────────────────

def make_code(de_term: str, mindset: str) -> str:
    """
    Stabiler Code aus DE-Term + Mindset — gleicher Input ergibt immer denselben Code.
    Format: §Txxxxxxxx§  (8 Hex-Zeichen aus MD5, Kollisionswahrscheinlichkeit vernachlässigbar)
    Vorteil: Codes sind build-stabil, kein Index nötig.
    """
    h = hashlib.md5(f"{mindset}:{de_term.lower()}".encode()).hexdigest()[:8]
    return f"§T{h}§"

# ── Domain-Klassifikation ─────────────────────────────────────────────────────

def classify_domains(domains_raw: str) -> set:
    mindsets = set()
    dl = domains_raw.lower()
    for keyword, mindset in DOMAIN_TO_MINDSET:
        if keyword in dl:
            mindsets.add(mindset)
    return mindsets

# ── TBX Parser ────────────────────────────────────────────────────────────────

def parse_mtc_tbx(path):
    print(f"  Lese MTC TBX: {path.name} ...")
    for enc in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            content = path.read_bytes().decode(enc)
            break
        except Exception:
            continue
    else:
        print("  [FEHLER] Encoding nicht erkannt")
        return []

    try:
        root = etree.fromstring(content.encode("utf-8"))
    except Exception as e:
        print(f"  [FEHLER] Parse-Fehler: {e}")
        return []

    XML_LANG_ATTRS = (
        "{http://www.w3.org/XML/1998/namespace}lang",
        "lang",
    )
    results = []

    for entry in root.iter("{*}termEntry"):
        terms = {}
        for langset in entry.findall("{*}langSet"):
            lang_raw = ""
            for attr in XML_LANG_ATTRS:
                lang_raw = langset.get(attr, "")
                if lang_raw:
                    break
            lang = lang_raw.split("-")[0].lower()
            if lang not in ("de", "en"):
                continue
            term_text = ""
            for container in list(langset.iter("{*}ntig")) + list(langset.iter("{*}tig")):
                term_el = container.find("{*}term")
                if term_el is None:
                    for tg in container.iter("{*}termGrp"):
                        term_el = tg.find("{*}term")
                        if term_el is not None:
                            break
                if term_el is not None and term_el.text:
                    term_text = term_el.text.strip()
                    break
            if term_text and lang not in terms:
                terms[lang] = term_text

        if "de" in terms and "en" in terms:
            results.append({"de": terms["de"], "en": terms["en"],
                            "source": "mtc", "domains": set()})

    print(f"  -> {len(results)} DE/EN-Paare")
    return results


def parse_iate_csv(path):
    print(f"  Lese IATE CSV: {path.name} ...")
    RELIABILITY_MAP = {
        "very reliable": 4, "reliable": 3,
        "minimum reliability": 1, "reliability not verified": 0,
    }
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                f.read(100)
            encoding = enc
            break
        except UnicodeDecodeError:
            continue
    else:
        print("  [FEHLER] Encoding nicht erkannt")
        return []

    groups = {}
    errors = 0
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter="|")
        for row in reader:
            try:
                term_id   = (row.get("E_ID") or "").strip()
                lang_code = (row.get("L_CODE") or "").strip().lower()[:2]
                term_text = (row.get("T_TERM") or "").strip()
                rel_raw   = (row.get("T_RELIABILITY") or "").strip().lower()
                dom_raw   = (row.get("E_DOMAINS") or "").strip()

                if not term_id or not lang_code or not term_text:
                    continue
                if lang_code not in ("de", "en"):
                    continue
                reliability = RELIABILITY_MAP.get(rel_raw, 0)
                if reliability < IATE_MIN_RELIABILITY:
                    continue

                if term_id not in groups:
                    groups[term_id] = {"domains": dom_raw}
                elif not groups[term_id]["domains"] and dom_raw:
                    groups[term_id]["domains"] = dom_raw

                existing = groups[term_id].get(lang_code)
                if existing is None or reliability > existing["reliability"]:
                    groups[term_id][lang_code] = {"text": term_text, "reliability": reliability}
            except Exception:
                errors += 1

    results = []
    for data in groups.values():
        if "de" in data and "en" in data:
            results.append({
                "de": data["de"]["text"], "en": data["en"]["text"],
                "source": "iate", "domains": classify_domains(data.get("domains", "")),
            })

    print(f"  -> {len(results)} DE/EN-Paare (min. Zuverlaessigkeit {IATE_MIN_RELIABILITY})")
    if errors:
        print(f"  -> {errors} Zeilen uebersprungen")
    return results

# ── Filter & Dedup ────────────────────────────────────────────────────────────

def is_trivial(de, en):
    for p in BLOCKLIST_PATTERNS:
        if re.match(p, de, re.IGNORECASE) or re.match(p, en, re.IGNORECASE):
            return True
    return de.lower() == en.lower()


def deduplicate(entries):
    seen = {}
    for e in entries:
        key = e["de"].lower()
        if key not in seen:
            seen[key] = dict(e); seen[key]["domains"] = set(e["domains"])
        else:
            seen[key]["domains"] |= e["domains"]
            if e["source"] == "iate" and seen[key]["source"] == "mtc":
                dom = seen[key]["domains"]
                seen[key] = dict(e); seen[key]["domains"] = dom
    return list(seen.values())


def assign_mindsets(entries):
    buckets = {m: [] for m in ALL_MINDSETS}
    for e in entries:
        d = e["domains"]
        if len(d) >= GENERAL_MIN_DOMAINS:
            buckets["general"].append(e)
        elif len(d) == 0:
            buckets["technical"].append(e)
        else:
            for m in d:
                if m in buckets:
                    buckets[m].append(e)
    return buckets

# ── Ollama-Filter ─────────────────────────────────────────────────────────────

def ollama_filter_batch(entries, mindset, model, host, batch_size=30):
    if not entries:
        return entries
    CONTEXT = {
        "general": "general-purpose reference", "technical": "software and IT documentation",
        "legal": "contracts and legislation", "medical": "clinical and research texts",
        "editorial": "journalism and prose", "academic": "scholarly publications",
        "marketing": "advertising and business", "political": "policy and government",
    }
    import urllib.request
    print(f"  Ollama-Filter [{mindset}]: {len(entries)} Eintraege ...")
    kept, skipped = [], 0
    total = (len(entries) + batch_size - 1) // batch_size

    for i in range(0, len(entries), batch_size):
        batch = entries[i: i + batch_size]
        bn = i // batch_size + 1
        numbered = "\n".join(f"{j+1}. DE: {e['de']} | EN: {e['en']}" for j, e in enumerate(batch))
        prompt = (
            f"Terminology filter for {CONTEXT.get(mindset, 'professional')} documents.\n"
            "Return ONLY numbers of genuine domain-specific terms. Not everyday words.\n"
            "Format: comma-separated. Example: 1,3,5  If none: none\n\n" + numbered
        )
        try:
            payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request(f"{host}/api/generate", data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                rt = json.loads(resp.read()).get("response", "").strip()
            if rt.lower() == "none":
                skipped += len(batch)
            else:
                indices = set()
                for p in rt.split(","):
                    p = p.strip()
                    if p.isdigit():
                        idx = int(p) - 1
                        if 0 <= idx < len(batch):
                            indices.add(idx)
                for idx in sorted(indices):
                    kept.append(batch[idx])
                skipped += len(batch) - len(indices)
            print(f"    Batch {bn}/{total}: {len(indices)} behalten")
            time.sleep(0.1)
        except Exception as ex:
            print(f"    [WARN] Batch {bn}: {ex}")
            kept.extend(batch)

    print(f"  -> [{mindset}] {len(kept)} behalten, {skipped} gefiltert")
    return kept

# ── Ausgabe ───────────────────────────────────────────────────────────────────

def write_mindset_files(entries, mindset_dir: Path, mindset: str) -> int:
    """
    Schreibt de.json und en.json in den Mindset-Ordner.

    Format: {"§Txxxxxxxx§": "Begriff"}
    Codes sind hash-basiert und damit build-stabil.
    """
    mindset_dir.mkdir(parents=True, exist_ok=True)
    de_map = {}
    en_map = {}

    for e in sorted(entries, key=lambda x: x["de"].lower()):
        code = make_code(e["de"], mindset)
        de_map[code] = e["de"]
        en_map[code] = e["en"]

    (mindset_dir / "de.json").write_text(
        json.dumps(de_map, ensure_ascii=False, indent=2), encoding="utf-8")
    (mindset_dir / "en.json").write_text(
        json.dumps(en_map, ensure_ascii=False, indent=2), encoding="utf-8")

    return len(de_map)

# ── Hauptfunktion ─────────────────────────────────────────────────────────────

def build(mtc_path, iate_path, output_dir, use_ollama, ollama_model, ollama_host):
    output_dir.mkdir(parents=True, exist_ok=True)
    all_entries = []

    print("\n[1] Quellen einlesen")
    if mtc_path and mtc_path.exists():
        all_entries.extend(parse_mtc_tbx(mtc_path))
    elif mtc_path:
        print(f"  [WARN] nicht gefunden: {mtc_path}")
    if iate_path and iate_path.exists():
        all_entries.extend(parse_iate_csv(iate_path))
    elif iate_path:
        print(f"  [WARN] nicht gefunden: {iate_path}")
    if not all_entries:
        print("[FEHLER] Keine Eintraege geladen.")
        sys.exit(1)
    print(f"  -> Gesamt: {len(all_entries)}")
    stats = {"raw": len(all_entries)}

    print("\n[2] Heuristischer Filter")
    before = len(all_entries)
    all_entries = [e for e in all_entries if not is_trivial(e["de"], e["en"])]
    stats["after_heuristic"] = len(all_entries)
    print(f"  -> {before - len(all_entries)} entfernt, {len(all_entries)} verbleiben")

    print("\n[3] Deduplizierung")
    before = len(all_entries)
    all_entries = deduplicate(all_entries)
    stats["after_dedup"] = len(all_entries)
    print(f"  -> {before - len(all_entries)} Duplikate entfernt, {len(all_entries)} verbleiben")

    print("\n[4] Mindset-Zuweisung")
    buckets = assign_mindsets(all_entries)
    for m in ALL_MINDSETS:
        print(f"  {m:12} -> {len(buckets[m]):>6} Eintraege")

    if use_ollama:
        print("\n[5] Ollama-Filter (pro Mindset)")
        for m in ALL_MINDSETS:
            buckets[m] = ollama_filter_batch(buckets[m], m, ollama_model, ollama_host)
    else:
        print("\n[5] Ollama-Filter uebersprungen (--filter nicht gesetzt)")

    print("\n[6] Ausgabe")
    final_counts = {}
    for m in ALL_MINDSETS:
        mindset_dir = output_dir / m
        count = write_mindset_files(buckets[m], mindset_dir, m)
        final_counts[m] = count
        print(f"  -> {m}/de.json + en.json ({count} Eintraege)")

    report = [
        "# build_terminology -- Report",
        f"Erstellt:             {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"MTC:                  {mtc_path}",
        f"IATE:                 {iate_path}",
        f"Ollama-Filter:        {'ja -- ' + ollama_model if use_ollama else 'nein'}",
        f"IATE_MIN_RELIABILITY: {IATE_MIN_RELIABILITY}",
        f"GENERAL_MIN_DOMAINS:  {GENERAL_MIN_DOMAINS}",
        f"Code-Format:          hash-basiert (stabil ueber Builds)",
        "",
        "## Pipeline",
        f"  Raw:              {stats['raw']}",
        f"  Nach Heuristik:   {stats['after_heuristic']}",
        f"  Nach Dedup:       {stats['after_dedup']}",
        "",
        "## Mindset-Listen",
    ] + [f"  {m:12} {final_counts[m]:>6}" for m in ALL_MINDSETS] + [
        f"  {'GESAMT':12} {sum(final_counts.values()):>6}",
        "",
        "## Stichprobe technical/de.json (erste 10)",
    ] + [
        f"  {make_code(e['de'], 'technical')}  {e['de']} -> {e['en']}"
        for e in sorted(buckets["technical"], key=lambda e: e["de"].lower())[:10]
    ]

    (output_dir / "build_report.txt").write_text("\n".join(report), encoding="utf-8")
    print(f"  -> build_report.txt")
    print(f"\nBuild abgeschlossen -- {sum(final_counts.values())} Eintraege in {len(ALL_MINDSETS)} Listen")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mtc",    type=Path)
    parser.add_argument("--iate",   type=Path)
    parser.add_argument("--out",    type=Path, default=Path("terminology"))
    parser.add_argument("--filter", action="store_true")
    parser.add_argument("--model",  default="mistral")
    parser.add_argument("--host",   default="http://localhost:11434")
    args = parser.parse_args()
    if not args.mtc and not args.iate:
        parser.error("Mindestens --mtc oder --iate muss angegeben werden")
    build(args.mtc, args.iate, args.out, args.filter, args.model, args.host)
