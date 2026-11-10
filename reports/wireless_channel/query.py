"""
reports/wireless_channel/query.py — Query DB untuk /wirelesschannel.

Sumber: indihome_ordering_detail_YYYYMM (raw), hanya produk WIRELESS. Koneksi &
retry memakai helper db.py; query-nya sendiri dikelompokkan di folder fitur ini.
"""

import logging
from datetime import date, timedelta

import db

logger = logging.getLogger(__name__)


def query_wireless_ps_channel(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Untuk /wireless_channel (PS EZNet Wireless by Channel): tabel raw
    indihome_ordering_detail_YYYYMM, HANYA produk yang product_commercial_name-nya
    mengandung WIRELESS, metrik PS (ps_ts dalam rentang tgl_dari..tgl_sampai
    INKLUSIF). Channel dipetakan sama spt query_ordering_detail (AGENCY /
    GRAPARI / DIGITAL / COMMUNITY). sf_code hanya diisi utk channel AGENCY
    (dipakai memisahkan SF Household vs SF Mobile lewat file mapping), channel
    lain sf_code = ''.

    Returns list of dicts: wok, branch, channel, sf_code, ps_trx.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = f"indihome_ordering_detail_{awal.strftime('%Y%m')}"
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (max(tgl_dari, awal), min(tgl_sampai, akhir_bulan))
        awal = awal + _rdelta(months=1)

    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        t_sampai_excl = t_sampai + timedelta(days=1)
        sql = f"""
            SELECT
                {db._GEO_SEL},
                {db._WOK_KAB} AS wok,
                {db._BRANCH_KAB} AS branch,
                CASE
                    WHEN UPPER(TRIM(channel_group)) = 'AGENCY'         THEN 'AGENCY'
                    WHEN UPPER(TRIM(channel_group)) = 'GRAPARI'        THEN 'GRAPARI'
                    WHEN UPPER(TRIM(channel_group)) = 'WEB&APP'        THEN 'DIGITAL'
                    WHEN UPPER(TRIM(channel_group)) IN (
                         'B2B2C&OTHERS','SOBI AFFILIATE')               THEN 'COMMUNITY'
                    ELSE 'OTHER'
                END AS channel,
                CASE WHEN UPPER(TRIM(channel_group)) = 'AGENCY'
                     THEN UPPER(TRIM(COALESCE(sf_code, ''))) ELSE '' END AS sf_code,
                COUNT(*) AS ps_trx
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND product_commercial_name LIKE '%%WIRELESS%%'
              AND ps_ts IS NOT NULL
              AND ps_ts != '0000-00-00'
              AND ps_ts >= %s AND ps_ts < %s
            GROUP BY {db._WOK_KAB}, {db._BRANCH_KAB}, channel, sf_code, {db._GEO_GRP}
        """
        def _jalankan():
            conn   = db.get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (db.DB_REGION_LIKE, t_dari, t_sampai_excl))
            r = db._resolve_geo(cursor.fetchall(), ('ps_trx',))
            cursor.close()
            conn.close()
            return r
        rows = db._jalankan_dengan_retry(_jalankan, f"query_wireless_ps_channel {tabel}")
        logger.info(f"query_wireless_ps_channel {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        rows_all += [r for r in rows if r["channel"] != "OTHER"]

    return rows_all
