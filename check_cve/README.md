# check_cve — CVE Relevance Filter

Runs [pip-audit](https://github.com/pypa/pip-audit) over your requirements file and says which findings are worth a closer look. pip-audit reports vulnerabilities per package; a "high" finding may describe a code path your project never calls. This tool compares each advisory with a list of the functions you actually use. Report only: it never blocks anything, never asks for confirmation, and the exit code is always 0. The decision stays with you — it narrows the list, it does not make the call.

## Verdicts

| Verdict | Meaning |
|---|---|
| `relevant` | the package is in the whitelist **and** the advisory text names one of its `used_functions` — look at this first |
| `unsure` | the package is in the whitelist, but no function name matched (advisories are free text and need not name the function) — not dismissed, not confirmed |
| `not_relevant` | the package is not in the whitelist at all — most likely a transitive dependency your code never calls |

By default only `relevant` findings are listed in detail; `--full` lists all.

For `unsure` findings, the tool can ask a **local** Ollama model whether the advisory text plausibly refers to one of your functions (for example "the encryption routine" against `AESGCM.encrypt`). Nothing leaves your machine; any failure (Ollama not running, timeout, unclear answer) falls back to `unsure`. Set `USE_OLLAMA = False` to skip it.

## Setup

1. `pip install pip-audit` — into the Python that runs the script.
2. Edit `cve_config.py`:

```python
REQUIREMENTS_FILE = "../my_project/requirements.txt"   # relative to check_cve/ (or absolute)
```

   Fill `CVE_WHITELIST` with your packages (the file contains two example entries to replace):

```python
CVE_WHITELIST = {
    "requests": {"used_functions": ["requests.get", "requests.Session"],
                 "note": "HTTP calls — api_client.py"},
}
```

3. Run `run_cve_check.bat` or `python check_cve_whitelist.py [--full]`.

## The whitelist

- `used_functions`: the functions and classes your code really calls — narrow, not the whole package surface. Matching ignores case, `_`, `.` and spaces; longer names are tried first, so `AESGCM.encrypt` wins over `AESGCM`.
- `note`: where it is used, so a later reader can check the entry.
- An **empty** `used_functions` list is allowed: the package counts as used (verdict at most `unsure`, never `not_relevant`), for example for a dependency no code of yours calls directly but the application needs at runtime. Do not guess function names you have not verified.
- Update the list when the project starts or stops using a function.

## Notes

- pip-audit is scoped with `-r <requirements file>`, so it checks what the project declares plus its resolved dependencies, not every package in the active environment.
- pip-audit queries an online advisory service with the names and versions of your dependencies. No source code is sent.
- A passing report is not a security review: advisories lag behind, and the keyword match only finds a function that the advisory text happens to name.
