"""
Lapisan data untuk report /agresif native (tanpa Excel). Query langsung ke
`indihome_ordering_detail_YYYYMM` (75 kolom — semua kolom tabel MINUS
order_ts, lihat db.query_ordering_detail_full), dedup, geocode kab2/kec2,
derive kolom turunan statis — setara isi sheet RAW + kolom formula
(kab2/kec2/MIDLOW/bulan/tgl) di master Excel, TAPI kolom formula live (IS
NEW AGRESIF/MIDLOW/CEK/kec3/Kab_kec/is kec agresif/is new fmc) sengaja
TIDAK dihitung di sini — itu tetap ditulis sebagai formula Excel oleh
agresif_report.py supaya logikanya tetap satu sumber (sheet 'data kec &
city'), bukan diduplikasi ke Python.

RAW_COLUMNS = urutan 94 kolom PERSIS seperti header Table1 di sheet RAW
master ("TEMPLATE AGRESIVE TAHAP 1 JULI.xlsx") — WAJIB sinkron kalau
struktur tabel DB atau template berubah. order_ts tetap ada di posisinya
(kolom kosong/None, tidak ditarik dari DB) supaya urutan/jumlah kolom RAW
export tidak berubah; begitu juga "bulan order"/"tgl order" turunannya
(ikut kosong — memang tidak dipakai perhitungan manapun).

Filter (sama pola dgn db.py query_ordering_detail/query_re_ps_raw):
  region LIKE 'JATENG%', order_type='NEW SALES', order_id LIKE 'AO%' (MO
  dibuang di level query), exclude produk wireless, DAN io_ts/re_ts/ps_ts
  jatuh di window 2 bulan (bulan_prev s/d akhir bulan_now) — lihat
  db.query_ordering_detail_full & build_raw().
Dedup per order_id, ambil baris dgn last_update TERBARU (satu order bisa muncul
berkali-kali di raw ordering detail seiring sync berkala).
"""
import os
from datetime import datetime, date, time

import pandas as pd
from dateutil.relativedelta import relativedelta

import db
from agresif_geocode import Geocoder, parse_coord

_GEOCODER = None


def _get_geocoder() -> Geocoder:
    """Lazy-load geocoder sekali (boundaries.js besar, ~11MB zip).

    Prioritas zip `tika/GeocodingJatengDIY_1.zip`, tapi file itu SUDAH 2x
    hilang dari folder ini di sesi yang sama (kemungkinan ke-cleanup oleh
    proses lain di luar kendali bot — bukan dihapus kode ini) sehingga
    build_raw() gagal total tiap kali itu terjadi. Fallback ke folder hasil
    extract `tika/GeocodingJatengDIY/boundaries.js` (SUDAH ada di disk,
    tidak pernah hilang) supaya /agresif tidak gagal cuma gara2 zip-nya
    raib lagi.
    """
    global _GEOCODER
    if _GEOCODER is None:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        zip_path = os.path.join(base, "tika", "GeocodingJatengDIY_1.zip")
        js_path = os.path.join(base, "tika", "GeocodingJatengDIY", "boundaries.js")
        if os.path.exists(zip_path):
            _GEOCODER = Geocoder.from_geocoding_zip(zip_path)
        elif os.path.exists(js_path):
            _GEOCODER = Geocoder.from_boundaries_js(js_path)
        else:
            raise FileNotFoundError(
                f"Geocoder data tidak ditemukan di zip ({zip_path}) "
                f"maupun folder extract ({js_path})."
            )
    return _GEOCODER


# 76 kolom mentah — urutan PERSIS SHOW COLUMNS indihome_ordering_detail (cek
# ulang kalau skema tabel berubah).
DB_COLUMNS = [
    "bb_id", "order_id", "order_initiator_id", "channel_transaction_id",
    "homepass_id", "hp_longitude", "hp_latitude", "hp_odp_name", "order_status",
    "sto_co", "cluster", "branch", "wok", "region", "area", "desa", "kecamatan",
    "kabupaten", "provinsi", "longitude", "latitude", "order_ts", "io_ts",
    "re_ts", "pi_ts", "ps_ts", "ro_ts", "fo_ts", "completed_ts",
    "existing_ont_type", "existing_ont_citem", "pdd_enabled", "pdd_commitment",
    "product_commercial_name", "price_total", "price_package", "fee_psb",
    "payment_method", "package_cat", "citem_product", "speed_product",
    "package_type", "order_type", "order_type_id", "process_state",
    "provi_group", "provi_subgroup", "channel_name", "channel_group",
    "unit_type", "unit_name", "product_id_co", "tgl_manja", "appointment_id",
    "appointment_start", "appointment_end", "c_wonum", "c_amcrew",
    "c_chief_code", "c_chief_name", "sf_code", "sf_name", "sf_company_name",
    "odp_name", "fallout_source", "fallout_category", "fallout_subcategory",
    "fallout_reason", "cancel_category", "cancel_reason", "dmo_category",
    "dmo_lp_name", "subchannel", "referral_code", "last_update", "event_date",
]

