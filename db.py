"""
db.py — Modul koneksi dan query ke MySQL dashboard_hourly_sales
Nama tabel otomatis per bulan: dashboard_hourly_sales_YYYYMM
Untuk MoM, otomatis query ke tabel bulan sebelumnya.
"""

import concurrent.futures
import logging
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
import mysql.connector
from mysql.connector import Error
from config import DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME, DB_TABLE_PREFIX, DB_REGION
import wilayah
import reports as _reports_aliases  # noqa: F401 — aktifkan alias modul lama di sys.meta_path

logger = logging.getLogger(__name__)

# Label region/regional di berbagai tabel sumber (dashboard_hourly_sales,
# indihome_ordering_detail, bwmp_c3mr_dd, djp_daily_user_detailed,
# ih_ten_segment_detail, homepass_sales, churn_dd) TIDAK konsisten dan bisa
# berubah antar-bulan (mis. "JATENG" <-> "JATENG-DIY"). Semua query di modul
# ini difilter pakai LIKE prefix ini, bukan exact match, biar otomatis tetap
# kedeteksi kalau labelnya berubah lagi bulan depan (aman terhadap region
# lain seperti JABAR/JATIM/JAKARTA BANTEN karena awalannya beda).
DB_REGION_LIKE = f"{DB_REGION}%"

# ── Pemetaan WOK/BRANCH BARU dari kolom KABUPATEN (lihat wilayah.py) ──────────
# wok & branch bawaan tabel TIDAK dipakai lagi; semua query memetakan ulang dari
# kabupaten, dan baris yang kabupatennya kosong/NAN/luar JATENG-DIY dibuang
# (kondisi _OK_* di WHERE). Kolom kabupaten: indihome_ordering_detail,
# dashboard_hourly_sales, churn_dd, retensi_dd = "kabupaten"; bwmp_c3mr_dd = "city".
_WOK_KAB    = wilayah.sql_wok("kabupaten")
_BRANCH_KAB = wilayah.sql_branch("kabupaten")
_OK_KAB     = wilayah.sql_terpetakan("kabupaten")
_KAB_NAMA   = wilayah.sql_kab_nama("kabupaten")   # nama city resmi (untuk report per city)

# Khusus indihome_ordering_detail: baris yang kabupatennya kosong/NAN/luar
# wilayah TIDAK dibuang. Query menarik koordinat (longitude/latitude) dan
# kabupaten_sto baris itu (kolom geo_*; NULL untuk baris biasa), lalu
# _resolve_geo() mengisi wok/branch lewat geotagging koordinat -> fallback STO.
_GEO_SEL = (
    f"(CASE WHEN {_OK_KAB} THEN NULL ELSE longitude END) AS geo_lon, "
    f"(CASE WHEN {_OK_KAB} THEN NULL ELSE latitude END) AS geo_lat, "
    f"(CASE WHEN {_OK_KAB} THEN NULL ELSE kabupaten_sto END) AS geo_sto"
)
_GEO_GRP    = "geo_lon, geo_lat, geo_sto"
_KAB_NAMA_OK = f"(CASE WHEN {_OK_KAB} THEN {_KAB_NAMA} END)"


def _resolve_geo(rows: list, sum_cols=None) -> list:
    """
    Lengkapi wok/branch (dan kabupaten bila ada) untuk baris yang tak
    terpetakan lewat kabupaten: geotag longitude/latitude, fallback kabupaten
    STO (wilayah.selesaikan_wilayah). Baris yang tetap tak terselesaikan
    dibuang. sum_cols = kolom angka yang dijumlahkan ulang (query agregat);
    None untuk query row-level.
    """
    hasil = []
    for r in rows:
        lon = r.pop("geo_lon", None)
        lat = r.pop("geo_lat", None)
        sto = r.pop("geo_sto", None)
        kunci_wilayah = "wok" if "wok" in r else "branch"   # query city tidak punya kolom wok
        if r.get(kunci_wilayah) is None:
            h = wilayah.selesaikan_wilayah(lon, lat, sto)
            if h is None:
                continue
            if "wok" in r:
                r["wok"] = h[0]
            r["branch"] = h[1]
            if "kabupaten" in r:
                r["kabupaten"] = h[2]
        hasil.append(r)
    if not sum_cols:
        return hasil
    gabung = {}
    for r in hasil:
        kunci = tuple((k, v) for k, v in r.items() if k not in sum_cols)
        if kunci in gabung:
            for c in sum_cols:
                gabung[kunci][c] = (gabung[kunci][c] or 0) + (r[c] or 0)
        else:
            gabung[kunci] = dict(r)
    return list(gabung.values())
_WOK_CITY    = wilayah.sql_wok("city")
_BRANCH_CITY = wilayah.sql_branch("city")
_OK_CITY     = wilayah.sql_terpetakan("city")
_KAB_NAMA_CITY = f" {wilayah.sql_kab_nama('city')} AS city,"


def get_table_name(tgl: date) -> str:
    """Generate nama tabel berdasarkan tahun-bulan. Contoh: dashboard_hourly_sales_202605"""
    return f"{DB_TABLE_PREFIX}{tgl.strftime('%Y%m')}"


class KoneksiDBError(Exception):
    """
    DB tidak terjangkau (VPN/GlobalProtect putus, server mati, dsb).

    SENGAJA bukan turunan mysql.connector.Error. Semua fungsi query di file ini
    memakai pola `except Error: return []` untuk menoleransi tabel bulanan yang
    belum ada. Kalau kegagalan koneksi ikut tertangkap di sana, hasilnya kosong
    dan laporan tetap dirender & terkirim dengan angka NOL SEMUA — seolah-olah
    "memang tidak ada penjualan". Dengan tipe terpisah, error ini menembus
    semua `except Error` dan menggagalkan perintahnya dengan pesan jelas.
    """


def get_connection():
    """
    Buat koneksi baru ke MySQL.

    Melempar KoneksiDBError kalau tidak bisa konek, supaya kegagalan VPN tidak
    disalahartikan sebagai "data kosong" oleh fungsi query di bawah.
    """
    try:
        return mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            connect_timeout=10,
        )
    except Error as e:
        raise KoneksiDBError(
            f"Database tidak terjangkau ({DB_HOST}:{DB_PORT}). "
            f"Cek koneksi VPN/GlobalProtect. Detail: {e}"
        ) from e


def test_connection() -> bool:
    """Cek apakah koneksi DB berhasil (konek + login penuh)."""
    try:
        conn = get_connection()
        conn.close()
        return True
    except (Error, KoneksiDBError) as e:
        logger.error(f"DB connection failed: {e}")
        return False


# errno mysql.connector yang menandakan koneksi/VPN putus (bukan error SQL
# biasa seperti tabel belum ada, errno 1146, yang tidak akan pernah sembuh
# kalau di-retry terus).
_ERRNO_KONEKSI = {2002, 2003, 2006, 2013, 2055}


def _error_koneksi(e: Exception) -> bool:
    """True kalau exception ini soal koneksi/VPN putus (layak di-retry terus-
    menerus), bukan error SQL/skema (mis. tabel belum ada — tidak ada gunanya
    diulang)."""
    if isinstance(e, KoneksiDBError):
        return True
    if isinstance(e, Error):
        return getattr(e, "errno", None) in _ERRNO_KONEKSI
    # Socket-level (mis. TimeoutError/ConnectionResetError saat baca hasil
    # query yang lama, kalau GlobalProtect idle-drop di tengah jalan).
    return isinstance(e, OSError)


def _jalankan_dengan_retry(fn, label: str, jeda_detik: int = 15):
    """
    Jalankan fn() (biasanya 1 query DB berat). TIDAK ADA batas waktu untuk
    query itu sendiri — dibiarkan jalan penuh sampai selesai. Kalau gagal
    karena koneksi/VPN putus (bukan error SQL asli), JANGAN menyerah: tunggu
    `jeda_detik` detik lalu ulang query dari awal, terus-menerus sampai
    berhasil (tidak ada batas percobaan) — supaya laporan tidak pernah
    dianggap gagal cuma gara-gara GlobalProtect sempat putus.
    """
    import time
    percobaan = 0
    while True:
        try:
            return fn()
        except Exception as e:
            if not _error_koneksi(e):
                raise
            percobaan += 1
            logger.warning(
                f"[{label}] DB/VPN putus (percobaan ke-{percobaan}): {e} — "
                f"tunggu {jeda_detik}s lalu diulang (tidak menyerah)..."
            )
            time.sleep(jeda_detik)


def port_terbuka(timeout: float = 3.0) -> bool:
    """
    Cek cepat apakah host:port DB bisa dijangkau — cuma buka socket TCP, TIDAK
    login MySQL. Dipakai untuk memantau pulihnya VPN secara sering (tiap
    beberapa detik) tanpa membebani server DB.

    Kalau VPN putus, koneksi TCP langsung ditolak/timeout, jadi hasilnya cepat.
    """
    import socket
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((DB_HOST, DB_PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


def query_re_ps(hari_ini: date, fallback_wok_lama: bool = False) -> list[dict]:
    """
    Query data RE & PS dari DB untuk keperluan laporan hourly & daily.

    Otomatis query ke 2 tabel:
      - Tabel bulan ini  (untuk data hari ini + WoW cur + MoM cur)
      - Tabel bulan lalu (untuk WoW prev + MoM prev, jika beda bulan)

    fallback_wok_lama=True (dipakai /liveupdate): baris dgn kabupaten kosong/nan
    dipetakan lewat kolom wok LAMA ke WOK baru (YOGYA 1/2 -> DAERAH ISTIMEWA
    YOGYAKARTA, SEMARANG 1/2 -> SEMARANG, dst); yang tak bisa dipetakan
    (kabupaten luar wilayah, JEPARA KUDUS - PATI, PEMALANG PURBALINGGA) jadi
    "KABUPATEN UNMAPPED" dan TETAP ikut dihitung. False: baris tak terpetakan dibuang.

    Returns list of dicts:
      wok, branch, activity_date, activity_hour, io_trx, re_trx, ps_trx
    """
    if fallback_wok_lama:
        wok_x, branch_x, ok_x = (wilayah.sql_wok_fallback("kabupaten", "wok", "cluster"),
                                 wilayah.sql_branch_fallback("kabupaten", "wok", "cluster"), "1=1")
    else:
        wok_x, branch_x, ok_x = _WOK_KAB, _BRANCH_KAB, _OK_KAB
    tabel_ini  = get_table_name(hari_ini)
    bulan_lalu = hari_ini - relativedelta(months=1)
    tabel_lalu = get_table_name(bulan_lalu)

    # Rentang tanggal yang dibutuhkan
    tgl_wow_prev_start = hari_ini - timedelta(days=13)   # WoW prev start
    tgl_mom_prev_start = bulan_lalu.replace(day=1)        # MoM prev start (awal bulan lalu)
    tgl_dari = min(tgl_wow_prev_start, tgl_mom_prev_start)

    # Pisahkan rentang: mana yang masuk tabel bulan lalu vs bulan ini
    awal_bulan_ini = hari_ini.replace(day=1)

    rows = []

    # ── Query tabel bulan lalu (jika rentang melewati awal bulan ini) ──────
    if tgl_dari < awal_bulan_ini:
        tgl_dari_lalu   = tgl_dari
        tgl_sampai_lalu = awal_bulan_ini - timedelta(days=1)

        sql_lalu = f"""
            SELECT
                {wok_x} AS wok,
                {branch_x} AS branch,
                activity_date,
                activity_hour,
                SUM(io_trx) AS io_trx,
                SUM(re_trx) AS re_trx,
                SUM(ps_trx) AS ps_trx
            FROM `{tabel_lalu}`
            WHERE activity_date BETWEEN %s AND %s
              AND region LIKE %s
              AND {ok_x}
            GROUP BY {wok_x}, {branch_x}, activity_date, activity_hour
        """
        def _jalankan_lalu():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql_lalu, (tgl_dari_lalu, tgl_sampai_lalu, DB_REGION_LIKE))
            r = cursor.fetchall()
            cursor.close()
            conn.close()
            return r
        try:
            rows += _jalankan_dengan_retry(_jalankan_lalu, f"query_re_ps {tabel_lalu}")
            logger.info(f"Query tabel lalu ({tabel_lalu}): {len(rows)} baris")
        except Error as e:
            logger.warning(f"Tabel bulan lalu tidak ditemukan ({tabel_lalu}): {e}")

    # ── Query tabel bulan ini ──────────────────────────────────────────────
    sql_ini = f"""
        SELECT
            {wok_x} AS wok,
            {branch_x} AS branch,
            activity_date,
            activity_hour,
            SUM(io_trx) AS io_trx,
            SUM(re_trx) AS re_trx,
            SUM(ps_trx) AS ps_trx
        FROM `{tabel_ini}`
        WHERE activity_date BETWEEN %s AND %s
          AND region LIKE %s
          AND {ok_x}
        GROUP BY {wok_x}, {branch_x}, activity_date, activity_hour
        ORDER BY activity_date, activity_hour
    """
    def _jalankan_ini():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql_ini, (awal_bulan_ini, hari_ini, DB_REGION_LIKE))
        r = cursor.fetchall()
        cursor.close()
        conn.close()
        return r
    try:
        rows_ini = _jalankan_dengan_retry(_jalankan_ini, f"query_re_ps {tabel_ini}")
        rows += rows_ini
        logger.info(f"Query tabel ini ({tabel_ini}): {len(rows_ini)} baris")
    except Error as e:
        logger.error(f"Query tabel bulan ini gagal ({tabel_ini}): {e}")
        raise

    if not rows:
        raise ValueError(f"Tidak ada data di DB untuk tanggal s/d {hari_ini}")

    return rows


