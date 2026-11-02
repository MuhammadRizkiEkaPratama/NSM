"""Backup routes: status and backup file contents."""
from fastapi import APIRouter

import backup_status

router = APIRouter(tags=["backup"])


@router.get("/backup/status")
def backup_status_ringkas():
    """Backup state: schedule, history, file contents and the second copy.
    Exists because backups once stopped silently for two days with nowhere in the app to show it.
    """
    return backup_status.ringkasan()


@router.get("/backup/isi")
def backup_isi(nama: str):
    """Detail of one backup file: which parts exist and their sizes."""
    return backup_status.isi_backup(nama)
