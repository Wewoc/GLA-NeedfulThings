"""
mutation_config.py
Needful Things — Mutation Runner · Configuration

Location: mutation_runner/
Usage:    run_mutation.bat  (or: python run_mutation.py)
Output:   results/YYYY-MM-DD_HHMMSS/summary.csv
          results/YYYY-MM-DD_HHMMSS/survivors.json
          results/YYYY-MM-DD_HHMMSS/REPORT.md
          results/YYYY-MM-DD_HHMMSS/modules/*.json   (basis for --resume)

Every value below is a placeholder for an imaginary project — adjust all of them.
"""

# ── Paths ──────────────────────────────────────────────────────────────────────
# SRC_ROOT is the folder that is copied into work/ and mutated there (your project
# is never touched). Relative to the location of this script (mutation_runner/),
# or absolute. It must contain the package folder AND the tests:
#
#   my_project/src/            <- SRC_ROOT
#       my_package/            <- PACKAGE_DIR (the modules that get mutated)
#       tests/                 <- the test files, started from SRC_ROOT as working dir

SRC_ROOT    = "../my_project/src"    # adjust!
PACKAGE_DIR = "my_package"           # folder below SRC_ROOT holding the modules to mutate

# Folders (names, not paths) that are NOT copied into work/ — anything the tests
# do not need and that only slows the copy down. "__pycache__" is always skipped.
COPY_IGNORE = ["docs", "screenshots"]

# ── Module -> test file ────────────────────────────────────────────────────────
# Key:   module path below PACKAGE_DIR, without ".py" ("sub/module" for sub-folders)
# Value: name of the test file that covers it, without ".py"
#
# A module without an entry is NOT mutated. The runner prints a warning at the start
# and lists it at the end of REPORT.md — check that list after adding modules.
# When a module's tests live in another file than its name suggests, map it there:
# a wrong mapping shows up as a pile of survivors that are not real gaps.

TEST_FOR = {
    "my_module":      "test_my_module",
    "other_module":   "test_basics",
    "sub/helper":     "test_basics",
}

# Run these modules first (a failure there matters most). Same keys as TEST_FOR.
CRITICAL = [
    # "my_module",
]

# Modules that are deliberately not mutated (no warning, reported as "excluded").
NO_TEST = ["__init__"]

# ── How a test file is started ────────────────────────────────────────────────
# A list of arguments, started from SRC_ROOT. Placeholders:
#   {python}  the interpreter from TEST_PYTHON
#   {test}    the test file name from TEST_FOR (without ".py")
# The command must exit with 0 when the tests pass and non-zero when one fails.
#
# Plain test scripts:   ["{python}", "tests/{test}.py"]
# pytest:               ["{python}", "-m", "pytest", "-x", "-q", "tests/{test}.py"]
# unittest:             ["{python}", "-m", "unittest", "tests.{test}"]

TEST_COMMAND = ["{python}", "tests/{test}.py"]

# Interpreter that runs the tests. It needs your project's requirements, which the
# interpreter running this script (the one with cosmic-ray) may not have.
# None = the interpreter that runs this script. Example (Windows):
#   TEST_PYTHON = r"C:\Python313\python.exe"
TEST_PYTHON = None

# ── Stage 2 (--stage2) ────────────────────────────────────────────────────────
# Every survivor of stage 1 is run against ALL other test files, in this order,
# stopping at the first failure. Put slow test files last.
# Empty list = every test file named in TEST_FOR, in order of appearance.
# List a test file here that belongs to no module (e.g. an integration test) to
# include it in the cross-check.

STAGE2_ORDER = []