def query_tanggal_tersedia(tgl_closing: date = None) -> list[date]:
    """
    Ambil daftar tanggal tersedia.
    Jika tgl_closing diberikan, cek tabel bulan tersebut + bulan sebelumnya.
    Jika tidak, cek tabel bulan ini + bulan lalu.
    """
    tgl_ref    = tgl_closing if tgl_closing else date.today()
    tabel_ref  = get_table_name(tgl_ref)
    tabel_prev = get_table_name(tgl_ref - relativedelta(months=1))

    rows = []
    for tabel in [tabel_ref, tabel_prev]:
        sql = f"""
            SELECT DISTINCT activity_date
            FROM `{tabel}`
            WHERE region LIKE %s
            ORDER BY activity_date DESC
            LIMIT 60
        """
        try:
            conn   = get_connection()
            cursor = conn.cursor()
            cursor.execute(sql, (DB_REGION_LIKE,))
            rows += [r[0] for r in cursor.fetchall()]
            cursor.close()
            conn.close()
        except Error as e:
            logger.warning(f"Query tanggal dari {tabel} gagal: {e}")

    return sorted(set(rows), reverse=True)


def query_last_update() -> dict:
    """
    Cek update terakhir di tabel bulan ini berdasarkan MAX(activity_time).
    Return dict:
      - tabel       : nama tabel yang dicek
      - last_update : datetime terakhir (activity_time)
      - last_date   : tanggal terakhir
      - last_hour   : jam terakhir (activity_hour)
      - total_rows  : total baris hari ini
    """
    tabel_ini = get_table_name(date.today())
    sql = f"""
        SELECT
            MAX(activity_time)  AS last_update,
            MAX(activity_date)  AS last_date,
            MAX(activity_hour)  AS last_hour,
            COUNT(*)            AS total_rows
        FROM `{tabel_ini}`
        WHERE region LIKE %s
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (DB_REGION_LIKE,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return {
            "tabel"       : tabel_ini,
            "last_update" : row["last_update"],
            "last_date"   : row["last_date"],
            "last_hour"   : row["last_hour"],
            "total_rows"  : row["total_rows"],
        }
    except Error as e:
        logger.error(f"Query last update error: {e}")
        raise



# 75 kolom raw (76 kolom tabel DIKURANGI order_ts) — order_ts sengaja tidak
# ikut di-SELECT (tidak dipakai perhitungan manapun di
# agresif_data/calculator_agresif, cuma dulu sumber kolom turunan "bulan
# order"/"tgl order" yang juga tidak dipakai kalkulasi), biar payload query
# lebih kecil. Kolom "order_ts" TETAP ADA di DataFrame RAW akhir — diisi
# None otomatis oleh agresif_data._pull_month_dedup() (loop DB_COLUMNS di
# sana), jadi struktur 94-kolom RAW export tidak berubah, cuma isinya kosong.
_AGRESIF_RAW_COLUMNS = (
    "bb_id, order_id, order_initiator_id, channel_transaction_id, "
    "homepass_id, hp_longitude, hp_latitude, hp_odp_name, order_status, "
    "sto_co, cluster, branch, wok, region, area, desa, kecamatan, "
    "kabupaten, provinsi, longitude, latitude, io_ts, "
    "re_ts, pi_ts, ps_ts, ro_ts, fo_ts, completed_ts, "
    "existing_ont_type, existing_ont_citem, pdd_enabled, pdd_commitment, "
    "product_commercial_name, price_total, price_package, fee_psb, "
    "payment_method, package_cat, citem_product, speed_product, "
    "package_type, order_type, order_type_id, process_state, "
    "provi_group, provi_subgroup, channel_name, channel_group, "
    "unit_type, unit_name, product_id_co, tgl_manja, appointment_id, "
    "appointment_start, appointment_end, c_wonum, c_amcrew, "
    "c_chief_code, c_chief_name, sf_code, sf_name, sf_company_name, "
    "odp_name, fallout_source, fallout_category, fallout_subcategory, "
    "fallout_reason, cancel_category, cancel_reason, dmo_category, "
    "dmo_lp_name, subchannel, referral_code, last_update, event_date"
)


def query_ordering_detail_full(bulan_ref: date, window_start: date,
                                window_end_exclusive: date) -> list[dict]:
    """
    SELECT 75 kolom (semua kolom tabel MINUS order_ts, lihat
    _AGRESIF_RAW_COLUMNS) dari indihome_ordering_detail_YYYYMM untuk 1 bulan
    penuh — dipakai agresif_data.build_raw() untuk mengisi ulang sheet RAW
    /agresif langsung dari DB (bukan paste manual).

    Filter sama seperti query_ordering_detail(): region LIKE 'JATENG%',
    order_type='NEW SALES', exclude produk wireless. TAMBAHAN:
      - order_id LIKE 'AO%' — cuma order AO (Agresif Order) yang dipakai
        report ini, order MO dibuang di level query (dulu dibuang belakangan
        di pandas oleh calculator_agresif._count/_count_promo, sekarang
        sekalian tidak usah ditarik dari DB biar payload lebih kecil).
      - io_ts ATAU re_ts ATAU ps_ts jatuh di [window_start,
        window_end_exclusive) — window ini dihitung sekali oleh build_raw
        (bulan_prev s/d akhir bulan_now, 2 bulan) dan dipakai SAMA utk kedua
        tabel bulanan yang ditarik, supaya order yang IO/RE/PS-nya menyeberang
        bulan tetap ketarik. Baris yang AO doang (belum ada io/re/ps ts sama
        sekali) atau io/re/ps-nya jauh di luar window ikut terbuang — aman,
        tidak dipakai metrik manapun (calculator_agresif cuma hitung baris
        dgn bulan_re/bulan_ps == bulan_now/bulan_prev, lihat _count()).

    Returns list of dicts, satu dict per baris = satu order (belum di-dedup).
    """
    REGION_ORDERING = "JATENG%"
    tabel = f"indihome_ordering_detail_{bulan_ref.strftime('%Y%m')}"
    sql = f"""
        SELECT {_AGRESIF_RAW_COLUMNS}
        FROM `{tabel}`
        WHERE region LIKE %s
          AND order_type = 'NEW SALES'
          AND order_id LIKE 'AO%%'
          AND (product_commercial_name NOT LIKE '%%WIRELESS%%'
               OR product_commercial_name IS NULL)
          AND (
                (io_ts >= %s AND io_ts < %s) OR
                (re_ts >= %s AND re_ts < %s) OR
                (ps_ts >= %s AND ps_ts < %s)
              )
    """
    params = (
        REGION_ORDERING,
        window_start, window_end_exclusive,
        window_start, window_end_exclusive,
        window_start, window_end_exclusive,
    )

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        r = cursor.fetchall()
        cursor.close()
        conn.close()
        return r

    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_ordering_detail_full {tabel}")
        logger.info(f"query_ordering_detail_full {tabel}: {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_ordering_detail_full {tabel} gagal: {e}")
        return []


def query_ordering_detail(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query indihome_ordering_detail untuk rentang tanggal tertentu.
    Hitung IO/RE/PS per WOK per channel, dengan mapping:
      AGENCY          → AGENCY
      GRAPARI         → GRAPARI
      WEB&APP         → DIGITAL
      B2B2C&OTHERS,
      SOBI AFFILIATE  → COMMUNITY

    IO = COUNT baris dimana io_ts valid (tidak NULL, tidak '0000-00-00')
         dan io_ts dalam rentang tgl_dari (inklusif) s/d tgl_sampai (EKSKLUSIF,
         caller wajib kirim tgl_sampai = tanggal terakhir yang diinginkan + 1
         hari — lihat calculator_channel.py)
    RE = COUNT baris dimana re_ts valid dan dalam rentang
    PS = COUNT baris dimana ps_ts valid dan dalam rentang

    Filter: region = 'JATENG-DIY', order_type = 'NEW SALES'
    Returns list of dicts: wok, branch, channel, io_trx, re_trx, ps_trx
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"

    def _ord_table(tgl: date) -> str:
        return f"{TABLE_PREFIX_ORD}{tgl.strftime('%Y%m')}"

    # Kumpulkan tabel yang dibutuhkan (support lintas bulan). tgl_sampai di
    # sini EKSKLUSIF (caller sudah +1 hari), jadi batas tiap tabel bulanan
    # juga harus dihitung eksklusif (awal bulan berikutnya) — BUKAN tanggal
    # kalender terakhir bulan itu (akhir_bulan lama = tgl doang jam 00:00,
    # yang di query DATETIME artinya membuang semua transaksi di hari
    # terakhir bulan itu, persis pas closing jatuh di akhir bulan).
    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal < tgl_sampai:
        nama = _ord_table(awal)
        awal_bulan_berikut = awal + _rdelta(months=1)   # batas eksklusif bulan ini
        t_dari  = max(tgl_dari,   awal)
        t_sampai_tabel = min(tgl_sampai, awal_bulan_berikut)
        if t_dari < t_sampai_tabel:
            tabels[nama] = (t_dari, t_sampai_tabel)
        awal = awal_bulan_berikut

    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                {_GEO_SEL},
                {_WOK_KAB} AS wok,
                {_BRANCH_KAB} AS branch,
                CASE
                    WHEN UPPER(TRIM(channel_group)) = 'AGENCY'         THEN 'AGENCY'
                    WHEN UPPER(TRIM(channel_group)) = 'GRAPARI'        THEN 'GRAPARI'
                    WHEN UPPER(TRIM(channel_group)) = 'WEB&APP'        THEN 'DIGITAL'
                    WHEN UPPER(TRIM(channel_group)) IN (
                         'B2B2C&OTHERS','SOBI AFFILIATE')               THEN 'COMMUNITY'
                    ELSE 'OTHER'
                END AS channel,
                COUNT(CASE WHEN io_ts IS NOT NULL
                            AND io_ts != '0000-00-00'
                            AND io_ts >= %s AND io_ts < %s THEN 1 END) AS io_trx,
                COUNT(CASE WHEN re_ts IS NOT NULL
                            AND re_ts != '0000-00-00'
                            AND re_ts >= %s AND re_ts < %s THEN 1 END) AS re_trx,
                COUNT(CASE WHEN ps_ts IS NOT NULL
                            AND ps_ts != '0000-00-00'
                            AND ps_ts >= %s AND ps_ts < %s THEN 1 END) AS ps_trx
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND (product_commercial_name NOT LIKE '%WIRELESS%'
                   OR product_commercial_name IS NULL)
            GROUP BY {_WOK_KAB}, {_BRANCH_KAB}, channel, {_GEO_GRP}
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (
                t_dari, t_sampai,
                t_dari, t_sampai,
                t_dari, t_sampai,
                REGION_ORDERING,
            ))
            r = _resolve_geo(cursor.fetchall(), ('io_trx', 're_trx', 'ps_trx'))
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_ordering_detail {tabel}")
            # Buang channel 'OTHER' yg tidak dikenali
            rows = [r for r in rows if r["channel"] != "OTHER"]
            rows_all += rows
            logger.info(f"query_ordering_detail {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            logger.warning(f"query_ordering_detail {tabel} gagal: {e}")

    return rows_all


def query_re_ps_raw(hari_ini: date) -> list[dict]:
    """
    Setara query_re_ps(hari_ini), tapi sumbernya LANGSUNG dari tabel raw
    indihome_ordering_detail_YYYYMM (bukan dashboard_hourly_sales yang sudah
    pre-aggregated) — dipakai /liveupdatebk & /closingbk sebagai cross-check
    independen dari data mentah, hitungan ulang dari nol.

    Filter identik dengan query_ordering_detail(): region='JATENG-DIY',
    order_type='NEW SALES', exclude produk WIRELESS.

    io_ts/re_ts/ps_ts adalah timestamp TERPISAH per baris (beda dari
    dashboard_hourly_sales yang sudah py-aggregated per activity_date/
    activity_hour) — jadi io/re/ps masing-masing di-GROUP BY tanggal & jam, {_GEO_GRP}
    dari timestamp-nya SENDIRI, lalu ditulis sebagai baris "long format"
    terpisah (baris IO: io_trx=N, re_trx=0, ps_trx=0, dst). Ini membuat
    hitung_re_ps_sql() (calculator_sql.py) bisa dipakai APA ADANYA — fungsi
    sum_col() di sana sudah filter & sum per-kolom, jadi baris metrik lain
    (yang re_trx=0 dst di baris itu) tidak ikut ke-hitung dobel.

    Returns list of dicts: wok, branch, activity_date, activity_hour,
    io_trx, re_trx, ps_trx (bentuk sama persis dengan query_re_ps()).
    """
    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"

    def _ord_table(tgl: date) -> str:
        return f"{TABLE_PREFIX_ORD}{tgl.strftime('%Y%m')}"

    bulan_lalu = hari_ini - relativedelta(months=1)
    tabel_ini  = _ord_table(hari_ini)
    tabel_lalu = _ord_table(bulan_lalu)

    # Rentang yang dibutuhkan sama persis dengan query_re_ps(): cukup s/d
    # awal WoW-prev / MoM-prev yang paling jauh.
    tgl_wow_prev_start = hari_ini - timedelta(days=13)
    tgl_mom_prev_start = bulan_lalu.replace(day=1)
    tgl_dari       = min(tgl_wow_prev_start, tgl_mom_prev_start)
    awal_bulan_ini = hari_ini.replace(day=1)

    METRICS = [("io_ts", "io_trx"), ("re_ts", "re_trx"), ("ps_ts", "ps_trx")]

    def _query_tabel(tabel: str, t_dari: date, t_sampai: date) -> list[dict]:
        # SATU scan tabel untuk IO+RE+PS sekaligus (dulu 3 scan terpisah).
        # Baris di-GROUP BY (geo, jam io_ts, jam re_ts, jam ps_ts) lalu dipecah
        # di Python jadi baris "long format" per metrik. ts_col DATETIME ->
        # batas eksklusif (t_sampai+1 hari) supaya seluruh hari t_sampai ikut.
        t_sampai_excl = t_sampai + timedelta(days=1)

        def _jam(c):
            return (f"(CASE WHEN {c} IS NULL OR {c} < '2000-01-01' THEN NULL "
                    f"ELSE CONCAT(DATE({c}), ' ', LPAD(HOUR({c}), 2, '0')) END)")
        sql = f"""
            SELECT
                {_GEO_SEL},
                {_WOK_KAB} AS wok,
                {_BRANCH_KAB} AS branch,
                {_jam('io_ts')} AS h_io,
                {_jam('re_ts')} AS h_re,
                {_jam('ps_ts')} AS h_ps,
                COUNT(*)        AS n
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND (product_commercial_name NOT LIKE '%%WIRELESS%%'
                   OR product_commercial_name IS NULL)
              AND ((io_ts >= %s AND io_ts < %s)
                OR (re_ts >= %s AND re_ts < %s)
                OR (ps_ts >= %s AND ps_ts < %s))
            GROUP BY {_WOK_KAB}, {_BRANCH_KAB}, h_io, h_re, h_ps, {_GEO_GRP}
        """
        prm = (REGION_ORDERING,) + (t_dari, t_sampai_excl) * 3

        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, prm)
            r = _resolve_geo(cursor.fetchall(), ('n',))
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_re_ps_raw {tabel}")
            logger.info(f"query_re_ps_raw {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris (1 scan)")
        except Error as e:
            logger.warning(f"query_re_ps_raw {tabel} gagal: {e}")
            return []

        out = []
        for r in rows:
            for hkey, trx_field in (("h_io", "io_trx"), ("h_re", "re_trx"), ("h_ps", "ps_trx")):
                h = r.get(hkey)
                if not h:
                    continue
                tgl = datetime.strptime(h[:10], "%Y-%m-%d").date()
                if tgl < t_dari or tgl > t_sampai:
                    continue
                out.append({
                    "wok"          : r["wok"],
                    "branch"       : r["branch"],
                    "activity_date": tgl,
                    "activity_hour": int(h[11:13]),
                    "io_trx"       : r["n"] if trx_field == "io_trx" else 0,
                    "re_trx"       : r["n"] if trx_field == "re_trx" else 0,
                    "ps_trx"       : r["n"] if trx_field == "ps_trx" else 0,
                })
        return out

    rows_all = []

    # ── Tabel bulan lalu (jika rentang melewati awal bulan ini) ────────────
    if tgl_dari < awal_bulan_ini:
        rows_all += _query_tabel(tabel_lalu, tgl_dari, awal_bulan_ini - timedelta(days=1))

    # ── Tabel bulan ini ──────────────────────────────────────────────────
    rows_all += _query_tabel(tabel_ini, awal_bulan_ini, hari_ini)

    if not rows_all:
        raise ValueError(f"Tidak ada data ordering_detail (raw) untuk tanggal s/d {hari_ini}")

    return rows_all


def query_daily_performance_raw(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Setara fmc_api.query_daily_performance_fmc(), tapi dari tabel raw
    indihome_ordering_detail_YYYYMM langsung (bukan dashboard_hourly_sales).
    Dipakai calculator_daily.hitung_daily_performance(data_source="raw")
    untuk /closingbk. Filter & pola long-format (io/re/ps sbg baris
    terpisah per tanggal timestamp-nya sendiri) sama seperti
    query_re_ps_raw() — lihat komentar di sana untuk alasannya.

    CATATAN: revenue (ps_rev) SENGAJA tidak di-query di sini — kolom
    revenue di raw table belum terverifikasi namanya, dan menebak nama
    kolom berisiko salah hitung. Revenue/ARPU untuk data_source="raw"
    ditandai N/A oleh calculator_daily.hitung_daily_performance() (sama
    seperti sudah dilakukan untuk data_source="fmc"), bukan bug.

    Returns list of dicts: wok, branch, activity_date, io_trx, re_trx, ps_trx.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"

    def _ord_table(tgl: date) -> str:
        return f"{TABLE_PREFIX_ORD}{tgl.strftime('%Y%m')}"

    # Kumpulkan tabel yang dibutuhkan (support lintas bulan, walau caller
    # saat ini selalu memanggil dengan rentang 1 bulan penuh).
    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _ord_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (max(tgl_dari, awal), min(tgl_sampai, akhir_bulan))
        awal = awal + _rdelta(months=1)

    METRICS  = [("io_ts", "io_trx"), ("re_ts", "re_trx"), ("ps_ts", "ps_trx")]
    rows_all = []

    for tabel, (t_dari, t_sampai) in tabels.items():
        t_sampai_excl = t_sampai + timedelta(days=1)
        for ts_col, trx_field in METRICS:
            sql = f"""
                SELECT
                    {_GEO_SEL},
                    {_WOK_KAB} AS wok,
                    {_BRANCH_KAB} AS branch,
                    DATE({ts_col}) AS activity_date,
                    COUNT(*)       AS trx
                FROM `{tabel}`
                WHERE region LIKE %s
                  AND order_type = 'NEW SALES'
                  AND (product_commercial_name NOT LIKE '%%WIRELESS%%'
                       OR product_commercial_name IS NULL)
                  AND {ts_col} IS NOT NULL
                  AND {ts_col} != '0000-00-00'
                  AND {ts_col} >= %s AND {ts_col} < %s
                GROUP BY {_WOK_KAB}, {_BRANCH_KAB}, DATE({ts_col}), {_GEO_GRP}
            """
            def _jalankan():
                conn   = get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute(sql, (REGION_ORDERING, t_dari, t_sampai_excl))
                r = _resolve_geo(cursor.fetchall(), ('trx',))
                cursor.close()
                conn.close()
                return r
            try:
                rows = _jalankan_dengan_retry(_jalankan, f"query_daily_performance_raw {tabel}.{ts_col}")
                logger.info(f"query_daily_performance_raw {tabel}.{ts_col} ({t_dari}~{t_sampai}): {len(rows)} baris")
                for r in rows:
                    rows_all.append({
                        "wok"          : r["wok"],
                        "branch"       : r["branch"],
                        "activity_date": r["activity_date"],
                        "io_trx"       : r["trx"] if trx_field == "io_trx" else 0,
                        "re_trx"       : r["trx"] if trx_field == "re_trx" else 0,
                        "ps_trx"       : r["trx"] if trx_field == "ps_trx" else 0,
                    })
            except Error as e:
                logger.warning(f"query_daily_performance_raw {tabel}.{ts_col} gagal: {e}")

    return rows_all


def query_daily_city_raw(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Pengganti sumber dashboard_hourly_sales untuk Performance MtD by WOK / by
    City (/closingsql): IO, RE, PS, dan REVENUE per WOK + kabupaten + tanggal,
    langsung dari indihome_ordering_detail_YYYYMM.

    - IO/RE/PS = COUNT order per tanggal io_ts / re_ts / ps_ts masing-masing
      (long format per metrik, lalu digabung jadi 1 baris per kunci).
    - Revenue (ps_rev) = SUM(price_package) order PS — sudah dicek PERSIS sama
      dengan dashboard_hourly_sales.ps_rev (mis. Sep-2026: 2.264.565.173).
    - Filter sama dgn report lain dari ordering_detail: region JATENG%,
      order_type='NEW SALES', exclude produk WIRELESS.
    - WOK/BRANCH dari kabupaten (wilayah.py); kabupaten kosong/NAN/luar wilayah
      diisi lewat geotag longitude/latitude -> fallback STO (_resolve_geo).

    Returns list of dicts: wok, branch, kabupaten, activity_date, io_trx,
    re_trx, ps_trx, ps_rev.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    REGION_ORDERING = "JATENG%"
    METRICS = [("io_ts", "io_trx"), ("re_ts", "re_trx"), ("ps_ts", "ps_trx")]

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = f"indihome_ordering_detail_{awal.strftime('%Y%m')}"
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (max(tgl_dari, awal), min(tgl_sampai, akhir_bulan))
        awal = awal + _rdelta(months=1)

    gabung: dict = {}
    for tabel, (t_dari, t_sampai) in tabels.items():
        t_sampai_excl = t_sampai + timedelta(days=1)
        for ts_col, trx_field in METRICS:
            rev_expr = "COALESCE(SUM(price_package), 0)" if ts_col == "ps_ts" else "0"
            sql = f"""
                SELECT
                    {_GEO_SEL},
                    {_WOK_KAB} AS wok,
                    {_BRANCH_KAB} AS branch,
                    {_KAB_NAMA_OK} AS kabupaten,
                    DATE({ts_col}) AS activity_date,
                    COUNT(*)       AS trx,
                    {rev_expr}     AS rev
                FROM `{tabel}`
                WHERE region LIKE %s
                  AND order_type = 'NEW SALES'
                  AND (product_commercial_name NOT LIKE '%%WIRELESS%%'
                       OR product_commercial_name IS NULL)
                  AND {ts_col} IS NOT NULL
                  AND {ts_col} != '0000-00-00'
                  AND {ts_col} >= %s AND {ts_col} < %s
                GROUP BY {_WOK_KAB}, {_BRANCH_KAB}, {_KAB_NAMA_OK}, DATE({ts_col}), {_GEO_GRP}
            """
            def _jalankan():
                conn   = get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute(sql, (REGION_ORDERING, t_dari, t_sampai_excl))
                r = _resolve_geo(cursor.fetchall(), ('trx', 'rev'))
                cursor.close()
                conn.close()
                return r
            try:
                rows = _jalankan_dengan_retry(_jalankan, f"query_daily_city_raw {tabel}.{ts_col}")
                logger.info(f"query_daily_city_raw {tabel}.{ts_col} ({t_dari}~{t_sampai}): {len(rows)} baris")
            except Error as e:
                logger.warning(f"query_daily_city_raw {tabel}.{ts_col} gagal: {e}")
                continue
            for r in rows:
                kunci = (r["wok"], r["branch"], r["kabupaten"], r["activity_date"])
                baris = gabung.setdefault(kunci, {
                    "wok": r["wok"], "branch": r["branch"], "kabupaten": r["kabupaten"],
                    "activity_date": r["activity_date"],
                    "io_trx": 0, "re_trx": 0, "ps_trx": 0, "ps_rev": 0,
                })
                baris[trx_field] += int(r["trx"] or 0)
                if trx_field == "ps_trx":
                    baris["ps_rev"] += int(r["rev"] or 0)
    return list(gabung.values())


def query_wireless_performance(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Untuk /wireless (IO-RE-PS EZNet Wireless per WOK): tabel raw
    indihome_ordering_detail_YYYYMM, HANYA produk yang product_commercial_name-nya
    mengandung kata WIRELESS (kebalikan dari filter di report lain yang justru
    meng-exclude WIRELESS). Pola long-format sama dgn query_daily_performance_raw:
    io/re/ps dihitung per tanggal timestamp-nya sendiri (io_ts/re_ts/ps_ts).

    Tidak ada filter package_cat 'HWA' — produk wireless bukan produk hardware,
    dan belum ada dasar untuk meng-exclude-nya.

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

    METRICS  = [("io_ts", "io_trx"), ("re_ts", "re_trx"), ("ps_ts", "ps_trx")]
    rows_all = []

    for tabel, (t_dari, t_sampai) in tabels.items():
        t_sampai_excl = t_sampai + timedelta(days=1)
        for ts_col, trx_field in METRICS:
            sql = f"""
                SELECT
                    {_GEO_SEL},
                    {_WOK_KAB} AS wok,
                    {_BRANCH_KAB} AS branch,
                    DATE({ts_col}) AS activity_date,
                    COUNT(*)       AS trx
                FROM `{tabel}`
                WHERE region LIKE %s
                  AND order_type = 'NEW SALES'
                  AND product_commercial_name LIKE '%%WIRELESS%%'
                  AND {ts_col} IS NOT NULL
                  AND {ts_col} != '0000-00-00'
                  AND {ts_col} >= %s AND {ts_col} < %s
                GROUP BY {_WOK_KAB}, {_BRANCH_KAB}, DATE({ts_col}), {_GEO_GRP}
            """
            def _jalankan():
                conn   = get_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute(sql, (DB_REGION_LIKE, t_dari, t_sampai_excl))
                r = _resolve_geo(cursor.fetchall(), ('trx',))
                cursor.close()
                conn.close()
                return r
            rows = _jalankan_dengan_retry(_jalankan, f"query_wireless_performance {tabel}.{ts_col}")
            logger.info(f"query_wireless_performance {tabel}.{ts_col} ({t_dari}~{t_sampai}): {len(rows)} baris")
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


def query_last_update_raw() -> dict:
    """
    Cek update terakhir tabel RAW indihome_ordering_detail bulan ini (kolom
    last_update) — dipakai sebagai cutoff untuk /liveupdatebk & /closingbk.
    Beda dari query_last_update() yang cek dashboard_hourly_sales; tabel
    ini tetap punya kolom last_update yang sama (lihat query_all_table_status()
    label "📦 Ordering Detail" yang sudah lebih dulu pakai kolom ini).

    Return dict: tabel, last_update, last_date (tanggal dari last_update),
    total_rows.
    """
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"
    tabel_ini = f"{TABLE_PREFIX_ORD}{date.today().strftime('%Y%m')}"
    sql = f"""
        SELECT
            MAX(last_update) AS last_update,
            COUNT(*)         AS total_rows
        FROM `{tabel_ini}`
        WHERE region LIKE 'JATENG%'
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        last_update = row["last_update"] if row else None
        return {
            "tabel"       : tabel_ini,
            "last_update" : last_update,
            "last_date"   : last_update.date() if last_update else None,
            "total_rows"  : row["total_rows"] if row else 0,
        }
    except Error as e:
        logger.error(f"Query last update raw error: {e}")
        raise


