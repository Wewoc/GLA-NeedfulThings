# netz2_diagnostics — Silo/Backfill Diagnostic Harness

Reproduces specific edge cases in [Garmin Local Archive](https://github.com/Wewoc/Garmin_Local_Archive)'s
"Net 2" reliability layer (silo repair, backfill, restore, bulk import) against
real core modules — no mocks of the logic under test, only of the external API
boundary. Pure observation: builds a fixture, calls the real function, logs
the result. No assertions, no pass/fail — the Markdown report is meant to be
read and assessed by hand (or fed to an LLM) afterwards.

Part of the [GLA-Tools](https://github.com/Wewoc/GLA-NeedfulThings) "Your Data · Your Tools" ecosystem — no cloud, no API key.

---

## What it does

Each `run_netz2_*.py` script targets one specific reliability question, e.g.:

| Script | Question |
|---|---|
| `run_netz2.py` | Does `repair_silos()` correctly recover a source-without-raw / raw-without-summary day, including a malformed-data variant? |
| `run_netz2_steps_async.py` | What happens when `patch_source_field()` keeps failing after retry — does the day stay stuck in a silent async state? |
| `run_netz2_stop_abort.py` | Does a stop event mid-backfill-loop ever produce a half-written day? |
| `run_netz2_restore_staleness.py` | Does a GUI restore button using a stale (closure-frozen) missing-days list silently downgrade a day that was re-synced in the meantime? |
| `run_netz2_bulk_import.py` | How does `load_bulk()` / `run_import()` behave when one day in a GDPR export is corrupt or incomplete? |

All fixture content is derived from a real `raw/` file in your own archive
(read-only access, structure copied and trimmed) — the diagnostic run itself
never touches your real archive; it writes into its own isolated
`diagnose_tmp_*/` folder per script.

`netz2_delta.py` is not a diagnostic scenario — it's a pre-check. It hashes
the six Net-2 core modules and compares them against the last diagnostic run,
so a stale report doesn't silently get relied on after one of those modules
changed.

---

## Requirements

- Python 3.10+
- A local checkout of [Garmin Local Archive](https://github.com/Wewoc/Garmin_Local_Archive) (the scripts import its
  core modules directly — `sys.path.insert`, no packaging)
- A local Garmin data archive (`garmin_data/` parent folder) with at least one
  real `raw/*.json` file — used read-only as a fixture template

---

## Setup

1. Place this folder (`netz2_diagnostics/`) next to your GLA checkout, or
   anywhere — the path to GLA is configured, not assumed.
2. Copy `netz2_config.example.py` → `netz2_config.py` and fill in:
   - `PROJECT_ROOT_REL` — relative path to your GLA checkout
   - `REAL_ARCHIVE_BASE_DIR` — absolute path to your real archive (parent of `garmin_data/`)
3. `netz2_config.py` is listed in `.gitignore` and never committed — it holds
   your personal local paths. The scripts themselves stay generic.

```
netz2_diagnostics/.gitignore:
netz2_config.py
diagnose_tmp*/
output/
```

---

## Usage

```
run_netz2_all.bat
```

Prompts for a version tag (e.g. `1658`), assigns a running report ID
(`v1658_01`, `v1658_02`, ...), runs `netz2_delta.py` first, then every
`run_netz2*.py` script in the folder, in sequence, against the same report ID.

Running a single script directly (`python run_netz2.py`) will not work —
each script requires `NETZ2_REPORT_ID` to be set in the environment, which
only `run_netz2_all.bat` does.

---

## Output

```
netz2_diagnostics/
├── output/
│   └── v1658_01/
│       ├── NETZ2_BEFUND_silo_repair.md
│       ├── NETZ2_BEFUND_steps_async.md
│       ├── NETZ2_BEFUND_stop_abort.md
│       ├── NETZ2_BEFUND_restore_staleness.md
│       ├── NETZ2_BEFUND_bulk_import.md
│       └── delta/
│           ├── NETZ2_DELTA_v1658_01.md
│           └── netz2_module_hashes.json      ← baseline for the next run
├── diagnose_tmp/                              ← isolated write targets,
├── diagnose_tmp_steps_async/                     recreated on every run,
├── diagnose_tmp_stop_abort/                      never touches your real
├── diagnose_tmp_restore_staleness/               archive
└── diagnose_tmp_bulk_import/
```

Each `NETZ2_BEFUND_*.md` report documents fixture content, the real
function's return value, file state before/after, and log output — enough to
assess the behavior without re-running anything.

---

## Structure

```
netz2_diagnostics/
├── run_netz2_all.bat            ← entry point, assigns report ID, runs everything
├── netz2_delta.py                ← pre-check: core-module hash comparison
├── run_netz2.py                  ← scenario: silo repair (#3 / #7)
├── run_netz2_steps_async.py      ← scenario: steps-backfill silo-async state
├── run_netz2_stop_abort.py       ← scenario: stop-event abort mid-loop
├── run_netz2_restore_staleness.py ← scenario: restore-data staleness window
├── run_netz2_bulk_import.py      ← scenario: bulk import, broken/missing day
├── netz2_config.example.py       ← template — copy to netz2_config.py
└── netz2_config.py               ← your local paths (not committed)
```

## Notes

- All five `run_netz2_*.py` scenario scripts follow the same shape: build a
  fixture from a real archive file → call the real core function (only the
  external API boundary is mocked) → observe file state, return value, and
  logs → write a Markdown report. Extending with a new scenario means
  copying that shape, not the mechanism itself — each script deliberately
  stays standalone rather than sharing a framework, since the core mechanism
  under test differs per script (silo repair vs. backfill vs. restore vs.
  import).
- `netz2_delta.py`'s "core module changed → diagnosis potentially stale"
  check is a pure file hash comparison — it has no understanding of *what*
  changed, only *that* something did.
