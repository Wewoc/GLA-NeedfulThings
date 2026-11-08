#!/usr/bin/env python3
"""Mutation test runner (Cosmic Ray), one test file per module.

Never touches your project: the source tree is copied into ./work first and mutated
there. Per module: init -> baseline -> exec, status line every 15 s, results written
per module right away (so --resume can skip finished modules).

What is mutated, which test file belongs to which module and how a test file is
started is set in mutation_config.py next to this script.

Output (results/<run-id>/):
  summary.csv     one row per module
  survivors.json  every surviving mutant with module, line, operator, diff
  REPORT.md       readable summary + survivors per module

Usage (needs cosmic-ray installed in the interpreter that runs this script):
  python run_mutation.py                       # all modules, critical first
  python run_mutation.py --only my_module      # comma-separated subset
  python run_mutation.py --only my_module --lines 85-195,226-365   # only mutants on these source lines
  python run_mutation.py --resume results/<run-id>
  python run_mutation.py --src path\\to\\src --interval 15 --timeout 120
  python run_mutation.py --stage2 results/<run-id> --jobs 3   # cross-check survivors
"""
import argparse
import csv
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "mutation_config.py"
LOW_PRIORITY = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS (Windows)


def load_config():
    """Import mutation_config.py from next to this script; stop with a clear message if it is unusable."""
    if not CONFIG_FILE.exists():
        sys.exit(f"config not found: {CONFIG_FILE}")
    spec = importlib.util.spec_from_file_location("mutation_config", CONFIG_FILE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # any error inside the config is reported the same way
        sys.exit(f"cannot load {CONFIG_FILE.name}: {exc!r}")
    missing = [n for n in ("SRC_ROOT", "PACKAGE_DIR", "TEST_FOR") if not hasattr(module, n)]
    if missing:
        sys.exit(f"{CONFIG_FILE.name}: missing setting(s): {', '.join(missing)}")
    if not isinstance(module.TEST_FOR, dict) or not module.TEST_FOR:
        sys.exit(f"{CONFIG_FILE.name}: TEST_FOR must be a non-empty dict (module -> test file name)")
    cmd = getattr(module, "TEST_COMMAND", ["{python}", "tests/{test}.py"])
    if not isinstance(cmd, (list, tuple)) or not all(isinstance(x, str) for x in cmd) \
            or not any("{test}" in x for x in cmd):
        sys.exit(f"{CONFIG_FILE.name}: TEST_COMMAND must be a list of strings that contains {{test}}")
    return module


CFG = load_config()
SRC_ROOT = (HERE / CFG.SRC_ROOT).resolve()
PACKAGE_DIR = CFG.PACKAGE_DIR.strip("/\\")
# module (path below SRC_ROOT/PACKAGE_DIR) -> test file name (without .py) that belongs to it
TEST_FOR = CFG.TEST_FOR
# modules where a failure matters most: run first
CRITICAL = list(getattr(CFG, "CRITICAL", []))
NO_TEST = list(getattr(CFG, "NO_TEST", []))  # reported, not mutated, no warning
TEST_COMMAND = list(getattr(CFG, "TEST_COMMAND", ["{python}", "tests/{test}.py"]))
TEST_PYTHON = getattr(CFG, "TEST_PYTHON", None) or sys.executable
COPY_IGNORE = ("__pycache__",) + tuple(getattr(CFG, "COPY_IGNORE", ()))
STAGE2_ORDER = list(getattr(CFG, "STAGE2_ORDER", [])) or list(dict.fromkeys(TEST_FOR.values()))

FORMAT_HINTS = ("indent", "ensure_ascii", "sort_keys", "log.", "logger.", "logging.", "print(")


def quote_arg(arg):
    """Quote an argument for the Cosmic Ray test-command line if it has a space or is an absolute path."""
    if "'" in arg:
        sys.exit(f"a single quote in the test command cannot be written to the Cosmic Ray config: {arg}")
    return f'"{arg}"' if (" " in arg or os.path.isabs(arg)) else arg


def command_for(args, test, python):
    """TEST_COMMAND with {python} and {test} filled in, as one string."""
    return " ".join(quote_arg(a.replace("{python}", python).replace("{test}", test)) for a in args)


def order(mods):
    first = [m for m in CRITICAL if m in mods]
    return first + sorted(m for m in mods if m not in first)


def cr_exe(name):
    exe = Path(sys.executable).parent / (name + (".exe" if os.name == "nt" else ""))
    if not exe.exists():
        sys.exit(f"{exe} not found - install cosmic-ray into the interpreter running this script")
    return str(exe)


def run(cmd, cwd, env, **kw):
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, creationflags=LOW_PRIORITY if os.name == "nt" else 0, **kw)