def query_order_terbaru_hari_ini() -> datetime | None:
    """
    Waktu order TERBARU hari ini di indihome_ordering_detail bulan ini =
    MAX(io_ts, re_ts, ps_ts) pada tanggal hari ini. Dipakai sebagai cutoff
    laporan live (/liveupdate dkk): jam cutoff D-1/D-7 Hourly di
    calculator_sql.hitung_re_ps_sql = jam dari waktu ini, jadi label footer
    dan batas data selalu sama. Filter sama dengan query_re_ps_raw
    (region JATENG%, NEW SALES, exclude WIRELESS). None bila belum ada order hari ini.
    """
    tabel = f"indihome_ordering_detail_{date.today().strftime('%Y%m')}"
    awal  = date.today()
    besok = awal + timedelta(days=1)
    kolom = ("io_ts", "re_ts", "ps_ts")
    pilih = ", ".join(
        f"MAX(CASE WHEN {c} >= %s AND {c} < %s THEN {c} END) AS m_{c}" for c in kolom)
    sql = f"""
        SELECT {pilih}
        FROM `{tabel}`
        WHERE region LIKE 'JATENG%%'
          AND order_type = 'NEW SALES'
          AND (product_commercial_name NOT LIKE '%%WIRELESS%%'
               OR product_commercial_name IS NULL)
    """
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (awal, besok) * 3)
        row = cursor.fetchone()
        cursor.close()
        conn.close()
    except Error as e:
        logger.error(f"Query order terbaru hari ini error: {e}")
        raise
    nilai = [v for v in (row or {}).values() if v]
    return max(nilai) if nilai else None


