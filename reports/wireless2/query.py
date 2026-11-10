"""
reports/wireless2/query.py - Query DB untuk /wireless2.

Sama dengan db.query_wireless_performance (/wireless), ditambah filter
`product_commercial_name NOT LIKE %<exclude_keyword>%` (mis. tanpa "murmer").
Koneksi & retry memakai helper db.py; db.py sendiri tidak diubah.
"""

import logging
from datetime import date, timedelta

import db

logger = logging.getLogger(__name__)


def query_wireless_performance(tgl_dari: date, tgl_sampai: date,
                               exclude_keyword: str) -> list[dict]:
    """
    Untuk /wireless2 (IO-RE-PS EZNet Wireless per WOK, TANPA produk exclude_keyword,
    mis. "murmer"): tabel raw
    indihome_ordering_detail_YYYYMM, HANYA produk yang product_commercial_name-nya
    mengandung kata WIRELESS (kebalikan dari filter di report lain yang justru
    meng-exclude WIRELESS). Pola long-format sama dgn query_daily_performance_raw:
    io/re/ps dihitung per tanggal timestamp-nya sendiri (io_ts/re_ts/ps_ts).

    Tidak ada filter package_cat 'HWA' — produk wireless bukan produk hardware,
    dan belum ada dasar untuk meng-exclude-nya.

    exclude_keyword: produk yang product_commercial_name-nya mengandung kata ini DIKELUARKAN.

    Returns list of dicts: wok, branch, activity_date, io_trx, re_trx, ps_trx.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = f"indihome_ordering_detail_{awal.strftime('%Y%m')}"
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (max(tgl_dari, awal), min(tgl_sampai, akhir_bulan))
        awal = awal + _rdelta(months=1)

    excl_param = f"%{exclude_keyword}%"
    METRICS  = [("io_ts", "io_trx"), ("re_ts", "re_trx"), ("ps_ts", "ps_trx")]
    rows_all = []

    for tabel, (t_dari, t_sampai) in tabels.items():
        t_sampai_excl = t_sampai + timedelta(days=1)
        for ts_col, trx_field in METRICS:
            sql = f"""
                SELECT
                    {db._GEO_SEL},
                    {db._WOK_KAB} AS wok,
                    {db._BRANCH_KAB} AS branch,
                    DATE({ts_col}) AS activity_date,
                    COUNT(*)       AS trx
                FROM `{tabel}`
                WHERE region LIKE %s
                  AND order_type = 'NEW SALES'
                  AND product_commercial_name LIKE '%%WIRELESS%%'
                  AND product_commercial_name NOT LIKE %s
                  AND {ts_col} IS NOT NULL
                  AND {ts_col} != '0000-00-00'
                  AND {ts_col} >= %s AND {ts_col} < %s
                GROUP BY {db._WOK_KAB}, {db._BRANCH_KAB}, DATE({ts_col}), {db._GEO_GRP}
            """
            def _jalankan():
                conn   = db.get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute(sql, (db.DB_REGION_LIKE, excl_param, t_dari, t_sampai_excl))
                r = db._resolve_geo(cursor.fetchall(), ('trx',))
                cursor.close()
                conn.close()
                return r
            rows = db._jalankan_dengan_retry(_jalankan, f"wireless2.query_wireless_performance {tabel}.{ts_col}")
            logger.info(f"wireless2.query_wireless_performance {tabel}.{ts_col} ({t_dari}~{t_sampai}): {len(rows)} baris")
            for r in rows:
                rows_all.append({
                    "wok"          : r["wok"],
                    "branch"       : r["branch"],
                    "activity_date": r["activity_date"],
                    "io_trx"       : r["trx"] if trx_field == "io_trx" else 0,
                    "re_trx"       : r["trx"] if trx_field == "re_trx" else 0,
                    "ps_trx"       : r["trx"] if trx_field == "ps_trx" else 0,
                })

    return rows_all
