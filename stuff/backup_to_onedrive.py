"""
backup_to_onedrive.py
─────────────────────────────────────────────────────────────────────────────
Synchronize a local folder 1:1 with a OneDrive backup folder.
Criteria: File name + file size (byte-precise).
Direction: Local is Master - OneDrive follows exactly.

• Local present, OneDrive missing   → copy
• Local present, size differing     → overwrite
• Local present, identical          → skip
• Only on OneDrive present         → delete  (locally deleted = delete from OneDrive)
• Empty folders on OneDrive        → remove after file deletion as well

Configuration: Adjust paths at the beginning of the file (LOCAL_DIR, BACKUP_DIR).
─────────────────────────────────────────────────────────────────────────────
"""

import shutil
import logging
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION — adjust here
# ══════════════════════════════════════════════════════════════════════════════

# Local source folder (recursively searched) — this is the master
LOCAL_DIR = Path(r"C:\your\source\folder")       # local master folder

# Backup target folder on OneDrive
BACKUP_DIR = Path(r"C:\Users\you\OneDrive\Backup") # OneDrive backup target

# Log file (in the same directory as this script)
LOG_FILE = Path(__file__).parent / "backup_to_onedrive.log"

# Folder and filenames that are completely ignored during sync (local & OneDrive)
EXCLUDE_DIRS = {"__pycache__", "garmin_token"}

# Dry-Run: True = only show what would happen, nothing copied
DRY_RUN = False
# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING SETUP
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  CORE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def collect_files(root: Path) -> dict[Path, int]:
    """
    Returns a dict: {relative_path → file_size_in_bytes}
    for all files below root (recursive).
    """
    result = {}
    for entry in root.rglob("*"):
        if entry.is_file():
            rel = entry.relative_to(root)
            if any(part in EXCLUDE_DIRS for part in rel.parts):
                continue
            try:
                result[rel] = entry.stat().st_size
            except OSError as e:
                log.warning(f"  Could not read file: {entry}  ({e})")
    return result


def remove_empty_dirs(root: Path, dry_run: bool = False) -> int:
    """
    Removes empty subfolders below root (bottom-up).
    Returns the number of removed folders.
    """
    removed = 0
    # rglob yields top-down; reversed() makes it bottom-up
    for folder in sorted(root.rglob("*"), reverse=True):
        if folder.is_dir() and folder != root:
            if folder.name in EXCLUDE_DIRS:
                continue
            try:
                if not any(folder.iterdir()):   # really empty?
                    if dry_run:
                        log.info(f"  [DRY-RUN] would delete empty folder: {folder.relative_to(root)}")
                    else:
                        folder.rmdir()
                        log.info(f"  FOLDER DELETED (empty)  {folder.relative_to(root)}")
                    removed += 1
            except OSError as e:
                log.warning(f"  Folder could not be removed: {folder}  ({e})")
    return removed


def run_backup(local_dir: Path, backup_dir: Path, dry_run: bool = False) -> None:
    start = datetime.now()
    log.info("=" * 70)
    log.info(f"Sync started {'[DRY-RUN] ' if dry_run else ''}")
    log.info(f"  Master (local) : {local_dir}")
    log.info(f"  Backup (OneDrive): {backup_dir}")
    log.info("=" * 70)

    # Validation
    if not local_dir.exists():
        log.error(f"Source folder does not exist: {local_dir}")
        return
    if not local_dir.is_dir():
        log.error(f"Source is not a folder: {local_dir}")
        return

    # Read the files
    log.info("Reading local files ...")
    local_files  = collect_files(local_dir)
    log.info("Reading backup files ...")
    backup_files = collect_files(backup_dir) if backup_dir.exists() else {}

    log.info(f"  Local found     : {len(local_files):>6} files")
    log.info(f"  Backup found    : {len(backup_files):>6} files")

    # ── Phase 1: What has to be copied / overwritten? ─────────────────────
    to_copy   = []
    skipped   = 0
    size_diff = 0

    for rel, local_size in local_files.items():
        target = backup_dir / rel
        if rel in backup_files:
            if local_size == backup_files[rel]:
                skipped += 1
            else:
                log.info(f"  DIFFERENT  {rel}  "
                         f"(local={local_size}B  backup={backup_files[rel]}B)")
                to_copy.append((local_dir / rel, target))
                size_diff += 1
        else:
            to_copy.append((local_dir / rel, target))

    # ── Phase 2: What exists only on OneDrive and has to be deleted? ───────────
    to_delete = [
        backup_dir / rel
        for rel in backup_files
        if rel not in local_files
    ]

    log.info("-" * 70)
    log.info(f"  Identical (skipped)     : {skipped:>6}")
    log.info(f"  Different (overwrite)   : {size_diff:>6}")
    log.info(f"  Missing (copy new)      : {len(to_copy) - size_diff:>6}")
    log.info(f"  Total to copy           : {len(to_copy):>6}")
    log.info(f"  Only on OneDrive (delete): {len(to_delete):>5}")
    log.info("-" * 70)

    copied = 0
    errors = 0

    # ── Copy ──────────────────────────────────────────────────────────────
    for src, dst in to_copy:
        rel_display = src.relative_to(local_dir)
        if dry_run:
            log.info(f"  [DRY-RUN] would copy: {rel_display}")
            copied += 1
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log.info(f"  COPIED  {rel_display}")
            copied += 1
        except Exception as e:
            log.error(f"  ERROR (copy)  {rel_display}  →  {e}")
            errors += 1

    # ── Delete (OneDrive-only files) ──────────────────────────────────────
    deleted = 0
    for dst in to_delete:
        rel_display = dst.relative_to(backup_dir)
        if dry_run:
            log.info(f"  [DRY-RUN] would delete: {rel_display}")
            deleted += 1
            continue
        try:
            dst.unlink()
            log.info(f"  DELETED  {rel_display}")
            deleted += 1
        except Exception as e:
            log.error(f"  ERROR (delete)  {rel_display}  →  {e}")
            errors += 1

    # ── Clean up empty folders ────────────────────────────────────────────────
    removed_dirs = 0
    if backup_dir.exists():
        removed_dirs = remove_empty_dirs(backup_dir, dry_run=dry_run)

    _log_summary(start, skipped, copied, deleted, removed_dirs, errors, dry_run)


def _log_summary(
    start: datetime,
    skipped: int,
    copied: int,
    deleted: int,
    removed_dirs: int,
    errors: int,
    dry_run: bool = False,
) -> None:
    elapsed = datetime.now() - start
    log.info("=" * 70)
    log.info(f"Sync finished {'[DRY-RUN] ' if dry_run else ''}in {elapsed.total_seconds():.1f}s")
    log.info(f"  Skipped           : {skipped}")
    log.info(f"  Copied            : {copied}")
    log.info(f"  Deleted (files)   : {deleted}")
    log.info(f"  Deleted (folders) : {removed_dirs}")
    log.info(f"  Errors            : {errors}")
    log.info("=" * 70)


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_backup(LOCAL_DIR, BACKUP_DIR, dry_run=DRY_RUN)