def _sql_wil(wok_lama: bool):
    """
    Fragmen SQL kolom wilayah: (SELECT, GROUP BY awal).
    wok_lama=True -> kolom `wok`/`branch` bawaan tabel (struktur WOK lama, 16 WOK);
    False -> WOK/BRANCH baru dari kabupaten (wilayah.py) + kolom geo.
    GROUP BY diakhiri koma/spasi supaya bisa langsung disambung kolom berikutnya.
    """
    if wok_lama:
        return "wok, branch", "wok, branch, "
    return (
        f"{_GEO_SEL}, {_WOK_KAB} AS wok, {_BRANCH_KAB} AS branch",
        f"{_WOK_KAB}, {_BRANCH_KAB}, ",
    )


def query_re_fallout(tgl_dari: date, tgl_sampai: date, wok_lama: bool = False) -> list[dict]:
    """
    Query indihome_ordering_detail untuk Monitoring RE : Fallout Salah
    Tagging/Salah Homepass (dipakai calculator_salahhomepass.py / /salahhomepass).

    RE          = COUNT baris dimana re_ts valid dan dalam rentang tgl_dari s/d tgl_sampai
    RE Fallout  = RE di atas dengan fallout_reason mengandung "SALAH TAGGING"
                  atau "SALAH HOMEPASS" (substring, bukan kategori bersih)

    Channel: AGENCY (channel_group = 'AGENCY') vs NON AGENCY (selain itu).
    Filter: region = 'JATENG-DIY', order_type = 'NEW SALES', exclude wireless
    (konsisten dengan query_ordering_detail / query_sf_agency dkk).

    Returns list of dicts: wok, branch, channel, re_trx, re_fallout
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"

    def _ord_table(tgl: date) -> str:
        return f"{TABLE_PREFIX_ORD}{tgl.strftime('%Y%m')}"

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _ord_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (
            max(tgl_dari,   awal),
            min(tgl_sampai, akhir_bulan),
        )
        awal = awal + _rdelta(months=1)

    sel_wil, grp_wil = _sql_wil(wok_lama)
    grp_geo = "" if wok_lama else f", {_GEO_GRP}"
    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                {sel_wil},
                CASE WHEN UPPER(TRIM(channel_group)) = 'AGENCY'
                     THEN 'AGENCY' ELSE 'NON AGENCY' END AS channel,
                COUNT(CASE WHEN re_ts IS NOT NULL
                            AND re_ts != '0000-00-00'
                            AND re_ts BETWEEN %s AND %s THEN 1 END) AS re_trx,
                COUNT(CASE WHEN re_ts IS NOT NULL
                            AND re_ts != '0000-00-00'
                            AND re_ts BETWEEN %s AND %s
                            AND (UPPER(fallout_reason) LIKE '%SALAH TAGGING%'
                                 OR UPPER(fallout_reason) LIKE '%SALAH HOMEPASS%')
                           THEN 1 END) AS re_fallout
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND (product_commercial_name NOT LIKE '%WIRELESS%'
                   OR product_commercial_name IS NULL)
            GROUP BY {grp_wil}channel{grp_geo}
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (
                t_dari, t_sampai,
                t_dari, t_sampai,
                REGION_ORDERING,
            ))
            r = cursor.fetchall() if wok_lama else _resolve_geo(cursor.fetchall(), ('re_trx', 're_fallout'))
            cursor.close()
            conn.close()
            return r
        try:
            # Retry dulu kalau VPN/DB putus di tengah — baru raise (batalkan
            # laporan) kalau errornya BUKAN soal koneksi (mis. tabel belum ada).
            rows = _jalankan_dengan_retry(_jalankan, f"query_re_fallout {tabel}")
            rows_all += rows
            logger.info(f"query_re_fallout {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            # JANGAN telan diam-diam lalu kembalikan data separuh. Kalau query
            # 1 bulan gagal (mis. VPN putus), pemanggil akan mengira bulan itu
            # nol -> MoM meledak jadi angka ngawur (pernah kejadian: RE bulan
            # lalu gagal diambil, MoM tampil +905900%). Lebih baik gagal jelas.
            logger.error(f"query_re_fallout {tabel} gagal: {e}")
            raise RuntimeError(
                f"Query {tabel} ({t_dari}~{t_sampai}) gagal: {e}. "
                f"Laporan dibatalkan supaya tidak menampilkan angka MoM yang salah."
            ) from e

    return rows_all


def query_re_fallout_raw(tgl_dari: date, tgl_sampai: date, wok_lama: bool = False) -> list[dict]:
    """
    Versi row-level (belum diagregasi) dari query_re_fallout(), untuk export
    raw data /salahtagging supaya bisa dicek manual — kolom & filter sama
    seperti query pengecekan manual "Monitor Salah Tagging.sql" (folder Willy),
    HANYA baris dengan fallout_reason mengandung "SALAH TAGGING" atau
    "SALAH HOMEPASS" (regex/LIKE, sama seperti definisi RE Fallout di
    query_re_fallout()).

    Returns list of dicts: bb_id, order_id, branch, wok, sto_co, order_status,
    io_ts, re_ts, ps_ts, product_commercial_name, process_state, channel_group,
    sf_code, sf_name, fallout_category, fallout_subcategory, fallout_reason
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"

    def _ord_table(tgl: date) -> str:
        return f"{TABLE_PREFIX_ORD}{tgl.strftime('%Y%m')}"

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _ord_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (
            max(tgl_dari,   awal),
            min(tgl_sampai, akhir_bulan),
        )
        awal = awal + _rdelta(months=1)

    sel_wil_raw = (
        "branch, wok" if wok_lama else
        f"{_GEO_SEL}, {_BRANCH_KAB} AS branch, {_WOK_KAB} AS wok"
    )
    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                bb_id,
                order_id,
                {sel_wil_raw},
                sto_co,
                order_status,
                io_ts,
                re_ts,
                ps_ts,
                product_commercial_name,
                process_state,
                channel_group,
                sf_code,
                sf_name,
                fallout_category,
                fallout_subcategory,
                fallout_reason
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND (product_commercial_name NOT LIKE '%WIRELESS%'
                   OR product_commercial_name IS NULL)
              AND re_ts IS NOT NULL
              AND re_ts != '0000-00-00'
              AND re_ts BETWEEN %s AND %s
              AND (UPPER(fallout_reason) LIKE '%SALAH TAGGING%'
                   OR UPPER(fallout_reason) LIKE '%SALAH HOMEPASS%')
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (REGION_ORDERING, t_dari, t_sampai))
            r = cursor.fetchall() if wok_lama else _resolve_geo(cursor.fetchall(), None)
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_re_fallout_raw {tabel}")
            rows_all += rows
            logger.info(f"query_re_fallout_raw {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            # Sama seperti query_re_fallout: jangan kembalikan data separuh —
            # export raw/kontributor SF-nya nanti bohong (baris hilang diam-diam).
            logger.error(f"query_re_fallout_raw {tabel} gagal: {e}")
            raise RuntimeError(
                f"Query {tabel} ({t_dari}~{t_sampai}) gagal: {e}. "
                f"Export dibatalkan supaya datanya tidak terpotong sebagian."
            ) from e

    return rows_all


def query_pdd(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query data PDD dari indihome_ordering_detail_YYYYMM untuk region JATENG-DIY.
    PS = order_id dengan ps_ts valid (tidak NULL, bukan '0000-00-00'), order_type = 'NEW SALES'.

    Channel mapping (beda dari query_ordering_detail — SOBI berdiri sendiri, bukan
    digabung ke COMMUNITY):
      AGENCY          -> AGENCY
      GRAPARI         -> GRAPARI
      SOBI AFFILIATE  -> SOBI
      WEB&APP         -> WEB_APPS
      lainnya (mis. B2B2C&OTHERS) -> OTHER (tetap disertakan, dibuang di layer kalkulator
      untuk breakdown per-channel, tapi tetap ikut dihitung sf_code untuk SF Active total)

    Returns row-level (bukan agregat): wok, branch, channel, sf_code, pdd_enabled.
    pdd_enabled=1 menandakan order tsb adalah order PDD.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"

    def _ord_table(tgl: date) -> str:
        return f"{TABLE_PREFIX_ORD}{tgl.strftime('%Y%m')}"

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _ord_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (
            max(tgl_dari,   awal),
            min(tgl_sampai, akhir_bulan),
        )
        awal = awal + _rdelta(months=1)

    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                {_GEO_SEL},
                {_WOK_KAB} AS wok,
                {_BRANCH_KAB} AS branch,
                sf_code,
                pdd_enabled,
                CASE
                    WHEN UPPER(TRIM(channel_group)) = 'AGENCY'          THEN 'AGENCY'
                    WHEN UPPER(TRIM(channel_group)) = 'GRAPARI'         THEN 'GRAPARI'
                    WHEN UPPER(TRIM(channel_group)) = 'SOBI AFFILIATE'  THEN 'SOBI'
                    WHEN UPPER(TRIM(channel_group)) = 'WEB&APP'         THEN 'WEB_APPS'
                    ELSE 'OTHER'
                END AS channel
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND ps_ts IS NOT NULL
              AND ps_ts != '0000-00-00'
              AND ps_ts BETWEEN %s AND %s
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (REGION_ORDERING, t_dari, t_sampai))
            r = _resolve_geo(cursor.fetchall(), None)
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_pdd {tabel}")
            rows_all += rows
            logger.info(f"query_pdd {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            logger.warning(f"query_pdd {tabel} gagal: {e}")

    return rows_all


def query_addon(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query data Addon (FTTR / Ultra Mesh Wifi / Indoor Camera) dari
    indihome_ordering_detail_YYYYMM untuk region JATENG-DIY.
    PS = order_id dengan ps_ts valid (tidak NULL, bukan '0000-00-00'),
    order_type = 'MODIFICATION - ADDON'.

    Klasifikasi produk dari product_commercial_name:
      FTTR       -> mengandung kata 'FTTR'
      MESH_WIFI  -> = 'Ultra Mesh Wifi'
      IP_CAM     -> = 'Indoor Camera'
      lainnya    -> dibuang (tidak masuk hasil)

    Returns row-level (bukan agregat): wok, branch, product, ps_ts.
    Agregasi per periode (Mei/Jun/MTD Jul dsb) dilakukan di calculator_addon.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"

    def _ord_table(tgl: date) -> str:
        return f"{TABLE_PREFIX_ORD}{tgl.strftime('%Y%m')}"

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _ord_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (
            max(tgl_dari,   awal),
            min(tgl_sampai, akhir_bulan),
        )
        awal = awal + _rdelta(months=1)

    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                {_GEO_SEL},
                {_WOK_KAB} AS wok,
                {_BRANCH_KAB} AS branch,
                ps_ts,
                CASE
                    WHEN UPPER(product_commercial_name) LIKE '%FTTR%' THEN 'FTTR'
                    WHEN UPPER(TRIM(product_commercial_name)) = 'ULTRA MESH WIFI' THEN 'MESH_WIFI'
                    WHEN UPPER(TRIM(product_commercial_name)) = 'INDOOR CAMERA'   THEN 'IP_CAM'
                    ELSE NULL
                END AS product
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'MODIFICATION - ADDON'
              AND ps_ts IS NOT NULL
              AND ps_ts != '0000-00-00'
              AND ps_ts BETWEEN %s AND %s
              AND (
                    UPPER(product_commercial_name) LIKE '%FTTR%'
                 OR UPPER(TRIM(product_commercial_name)) IN ('ULTRA MESH WIFI', 'INDOOR CAMERA')
              )
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (REGION_ORDERING, t_dari, t_sampai))
            r = _resolve_geo(cursor.fetchall(), None)
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_addon {tabel}")
            rows_all += rows
            logger.info(f"query_addon {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            logger.warning(f"query_addon {tabel} gagal: {e}")

    return rows_all


def query_homepass(bulan_ref: date, wok_lama: bool = False) -> list[dict]:
    """
    Query Homepass Report — homepass_sales_YYYYMM (bulan bulan_ref + bulan sebelumnya,
    UNION ALL) LEFT JOIN indihome_ordering_detail_YYYYMM (bulan yang sama), via
    order_transaction = order_id. Union 2 bulan supaya order yang homepass-nya dibuat
    di ujung bulan tapi baru match ordering_detail di bulan sebelah (atau sebaliknya)
    tetap ketemu — replikasi pola query yang dikasih user.

    Tidak ada filter tanggal di sini (dikembalikan row-level apa adanya); filter MtD
    per metrik (created_at untuk Total IO, io_ts/re_ts/ps_ts masing-masing untuk
    IO/RE/PS) dilakukan di layer kalkulator.

    WOK/BRANCH dipetakan dari kabupaten (wilayah.py), bukan dari kolom wok/branch
    tabel: homepass_sales tidak punya kolom kabupaten, jadi dipakai
      1) kabupaten order (indihome_ordering_detail.kabupaten) bila order-nya ada
         dan kabupatennya terpetakan, selain itu
      2) geotagging longitude/latitude order (wilayah.geotag_kab), selain itu
      3) kabupaten STO (sto_id homepass -> indihome_ordering_detail.sto_co ->
         kabupaten_sto) sbg pilihan terakhir (order tak ketemu). Baris yang tetap
         tidak terpetakan dibuang.
    Kolom sto_co = STO order apa adanya (sto_id homepass bila order tak ketemu); WOK
    TIDAK diturunkan dari STO, jadi satu STO bisa muncul di beberapa WOK (breakdown per STO).

    Returns row-level: order_id, wok, branch, sto_co, created_at, sf_code, io_ts,
                        re_ts, ps_ts, fallout_reason.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    if wok_lama:
        return _query_homepass_wok_lama(bulan_ref)

    REGIONAL = "JATENG%"
    bulan_prev = bulan_ref - _rdelta(months=1)

    tabel_hp_ref  = f"homepass_sales_{bulan_ref.strftime('%Y%m')}"
    tabel_hp_prev = f"homepass_sales_{bulan_prev.strftime('%Y%m')}"
    tabel_iod_ref  = f"indihome_ordering_detail_{bulan_ref.strftime('%Y%m')}"
    tabel_iod_prev = f"indihome_ordering_detail_{bulan_prev.strftime('%Y%m')}"

    sql = f"""
        WITH homepass AS (
            SELECT sto_id, order_transaction, created_at
            FROM `{tabel_hp_ref}`
            WHERE regional LIKE %s

            UNION ALL

            SELECT sto_id, order_transaction, created_at
            FROM `{tabel_hp_prev}`
            WHERE regional LIKE %s
        )
        SELECT
            hp.order_transaction                         AS order_id,
            hp.sto_id,
            COALESCE(a.kabupaten, b.kabupaten)           AS kabupaten_order,
            COALESCE(a.longitude, b.longitude)           AS lon_order,
            COALESCE(a.latitude, b.latitude)             AS lat_order,
            hp.created_at,
            COALESCE(a.sto_co, b.sto_co, hp.sto_id)      AS sto_co,
            COALESCE(a.sf_code, b.sf_code)               AS sf_code,
            COALESCE(a.io_ts, b.io_ts)                   AS io_ts,
            COALESCE(a.re_ts, b.re_ts)                   AS re_ts,
            COALESCE(a.ps_ts, b.ps_ts)                   AS ps_ts,
            COALESCE(a.fallout_reason, b.fallout_reason) AS fallout_reason
        FROM homepass hp
        LEFT JOIN `{tabel_iod_ref}`  a ON hp.order_transaction = a.order_id
        LEFT JOIN `{tabel_iod_prev}` b ON hp.order_transaction = b.order_id
    """
    # Referensi STO -> kabupaten (kabupaten lokasi STO), dari ordering_detail 2 bulan
    sql_sto = f"""
        SELECT sto_co, kabupaten_sto FROM `{tabel_iod_ref}`  WHERE region LIKE %s
        UNION
        SELECT sto_co, kabupaten_sto FROM `{tabel_iod_prev}` WHERE region LIKE %s
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (REGIONAL, REGIONAL))
        r = cursor.fetchall()
        cursor.execute(sql_sto, (REGIONAL, REGIONAL))
        sto = cursor.fetchall()
        cursor.close()
        conn.close()
        return r, sto
    try:
        rows, sto_rows = _jalankan_dengan_retry(_jalankan, f"query_homepass {tabel_hp_ref}+{tabel_hp_prev}")
    except Error as e:
        logger.warning(f"query_homepass {tabel_hp_ref}+{tabel_hp_prev} gagal: {e}")
        return []

    sto_ke_kab = {}
    for s in sto_rows:
        kunci = str(s["sto_co"] or "").strip().upper()
        if kunci and wilayah.petakan_kab(s["kabupaten_sto"]):
            sto_ke_kab.setdefault(kunci, s["kabupaten_sto"])

    hasil, dibuang = [], 0
    for r in rows:
        h = wilayah.petakan_kab(r.pop("kabupaten_order", None))
        lon, lat = r.pop("lon_order", None), r.pop("lat_order", None)
        if h is None:
            h = wilayah.petakan_kab(wilayah.geotag_kab(lon, lat))
        if h is None:
            kab_sto = sto_ke_kab.get(str(r.get("sto_id") or "").strip().upper())
            h = wilayah.petakan_kab(kab_sto)
        if h is None:
            dibuang += 1
            continue
        r["wok"], r["branch"] = h
        hasil.append(r)
    logger.info(
        f"query_homepass {tabel_hp_ref}+{tabel_hp_prev}: {len(hasil)} baris "
        f"({dibuang} dibuang: kabupaten & STO tidak terpetakan)"
    )
    return hasil


def _query_homepass_wok_lama(bulan_ref: date) -> list[dict]:
    """query_homepass() versi struktur WOK LAMA: wok/branch dari kolom homepass_sales."""
    from dateutil.relativedelta import relativedelta as _rdelta

    REGIONAL = "JATENG%"
    bulan_prev = bulan_ref - _rdelta(months=1)

    tabel_hp_ref  = f"homepass_sales_{bulan_ref.strftime('%Y%m')}"
    tabel_hp_prev = f"homepass_sales_{bulan_prev.strftime('%Y%m')}"
    tabel_iod_ref  = f"indihome_ordering_detail_{bulan_ref.strftime('%Y%m')}"
    tabel_iod_prev = f"indihome_ordering_detail_{bulan_prev.strftime('%Y%m')}"

    sql = f"""
        WITH homepass AS (
            SELECT wok, branch, order_transaction, created_at
            FROM `{tabel_hp_ref}`
            WHERE regional LIKE %s

            UNION ALL

            SELECT wok, branch, order_transaction, created_at
            FROM `{tabel_hp_prev}`
            WHERE regional LIKE %s
        )
        SELECT
            hp.order_transaction                         AS order_id,
            hp.wok,
            hp.branch,
            hp.created_at,
            COALESCE(a.sto_co, b.sto_co)                 AS sto_co,
            COALESCE(a.sf_code, b.sf_code)               AS sf_code,
            COALESCE(a.io_ts, b.io_ts)                   AS io_ts,
            COALESCE(a.re_ts, b.re_ts)                   AS re_ts,
            COALESCE(a.ps_ts, b.ps_ts)                   AS ps_ts,
            COALESCE(a.fallout_reason, b.fallout_reason) AS fallout_reason
        FROM homepass hp
        LEFT JOIN `{tabel_iod_ref}`  a ON hp.order_transaction = a.order_id
        LEFT JOIN `{tabel_iod_prev}` b ON hp.order_transaction = b.order_id
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (REGIONAL, REGIONAL))
        r = cursor.fetchall()
        cursor.close()
        conn.close()
        return r
    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_homepass(wok lama) {tabel_hp_ref}+{tabel_hp_prev}")
        logger.info(f"query_homepass(wok lama) {tabel_hp_ref}+{tabel_hp_prev}: {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_homepass(wok lama) {tabel_hp_ref}+{tabel_hp_prev} gagal: {e}")
        return []


def query_last_update_homepass_sales(bulan_ref: date = None):
    """
    MAX(created_at) tabel homepass_sales_YYYYMM bulan berjalan — dipakai
    /homepass untuk menampilkan tanggal update masing-masing sumber data
    (homepass_sales terpisah dari indihome_ordering_detail).
    """
    bulan_ref = bulan_ref or date.today()
    tabel = f"homepass_sales_{bulan_ref.strftime('%Y%m')}"
    sql = f"SELECT MAX(created_at) AS ts FROM `{tabel}` WHERE regional LIKE %s"
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (DB_REGION_LIKE,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row["ts"] if row else None
    except Error as e:
        logger.warning(f"query_last_update_homepass_sales {tabel} gagal: {e}")
        return None


def query_sf_agency(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query SF (sales force) channel AGENCY dari indihome_ordering_detail.
    Filter: region='JATENG-DIY', order_type='NEW SALES', channel_group='AGENCY',
            produk non-wireless, ps_ts valid & BETWEEN tgl_dari s/d tgl_sampai.
    Otomatis query lintas tabel bulan jika rentang melewati batas bulan.

    NB: mengembalikan baris mentah (tidak di-aggregate di SQL) supaya
    COUNT(DISTINCT sf_code) tetap akurat kalau rentang tanggal melintasi
    2 bulan (aggregate dilakukan di pandas oleh pemanggil, sama seperti
    pola query_djp() + calculator_djp.agg_wok()).

    Returns list of dicts: wok, branch, sf_code, ps_ts
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    ORD_PREFIX = "indihome_ordering_detail_"
    REGION_SF  = "JATENG%"
    def _ord_table(tgl: date) -> str:
        return f"{ORD_PREFIX}{tgl.strftime('%Y%m')}"

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _ord_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (
            max(tgl_dari,   awal),
            min(tgl_sampai, akhir_bulan),
        )
        awal = awal + _rdelta(months=1)

    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                {_GEO_SEL},
                {_WOK_KAB} AS wok,
                {_BRANCH_KAB} AS branch,
                sf_code,
                ps_ts
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND UPPER(TRIM(channel_group)) = 'AGENCY'
              AND (product_commercial_name NOT LIKE '%WIRELESS%'
                   OR product_commercial_name IS NULL)
              AND ps_ts IS NOT NULL
              AND ps_ts != '0000-00-00'
              AND ps_ts BETWEEN %s AND %s
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (REGION_SF, t_dari, t_sampai))
            r = _resolve_geo(cursor.fetchall(), None)
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_sf_agency {tabel}")
            rows_all += rows
            logger.info(f"query_sf_agency {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            logger.warning(f"query_sf_agency {tabel} gagal: {e}")

    return rows_all


def query_iod_io(tgl_dari: date, tgl_sampai: date, wok_lama: bool = False) -> list[dict]:
    """
    Query IO langsung dari indihome_ordering_detail (TIDAK lewat homepass_sales) —
    dipakai untuk Homepass Report sebagai baseline "Total IO" dan "SF Active IO",
    supaya bisa dibandingkan dengan cakupan homepass_sales yang datanya tidak
    selalu lengkap.

    Filter: region='JATENG-DIY', order_type='NEW SALES', channel_group='AGENCY',
            produk non-wireless, io_ts valid & BETWEEN tgl_dari s/d tgl_sampai.
    Otomatis query lintas tabel bulan jika rentang melewati batas bulan.

    Returns list of dicts: order_id, wok, branch, sto_co, sf_code, io_ts
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    ORD_PREFIX = "indihome_ordering_detail_"
    REGION_IOD = "JATENG%"
    def _ord_table(tgl: date) -> str:
        return f"{ORD_PREFIX}{tgl.strftime('%Y%m')}"

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _ord_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (
            max(tgl_dari,   awal),
            min(tgl_sampai, akhir_bulan),
        )
        awal = awal + _rdelta(months=1)

    sel_wil = _sql_wil(wok_lama)[0]
    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                order_id,
                {sel_wil},
                sto_co,
                sf_code,
                io_ts
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND UPPER(TRIM(channel_group)) = 'AGENCY'
              AND (product_commercial_name NOT LIKE '%WIRELESS%'
                   OR product_commercial_name IS NULL)
              AND io_ts IS NOT NULL
              AND io_ts != '0000-00-00'
              AND io_ts BETWEEN %s AND %s
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (REGION_IOD, t_dari, t_sampai))
            r = cursor.fetchall() if wok_lama else _resolve_geo(cursor.fetchall(), None)
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_iod_io {tabel}")
            rows_all += rows
            logger.info(f"query_iod_io {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            logger.warning(f"query_iod_io {tabel} gagal: {e}")

    return rows_all


def query_ps_daily(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query jumlah PS harian per WOK dari indihome_ordering_detail_YYYYMM untuk
    keperluan %DoD (Day over Day).

    PS = order_id dengan ps_ts valid (bukan NULL / '0000-00-00'), pada tanggal
    tertentu (DATE(ps_ts)).
    Filter: region='JATENG-DIY', order_type='NEW SALES',
            package_cat <> 'HWA' (exclude produk hardware/Orbit — BUKAN
            product_commercial_name, kolom itu tidak pernah berisi literal
            'HWA'; filter lama salah kolom, ketemu 04-Aug-2026),
            product_commercial_name TIDAK mengandung 'WIRELESS' (exclude —
            filter TERPISAH, sebagian produk wireless package_cat-nya kosong
            bukan 'HWA', jadi dua-duanya tetap dibutuhkan).
    Asumsi tgl_dari & tgl_sampai berada di bulan yang sama (1 tabel per bulan).

    Returns list of dicts: wok, branch, ps_date, ps_count
    """
    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"
    tabel = f"{TABLE_PREFIX_ORD}{tgl_sampai.strftime('%Y%m')}"

    sql = f"""
        SELECT
            {_GEO_SEL},
            {_WOK_KAB} AS wok,
            {_BRANCH_KAB} AS branch,
            DATE(ps_ts) AS ps_date,
            COUNT(*) AS ps_count
        FROM `{tabel}`
        WHERE region LIKE %s
          AND order_type = 'NEW SALES'
          AND (UPPER(TRIM(package_cat)) <> 'HWA'
               OR package_cat IS NULL)
          AND (product_commercial_name NOT LIKE '%WIRELESS%'
               OR product_commercial_name IS NULL)
          AND ps_ts IS NOT NULL
          AND ps_ts != '0000-00-00'
          AND ps_ts >= %s AND ps_ts < %s
        GROUP BY {_WOK_KAB}, {_BRANCH_KAB}, DATE(ps_ts), {_GEO_GRP}
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (
            REGION_ORDERING, tgl_dari, tgl_sampai + timedelta(days=1)
        ))
        r = _resolve_geo(cursor.fetchall(), ('ps_count',))
        cursor.close()
        conn.close()
        return r
    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_ps_daily {tabel}")
        logger.info(f"query_ps_daily {tabel} ({tgl_dari}~{tgl_sampai}): {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_ps_daily {tabel} gagal: {e}")
        return []


def query_ps_daily_by_product(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query jumlah PS harian per product_commercial_name, digabung seluruh
    WOK/BRANCH (all territory JATENG-DIY), untuk breakdown produk %DoD.
    Filter sama dengan query_ps_daily: order_type='NEW SALES', exclude HWA,
    exclude WIRELESS.

    Returns list of dicts: product_commercial_name, ps_date, ps_count
    """
    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"
    tabel = f"{TABLE_PREFIX_ORD}{tgl_sampai.strftime('%Y%m')}"

    sql = f"""
        SELECT
            product_commercial_name,
            DATE(ps_ts) AS ps_date,
            COUNT(*) AS ps_count
        FROM `{tabel}`
        WHERE region LIKE %s
          AND order_type = 'NEW SALES'
          AND (UPPER(TRIM(package_cat)) <> 'HWA'
               OR package_cat IS NULL)
          AND (product_commercial_name NOT LIKE '%WIRELESS%'
               OR product_commercial_name IS NULL)
          AND ps_ts IS NOT NULL
          AND ps_ts != '0000-00-00'
          AND ps_ts >= %s AND ps_ts < %s
        GROUP BY product_commercial_name, DATE(ps_ts)
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (
            REGION_ORDERING, tgl_dari, tgl_sampai + timedelta(days=1)
        ))
        r = cursor.fetchall()
        cursor.close()
        conn.close()
        return r
    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_ps_daily_by_product {tabel}")
        logger.info(f"query_ps_daily_by_product {tabel} ({tgl_dari}~{tgl_sampai}): {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_ps_daily_by_product {tabel} gagal: {e}")
        return []


def query_ps_by_wok_product(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query jumlah PS (total dalam rentang, bukan harian) per WOK + BRANCH +
    product_commercial_name dari indihome_ordering_detail_YYYYMM — dipakai
    report /closingsql "Sales by Kategori Paket IndiHome" (Tsel One / EZnet /
    IH Reguler, breakdown per WOK/Branch).

    Filter SAMA dengan query_ps_daily (definisi PS): region='JATENG-DIY',
    order_type='NEW SALES', exclude HWA, exclude WIRELESS, ps_ts valid.
    Klasifikasi kategori paket dilakukan di Python
    (reports.kategori_paket.calculator._classify) dari product_commercial_name.
    Asumsi tgl_dari & tgl_sampai berada di bulan yang sama (1 tabel per bulan).

    Returns list of dicts: wok, branch, product_commercial_name, ps_count
    """
    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"
    tabel = f"{TABLE_PREFIX_ORD}{tgl_sampai.strftime('%Y%m')}"

    sql = f"""
        SELECT
            {_GEO_SEL},
            {_WOK_KAB} AS wok,
            {_BRANCH_KAB} AS branch,
            product_commercial_name,
            COUNT(*) AS ps_count
        FROM `{tabel}`
        WHERE region LIKE %s
          AND order_type = 'NEW SALES'
          AND (UPPER(TRIM(package_cat)) <> 'HWA'
               OR package_cat IS NULL)
          AND (product_commercial_name NOT LIKE '%WIRELESS%'
               OR product_commercial_name IS NULL)
          AND ps_ts IS NOT NULL
          AND ps_ts != '0000-00-00'
          AND ps_ts >= %s AND ps_ts < %s
        GROUP BY {_WOK_KAB}, {_BRANCH_KAB}, product_commercial_name, {_GEO_GRP}
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (
            REGION_ORDERING, tgl_dari, tgl_sampai + timedelta(days=1)
        ))
        r = _resolve_geo(cursor.fetchall(), ('ps_count',))
        cursor.close()
        conn.close()
        return r
    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_ps_by_wok_product {tabel}")
        logger.info(f"query_ps_by_wok_product {tabel} ({tgl_dari}~{tgl_sampai}): {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_ps_by_wok_product {tabel} gagal: {e}")
        return []


def query_ps_daily_by_city(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query jumlah PS harian per KABUPATEN (city) + BRANCH dari
    indihome_ordering_detail_YYYYMM — dipakai report %DoD per City (/dod report 3).

    Filter SAMA PERSIS dengan query_ps_daily (definisi PS %DoD):
    region='JATENG-DIY', order_type='NEW SALES',
    package_cat <> 'HWA' (exclude HWA), exclude WIRELESS, ps_ts valid.
    Asumsi tgl_dari & tgl_sampai berada di bulan yang sama (1 tabel per bulan).

    Returns list of dicts: branch, kabupaten, ps_date, ps_count
    """
    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"
    tabel = f"{TABLE_PREFIX_ORD}{tgl_sampai.strftime('%Y%m')}"

    sql = f"""
        SELECT
            {_GEO_SEL},
            {_BRANCH_KAB} AS branch,
            {_KAB_NAMA_OK} AS kabupaten,
            DATE(ps_ts) AS ps_date,
            COUNT(*) AS ps_count
        FROM `{tabel}`
        WHERE region LIKE %s
          AND order_type = 'NEW SALES'
          AND (UPPER(TRIM(package_cat)) <> 'HWA'
               OR package_cat IS NULL)
          AND (product_commercial_name NOT LIKE '%WIRELESS%'
               OR product_commercial_name IS NULL)
          AND ps_ts IS NOT NULL
          AND ps_ts != '0000-00-00'
          AND ps_ts >= %s AND ps_ts < %s
        GROUP BY {_BRANCH_KAB}, {_KAB_NAMA_OK}, DATE(ps_ts), {_GEO_GRP}
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (
            REGION_ORDERING, tgl_dari, tgl_sampai + timedelta(days=1)
        ))
        r = _resolve_geo(cursor.fetchall(), ('ps_count',))
        cursor.close()
        conn.close()
        return r
    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_ps_daily_by_city {tabel}")
        logger.info(f"query_ps_daily_by_city {tabel} ({tgl_dari}~{tgl_sampai}): {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_ps_daily_by_city {tabel} gagal: {e}")
        return []


def query_ps_daily_by_city_product(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query jumlah PS harian per KABUPATEN (city) + PRODUCT + BRANCH dari
    indihome_ordering_detail_YYYYMM — dipakai report DoD FMC City yang
    dibreakdown per city SEKALIGUS per paket dalam 1 tabel.

    Filter SAMA dengan query_ps_daily (definisi PS %DoD): region='JATENG-DIY',
    order_type='NEW SALES', exclude HWA, exclude WIRELESS, ps_ts valid.
    Klasifikasi kategori paket (IH REGULER / EZNET / TSEL ONE) dilakukan di
    Python (calculator_dod._classify_product) dari product_commercial_name.

    Returns list of dicts: branch, kabupaten, product_commercial_name, ps_date, ps_count
    """
    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"
    tabel = f"{TABLE_PREFIX_ORD}{tgl_sampai.strftime('%Y%m')}"

    sql = f"""
        SELECT
            {_GEO_SEL},
            {_BRANCH_KAB} AS branch,
            {_KAB_NAMA_OK} AS kabupaten,
            product_commercial_name,
            DATE(ps_ts) AS ps_date,
            COUNT(*) AS ps_count
        FROM `{tabel}`
        WHERE region LIKE %s
          AND order_type = 'NEW SALES'
          AND (UPPER(TRIM(package_cat)) <> 'HWA'
               OR package_cat IS NULL)
          AND (product_commercial_name NOT LIKE '%WIRELESS%'
               OR product_commercial_name IS NULL)
          AND ps_ts IS NOT NULL
          AND ps_ts != '0000-00-00'
          AND ps_ts >= %s AND ps_ts < %s
        GROUP BY {_BRANCH_KAB}, {_KAB_NAMA_OK}, product_commercial_name, DATE(ps_ts), {_GEO_GRP}
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (
            REGION_ORDERING, tgl_dari, tgl_sampai + timedelta(days=1)
        ))
        r = _resolve_geo(cursor.fetchall(), ('ps_count',))
        cursor.close()
        conn.close()
        return r
    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_ps_daily_by_city_product {tabel}")
        logger.info(f"query_ps_daily_by_city_product {tabel} ({tgl_dari}~{tgl_sampai}): {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_ps_daily_by_city_product {tabel} gagal: {e}")
        return []


def query_ps_daily_promo(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query jumlah PS harian paket PROMO 'One Dynamic' dari
    indihome_ordering_detail_YYYYMM, dipecah per BRANCH, WOK, dan KABUPATEN
    (city) sekaligus — dipakai command /promo.

    PS = order dengan ps_ts valid (bukan NULL / '0000-00-00'), pada tanggal
    tertentu (DATE(ps_ts)).
    Filter: region='JATENG-DIY', order_type='NEW SALES',
            product_commercial_name LIKE '%One Dynamic Promo%' (KHUSUS paket
            PROMO, mis. 'One Dynamic Promo 20Mbps 30GB' — TIDAK termasuk
            'One Dynamic' biasa/non-promo).
    Asumsi tgl_dari & tgl_sampai berada di bulan yang sama (1 tabel per bulan).

    Returns list of dicts: branch, wok, kabupaten, ps_date, ps_count
    """
    REGION_ORDERING  = "JATENG%"
    TABLE_PREFIX_ORD = "indihome_ordering_detail_"
    tabel = f"{TABLE_PREFIX_ORD}{tgl_sampai.strftime('%Y%m')}"

    sql = f"""
        SELECT
            {_GEO_SEL},
            {_BRANCH_KAB} AS branch,
            {_WOK_KAB} AS wok,
            {_KAB_NAMA_OK} AS kabupaten,
            DATE(ps_ts) AS ps_date,
            COUNT(*) AS ps_count
        FROM `{tabel}`
        WHERE region LIKE %s
          AND order_type = 'NEW SALES'
          AND UPPER(product_commercial_name) LIKE '%%ONE DYNAMIC PROMO%%'
          AND ps_ts IS NOT NULL
          AND ps_ts != '0000-00-00'
          AND ps_ts >= %s AND ps_ts < %s
        GROUP BY {_BRANCH_KAB}, {_WOK_KAB}, {_KAB_NAMA_OK}, DATE(ps_ts), {_GEO_GRP}
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (
            REGION_ORDERING, tgl_dari, tgl_sampai + timedelta(days=1)
        ))
        r = _resolve_geo(cursor.fetchall(), ('ps_count',))
        cursor.close()
        conn.close()
        return r
    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_ps_daily_promo {tabel}")
        logger.info(f"query_ps_daily_promo {tabel} ({tgl_dari}~{tgl_sampai}): {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_ps_daily_promo {tabel} gagal: {e}")
        return []


def _check_table_status(chk: dict) -> dict:
    tabel = chk["tabel"]
    sql   = chk["sql"].format(tabel=tabel)
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        if chk["param"]: cursor.execute(sql, chk["param"])
        else:            cursor.execute(sql)
        row = cursor.fetchone()
        cursor.close(); conn.close()
        if chk.get("kind") == "count":
            cnt = row["cnt"] if row else 0
            info = f"📊 Jumlah baris: *{cnt:,}*" if cnt else "📊 Jumlah baris: _tidak ada data_"
            return {"label":chk["label"],"tabel":tabel,"last_update":None,"info":info,"error":None}
        return {"label":chk["label"],"tabel":tabel,"last_update":row["ts"] if row else None,"info":None,"error":None}
    except Error as e:
        return {"label":chk["label"],"tabel":tabel,"last_update":None,"info":None,"error":str(e)}


def query_all_table_status() -> list[dict]:
    """
    Cek status update semua tabel sumber bot untuk bulan ini (query paralel).
    Tidak ada timeout — ditunggu sampai selesai supaya tanggal update terakhir
    yang didapat selalu data asli, bukan status "timeout".
    """
    bulan_ini = date.today().replace(day=1)
    yyyymm    = bulan_ini.strftime("%Y%m")
    checks = [
        {"label":"📡 Hourly Sales (RE/PS)",         "tabel":f"dashboard_hourly_sales_{yyyymm}",    "sql":"SELECT MAX(activity_time) AS ts FROM `{tabel}` WHERE region LIKE %s", "param":(DB_REGION_LIKE,)},
        {"label":"🏠 Homepass Sales (/homepass)",    "tabel":f"homepass_sales_{yyyymm}",           "sql":"SELECT MAX(created_at) AS ts FROM `{tabel}` WHERE regional LIKE %s", "param":(DB_REGION_LIKE,)},
        {"label":"📦 Ordering Detail (IO/RE/PS)",    "tabel":f"indihome_ordering_detail_{yyyymm}",  "sql":"SELECT MAX(last_update) AS ts FROM `{tabel}` WHERE region LIKE 'JATENG%'", "param":()},
        {"label":"🚶 DJP (Door to Door Journey)",    "tabel":f"djp_daily_user_detailed_{yyyymm}",   "sql":"SELECT MAX(tugas_date) AS ts FROM `{tabel}` WHERE regional LIKE 'JATENG%'", "param":()},
        {"label":"💳 C3MR (Clearing Rate)",          "tabel":f"bwmp_c3mr_dd_{yyyymm}",             "sql":"SELECT MAX(updated_time) AS ts FROM `{tabel}` WHERE region LIKE 'JATENG%'", "param":()},
        {"label":"🎯 Segment Detail (C3MR10S)",      "tabel":f"ih_ten_segment_detail_{yyyymm}",     "sql":"SELECT MAX(event_date) AS ts FROM `{tabel}` WHERE region LIKE 'JATENG%'", "param":()},
        # churn_dd_YYYYMM tidak punya kolom sync-timestamp; MAX(deactivation_date)
        # dipakai sebagai proksi tanggal churn terbaru yang tercatat di tabel ini.
        {"label":"⚠️ CAPS (Churn, tgl deaktivasi terbaru)", "tabel":f"churn_dd_{yyyymm}",            "sql":"SELECT MAX(deactivation_date) AS ts FROM `{tabel}` WHERE region LIKE 'JATENG%%'", "param":()},
        # retensi_dd_YYYYMM — sumber /caps report ke-3 (by Channel) & ke-4 (by Reason).
        # Sama seperti churn_dd, tidak ada kolom sync-timestamp -> pakai
        # MAX(deactivation_date) baris DO sebagai proksi cutoff data.
        {"label":"🔁 Retensi (CAPS by Channel/Reason)", "tabel":f"retensi_dd_{yyyymm}",              "sql":"SELECT MAX(deactivation_date) AS ts FROM `{tabel}` WHERE retention_category = 'DO' AND region_sales LIKE '%%JATENG%%'", "param":()},
        # Catatan: CVM Profile (ih_cb_cvm_prfl_mm_YYYYMM) sengaja TIDAK dicek di
        # sini — tabelnya tidak punya kolom tanggal sync, dan cek jumlah barisnya
        # (COUNT atas ~1,3 juta baris) memberatkan /dbstatus tanpa info tanggal
        # yang berguna. Tabelnya sendiri tetap dipakai internal oleh /c3mr10s.
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(checks)) as executor:
        results = list(executor.map(_check_table_status, checks))
    return results


def query_c3mr(bill_period_date, with_city: bool = False) -> list[dict]:
    """
    Query data C3MR dari bwmp_c3mr_dd_YYYYMM.
    Filter: region='JATENG-DIY', bill_period='YYYY-MM-01'.
    Ambil SEMUA baris termasuk yang belum bayar.
    Kolom bb_id disertakan untuk JOIN ke tabel segment.
    with_city=True: tambah kolom `city` (nama kabupaten resmi, wilayah.py) untuk
    report per City. Default False supaya /c3mr10s tidak ikut menanggung RAM-nya.
    """
    C3MR_TABLE_PREFIX = "bwmp_c3mr_dd_"
    C3MR_REGION       = "JATENG%"
    tabel           = f"{C3MR_TABLE_PREFIX}{bill_period_date.strftime('%Y%m')}"
    bill_period_str = bill_period_date.strftime("%Y-%m-01")
    sql = f"""
        SELECT {_WOK_CITY} AS wok, {_BRANCH_CITY} AS branch,{_KAB_NAMA_CITY if with_city else ""}
               account_num, bb_id, los_category,
               bill_amount, clearing_amount, paid_flag, payment_date
        FROM `{tabel}`
        WHERE region LIKE %s AND bill_period = %s
          AND {_OK_CITY}
    """

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (C3MR_REGION, bill_period_str))
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        logger.info(f"query_c3mr {tabel} bill_period={bill_period_str}: {len(rows)} baris")
        return rows

    try:
        # Retry terus-menerus kalau DB/VPN putus di tengah jalan — query berat
        # ini TIDAK dibatalkan/timeout, cuma diulang sampai koneksi pulih.
        return _jalankan_dengan_retry(_jalankan, f"query_c3mr {tabel}")
    except Error as e:
        # Error SQL asli (mis. tabel bulan itu belum ada) — bukan soal koneksi,
        # tidak ada gunanya diulang, kembalikan kosong seperti semula.
        logger.warning(f"query_c3mr {tabel} gagal: {e}")
        return []


def query_payment(tgl: date) -> list[dict]:
    """
    Query raw data payment dari bwmp_c3mr_dd_YYYYMM untuk /payment command.
    Logic pemilihan tabel sama dengan C3MR:
      - Tgl 1-5: pakai tabel bulan M-1 (masih closing period bulan sebelumnya)
      - Tgl 6+:  pakai tabel bulan M (bulan berjalan)
    Filter: region LIKE 'JATENG%', payment_date = tgl yang diminta.
    Return: list of dict dengan kolom bb_id, account_num, payment_date,
            clearing_amount, payment_amount.
    """
    C3MR_TABLE_PREFIX = "bwmp_c3mr_dd_"
    C3MR_REGION       = "JATENG%"

    # Tentukan bill period (= bulan tabel) berdasarkan tanggal
    if tgl.day <= 5:
        bp = (tgl - relativedelta(months=1)).replace(day=1)
    else:
        bp = tgl.replace(day=1)

    tabel            = f"{C3MR_TABLE_PREFIX}{bp.strftime('%Y%m')}"
    payment_date_str = tgl.strftime("%Y-%m-%d")

    sql = f"""
        SELECT a.bb_id,
               a.account_num,
               a.payment_date,
               a.clearing_amount,
               a.payment_amount
        FROM `{tabel}` a
        WHERE a.region LIKE %s
          AND a.payment_date = %s
    """

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (C3MR_REGION, payment_date_str))
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        logger.info(
            f"query_payment {tabel} payment_date={payment_date_str}: "
            f"{len(rows)} baris"
        )
        return rows

    try:
        return _jalankan_dengan_retry(_jalankan, f"query_payment {tabel}")
    except Error as e:
        logger.warning(f"query_payment {tabel} gagal: {e}")
        return []


