# menu — Context Menu Integration

Adds right-click entries for the needfull things `stuff/` scripts to
Windows Explorer and OneCommander. The original scripts are not modified.

---

## Setup

### Windows Explorer

Double-click `install.bat`. No admin required — entries go into `HKCU`.

Re-open any Explorer window to see the new entries.

To remove: double-click `uninstall.bat`.

### OneCommander

OneCommander does not read from the registry. Import manually:

1. Open OneCommander
2. Settings → Custom Commands → Import
3. Select `onecommander_custom_actions.txt`
4. Adjust the paths if your repo is not at `D:\Github\GLA-NeedfulThings\`

---

## Available entries

| Menu entry | What it does | Output |
|---|---|---|
| Merge folder to MD | Merges all files into one Markdown | `merged.md` in target folder |
| Generate folder tree | Writes folder structure | `struktur.md` in target folder |
| Count project stats | Lines / words / chars by file type | `project_stats.md` in target folder |
| Count chat stats | Turns / words / chars per user and AI | `chat_stats.md` in target folder |
| Anonymize JSONs here | Anonymizes all `.json` files | `anonymized/` subfolder (auto-numbered) |

All entries: right-click on a **folder** in Explorer or OneCommander.

---

## How it works

`install.bat` reads its own location via `%~dp0` — no hardcoded paths.
Works wherever the repo is placed. The wrapper `.bat` files call the original
scripts one level up (`../script.py`) and pass the clicked folder as `%1`.

`run_anonymize.py` is standalone — it contains its own logic and does not
call `anonymize_json.py`. Output folder is auto-numbered:
`anonymized/` → `anonymized_02/` → `anonymized_03/` etc.

---

## Structure

```
stuff/
├── merge_to_md.py          ← unchanged
├── generate_tree.bat       ← unchanged
├── count_project.py        ← +argv[1] support (see anchor delivery)
├── count_chats.py          ← +argv[1] support (see anchor delivery)
├── anonymize_json.py       ← unchanged
│
└── menu/
    ├── install.bat
    ├── uninstall.bat
    ├── run_merge.bat
    ├── run_tree.bat
    ├── run_count_proj.bat
    ├── run_count_chats.bat
    ├── run_anonymize.py
    ├── onecommander_custom_actions.txt
    └── README.md
```
