#!/usr/bin/env python3
"""
repo_diff.py
Compares a local working folder against the current state of a GitHub repo (HEAD).

Result: categorized list of changed files.
  MODIFIED  — present in both, content differs
  NEW       — local only (not yet on GitHub)
  DELETED   — on GitHub only (removed locally)
  IDENTICAL — unchanged (shown only with SHOW_IDENTICAL = True in config.py)

Comparison method: Git blob SHA1
  GitHub internally uses SHA1 hashes via the Trees API.
  Locally the same hash is computed: sha1("blob {size}\0{content}")
  → Detects every content difference, including text changes of equal size.

Usage:
  python repo_diff.py

Output: diff.md written next to this script.
"""

import hashlib
import urllib.request
import json
from pathlib import Path

from config import (
    GITHUB_TOKEN, REPO_OWNER, REPO_NAME, BRANCH,
    LOCAL_DIR, IGNORE, SHOW_IDENTICAL,
)

# ── GitHub API ─────────────────────────────────────────────────────────────────

def github_request(url: str) -> dict | list:
    req = urllib.request.Request(url)
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "git-analyse")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def fetch_repo_tree() -> dict[str, str]:
    url  = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/git/trees/{BRANCH}?recursive=1"
    data = github_request(url)
    if data.get("truncated"):
        print("  WARNING: Repo tree was truncated by GitHub (>100k files).")
    return {
        item["path"]: item["sha"]
        for item in data.get("tree", [])
        if item["type"] == "blob"
        and not any(part in IGNORE for part in Path(item["path"]).parts)
    }

# ── Local files ────────────────────────────────────────────────────────────────

def git_blob_sha1(path: Path) -> str:
    data   = path.read_bytes()
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def is_ignored(rel: Path) -> bool:
    for pattern in IGNORE:
        if pattern.startswith("*"):
            if any(p.endswith(pattern[1:]) for p in rel.parts):
                return True
        else:
            if pattern in rel.parts:
                return True
    return False


def collect_local_files(root: Path) -> dict[str, str]:
    result = {}
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        rel = entry.relative_to(root)
        if is_ignored(rel):
            continue
        try:
            result[rel.as_posix()] = git_blob_sha1(entry)
        except OSError as e:
            print(f"  WARNING: Could not read {rel.as_posix()}: {e}")
    return result

# ── Diff ───────────────────────────────────────────────────────────────────────

def run_diff() -> str:
    lines = []
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"  REPO DIFF  —  {REPO_OWNER}/{REPO_NAME}  [{BRANCH}]")
    lines.append("=" * 70)
    lines.append(f"  Local : {LOCAL_DIR.resolve()}")
    lines.append("")

    if not LOCAL_DIR.exists():
        lines.append(f"  ERROR: Local folder not found: {LOCAL_DIR}")
        return "\n".join(lines)

    if not GITHUB_TOKEN:
        lines.append("  WARNING: No GITHUB_TOKEN found — anonymous requests (60/h limit).")

    lines.append("  Fetching repo tree from GitHub ...")
    try:
        repo_files = fetch_repo_tree()
    except Exception as e:
        lines.append(f"  ERROR fetching GitHub tree: {e}")
        return "\n".join(lines)
    lines.append(f"  GitHub : {len(repo_files):>5} files")

    lines.append("  Reading local files ...")
    local_files = collect_local_files(LOCAL_DIR)
    lines.append(f"  Local  : {len(local_files):>5} files (after IGNORE filter)")
    lines.append("")

    modified = []
    new_local = []
    deleted = []
    identical = []

    for path in sorted(set(repo_files) | set(local_files)):
        in_repo  = path in repo_files
        in_local = path in local_files
        if in_repo and in_local:
            if repo_files[path] == local_files[path]:
                identical.append(path)
            else:
                modified.append(path)
        elif in_local:
            new_local.append(path)
        else:
            deleted.append(path)

    def section(title, files, marker):
        if not files:
            return
        lines.append(f"  ── {title}")
        for f in files:
            lines.append(f"    {marker}  {f}")
        lines.append("")

    section("MODIFIED  (changed locally, not yet on GitHub)", modified,  "~")
    section("NEW       (local only, missing on GitHub)",      new_local, "+")
    section("DELETED   (on GitHub, removed locally)",         deleted,   "-")
    if SHOW_IDENTICAL:
        section("IDENTICAL (unchanged)", identical, "=")

    lines.append("─" * 70)
    lines.append(f"  Summary:")
    lines.append(f"    ~ Modified  : {len(modified):>4}")
    lines.append(f"    + New       : {len(new_local):>4}")
    lines.append(f"    - Deleted   : {len(deleted):>4}")
    lines.append(f"    = Identical : {len(identical):>4}")
    lines.append("")
    total = len(modified) + len(new_local) + len(deleted)
    if total == 0:
        lines.append("  ✓ Local folder is identical to GitHub.")
    else:
        lines.append(f"  → {total} file(s) differ from GitHub.")
    lines.append("=" * 70)
    lines.append("")
    return "\n".join(lines)


def main():
    output   = run_diff()
    print(output)
    md_path  = Path(__file__).parent / "diff.md"
    md_path.write_text(output, encoding="utf-8")
    print(f"  → diff.md written: {md_path}")


if __name__ == "__main__":
    main()