def query_c3mr_paid_status(bb_ids: list, bill_period_date) -> list[dict]:
    """
    Query status pembayaran (paid_flag, payment_date, bill_amount, wok) dari
    bwmp_c3mr_dd_YYYYMM untuk daftar bb_id tertentu — dipakai /klaim untuk
    refresh Paid Flag LIVE dari DB tiap report di-generate, menggantikan
    VLOOKUP manual by Nomor Internet.
    Filter: region='JATENG-DIY', bill_period='YYYY-MM-01', bb_id IN (...).
    Di-chunk per 1000 bb_id (menghindari query IN() yang kepanjangan).
    """
    C3MR_TABLE_PREFIX = "bwmp_c3mr_dd_"
    C3MR_REGION       = "JATENG%"
    tabel           = f"{C3MR_TABLE_PREFIX}{bill_period_date.strftime('%Y%m')}"
    bill_period_str = bill_period_date.strftime("%Y-%m-01")

    bb_ids = [b for b in bb_ids if b is not None]
    if not bb_ids:
        return []

    CHUNK = 1000

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        hasil = []
        for i in range(0, len(bb_ids), CHUNK):
            chunk = bb_ids[i:i + CHUNK]
            placeholders = ",".join(["%s"] * len(chunk))
            sql = f"""
                SELECT bb_id, {_WOK_CITY} AS wok, bill_amount, paid_flag, payment_date
                FROM `{tabel}`
                WHERE region LIKE %s AND bill_period = %s AND bb_id IN ({placeholders})
            """
            cursor.execute(sql, (C3MR_REGION, bill_period_str, *chunk))
            hasil.extend(cursor.fetchall())
        cursor.close(); conn.close()
        return hasil

    try:
        # Kalau putus di tengah chunk ke-N, seluruh proses diulang dari chunk 1
        # (bukan cuma chunk yang gagal) — lebih simpel & aman daripada state
        # partial yang sulit dilanjut persis di titik putusnya.
        rows_all = _jalankan_dengan_retry(_jalankan, f"query_c3mr_paid_status {tabel}")
        logger.info(f"query_c3mr_paid_status {tabel}: {len(rows_all)}/{len(bb_ids)} bb_id ketemu")
        return rows_all
    except Error as e:
        logger.warning(f"query_c3mr_paid_status {tabel} gagal: {e}")
        return []


