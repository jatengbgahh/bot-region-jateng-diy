"""
pranpc_data.py — Akses DB Indiana (server terpisah) untuk report PraNPC.

Tabel:
  indiana_tr_migrasi_pranpc[YYYYMM]          base WO PraNPC (1 baris = 1 SSL)
  ocs_aging_migrasi_ih_pranpc_detail[YYYYMM] status harian per SND
                                              (PK: SND, event_date)
Tabel TANPA suffix = bulan berjalan (periode terbaru); bulan sebelumnya pakai
suffix YYYYMM.

Fallback tabel belum ada (_tabel): kalau tabel periode yang diminta belum dibuat di Indiana
(mis. awal bulan: status OCS sudah tanggal 202611 tapi indiana_tr_migrasi_pranpc202611 belum
ada), dipakai tabel periode month-1 (202610; tanpa suffix bila itu periode berjalan).

Definisi PAID (sesuai kolom status_bayarnew2 di workbook Tracking PraNPC):
  status OCS pada tanggal cut-off != 'U'  -> Paid   (A / S / E = Paid)
  status OCS == 'U'                        -> Unpaid
"""

import logging
from datetime import date
import mysql.connector
from mysql.connector import Error
from config import DB2_HOST, DB2_PORT, DB2_USER, DB2_PASS, DB2_NAME, DB2_REGIONAL
from db import KoneksiDBError, _jalankan_dengan_retry
import pranpc_ref

logger = logging.getLogger(__name__)

BASE_PREFIX = "indiana_tr_migrasi_pranpc"
OCS_PREFIX  = "ocs_aging_migrasi_ih_pranpc_detail"


def get_connection():
    try:
        return mysql.connector.connect(
            host=DB2_HOST, port=DB2_PORT, user=DB2_USER, password=DB2_PASS,
            database=DB2_NAME, connect_timeout=10,
        )
    except Error as e:
        raise KoneksiDBError(
            f"Database Indiana tidak terjangkau ({DB2_HOST}:{DB2_PORT}). Detail: {e}"
        ) from e


def _query(sql: str, params: tuple = (), label: str = "pranpc") -> list[tuple]:
    def _jalankan():
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            conn.close()
    return _jalankan_dengan_retry(_jalankan, label)


def periode_berjalan() -> str:
    """Periode (YYYYMM) yang sedang ada di tabel tanpa suffix."""
    rows = _query(f"SELECT MAX(periode) FROM `{BASE_PREFIX}`", label="pranpc periode")
    return str(rows[0][0])


def _suffix(periode: str, cur_periode: str) -> str:
    return "" if periode == cur_periode else periode


def _bulan_lalu(periode: str) -> str:
    y, m = int(periode[:4]), int(periode[4:6])
    return f"{y - 1}12" if m == 1 else f"{y}{m - 1:02d}"


def _ada_tabel(tbl: str) -> bool:
    rows = _query("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                  (DB2_NAME, tbl), label=f"pranpc cek tabel {tbl}")
    return bool(rows and rows[0][0])


def _tabel(prefix: str, periode: str, cur_periode: str) -> str:
    """
    Nama tabel untuk periode. Bila tabel itu belum ada -> fallback ke tabel periode month-1
    (sesuai permintaan 09-11-2026). Bila keduanya tidak ada, kembalikan nama asli supaya
    error 1146 tetap terlihat jelas.
    """
    asli = prefix + _suffix(periode, cur_periode)
    if _ada_tabel(asli):
        return asli
    lalu = _bulan_lalu(periode)
    for cand in dict.fromkeys((prefix + _suffix(lalu, cur_periode), prefix + lalu)):
        if _ada_tabel(cand):
            logger.warning(f"Tabel {asli} belum ada -> fallback ke tabel month-1 {cand}")
            return cand
    return asli


def tanggal_status_terakhir(periode: str, cur_periode: str, maks: date | None = None) -> date | None:
    """event_date terakhir di tabel OCS periode tsb (<= maks bila diisi)."""
    tbl = _tabel(OCS_PREFIX, periode, cur_periode)
    try:
        if maks:
            rows = _query(f"SELECT MAX(event_date) FROM `{tbl}` WHERE event_date <= %s",
                          (maks,), label=f"pranpc maxdate {tbl}")
        else:
            rows = _query(f"SELECT MAX(event_date) FROM `{tbl}`", label=f"pranpc maxdate {tbl}")
    except Error as e:
        if getattr(e, "errno", None) == 1146:   # tabel belum ada
            return None
        raise
    return rows[0][0] if rows else None


def load_base(periode: str, cur_periode: str) -> list[dict]:
    """
    Base WO PraNPC regional (JATENG-DIY) satu periode.
    Tiap dict ditambah 'wok_svp' (mapping kabupaten -> Cluster SVP).
    """
    tbl = _tabel(BASE_PREFIX, periode, cur_periode)
    cols = ["snd", "branch", "kabupaten", "mitra", "ctb", "segment", "los",
            "bucket1", "bucket2", "byr1", "byr2", "adjustment_crd", "adjustment_dbt",
            "order_id", "flag_order_created", "product_commercial_name", "order_ts",
            "do_order_id", "do_order_ts"]
    # Skema tabel bulanan lama tidak lengkap (mis. do_order_id/do_order_ts baru
    # ada sejak 202609, adjustment_* sejak 202601) — kolom yang tidak ada
    # diambil sebagai NULL supaya query tidak error.
    ada = {c for (c,) in _query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (DB2_NAME, tbl), label=f"pranpc kolom {tbl}")}
    sel = [f"`{c}`" if c in ada else f"NULL AS `{c}`" for c in cols]
    rows = _query(
        f"SELECT {', '.join(sel)} FROM `{tbl}` WHERE regional = %s",
        (DB2_REGIONAL,), label=f"pranpc base {tbl}",
    )
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["wok_svp"] = pranpc_ref.wok_of(d["kabupaten"])
        out.append(d)
    logger.info(f"load_base {tbl}: {len(out)} baris")
    return out


def load_status(periode: str, cur_periode: str, tgl: date) -> dict[str, str]:
    """{snd: subscriber_status} pada event_date = tgl."""
    tbl = _tabel(OCS_PREFIX, periode, cur_periode)
    rows = _query(
        f"SELECT SND, subscriber_status FROM `{tbl}` WHERE event_date = %s",
        (tgl,), label=f"pranpc status {tbl} {tgl}",
    )
    logger.info(f"load_status {tbl} {tgl}: {len(rows)} baris")
    return {str(s): st for s, st in rows}


def is_paid(status: str | None) -> bool:
    return status is not None and status != "U"


CARING_TABLE = "indiana_tr_migrasi_pranpc_transkom"


def load_caring(periode: str) -> dict[str, dict]:
    """
    Data caring VIONA/Transkom per SND (1 baris per periode+SND = caring TERAKHIR).
    Return {snd: {'jenis': 'Visit'/'Digital'/None, 'status_voc': ..., 'num_priority': ...}}.
    Catatan: hanya kondisi terakhir yang tersimpan, jadi caring untuk tanggal
    lampau tidak bisa direka ulang persis.
    """
    rows = _query(
        f"SELECT snd, jenis, status_voc, num_priority, tgl_visit FROM `{CARING_TABLE}` WHERE periode = %s",
        (periode,), label=f"pranpc caring {periode}",
    )
    logger.info(f"load_caring {periode}: {len(rows)} baris")
    return {str(s): {"jenis": j or None, "status_voc": sv, "num_priority": pr, "tgl_visit": tv}
            for s, j, sv, pr, tv in rows}