def fmt(sec):
    sec = int(sec)
    return f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s"


def count(db, table):
    try:
        with sqlite3.connect(db) as c:
            return c.execute(f"select count(*) from {table}").fetchone()[0]
    except sqlite3.Error:
        return 0


def classify(diff):
    changed = [ln[1:] for ln in diff.splitlines()
               if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    return "format/log (likely harmless)" if changed and any(h in " ".join(changed) for h in FORMAT_HINTS) \
        else "behavior (check)"


def collect(db, mod, test):
    stats = {"module": mod, "test_file": test + ".py", "mutants": 0, "killed": 0, "survived": 0,
             "incompetent": 0, "timeout": 0, "pending": 0}
    survivors = []
    with sqlite3.connect(db) as c:
        stats["mutants"] = c.execute("select count(*) from work_items").fetchone()[0]
        rows = c.execute(
            "select s.job_id, s.operator_name, s.start_pos_row, s.definition_name, r.test_outcome, r.diff "
            "from mutation_specs s left join work_results r using(job_id) order by s.start_pos_row").fetchall()
    for job, op, line, func, outcome, diff in rows:
        if outcome is None:
            stats["pending"] += 1
        elif outcome == "KILLED":
            stats["killed"] += 1
        elif outcome == "INCOMPETENT":
            stats["incompetent"] += 1
        elif outcome == "TIMEOUT":
            stats["timeout"] += 1
        elif outcome == "SURVIVED":
            stats["survived"] += 1
            d = diff or ""
            removed = [x[1:].strip() for x in d.splitlines() if x.startswith("-") and not x.startswith("---")]
            added = [x[1:].strip() for x in d.splitlines() if x.startswith("+") and not x.startswith("+++")]
            survivors.append({"module": mod, "test_file": test + ".py", "job_id": job, "line": line,
                              "function": func, "operator": op, "kind": classify(d),
                              "removed": " ".join(removed), "added": " ".join(added), "diff": d})
    judged = stats["killed"] + stats["survived"] + stats["timeout"]
    stats["kill_rate_pct"] = round(100 * (stats["killed"] + stats["timeout"]) / judged, 1) if judged else ""
    return stats, survivors


def write_outputs(out, modstats, survivors, skipped, started):
    cols = ["module", "test_file", "mutants", "killed", "survived", "incompetent", "timeout",
            "pending", "kill_rate_pct", "seconds"]
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(modstats)
    (out / "survivors.json").write_text(json.dumps(survivors, indent=2, ensure_ascii=False), encoding="utf-8")
    tot = {k: sum(m.get(k, 0) for m in modstats) for k in ("mutants", "killed", "survived", "incompetent", "timeout")}
    L = [f"# Mutation report - {out.name}", "",
         f"Started {started:%Y-%m-%d %H:%M}, {len(modstats)} modules, "
         f"{tot['mutants']} mutants: {tot['killed']} killed, {tot['survived']} survived, "
         f"{tot['incompetent']} incompetent, {tot['timeout']} timeout.", "",
         "| module | test file | mutants | killed | survived | kill % |", "|---|---|---:|---:|---:|---:|"]
    for m in modstats:
        L.append(f"| {m['module']} | {m['test_file']} | {m['mutants']} | {m['killed']} | "
                 f"{m['survived']} | {m['kill_rate_pct']} |")
    if skipped:
        L += ["", "Not mutated: " + "; ".join(f"{k} ({v})" for k, v in skipped.items())]
    L += ["", "## Survivors", "",
          "Kind is a rough guess from the changed line (format/log vs behavior); judge each one.", ""]
    for m in modstats:
        mine = [s for s in survivors if s["module"] == m["module"]]
        if not mine:
            continue
        L += [f"### {m['module']} ({len(mine)})", ""]
        for s in mine:
            L += [f"- line {s['line']} in `{s['function']}` - {s['operator']} - **{s['kind']}**",
                  f"  - `{s['removed']}` -> `{s['added']}`"]
        L.append("")
    (out / "REPORT.md").write_text("\n".join(L), encoding="utf-8")


def _force_remove(func, path, _exc):
    os.chmod(path, 0o700)  # read-only files/dirs block deletion on Windows
    func(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC_ROOT))
    ap.add_argument("--only", default="")
    ap.add_argument("--resume", default="")
    ap.add_argument("--test-python", default=TEST_PYTHON,
                    help="interpreter for the test files (needs the project requirements); "
                         "default: TEST_PYTHON from the config, else this interpreter")
    ap.add_argument("--lines", default="",
                    help="only mutants on these source lines, e.g. 85-195,226-365 (use with a single --only module)")
    ap.add_argument("--interval", type=int, default=15)
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds per mutant")
    ap.add_argument("--stage2", nargs="+", default=[], metavar="RUN_DIR",
                    help="cross-check the survivors of these run dirs against all other test files")
    ap.add_argument("--jobs", type=int, default=3, help="parallel modules in --stage2")
    a = ap.parse_args()
    if a.stage2:
        return stage2(a)

    started = datetime.now()
    out = Path(a.resume) if a.resume else HERE / "results" / started.strftime("%Y-%m-%d_%H%M%S")
    (out / "modules").mkdir(parents=True, exist_ok=True)
    work = HERE / "work"
    src = Path(a.src)

    if not (src / PACKAGE_DIR).is_dir():
        sys.exit(f"package folder not found: {src / PACKAGE_DIR} (check SRC_ROOT / PACKAGE_DIR in the config)")
    mods = sorted(p.relative_to(src / PACKAGE_DIR).with_suffix("").as_posix()
                  for p in (src / PACKAGE_DIR).rglob("*.py") if "__pycache__" not in p.parts)
    skipped = {m: "excluded (NO_TEST)" if m in NO_TEST else "no test file" for m in mods if m not in TEST_FOR}
    unmapped = sorted(m for m in skipped if m not in NO_TEST)
    if unmapped:
        print("WARNING: no entry in TEST_FOR, not mutated: " + ", ".join(unmapped), flush=True)
    stale = sorted(m for m in TEST_FOR if m not in mods)
    if stale:
        print("WARNING: TEST_FOR entries without a module file: " + ", ".join(stale), flush=True)
    mods = [m for m in mods if m in TEST_FOR]
    if a.only:
        wanted = [x.strip() for x in a.only.split(",")]
        mods = [m for m in mods if m in wanted or m.split("/")[-1] in wanted]
    mods = order(mods)

    # fresh copy of src (the repo is never mutated)
    for attempt in range(10):  # Windows may hold files briefly (indexer, antivirus)
        if not work.exists():
            break
        try:
            shutil.rmtree(work, onerror=_force_remove)
        except OSError:
            time.sleep(2)
    else:
        sys.exit(f"cannot remove {work}")
    shutil.copytree(src, work / "src", ignore=shutil.ignore_patterns(*COPY_IGNORE))
    cwd = work / "src"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cosmic, py = cr_exe("cosmic-ray"), a.test_python

    done = {m for m in mods if (out / "modules" / (m.replace("/", "__") + ".json")).exists()}
    todo = [m for m in mods if m not in done]
    modstats, survivors = [], []
    for m in done:  # reload finished modules
        d = json.loads((out / "modules" / (m.replace("/", "__") + ".json")).read_text(encoding="utf-8"))
        modstats.append(d["stats"])
        survivors += d["survivors"]

    # init everything first, so x/y over all mutants is known
    plan = {}
    for m in todo:
        t = TEST_FOR[m]
        tag = m.replace("/", "__")
        toml, db = cwd / f"cr_{tag}.toml", cwd / f"cr_{tag}.sqlite"
        toml.write_text("\n".join([
            "[cosmic-ray]",
            f'module-path = "{PACKAGE_DIR}/{m}.py"',
            f"timeout = {a.timeout}",
            "excluded-modules = []",
            f"test-command = '{command_for(TEST_COMMAND, t, py)}'",
            "",
            "[cosmic-ray.distributor]",
            'name = "local"',
            ""]), encoding="utf-8")
        r = run([cosmic, "init", str(toml), str(db)], cwd, env)
        if r.returncode == 0 and a.lines:
            keep = [tuple(int(x) for x in part.split("-")) for part in a.lines.split(",")]
            with sqlite3.connect(db) as c:
                drop = [j for j, row in c.execute("select job_id, start_pos_row from mutation_specs").fetchall()
                        if not any(lo <= row <= hi for lo, hi in keep)]
                c.executemany("delete from mutation_specs where job_id=?", [(j,) for j in drop])
                c.executemany("delete from work_items where job_id=?", [(j,) for j in drop])
        plan[m] = (t, toml, db, count(db, "work_items") if r.returncode == 0 else -1)
    total = sum(max(p[3], 0) for p in plan.values())
    print(f"{len(todo)} modules, {total} mutants to run (results: {out})", flush=True)

    base_done, t0 = 0, time.time()
    for i, m in enumerate(todo, 1):
        t, toml, db, n = plan[m]
        if n <= 0:
            skipped[m] = "init failed or no mutants"
            continue
        b = run([cosmic, "baseline", str(toml)], cwd, env)
        if b.returncode != 0:
            skipped[m] = f"baseline red with {t}.py"
            print(f"[{i}/{len(todo)}] {m}: BASELINE RED - skipped", flush=True)
            continue
        ts = time.time()
        proc = subprocess.Popen([cosmic, "exec", str(toml), str(db)], cwd=cwd, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=LOW_PRIORITY if os.name == "nt" else 0)
        nxt = 0.0
        while proc.poll() is None:
            time.sleep(1)
            if time.time() >= nxt:
                nxt = time.time() + a.interval
                c = count(db, "work_results")
                allc = base_done + c
                el = time.time() - t0
                eta = fmt(el / allc * (total - allc)) if allc else "?"
                print(f"[{i}/{len(todo)}] {m}: {c}/{n} | total {allc}/{total} "
                      f"({100 * allc // max(total, 1)}%) | elapsed {fmt(el)} | ETA {eta}", flush=True)
        base_done += n
        stats, surv = collect(db, m, t)
        stats["seconds"] = int(time.time() - ts)
        (out / "modules" / (m.replace("/", "__") + ".json")).write_text(
            json.dumps({"stats": stats, "survivors": surv}, indent=1, ensure_ascii=False), encoding="utf-8")
        modstats.append(stats)
        survivors += surv
        print(f"[{i}/{len(todo)}] {m} done: {stats['killed']} killed, {stats['survived']} survived, "
              f"{stats['incompetent']} incompetent ({stats['seconds']}s)", flush=True)
        write_outputs(out, order_stats(modstats), survivors, skipped, started)

    write_outputs(out, order_stats(modstats), survivors, skipped, started)
    print(f"finished in {fmt(time.time() - t0)} - see {out / 'REPORT.md'}", flush=True)


