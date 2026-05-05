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
#  KERN-LOGIK
# ══════════════════════════════════════════════════════════════════════════════

def collect_files(root: Path) -> dict[Path, int]:
    """
    Gibt ein Dict zurück: {relativer_pfad → dateigröße_in_bytes}
    für alle Dateien unterhalb von root (rekursiv).
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
                log.warning(f"  Konnte Datei nicht lesen: {entry}  ({e})")
    return result


def remove_empty_dirs(root: Path, dry_run: bool = False) -> int:
    """
    Entfernt leere Unterordner unterhalb von root (bottom-up).
    Gibt die Anzahl entfernter Ordner zurück.
    """
    removed = 0
    # rglob liefert top-down; reversed() macht daraus bottom-up
    for folder in sorted(root.rglob("*"), reverse=True):
        if folder.is_dir() and folder != root:
            if folder.name in EXCLUDE_DIRS:
                continue
            try:
                if not any(folder.iterdir()):   # wirklich leer?
                    if dry_run:
                        log.info(f"  [DRY-RUN] würde leeren Ordner löschen: {folder.relative_to(root)}")
                    else:
                        folder.rmdir()
                        log.info(f"  ORDNER GELÖSCHT (leer)  {folder.relative_to(root)}")
                    removed += 1
            except OSError as e:
                log.warning(f"  Ordner konnte nicht entfernt werden: {folder}  ({e})")
    return removed


def run_backup(local_dir: Path, backup_dir: Path, dry_run: bool = False) -> None:
    start = datetime.now()
    log.info("=" * 70)
    log.info(f"Sync gestartet {'[DRY-RUN] ' if dry_run else ''}")
    log.info(f"  Master (lokal) : {local_dir}")
    log.info(f"  Backup (OneDrive): {backup_dir}")
    log.info("=" * 70)

    # Validierung
    if not local_dir.exists():
        log.error(f"Quellordner existiert nicht: {local_dir}")
        return
    if not local_dir.is_dir():
        log.error(f"Quelle ist kein Ordner: {local_dir}")
        return

    # Dateien einlesen
    log.info("Lese lokale Dateien ...")
    local_files  = collect_files(local_dir)
    log.info("Lese Backup-Dateien ...")
    backup_files = collect_files(backup_dir) if backup_dir.exists() else {}

    log.info(f"  Lokal gefunden  : {len(local_files):>6} Dateien")
    log.info(f"  Backup gefunden : {len(backup_files):>6} Dateien")

    # ── Phase 1: Was muss kopiert / überschrieben werden? ─────────────────────
    to_copy   = []
    skipped   = 0
    size_diff = 0

    for rel, local_size in local_files.items():
        target = backup_dir / rel
        if rel in backup_files:
            if local_size == backup_files[rel]:
                skipped += 1
            else:
                log.info(f"  ABWEICHEND  {rel}  "
                         f"(lokal={local_size}B  backup={backup_files[rel]}B)")
                to_copy.append((local_dir / rel, target))
                size_diff += 1
        else:
            to_copy.append((local_dir / rel, target))

    # ── Phase 2: Was ist nur auf OneDrive und muss gelöscht werden? ───────────
    to_delete = [
        backup_dir / rel
        for rel in backup_files
        if rel not in local_files
    ]

    log.info("-" * 70)
    log.info(f"  Identisch (übersprungen) : {skipped:>6}")
    log.info(f"  Abweichend (überschreiben): {size_diff:>6}")
    log.info(f"  Fehlend (neu kopieren)   : {len(to_copy) - size_diff:>6}")
    log.info(f"  Gesamt zu kopieren       : {len(to_copy):>6}")
    log.info(f"  Nur auf OneDrive (löschen): {len(to_delete):>5}")
    log.info("-" * 70)

    copied = 0
    errors = 0

    # ── Kopieren ──────────────────────────────────────────────────────────────
    for src, dst in to_copy:
        rel_display = src.relative_to(local_dir)
        if dry_run:
            log.info(f"  [DRY-RUN] würde kopieren: {rel_display}")
            copied += 1
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log.info(f"  KOPIERT  {rel_display}")
            copied += 1
        except Exception as e:
            log.error(f"  FEHLER (kopieren)  {rel_display}  →  {e}")
            errors += 1

    # ── Löschen (OneDrive-only Dateien) ──────────────────────────────────────
    deleted = 0
    for dst in to_delete:
        rel_display = dst.relative_to(backup_dir)
        if dry_run:
            log.info(f"  [DRY-RUN] würde löschen: {rel_display}")
            deleted += 1
            continue
        try:
            dst.unlink()
            log.info(f"  GELÖSCHT  {rel_display}")
            deleted += 1
        except Exception as e:
            log.error(f"  FEHLER (löschen)  {rel_display}  →  {e}")
            errors += 1

    # ── Leere Ordner aufräumen ────────────────────────────────────────────────
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
    log.info(f"Sync abgeschlossen {'[DRY-RUN] ' if dry_run else ''}in {elapsed.total_seconds():.1f}s")
    log.info(f"  Übersprungen      : {skipped}")
    log.info(f"  Kopiert           : {copied}")
    log.info(f"  Gelöscht (Dateien): {deleted}")
    log.info(f"  Gelöscht (Ordner) : {removed_dirs}")
    log.info(f"  Fehler            : {errors}")
    log.info("=" * 70)


# ══════════════════════════════════════════════════════════════════════════════
#  EINSTIEGSPUNKT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_backup(LOCAL_DIR, BACKUP_DIR, dry_run=DRY_RUN)