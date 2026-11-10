"""
reports/market_share/query.py — Query tabel fixed_ms_city (region JATENG-DIY saja).

Koneksi & retry memakai helper db.py; db.py sendiri tidak diubah.
"""

import logging
from datetime import date

import db

logger = logging.getLogger(__name__)

TABEL = "fixed_ms_city"
REGION = "JATENG-DIY"

TABEL_REGION = "fixed_ms_region"
TABEL_BRANCH = "fixed_ms_branch"

KOLOM_PEMAIN = [
    "indihome", "tsel_orbit", "cbn_network", "icon_pln", "xl_home",
    "first_media", "indosat", "myrepublic", "mnc_play", "biznet", "others",
]


def _fetch(sql: str, params: tuple) -> list[dict]:
    def _run():
        conn = db.get_connection()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, params)
            rows = cur.fetchall()
            cur.close()
            return rows
        finally:
            conn.close()
    return db._jalankan_dengan_retry(_run, "market_share")


def query_event_date_terakhir(batas: date = None, tabel: str = TABEL) -> date | None:
    """
    event_date terbaru untuk region JATENG-DIY.
    batas=None -> update terakhir tabel; batas=tgl -> event_date terbaru yang <= tgl.
    """
    if batas is None:
        sql, params = f"SELECT MAX(event_date) AS d FROM `{tabel}` WHERE region = %s", (REGION,)
    else:
        sql = f"SELECT MAX(event_date) AS d FROM `{tabel}` WHERE region = %s AND event_date <= %s"
        params = (REGION, batas)
    rows = _fetch(sql, params)
    return rows[0]["d"] if rows and rows[0]["d"] else None


def query_event_date_sebelum(batas: date, paling_lama: date, tabel: str = TABEL) -> date | None:
    """event_date terbaru yang <= batas tapi >= paling_lama (None kalau tidak ada)."""
    sql = (f"SELECT MAX(event_date) AS d FROM `{tabel}` "
           f"WHERE region = %s AND event_date <= %s AND event_date >= %s")
    rows = _fetch(sql, (REGION, batas, paling_lama))
    return rows[0]["d"] if rows and rows[0]["d"] else None


def query_share(event_date: date) -> list[dict]:
    """Baris market share per city pada satu event_date (urutan asli tabel)."""
    kolom = ", ".join(KOLOM_PEMAIN)
    sql = (f"SELECT city, {kolom}, status, closest_competitor FROM `{TABEL}` "
           f"WHERE region = %s AND event_date = %s")
    return _fetch(sql, (REGION, event_date))


def query_share_branch(event_date: date) -> list[dict]:
    """Baris market share per BRANCH (fixed_ms_branch) pada satu event_date.
    Nama branch dikembalikan sebagai 'city' (= kolom TERRITORY)."""
    kolom = ", ".join(KOLOM_PEMAIN)
    sql = (f"SELECT branch AS city, {kolom}, status, closest_competitor FROM `{TABEL_BRANCH}` "
           f"WHERE region = %s AND event_date = %s")
    return _fetch(sql, (REGION, event_date))


def query_share_region(event_date: date) -> list[dict]:
    """
    Baris region JATENG-DIY dari fixed_ms_region pada satu event_date. Kolomnya sama
    dengan fixed_ms_city; nama region dikembalikan sebagai 'city' (= kolom TERRITORY).
    """
    kolom = ", ".join(KOLOM_PEMAIN)
    sql = (f"SELECT region AS city, {kolom}, status, closest_competitor FROM `{TABEL_REGION}` "
           f"WHERE region = %s AND event_date = %s")
    return _fetch(sql, (REGION, event_date))