# Kolom statis yang di-hitung ulang tiap refresh (bukan formula Excel).
STATIC_COLUMNS = ["rn", "bulan order", "tgl order", "bulan re", "tgl re",
                   "bulan ps", "tgl ps", "kab2", "kec2"]

# Kolom formula LIVE di Excel — ditulis kosong di sini, diisi formula oleh
# agresif_report.py setelah tabel di-resize. Urutan HARUS sama dengan posisi
# aslinya di antara STATIC_COLUMNS supaya RAW_COLUMNS cocok persis header Table1.
FORMULA_COLUMNS = ["IS NEW AGRESIF", "MIDLOW", "CEK", "kec3", "Kab_kec",
                    "is kec agresif", "is new fmc"]

# Kolom yang memang tidak dipakai formula manapun — dikosongkan saja.
UNUSED_COLUMNS = ["kab3", "week"]

# Urutan 94 kolom PERSIS header Table1 (hasil inspeksi manual master).
RAW_COLUMNS = DB_COLUMNS + [
    "rn", "bulan order", "tgl order", "bulan re", "tgl re", "bulan ps", "tgl ps",
    "IS NEW AGRESIF", "MIDLOW", "kab2", "kec2", "CEK", "kab3", "kec3", "Kab_kec",
    "is kec agresif", "is new fmc", "week",
]


def _pull_month_dedup(d: date, window_start: date, window_end_exclusive: date) -> pd.DataFrame:
    """
    Tarik satu bulan tabel ordering_detail (75 kolom MINUS order_ts,
    order_id LIKE 'AO%' DAN io_ts/re_ts/ps_ts jatuh di window
    [window_start, window_end_exclusive) — lihat
    db.query_ordering_detail_full, retry-aware via
    db._jalankan_dengan_retry), lalu LANGSUNG dedup per order_id (ambil
    last_update TERBARU) SEBELUM digabung dengan bulan lain.

    Sengaja dipisah per-bulan (bukan kumpulkan semua row 2 bulan dulu baru
    dedup sekali di akhir) — satu order bisa ke-sync berkali-kali di raw
    ordering_detail, jadi row mentahnya bisa berkali-lipat dari jumlah order
    asli. Dedup lebih awal = DataFrame gabungan jauh lebih kecil, jaga
    puncak pemakaian memori (server bot RAM-nya pas-pasan).
    """
    rows = db.query_ordering_detail_full(d, window_start, window_end_exclusive)
    if not rows:
        return pd.DataFrame(columns=DB_COLUMNS)

    df = pd.DataFrame(rows)
    rows.clear()  # lepas list mentah secepatnya, sebelum lanjut proses df
    for col in DB_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df.sort_values(["last_update", "bb_id"], na_position="first")
    df = df.drop_duplicates(subset="order_id", keep="last")
    return df.reset_index(drop=True)