def query_c3mr_last_update(bill_period_date):
    """
    Cek MAX(updated_time) dari bwmp_c3mr_dd_YYYYMM (region='JATENG-DIY') —
    dipakai /klaim untuk menampilkan kapan sumber data Paid Flag terakhir
    di-refresh oleh proses batch di sisi tabel (bukan oleh bot ini), supaya
    jelas kalau angka tidak berubah karena tabelnya sendiri belum di-refresh
    hari itu, bukan karena bot gagal query live.
    Return datetime atau None kalau gagal/kosong.
    """
    C3MR_TABLE_PREFIX = "bwmp_c3mr_dd_"
    C3MR_REGION       = "JATENG%"
    tabel = f"{C3MR_TABLE_PREFIX}{bill_period_date.strftime('%Y%m')}"
    sql = f"SELECT MAX(updated_time) AS ts FROM `{tabel}` WHERE region LIKE %s"
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (C3MR_REGION,))
        row = cursor.fetchone()
        cursor.close(); conn.close()
        return row["ts"] if row else None
    except Error as e:
        logger.warning(f"query_c3mr_last_update {tabel} gagal: {e}")
        return None


def query_c3mr_segment(bill_period_date) -> dict:
    """
    Mapping bb_id → customer_segment dari tabel CVM profile bulanan
    ih_cb_cvm_prfl_mm_YYYYMM, region JATENG. Return dict {bb_id: segment}.

    PENTING — bulan tabel CVM = M-1 dari bill period C3MR-nya.
    Profil CVM disusun dari perilaku bulan sebelumnya, jadi C3MR bill period
    202607 dipasangkan dengan ih_cb_cvm_prfl_mm_202606.

    (Sebelumnya memakai ih_ten_segment_detail_YYYYMM bulan yang sama, tapi
    kolom customer_segment di tabel itu ter-load rusak — isinya '0'/'1'/'' —
    sehingga seluruh laporan /c3mr10s tampil nol.)

    Dua hal yang sengaja dilakukan demi kecepatan (tabelnya 1,3 juta baris):
    1. TANPA DISTINCT — bb_id adalah PRIMARY KEY, mustahil duplikat. DISTINCT
       cuma memaksa MySQL menyortir 1,3 juta baris untuk membuang nol duplikat
       (terukur 60,7 detik dengan DISTINCT vs 28,1 detik tanpa).
    2. Cursor biasa (tuple), BUKAN dictionary=True — membuat 1,3 juta dict
       menambah ±28 detik sendiri. Dict hasil akhir dibangun langsung di sini.
    """
    SEG_TABLE_PREFIX = "ih_cb_cvm_prfl_mm_"
    SEG_REGION       = "JATENG%"
    bulan_cvm = bill_period_date - relativedelta(months=1)
    tabel = tabel_atau_bulan_lalu(f"{SEG_TABLE_PREFIX}{bulan_cvm.strftime('%Y%m')}")   # CVM belum ada -> month-1
    sql = f"SELECT bb_id, customer_segment FROM `{tabel}` WHERE region LIKE %s"

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, (SEG_REGION,))
        hasil = {
            str(bb).strip(): (seg.strip() if isinstance(seg, str) else seg)
            for bb, seg in cursor.fetchall()
        }
        cursor.close(); conn.close()
        return hasil

    try:
        hasil = _jalankan_dengan_retry(_jalankan, f"query_c3mr_segment {tabel}")
        logger.info(f"query_c3mr_segment {tabel}: {len(hasil)} bb_id")
        return hasil
    except Error as e:
        logger.warning(f"query_c3mr_segment {tabel} gagal: {e}")
        return {}


