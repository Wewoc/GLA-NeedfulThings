# mutation_runner — Mutation Test Runner

Checks whether your tests would notice a change in the code. [Cosmic Ray](https://github.com/sixty-north/cosmic-ray) changes one spot in a module (e.g. `<` to `<=`) and runs the test file that belongs to the module. A **killed** mutant means a test failed (good); a **survivor** means all tests still passed (a gap, or a harmless change). Your project is never touched — the source tree is copied into `work/` and mutated there.

This runner adds what Cosmic Ray does not do by itself: one test file per module, a status line with ETA, results written per module (so a run can be resumed), a readable report, and a second stage that cross-checks every survivor against all other test files.

## Requirements

- Python 3.11+ with `cosmic-ray==8.7.0` — runs the script. Use a venv of your own, kept outside any temporary folder:
  `python -m venv venv`, then `venv\Scripts\pip install cosmic-ray==8.7.0`. `run_mutation.bat` uses `venv\Scripts\python.exe` automatically when it exists.
- Pin the version: the runner reads Cosmic Ray's internal SQLite tables (`work_items`, `mutation_specs`, `work_results`), which are not a stable interface. A different version may change them.
- A test setup that runs one test file from the command line and exits non-zero on failure (see `TEST_COMMAND`).
- Windows: set by the script itself: `PYTHONUTF8=1`, low process priority.

## Setup

Edit `mutation_config.py` — every value in it is a placeholder:

| Setting | Meaning |
|---|---|
| `SRC_ROOT` | folder that is copied and mutated; contains the package and the tests |
| `PACKAGE_DIR` | folder below `SRC_ROOT` holding the modules to mutate |
| `COPY_IGNORE` | folder names that are not copied (docs, screenshots, …) |
| `TEST_FOR` | module → test file name (no `.py`); **a module without an entry is not mutated** |
| `CRITICAL` | modules to run first |
| `NO_TEST` | modules deliberately not mutated (no warning) |
| `TEST_COMMAND` | argument list that starts one test file, with `{python}` and `{test}` |
| `TEST_PYTHON` | interpreter for the tests (needs your project requirements); `None` = the one running the script |
| `STAGE2_ORDER` | order of the cross-check in stage 2; empty = all test files from `TEST_FOR` |

Examples for `TEST_COMMAND`: plain test scripts `["{python}", "tests/{test}.py"]` (default), pytest `["{python}", "-m", "pytest", "-x", "-q", "tests/{test}.py"]`.

At the start the runner warns about every module that has no `TEST_FOR` entry, and about entries that match no module file. Check this list when you add modules — an unmapped module goes unmeasured, silently in the report and easy to miss.

## Stage 1 — each module against its own test file

```
python run_mutation.py                      # all modules, critical ones first
python run_mutation.py --only my_module     # comma-separated subset (name or sub/module)
python run_mutation.py --only my_module --lines 85-195,226-365   # only mutants on these source lines (one module)
python run_mutation.py --resume results/<run-dir>   # skip modules already done
```

Always check the mapping when a module's tests live in another file than its name suggests: a wrong mapping looks like a pile of survivors. Modules whose test file is red on the untouched code are skipped and listed.

Status line every 15 s (`--interval`): module, mutants done, total x/y, elapsed, ETA.

## Stage 2 — cross-check the survivors against all other test files

A survivor of stage 1 only means "the own test file did not catch it". Stage 2 runs each survivor against every other test file (stop at first failure):

```
python run_mutation.py --stage2 results/<run-dir-1> results/<run-dir-2> --jobs 3
python run_mutation.py --stage2 results/<run-dir> --resume results/<..._combined>
```

- `gap` — survives the whole suite: untested behaviour or a harmless change
- `covered elsewhere (test_xyz)` — another file catches it (not a gap)
- several run dirs are merged into one `..._combined` report

`--jobs N` runs N modules in parallel in separate copies (`work_stage2/`).

## Output (`results/<run-id>/`)

| File | Content |
|---|---|
| `summary.csv` | one row per module: mutants, killed, survived, kill %, (stage 2: covered elsewhere, gaps) |
| `survivors.json` | every survivor: module, test file, line, function, operator, removed/added, diff, kind, stage2 |
| `REPORT.md` | readable summary and survivors per module |
| `modules/*.json` | per-module result, written immediately (basis for `--resume`) |

`kind` is only a rough guess (format/log vs behavior) from the changed line — judge every survivor yourself. `incompetent` = mutant that does not run at all (not counted).

## Notes

- Run time depends mostly on how long one test run takes: mutants × test time. Start with `--only` on one module.
- Interrupt with Ctrl+C or close the window, then `--resume`. Do not run two stage-1 runs at the same time (shared `work/`); stage 1 and stage 2 can run side by side.
- `work/`, `work_stage2/` and `results/` can be deleted at any time.
- The runner never writes into `SRC_ROOT`. Findings are yours to track elsewhere.
