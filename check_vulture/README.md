# check_vulture — Dead Code Finder

Runs [Vulture](https://github.com/jendrikseipp/vulture) over your source tree and sorts the findings, so a list of "unused" code is something you can act on instead of something you scroll past. Report only: it never blocks a build or a test run, and it never touches your code.

## What it does

Vulture runs twice against the source root:

| Run | Scope |
|---|---|
| A — production | everything except the tests folder and the folders in `EXCLUDED_ALWAYS` |
| B — production + tests | Run A's scope plus the tests folder |

Run B can only find a subset of what Run A finds (more references, never fewer), so Run A alone is the complete candidate list. Run B only labels each finding:

- `dead_everywhere` — still unused even when the tests are counted
- `test_only` — production never calls it, a test still does

Both runs are filtered against `VULTURE_WHITELIST` **after** parsing, by `(file, name)`. Vulture's own whitelist matches by name only, so a generic name (`alignment`, `mousePressEvent`) confirmed as a false positive in one file would hide a genuinely dead one elsewhere. Path separators are compared normalized, so a list written on Windows works on Linux.

Exit code 0 only if Run A found nothing after the whitelist. That is a signal for the person running it, not a build gate.

## Setup

1. `pip install vulture` — into the Python that runs the script.
2. Edit `vulture_config.py`:

```python
SRC_ROOT        = "../my_project/src"   # source root, relative to check_vulture/ (or absolute)
TESTS_DIR       = "tests"               # tests folder below SRC_ROOT
EXCLUDED_ALWAYS = []                    # folders scanned in neither run (build tooling, probes)
```

Optional: `MIN_CONFIDENCE` (default 60), `OUTPUT_FILE` (default `output/vulture.json`), `VERSION_FILE` and `VERSION_VARIABLE` (record the project version in the result).

3. Run `run_vulture_check.bat` or `python check_vulture.py [--target-version vX.Y.Z]`.

## The whitelist

`VULTURE_WHITELIST` in `vulture_config.py`: `{(file, name): "reason"}`, with the file path as Vulture reports it, relative to `SRC_ROOT`.

Vulture cannot see code that is reached only by name or by decorator — GUI event handlers called by the framework, plugin or tool registration, attributes a library reads internally. Those show up as unused although they are load-bearing. Build the list from real findings, not preemptively, one narrow entry per confirmed false positive, each with a reason a later reader can verify.

## Output

A report on the console and `output/vulture.json` (scan time, project version, whitelist count, total and every finding with file, line, kind, name, confidence and status). Other tools can read the JSON.

## Notes

- Vulture works on static code only. It reports a name as used if the name appears anywhere, so it also misses dead code that shares a name with live code.
- `output/` is ignored by Git.
