"""
reports/murmer/query.py — Query DB untuk /murmer (EZNET Wireless Murmer).

Satu-satunya file di fitur ini yang menyentuh DB. TIDAK ditaruh di db.py (yang
sudah menampung query semua fitur lain) supaya query khusus murmer tetap
terkelompok di folder fiturnya sendiri.

Cara ambil data (port dari skrip "Report EZNET Wireless Murmer/murmer.py" v2):
  - tiap tabel bulanan indihome_ordering_detail_YYYYMM di-query TERPISAH dan
    PARALEL (koneksi sendiri per thread), filter
    product_commercial_name LIKE %<keyword>% AND order_type = 'new sales'
  - hasilnya digabung di pandas (kolom yang tidak ada di suatu bulan diisi
    kosong) — jadi struktur kolom antar bulan boleh beda (tidak ada UNION di
    MySQL, yang dulu kena error 1222 & sangat lambat)
  - dedup per order_id: ambil baris dengan event_date TERBARU (satu order bisa
    ke-sync berkali-kali)
TIDAK difilter region — semua region (JATENG-DIY, JATIM, JABAR, EASTERN
JABOTABEK, dst.) diambil untuk ranking di caption. `SELECT *` sengaja dipakai
supaya raw data lengkap bisa diexport (Senin) tanpa query ulang.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
from mysql.connector import Error

import db

logger = logging.getLogger(__name__)


def get_ytd_tables(cutoff: date, ytd_start_month: int) -> list[str]:
    """Nama tabel indihome_ordering_detail_YYYYMM dari ytd_start_month s/d bulan cutoff."""
    return [
        f"indihome_ordering_detail_{cutoff.year}{str(m).zfill(2)}"
        for m in range(ytd_start_month, cutoff.month + 1)
    ]


def _tabel_ada(tables: list[str]) -> list[str]:
    """Filter hanya tabel yang benar-benar ada di database."""
    if not tables:
        return []

    def _jalankan():
        conn = db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT DATABASE()")
            nama_db = cur.fetchone()[0]
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                f"WHERE table_schema=%s AND table_name IN ({','.join(['%s'] * len(tables))})",
                [nama_db] + tables,
            )
            ada = {r[0] for r in cur.fetchall()}
            cur.close()
            return ada
        finally:
            conn.close()

    ada = db._jalankan_dengan_retry(_jalankan, "murmer cek tabel")
    return [t for t in tables if t in ada]


def _query_tabel(tabel: str, product_keyword: str) -> pd.DataFrame:
    """Query 1 tabel bulanan (jalan di thread sendiri, koneksi sendiri)."""
    sql = (
        f"SELECT * FROM `{tabel}` "
        f"WHERE product_commercial_name LIKE %s AND order_type = 'new sales'"
    )

    def _jalankan():
        conn = db.get_connection()
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (f"%{product_keyword}%",))
            rows = cur.fetchall()
            cur.close()
            return rows
        finally:
            conn.close()

    return pd.DataFrame(db._jalankan_dengan_retry(_jalankan, f"murmer {tabel}"))


def fetch_data(cutoff: date, ytd_start_month: int, product_keyword: str,
               workers: int = 4) -> pd.DataFrame:
    """
    Tarik data EZNET Murmer YTD s/d bulan cutoff (semua region, belum di-filter
    tanggal — filter IO/RE/PS/tanggal dilakukan di calculator.py).

    Raise ValueError kalau cutoff.month < ytd_start_month (tidak ada tabel yang
    valid untuk di-query); RuntimeError kalau ada tabel yang gagal di-query (data
    tidak boleh dilaporkan setengah-setengah).
    """
    kandidat = get_ytd_tables(cutoff, ytd_start_month)
    if not kandidat:
        raise ValueError(
            f"Tanggal {cutoff.strftime('%d-%m-%Y')} sebelum YTD_START_MONTH "
            f"({ytd_start_month}) — tidak ada tabel yang bisa di-query."
        )

    tabel = _tabel_ada(kandidat)
    hilang = sorted(set(kandidat) - set(tabel))
    if hilang:
        logger.info(f"[murmer] Tabel tidak ada, dilewati: {', '.join(hilang)}")

    hasil, gagal = {}, []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(tabel) or 1))) as ex:
        futs = {ex.submit(_query_tabel, t, product_keyword): t for t in tabel}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                d = fut.result()
            except Error as e:
                gagal.append(t)
                logger.warning(f"[murmer] GAGAL {t}: {e}")
                continue
            logger.info(f"[murmer] {t}: {len(d)} baris")
            if not d.empty:
                d["source_table"] = t
                hasil[t] = d

    if gagal:
        raise RuntimeError(f"Tabel gagal di-query, data tidak lengkap: {', '.join(sorted(gagal))}")

    frames = [hasil[t] for t in tabel if t in hasil]
    if not frames:
        return pd.DataFrame()

    semua_kolom = list(dict.fromkeys(c for f in frames for c in f.columns))
    df = pd.concat(frames, ignore_index=True, sort=False)[semua_kolom]

    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df = df.sort_values("event_date", ascending=False, na_position="last")
    return df.drop_duplicates(subset="order_id", keep="first").reset_index(drop=True)