def query_c3mrnew(bp_date, channel_group: str = None) -> list[dict]:
    """
    Query C3MR per BILL-N (new sales cohort).

    Logic:
    - bwmp_c3mr_dd_YYYYMM = tabel C3MR aktif (bp_date)
    - BILL-1 = ps_ts di bulan M-1, BILL-2 = M-2, ..., BILL-6 = M-6
    - JOIN: indihome_ordering_detail_YYYYMM.bb_id = bwmp.bb_id
    - Ambil billing terbaru per bb_id dari bwmp (ROW_NUMBER by payment_date DESC)
    - Filter ordering: region='JATENG-DIY', order_type='NEW SALES'
    - channel_group: None = semua channel, 'AGENCY' = agency only

    Returns list of dicts:
        bb_id, ps_ts, channel_group, sf_code, sf_company_name,
        product_commercial_name, wok, branch, los_category, bill_n,
        bill_amount, clearing_amount, paid_flag, payment_date
    """
    BWMP_PREFIX = "bwmp_c3mr_dd_"
    ORD_PREFIX  = "indihome_ordering_detail_"
    C3MR_REGION = "JATENG%"
    bwmp_tabel = f"{BWMP_PREFIX}{bp_date.strftime('%Y%m')}"

    from dateutil.relativedelta import relativedelta as _rdelta

    # Filter channel opsional
    channel_filter = "AND channel_group = %s" if channel_group else ""

    union_parts = []
    params      = []
    for n in range(1, 7):
        ord_date  = (bp_date - _rdelta(months=n))
        ord_tabel = f"{ORD_PREFIX}{ord_date.strftime('%Y%m')}"
        ps_dari   = ord_date.replace(day=1)
        ps_sampai = (ps_dari + _rdelta(months=1))
        union_parts.append(f"""
            SELECT bb_id, ps_ts, channel_group, sf_code, sf_company_name,
                   product_commercial_name, {n} AS bill_n
            FROM `{ord_tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND ps_ts >= %s AND ps_ts < %s
              AND ps_ts IS NOT NULL
              AND ps_ts != '0000-00-00 00:00:00'
              {channel_filter}
        """)
        params += [C3MR_REGION, ps_dari, ps_sampai]
        if channel_group:
            params.append(channel_group)

    union_sql = " UNION ALL ".join(union_parts)

    sql = f"""
        SELECT
            x.bb_id,
            x.ps_ts,
            x.channel_group,
            x.sf_code,
            x.sf_company_name,
            x.product_commercial_name,
            b.wok,
            b.branch,
            b.los_category,
            x.bill_n,
            b.bill_amount,
            b.clearing_amount,
            b.paid_flag,
            b.payment_date
        FROM (
            SELECT bb_id, ps_ts, channel_group, sf_code, sf_company_name,
                   product_commercial_name, MIN(bill_n) AS bill_n
            FROM ({union_sql}) u
            GROUP BY bb_id, ps_ts, channel_group, sf_code, sf_company_name,
                     product_commercial_name
        ) x
        LEFT JOIN (
            SELECT bb_id, {_WOK_CITY} AS wok, {_BRANCH_CITY} AS branch, los_category,
                   bill_amount, clearing_amount, paid_flag, payment_date
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY bb_id
                           ORDER BY payment_date DESC
                       ) AS rn_b
                FROM `{bwmp_tabel}`
                WHERE region LIKE %s
                  AND {_OK_CITY}
            ) t
            WHERE rn_b = 1
        ) b ON x.bb_id = b.bb_id
    """
    params.append(C3MR_REGION)

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        r = cursor.fetchall()
        cursor.close(); conn.close()
        return r

    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_c3mrnew {bwmp_tabel}")
        logger.info(f"query_c3mrnew {bwmp_tabel}: {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_c3mrnew {bwmp_tabel} gagal: {e}")
        return []