# ── stage 2: cross-check survivors against every other test file ──────────────
S2_RUNNER = '''import subprocess, sys
CMD = %s
own, names = sys.argv[1], sys.argv[2:]
for n in names:
    if n == own:
        continue
    cmd = [x.replace("{python}", sys.executable).replace("{test}", n) for x in CMD]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print("KILLED_BY:" + n)
        sys.exit(1)
'''


def _removed_added(diff):
    d = diff or ""
    rem = " ".join(x[1:].strip() for x in d.splitlines() if x.startswith("-") and not x.startswith("---"))
    add = " ".join(x[1:].strip() for x in d.splitlines() if x.startswith("+") and not x.startswith("+++"))
    return rem, add


def stage2(a):
    import re
    from concurrent.futures import ThreadPoolExecutor

    started = datetime.now()
    data = {}
    for d in a.stage2:
        for f in sorted((Path(d) / "modules").glob("*.json")):
            j = json.loads(f.read_text(encoding="utf-8"))
            data[j["stats"]["module"]] = j
    mods = [m for m in order(list(data)) if data[m]["survivors"]]
    if a.only:
        wanted = [x.strip() for x in a.only.split(",")]
        mods = [m for m in mods if m in wanted or m.split("/")[-1] in wanted]
    out = Path(a.resume) if a.resume else HERE / "results" / (started.strftime("%Y-%m-%d_%H%M%S") + "_combined")
    (out / "modules").mkdir(parents=True, exist_ok=True)
    done = {m for m in mods if (out / "modules" / (m.replace("/", "__") + ".json")).exists()}

    work = HERE / "work_stage2"
    for attempt in range(10):
        if not work.exists():
            break
        try:
            shutil.rmtree(work, onerror=_force_remove)
        except OSError:
            time.sleep(2)
    cwds = []
    for k in range(a.jobs):
        c = work / f"s{k}"
        shutil.copytree(Path(a.src), c, ignore=shutil.ignore_patterns(*COPY_IGNORE))
        (c / "stage2_runner.py").write_text(S2_RUNNER % json.dumps(TEST_COMMAND), encoding="utf-8")
        cwds.append(c)
    (work / "db").mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cosmic, py = cr_exe("cosmic-ray"), a.test_python

    plan = {}  # module -> (toml, db, n)
    for m in mods:
        if m in done:
            continue
        tag = m.replace("/", "__")
        own = TEST_FOR[m]
        names = " ".join(n for n in STAGE2_ORDER if n != own)
        toml, db = work / "db" / f"{tag}.toml", work / "db" / f"{tag}.sqlite"
        toml.write_text("\n".join([
            "[cosmic-ray]", f'module-path = "{PACKAGE_DIR}/{m}.py"', f"timeout = {a.timeout * 2}",
            "excluded-modules = []",
            f"test-command = '{quote_arg(py)} stage2_runner.py {own} {names}'", "",
            "[cosmic-ray.distributor]", 'name = "local"', ""]), encoding="utf-8")
        r = run([cosmic, "init", str(toml), str(db)], cwds[0], env)
        if r.returncode != 0:
            continue
        keys = {(s["line"], s["operator"]) for s in data[m]["survivors"]}
        with sqlite3.connect(db) as c:
            drop = [j for j, row, op in c.execute(
                "select job_id, start_pos_row, operator_name from mutation_specs") if (row, op) not in keys]
            c.executemany("delete from mutation_specs where job_id=?", [(j,) for j in drop])
            c.executemany("delete from work_items where job_id=?", [(j,) for j in drop])
            n = c.execute("select count(*) from work_items").fetchone()[0]
        plan[m] = (toml, db, n)
    total = sum(p[2] for p in plan.values())
    print(f"stage 2: {len(plan)} modules, {total} candidate mutants, {a.jobs} jobs (results: {out})", flush=True)

    prog = {m: 0 for m in plan}
    finished = []
    slots = list(range(a.jobs))
    import threading
    lock = threading.Lock()

    def work_module(m):
        with lock:
            k = slots.pop()
        try:
            toml, db, n = plan[m]
            cwd = cwds[k]
            b = run([cosmic, "baseline", str(toml)], cwd, env)
            if b.returncode != 0:
                return m, "baseline red in stage 2 (other test files fail on pristine code)"
            p = subprocess.Popen([cosmic, "exec", str(toml), str(db)], cwd=cwd, env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=LOW_PRIORITY if os.name == "nt" else 0)
            while p.poll() is None:
                time.sleep(1)
                prog[m] = count(db, "work_results")
            prog[m] = n
            res = {}
            with sqlite3.connect(db) as c:
                for row, op, outcome, diff, output in c.execute(
                        "select s.start_pos_row, s.operator_name, r.test_outcome, r.diff, r.output "
                        "from mutation_specs s join work_results r using(job_id)"):
                    rem, add = _removed_added(diff)
                    kb = re.search(r"KILLED_BY:(\w+)", output or "")
                    res[(row, op, rem, add)] = (outcome, kb.group(1) if kb else None)
            for s in data[m]["survivors"]:
                outcome, by = res.get((s["line"], s["operator"], s["removed"], s["added"]), (None, None))
                s["stage2"] = ("gap" if outcome == "SURVIVED" else
                               f"covered elsewhere ({by or outcome})" if outcome else "unmatched")
            (out / "modules" / (m.replace("/", "__") + ".json")).write_text(
                json.dumps(data[m], indent=1, ensure_ascii=False), encoding="utf-8")
            return m, None
        finally:
            with lock:
                slots.append(k)

    t0 = time.time()
    skipped = {}
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(work_module, m) for m in plan]
        nxt = 0.0
        while not all(f.done() for f in futs):
            time.sleep(1)
            if time.time() >= nxt:
                nxt = time.time() + a.interval
                x = sum(prog.values())
                el = time.time() - t0
                active = [m for m, v in prog.items() if 0 < v < plan[m][2]]
                eta = fmt(el / x * (total - x)) if x else "?"
                print(f"stage2 {x}/{total} ({100 * x // max(total, 1)}%) | modules done "
                      f"{sum(f.done() for f in futs)}/{len(futs)} | active: {', '.join(active)} | "
                      f"elapsed {fmt(el)} | ETA {eta}", flush=True)
        for f in futs:
            m, err = f.result()
            if err:
                skipped[m] = err

    # combined output (stage 1 + stage 2) for every module of the given runs
    rows, allsurv = [], []
    for m in order(list(data)):
        j = data[m]
        f = out / "modules" / (m.replace("/", "__") + ".json")
        if f.exists():
            j = json.loads(f.read_text(encoding="utf-8"))
        st, sv = j["stats"], j["survivors"]
        if sv and not any("stage2" in s for s in sv):
            st = dict(st, stage2="not checked")
        gap = sum(1 for s in sv if s.get("stage2") == "gap")
        else_ = sum(1 for s in sv if str(s.get("stage2", "")).startswith("covered"))
        rows.append(dict(st, covered_elsewhere=else_, gaps=gap,
                         unchecked=len(sv) - gap - else_))
        allsurv += sv
    cols = ["module", "test_file", "mutants", "killed", "survived", "covered_elsewhere", "gaps",
            "unchecked", "incompetent", "kill_rate_pct"]
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (out / "survivors.json").write_text(json.dumps(allsurv, indent=2, ensure_ascii=False), encoding="utf-8")
    L = [f"# Mutation report (stage 1 + 2) - {out.name}", "",
         "Stage 1: each mutant against the test file of its own module. Stage 2: every survivor against all "
         "other test files. `gap` = survives the whole suite, `covered elsewhere` = another file kills it.", "",
         "| module | mutants | killed (own file) | survived | covered elsewhere | **gaps** | unchecked |",
         "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        L.append(f"| {r['module']} | {r['mutants']} | {r['killed']} | {r['survived']} | "
                 f"{r['covered_elsewhere']} | **{r['gaps']}** | {r['unchecked']} |")
    if skipped:
        L += ["", "Not cross-checked: " + "; ".join(f"{k} ({v})" for k, v in skipped.items())]
    L += ["", "## Gaps (survive the whole suite)", ""]
    for r in rows:
        mine = [s for s in allsurv if s["module"] == r["module"] and s.get("stage2") == "gap"]
        if not mine:
            continue
        L += [f"### {r['module']} ({len(mine)})", ""]
        for s in mine:
            L += [f"- line {s['line']} in `{s['function']}` - {s['operator']} - **{s['kind']}**",
                  f"  - `{s['removed']}` -> `{s['added']}`"]
        L.append("")
    (out / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print(f"stage 2 finished in {fmt(time.time() - t0)} - see {out / 'REPORT.md'}", flush=True)


def order_stats(stats):
    pos = {m: i for i, m in enumerate(order([s["module"] for s in stats]))}
    return sorted(stats, key=lambda s: pos[s["module"]])


if __name__ == "__main__":
    main()
