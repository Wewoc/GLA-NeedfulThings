import os

SOURCE_DIR  = "."
OUTPUT_FILE = "summary.md"
EXCLUDE     = {OUTPUT_FILE, "merge_to_md.py", "struktur.md"}

def merge_files_to_markdown(source_dir, output_file):
    if not os.path.exists(source_dir):
        print(f"Error: Folder '{source_dir}' not found.")
        return
    file_count = 0
    with open(output_file, "w", encoding="utf-8") as outfile:
        for root, dirs, files in os.walk(source_dir):
            for filename in files:
                if filename in EXCLUDE:
                    continue
                filepath = os.path.join(root, filename)
                outfile.write(f"## File: {filepath}\n\n")
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as infile:
                        outfile.write(infile.read())
                        file_count += 1
                except Exception as e:
                    outfile.write(f"*Error: {e}*")
                outfile.write("\n\n---\n\n")
    print(f"Done: {file_count} files merged into '{output_file}'.")

if __name__ == "__main__":
    merge_files_to_markdown(SOURCE_DIR, OUTPUT_FILE)