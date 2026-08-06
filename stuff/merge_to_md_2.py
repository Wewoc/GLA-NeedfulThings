import os

# ──────────────────────────────────────────────
#  CONFIG
# ──────────────────────────────────────────────
TARGET_FILE = "MAINTENANCE_translator.md"   # Dateiname, nach dem gesucht wird
SOURCE_DIR  = "."                           # Startordner (rekursiv)
OUTPUT_FILE = "summary.md"                  # Ergebnisdatei
# ──────────────────────────────────────────────


def merge_target_files(source_dir, target_file, output_file):
    if not os.path.exists(source_dir):
        print(f"Fehler: Ordner '{source_dir}' nicht gefunden.")
        return

    matches = []
    for root, dirs, files in os.walk(source_dir):
        for filename in files:
            if filename == target_file:
                matches.append(os.path.join(root, filename))

    if not matches:
        print(f"Keine Datei '{target_file}' gefunden.")
        return

    matches.sort()

    with open(output_file, "w", encoding="utf-8") as outfile:
        outfile.write(f"# Merged: `{target_file}`\n\n")
        outfile.write(f"Gefundene Dateien: {len(matches)}\n\n---\n\n")

        for filepath in matches:
            outfile.write(f"## {filepath}\n\n")
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as infile:
                    outfile.write(infile.read())
            except Exception as e:
                outfile.write(f"*Fehler beim Lesen: {e}*")
            outfile.write("\n\n---\n\n")

    print(f"Fertig: {len(matches)} Datei(en) → '{output_file}'")
    for p in matches:
        print(f"  {p}")


if __name__ == "__main__":
    merge_target_files(SOURCE_DIR, TARGET_FILE, OUTPUT_FILE)
