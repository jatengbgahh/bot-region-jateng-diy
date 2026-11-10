"""
utils/scheduler_db.py — Pengelola Jadwal & Job Execution Log berbasis SQLite.

Menyimpan konfigurasi jadwal dinamis di `storage/state/scheduler.db`.
Fitur:
  - Auto-seed jadwal awal dari `config.JADWAL_LAPORAN`.
  - CRUD slot jadwal (aktifkan/nonaktifkan, ubah jam/menit, tambah, hapus).
  - Pencatatan log eksekusi job (status, durasi, jumlah media terkirim, error).
  - Dapat diakses dan dimodifikasi langsung tanpa coding & tanpa restart bot.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "storage" / "state" / "scheduler.db"


def _get_connection() -> sqlite3.Connection:
    """Buka koneksi ke SQLite database scheduler."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=20.0)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    """Inisialisasi tabel SQLite jika belum ada."""
    with _get_connection() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                jam INTEGER NOT NULL,
                menit INTEGER NOT NULL,
                hari TEXT,
                topic TEXT NOT NULL,
                reports_json TEXT NOT NULL,
                kirim_wa INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS job_execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER,
                report_name TEXT NOT NULL,
                topic TEXT NOT NULL,
                waktu_mulai TEXT NOT NULL,
                waktu_selesai TEXT,
                status TEXT NOT NULL,
                media_terkirim INTEGER DEFAULT 0,
                error_message TEXT,
                triggered_by TEXT NOT NULL DEFAULT 'SCHEDULER',
                FOREIGN KEY (job_id) REFERENCES scheduled_jobs(id) ON DELETE SET NULL
            );
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_active ON scheduled_jobs(is_active);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_logs_job ON job_execution_logs(job_id);")
        con.execute("CREATE INDEX IF NOT EXISTS idx_logs_mulai ON job_execution_logs(waktu_mulai);")


def seed_initial_jobs(initial_slots: list[dict[str, Any]]) -> int:
    """
    Isi jadwal awal dari list config.JADWAL_LAPORAN jika tabel masih kosong.
    Return jumlah row yang dimasukkan.
    """
    init_db()
    with _get_connection() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) AS total FROM scheduled_jobs")
        row = cur.fetchone()
        if row and row["total"] > 0:
            return 0  # Sudah ada data, jangan timpa

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inserted = 0
        for slot in initial_slots:
            jam = int(slot["jam"])
            menit = int(slot["menit"])
            hari = slot.get("hari")
            topic = str(slot["topic"])
            laporan = slot.get("laporan", [])
            kirim_wa = 1 if slot.get("wa") else 0
            label = f"{topic} {jam:02d}:{menit:02d}"

            cur.execute(
                """
                INSERT INTO scheduled_jobs (
                    label, jam, menit, hari, topic, reports_json, kirim_wa, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?);
                """,
                (label, jam, menit, hari, topic, json.dumps(laporan), kirim_wa, now_str, now_str),
            )
            inserted += 1
        con.commit()
        logger.info(f"[SCHEDULER-DB] Berhasil mengimpor {inserted} jadwal awal ke SQLite.")
        return inserted


def sync_declared_report_schedules() -> int:
    """
    Scanning semua subclass BaseReport:
    Jika sebuah class mendefinisikan atribut `schedule = {...}` dan jadwal/laporannya
    belum ada di database SQLite, otomatis tambahkan ke `scheduled_jobs`.
    Jika sudah ada di database, biarkan (tidak menimpa perubahan user/admin di database).
    Return jumlah jadwal baru yang didaftarkan.
    """
    init_db()
    from reports.base import BaseReport

    classes = getattr(BaseReport, "_REPORT_CLASSES", [])
    if not classes:
        return 0

    all_jobs = get_all_jobs(only_active=False)
    # Kumpulkan nama-nama report yang sudah terdaftar di slot manapun di database
    registered_reports = set()
    for job in all_jobs:
        for item in job.get("laporan", []):
            if isinstance(item, (list, tuple)) and item:
                registered_reports.add(str(item[0]).lower())
            elif isinstance(item, str):
                registered_reports.add(item.lower())

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_inserted = 0

    with _get_connection() as con:
        cur = con.cursor()
        for cls in classes:
            sch = getattr(cls, "schedule", None)
            cmd_name = (getattr(cls, "command_name", "") or getattr(cls, "name", "")).lower().strip()
            if not sch or not cmd_name:
                continue

            # Cek apakah command report ini sudah pernah ada di database
            if cmd_name in registered_reports:
                continue

            jam = int(sch.get("jam", 8))
            menit = int(sch.get("menit", 0))
            topic = str(sch.get("topic", "SALES")).upper()
            offset = sch.get("offset", getattr(cls, "default_date_offset", 1))
            hari = sch.get("hari")
            kirim_wa = 1 if (sch.get("kirim_wa") or getattr(cls, "send_wa", False)) else 0
            label = sch.get("label") or f"{topic} {jam:02d}:{menit:02d} ({cmd_name})"
            reports_data = [[cmd_name, offset]]

            cur.execute(
                """
                INSERT INTO scheduled_jobs (
                    label, jam, menit, hari, topic, reports_json, kirim_wa, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?);
                """,
                (label, jam, menit, hari, topic, json.dumps(reports_data), kirim_wa, now_str, now_str),
            )
            registered_reports.add(cmd_name)
            new_inserted += 1
            logger.info(f"[SCHEDULER-DB] Auto-registered jadwal deklaratif baru: /{cmd_name} pada {jam:02d}:{menit:02d} topic {topic}")

        if new_inserted > 0:
            con.commit()

    return new_inserted


def get_all_jobs(only_active: bool = False) -> list[dict[str, Any]]:
    """Ambil daftar semua slot jadwal."""
    init_db()
    with _get_connection() as con:
        query = "SELECT * FROM scheduled_jobs"
        if only_active:
            query += " WHERE is_active = 1"
        query += " ORDER BY jam ASC, menit ASC, topic ASC"
        cur = con.execute(query)
        rows = cur.fetchall()
        jobs = []
        for r in rows:
            d = dict(r)
            try:
                d["laporan"] = json.loads(d["reports_json"])
            except Exception:
                d["laporan"] = []
            d["wa"] = bool(d["kirim_wa"])
            jobs.append(d)
        return jobs


def get_job_by_id(job_id: int) -> Optional[dict[str, Any]]:
    """Ambil satu job berdasarkan ID."""
    init_db()
    with _get_connection() as con:
        cur = con.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["laporan"] = json.loads(d["reports_json"])
        except Exception:
            d["laporan"] = []
        d["wa"] = bool(d["kirim_wa"])
        return d


def toggle_job(job_id: int, active: Optional[bool] = None) -> bool:
    """Aktifkan atau nonaktifkan job. Jika active=None, switch status saat ini."""
    init_db()
    with _get_connection() as con:
        cur = con.cursor()
        if active is None:
            cur.execute(
                """
                UPDATE scheduled_jobs
                SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END,
                    updated_at = ?
                WHERE id = ?;
                """,
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_id),
            )
        else:
            cur.execute(
                """
                UPDATE scheduled_jobs
                SET is_active = ?, updated_at = ?
                WHERE id = ?;
                """,
                (1 if active else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_id),
            )
        con.commit()
        return cur.rowcount > 0


def update_job_time(job_id: int, jam: int, menit: int, hari: Optional[str] = None) -> bool:
    """Ubah waktu slot jadwal."""
    init_db()
    with _get_connection() as con:
        cur = con.cursor()
        cur.execute(
            """
            UPDATE scheduled_jobs
            SET jam = ?, menit = ?, hari = ?, updated_at = ?
            WHERE id = ?;
            """,
            (jam, menit, hari, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_id),
        )
        con.commit()
        return cur.rowcount > 0


def record_log_start(
    job_id: Optional[int],
    report_name: str,
    topic: str,
    triggered_by: str = "SCHEDULER",
) -> int:
    """Catat awal eksekusi job, kembalikan log_id."""
    init_db()
    with _get_connection() as con:
        cur = con.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            INSERT INTO job_execution_logs (
                job_id, report_name, topic, waktu_mulai, status, triggered_by
            ) VALUES (?, ?, ?, ?, 'RUNNING', ?);
            """,
            (job_id, report_name, topic, now_str, triggered_by),
        )
        con.commit()
        return cur.lastrowid


def record_log_finish(
    log_id: int,
    status: str,
    media_terkirim: int = 0,
    error_message: Optional[str] = None,
) -> None:
    """Perbarui status akhir eksekusi job."""
    if not log_id:
        return
    with _get_connection() as con:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        con.execute(
            """
            UPDATE job_execution_logs
            SET waktu_selesai = ?, status = ?, media_terkirim = ?, error_message = ?
            WHERE id = ?;
            """,
            (now_str, status, media_terkirim, error_message, log_id),
        )
        con.commit()


def get_recent_logs(limit: int = 15, job_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Ambil log eksekusi terbaru."""
    init_db()
    with _get_connection() as con:
        if job_id:
            cur = con.execute(
                """
                SELECT l.*, j.label AS job_label
                FROM job_execution_logs l
                LEFT JOIN scheduled_jobs j ON l.job_id = j.id
                WHERE l.job_id = ?
                ORDER BY l.id DESC LIMIT ?;
                """,
                (job_id, limit),
            )
        else:
            cur = con.execute(
                """
                SELECT l.*, j.label AS job_label
                FROM job_execution_logs l
                LEFT JOIN scheduled_jobs j ON l.job_id = j.id
                ORDER BY l.id DESC LIMIT ?;
                """,
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]