def build_raw(cutoff: date) -> pd.DataFrame:
    """
    Bangun DataFrame RAW-equivalent (94 kolom, urutan = RAW_COLUMNS) utk bulan
    berjalan (cutoff.month) DAN bulan sebelumnya (basis MTD-1) — dua bulan itu
    cukup, formula MTD-1 hanya membandingkan ke bulan tepat sebelumnya, bukan
    histori lebih jauh. Kolom FORMULA_COLUMNS dikosongkan (None) — diisi
    formula Excel oleh agresif_report.py setelah tabel di-resize.

    bulan/tgl (order/re/ps) = MONTH()/DAY() NUMERIK (bukan string "YYYY-MM") —
    dikonfirmasi dari isi live master: 2 bulan RAW selalu berurutan jadi angka
    bulan (1-12) sudah cukup unik sebagai pembeda MTD vs MTD-1, tak perlu tahun.
    NaN kalau timestamp-nya kosong/'0000-00-00' (setara kosong di Excel lama).
    """
    bulan_now = cutoff.replace(day=1)
    bulan_prev = bulan_now - relativedelta(months=1)

    # Window io_ts/re_ts/ps_ts dikirim SAMA ke kedua tabel bulanan (bulan_now
    # & bulan_prev) supaya order yang IO/RE/PS-nya menyeberang bulan tetap
    # ketarik dari tabel manapun ia berada — window_start = awal bulan_prev,
    # window_end EKSKLUSIF = awal bulan setelah bulan_now.
    window_start = bulan_prev
    window_end_exclusive = bulan_now + relativedelta(months=1)

    df_now = _pull_month_dedup(bulan_now, window_start, window_end_exclusive)
    if bulan_prev.strftime("%Y%m") != bulan_now.strftime("%Y%m"):
        df_prev = _pull_month_dedup(bulan_prev, window_start, window_end_exclusive)
        df = pd.concat([df_prev, df_now], ignore_index=True)
        del df_prev, df_now
    else:
        df = df_now

    if df.empty:
        return pd.DataFrame(columns=RAW_COLUMNS)

    # SENGAJA TIDAK filter cutoff pakai last_update di sini (dulu ada, dibuang
    # 02-Aug-2026). last_update = kapan baris ini TERAKHIR DI-SYNC oleh ETL,
    # BUKAN tanggal transaksi bisnis (order/re/ps) — pada praktiknya selalu
    # lag 1+ hari dari tanggal transaksi asli (row transaksi tanggal 1 Agustus
    # baru ke-sync tanggal 2 Agustus). Kalau difilter <= cutoff di sini, cutoff
    # "hari ini/kemarin" akan membuang SEMUA baris hari itu (last_update-nya
    # pasti > cutoff karena belum sempat ke-sync ulang) — kebuktian: 16.088 PS
    # tanggal 1 Agustus 2026 ada di DB, tapi 0 yang lolos filter ini dgn
    # cutoff=01-08-2026. Filter tanggal yang BENAR sudah dilakukan
    # calculator_agresif.py berdasar tgl_ps/tgl_re/bulan_ps/bulan_re (tanggal
    # bisnis asli), jadi filter di sini murni redundan sekaligus merusak.

    # Dedup lintas-bulan (jaga-jaga kalau 1 order_id sempat kepotong di 2
    # tabel bulanan) — DataFrame di titik ini sudah jauh lebih kecil daripada
    # gabungan mentah 2 bulan, karena tiap bulan sudah dedup lebih dulu.
    df = df.sort_values(["last_update", "bb_id"], na_position="first")
    df = df.drop_duplicates(subset="order_id", keep="last").reset_index(drop=True)

    # Geocode kab2/kec2 dari longitude/latitude (validated 100% match, lihat
    # agresif_geocode.py).
    gc = _get_geocoder()
    cache: dict[tuple, tuple] = {}

    def geocode_row(lon, lat):
        x, y = parse_coord(lon), parse_coord(lat)
        key = (x, y)
        if key not in cache:
            k, c, _d, _st = gc.kab_kec(x, y)
            cache[key] = (k.strip().upper() if k else "", c.strip().upper() if c else "")
        return cache[key]

    kab2_list, kec2_list = [], []
    for lon, lat in zip(df["longitude"], df["latitude"]):
        k, c = geocode_row(lon, lat)
        kab2_list.append(k)
        kec2_list.append(c)
    df["kab2"] = kab2_list
    df["kec2"] = kec2_list

    def bulan_tgl(ts_col):
        ts = pd.to_datetime(df[ts_col], errors="coerce")
        bulan = ts.dt.month
        tgl = ts.dt.day
        return bulan, tgl

    df["bulan order"], df["tgl order"] = bulan_tgl("order_ts")
    df["bulan re"], df["tgl re"] = bulan_tgl("re_ts")
    df["bulan ps"], df["tgl ps"] = bulan_tgl("ps_ts")
    df["rn"] = 1  # helper dedup lama, tidak dipakai formula manapun

    for col in FORMULA_COLUMNS + UNUSED_COLUMNS:
        df[col] = None

    return df[RAW_COLUMNS].reset_index(drop=True)