def tabel_atau_bulan_lalu(tabel: str) -> str:
    """
    Fallback tabel bulanan (nama berakhiran YYYYMM, mis. churn_dd_202611, ih_cb_cvm_prfl_mm_202610):
    bila tabel itu belum ada di DB (awal bulan / tabel baru belum dibuat), pakai tabel month-1.
    Bila tabel month-1 juga tidak ada, atau pengecekan gagal (mis. mode CSV), kembalikan nama asli.
    """
    import re
    m = re.fullmatch(r"(.*?)(\d{4})(\d{2})", tabel or "")
    if not m or not 1 <= int(m.group(3)) <= 12:
        return tabel
    y, mo = int(m.group(2)), int(m.group(3))
    y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
    lalu = f"{m.group(1)}{y:04d}{mo:02d}"

    def _ada(t):
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() AND table_name = %s", (t,))
            return bool(cur.fetchone()[0])
        finally:
            conn.close()

    try:
        if _ada(tabel) or not _ada(lalu):
            return tabel
    except Exception as e:
        logger.debug(f"cek tabel {tabel} gagal ({e}) -> pakai nama asli")
        return tabel
    logger.warning(f"Tabel {tabel} belum ada -> fallback ke tabel month-1 {lalu}")
    return lalu


def query_caps(tabel: str, region_prefix: str) -> list[dict]:
    """
    Query data CAPS (Churn) dari tabel churn_dd_YYYYMM (nama tabel LITERAL, sudah
    di-generate oleh calculator_caps.py, contoh: churn_dd_202607).

    Penamaan region TIDAK konsisten antar bulan di sumber data:
      - churn_dd_202606: region = 'JATENG-DIY'
      - churn_dd_202607: region = 'JATENG'
    Jadi filter pakai LIKE 'JATENG%%' supaya nangkep dua-duanya (aman terhadap
    region lain seperti JABAR/JATIM/JAKARTA BANTEN karena awalannya beda).
    Ambil bb_id, branch, wok, los_category, deactivation_date.
    Tabel belum ada -> fallback tabel month-1 (tabel_atau_bulan_lalu).
    """
    tabel = tabel_atau_bulan_lalu(tabel)
    sql = f"""
        SELECT bb_id, {_BRANCH_KAB} AS branch, {_WOK_KAB} AS wok, region, los_category, deactivation_date
        FROM `{tabel}`
        WHERE region LIKE %s
          AND {_OK_KAB}
    """
    like_pattern = f"{region_prefix}%"

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (like_pattern,))
        r = cursor.fetchall()
        cursor.close(); conn.close()
        return r

    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_caps {tabel}")
        logger.info(f"query_caps {tabel} region LIKE '{like_pattern}': {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_caps {tabel} gagal: {e}")
        return []


def query_caps_segment(tabel_churn: str, tabel_segment: str, region_prefix: str) -> list[dict]:
    """
    Query CAPS (Churn) + Customer Segment: churn_dd_YYYYMM (bulan N) LEFT JOIN
    ih_cb_cvm_prfl_mm_YYYYMM (bulan N-1 — snapshot profil pelanggan SEBELUM
    churn, krn bulan N pelanggan yg sudah churn tidak akan punya profil lagi)
    ON bb_id. Dipakai calculator_caps_segment.py untuk report kedua /caps
    (CAPS by Segmen Pelanggan).
    Region LIKE prefix, sama alasan seperti query_caps() (label region
    beda antar bulan: JATENG-DIY vs JATENG).
    Tabel churn / CVM belum ada -> fallback tabel month-1 (tabel_atau_bulan_lalu).
    """
    tabel_churn = tabel_atau_bulan_lalu(tabel_churn)
    tabel_segment = tabel_atau_bulan_lalu(tabel_segment)
    _WOK_KAB_A    = wilayah.sql_wok("a.kabupaten")
    _BRANCH_KAB_A = wilayah.sql_branch("a.kabupaten")
    _OK_KAB_A     = wilayah.sql_terpetakan("a.kabupaten")
    sql = f"""
        SELECT
            a.bb_id,
            a.deactivation_date,
            {_BRANCH_KAB_A} AS branch,
            {_WOK_KAB_A} AS wok,
            a.los_category,
            b.customer_segment
        FROM `{tabel_churn}` a
        LEFT JOIN `{tabel_segment}` b
            ON a.bb_id = b.bb_id
        WHERE a.region LIKE %s
          AND {_OK_KAB_A}
    """
    like_pattern = f"{region_prefix}%"

    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (like_pattern,))
        r = cursor.fetchall()
        cursor.close(); conn.close()
        return r

    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_caps_segment {tabel_churn}+{tabel_segment}")
        logger.info(f"query_caps_segment {tabel_churn}+{tabel_segment} region LIKE '{like_pattern}': {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_caps_segment {tabel_churn}+{tabel_segment} gagal: {e}")
        return []


def query_retensi_do(tabel: str) -> list[dict]:
    """
    Query order CAPS (DO) dari retensi_dd_YYYYMM (nama tabel LITERAL, mis.
    retensi_dd_202607). Dipakai calculator_caps_channel.py (report /caps ke-3)
    dan calculator_caps_reason.py (report /caps ke-4).

    Filter (sesuai definisi report):
      - retention_category = 'DO'  (hanya order yang benar-benar CAPS/cabut,
        bukan 'MO RETENSI' yang berhasil diretensi)
      - region_sales LIKE '%JATENG%' — pola %..% (bukan prefix seperti
        query_caps()) karena penamaan region di retensi_dd bisa 'JATENG'
        maupun 'JATENG-DIY' antar bulan; region lain (JATIM, JABAR, dst)
        tidak mengandung substring 'JATENG' jadi tetap aman.
      - Cutoff MtD di-filter di sisi kalkulator pakai deactivation_date.

    Kolom branch di tabel ini bernama branch_sales (bukan branch seperti
    churn_dd) — di-alias jadi `branch` supaya seragam dengan kalkulator lain.
    Tabel belum ada -> fallback tabel month-1 (tabel_atau_bulan_lalu).
    """
    tabel = tabel_atau_bulan_lalu(tabel)
    sql = f"""
        SELECT bb_id,
               {_BRANCH_KAB} AS branch,
               {_WOK_KAB} AS wok,
               region_sales AS region,
               unit_type,
               reason,
               deactivation_date
        FROM `{tabel}`
        WHERE retention_category = 'DO'
          AND region_sales LIKE %s
          AND {_OK_KAB}
    """
    def _jalankan():
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, ("%JATENG%",))
        r = cursor.fetchall()
        cursor.close(); conn.close()
        return r

    try:
        rows = _jalankan_dengan_retry(_jalankan, f"query_retensi_do {tabel}")
        logger.info(f"query_retensi_do {tabel}: {len(rows)} baris")
        return rows
    except Error as e:
        logger.warning(f"query_retensi_do {tabel} gagal: {e}")
        return []


def query_djp(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Query data DJP dari djp_daily_user_detailed_YYYYMM.
    Filter: regional = 'JATENG', tugas_date BETWEEN tgl_dari AND tgl_sampai.
    Otomatis query lintas tabel bulan jika rentang melewati batas bulan.

    Returns list of dicts: area_name, regional, branch, wok, tugas_date,
                           user_code, odp_name
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    DJP_TABLE_PREFIX = "djp_daily_user_detailed_"
    DJP_REGION       = "JATENG%"
    def _djp_table(tgl: date) -> str:
        return f"{DJP_TABLE_PREFIX}{tgl.strftime('%Y%m')}"

    tabels = {}
    awal = tgl_dari.replace(day=1)
    while awal <= tgl_sampai:
        nama = _djp_table(awal)
        akhir_bulan = (awal + _rdelta(months=1)) - timedelta(days=1)
        tabels[nama] = (
            max(tgl_dari,   awal),
            min(tgl_sampai, akhir_bulan),
        )
        awal = awal + _rdelta(months=1)

    rows_all = []
    for tabel, (t_dari, t_sampai) in tabels.items():
        sql = f"""
            SELECT
                area_name,
                regional,
                branch,
                wok,
                tugas_date,
                user_code,
                odp_name
            FROM `{tabel}`
            WHERE regional LIKE %s
              AND tugas_date BETWEEN %s AND %s
        """
        def _jalankan():
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, (DJP_REGION, t_dari, t_sampai))
            r = cursor.fetchall()
            cursor.close()
            conn.close()
            return r
        try:
            rows = _jalankan_dengan_retry(_jalankan, f"query_djp {tabel}")
            rows_all += rows
            logger.info(f"query_djp {tabel} ({t_dari}~{t_sampai}): {len(rows)} baris")
        except Error as e:
            logger.warning(f"query_djp {tabel} gagal: {e}")

    return rows_all
