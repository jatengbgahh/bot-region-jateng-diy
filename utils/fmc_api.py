"""
fmc_api.py — Sumber data backup untuk /liveupdateutoip dan /closingutoip.

Beda dari db.py (query MySQL dashboard_hourly_sales) & calculator_daily.py /
calculator_channel.py (query MySQL indihome_ordering_detail), modul ini ambil
data lewat HTTP API dashboard FMC Telkomsel (halaman "Detail Order KPRO -
Funneling"), order-level, lalu diagregasi sendiri di sini supaya bentuk
outputnya SAMA PERSIS dengan fungsi query DB yang digantikan:
  - query_re_ps()               ~ db.query_re_ps()                  (/liveupdateutoip)
  - query_ordering_detail_fmc() ~ db.query_ordering_detail()        (channel report)
  - query_daily_performance_fmc() ~ calculator_daily._query_dashboard() (Daily Performance WOK)
  - fetch_orders_raw_for_export() ~ calculator_daily.export_raw_csv() (raw CSV, kolom native FMC)
Dengan bentuk row yang sama (atau native raw untuk export), dipakai fungsi
hitung yang sama persis sehingga laporan /closingutoip mirip /closingsql,
cuma sumber datanya beda.

CATATAN / ASUMSI yang perlu divalidasi manual sebelum dipakai sebagai
fallback resmi:
- x-token & Cookie session-based dan akan expire. Lihat komentar
  FMC_COOKIE/FMC_XTOKEN di config.py cara refresh-nya.
- Endpoint kpro-detail-funneling di-assume bisa difilter per-hari lewat
  field "dateRange" (epoch start=00:00:00, end=23:59:59 hari itu). Kalau
  ternyata endpoint ini cuma balikin snapshot "sekarang" (bukan tanggal
  bebas), data untuk "kemarin" (re_d1_fd / re_d1_hourly) tidak akan akurat.
- Halaman "Funneling" kemungkinan cuma nampilin order yang masih aktif di
  funnel. Kalau order yang sudah closed/PS lama hilang dari listing ini,
  angka RE/PS bisa under-count dibanding sumber DB. Bandingkan hasil
  /liveupdateutoip dengan /liveupdate pada jam yang sama sebelum dipakai
  serius sebagai backup.
- render_tabel/render_simple (mode hourly) butuh D-1 dan D-7, jadi fetch
  dibatasi ke 3 hari itu saja (hari ini, kemarin, 7 hari lalu) supaya cepat —
  bukan rentang WoW/MoM penuh seperti di db.query_re_ps().
- Field "channel_group" ADA di payload tapi ISINYA KOSONG di semua order yang
  dicek (21.360 order, rentang 01-Jun s/d 16-Jul-2026, dicek langsung
  2026-07-17) — TIDAK dipakai lagi utk channel report (dulu sempat dipakai,
  hasilnya semua order jatuh ke "OTHER" dan channel report jadi 0 baris).
  Channel report sekarang derive dari field "subchannel", yang isinya penuh
  (0 blank) dan konsisten di seluruh sample: "DigiPos SF"/"DigiPos Outlet" →
  AGENCY, "GraPARI DSC" → GRAPARI, "LP"/"MyTelkomsel App"/"MyTelkomsel Web" →
  DIGITAL, "SOBI" → COMMUNITY (lihat _map_channel()). Ini dipetakan dari
  NAMA field, bukan dikonfirmasi definisi resminya ke tim FMC — cross-check
  ke db.query_ordering_detail() (kolom channel_group asli di MySQL) untuk
  periode yang sama begitu DB & FMC bisa diakses bersamaan, sebelum dipakai
  serius sebagai angka final. "product_commercial_name" tetap terkonfirmasi
  ada & terisi.
- Field "kabupaten" (dipakai Daily Performance level City) DAN "ps_rev"/
  revenue TIDAK ADA di payload FMC — sudah dicek, memang tidak dikirim.
  Jangan coba tebak dari field lain yang beda arti (mis. "price_package" =
  harga list, bukan revenue realisasi). Daily Performance City tetap harus
  dari DB; Daily Performance WOK versi FMC akan selalu 0/None untuk
  revenue/ARPU.
- Fetch rentang lebar (1 bulan, dipakai channel/daily-performance/export CSV
  di /closingutoip) belum pernah diuji tahan-banting ke endpoint ini — kalau
  sering ConnectionReset, coba pecah fetch_orders_range() per minggu.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone

import requests
import urllib3

from config import FMC_BASE_URL, FMC_COOKIE, FMC_XTOKEN, FMC_VERIFY_SSL, WOK_ORDER

logger = logging.getLogger(__name__)

FUNNELING_URL = f"{FMC_BASE_URL}/fmc-be/kpro-detail-funneling"
PAGE_LIMIT    = 200
# Order/aktivitas di FMC dicatat dalam WIB (UTC+7), bukan UTC — dipakai untuk
# membangun batas hari di _range_epoch() supaya "tanggal 1 Juli" berarti
# 00:00-23:59 WIB, bukan 00:00-23:59 UTC. Perbaikan yang benar secara teknis,
# tapi BUKAN penyebab utama gap DB vs FMC yang ditemukan 2026-07-19 (lihat
# BACKLOG_LOOKBACK_DAYS di bawah untuk penyebab sebenarnya).
WIB = timezone(timedelta(hours=7))

# Filter "dateRange" di endpoint kpro-detail-funneling ternyata berbasis
# TANGGAL ORDER DIBUAT (input_order), BUKAN tanggal event re_ts/ps_ts —
# dikonfirmasi empiris 2026-07-19: WOK Jepara Kudus Pati, PS tgl 1 Jul di DB
# = 32, tapi query_daily_performance_fmc(1 Jul, 18 Jul) cuma dapat 13 (order
# yang DIBUAT sebelum 1 Jul tapi baru PS di tgl 1 Jul kelewat). Setelah fetch
# range dimundurkan ke 15 Jun, PS tgl 1 Jul jadi 32 (cocok) dan total 1-18
# Jul jadi 408 (cocok persis dgn laporan resmi). Makanya fungsi yang butuh
# akurasi historis (Daily Performance WOK, Channel report, raw export —
# dipakai /closingutoip) fetch dengan buffer mundur ke AWAL BULAN SEBELUMNYA
# (bukan angka hari kaku), lalu tetap filter hasil akhir by tanggal event
# asli (re_ts/ps_ts), bukan tanggal fetch. TIDAK diterapkan ke query_re_ps()
# (dipakai /liveupdateutoip yg jalan otomatis 8x/hari) supaya command itu
# tetap cepat & tidak makin rawan gagal dari FMC untuk rentang fetch yang
# jauh lebih besar.
def _lookback_start(tgl_dari: date) -> date:
    """Tanggal 1 di bulan sebelum tgl_dari (mis. tgl_dari=1 Jul -> 1 Jun)."""
    akhir_bulan_lalu = tgl_dari.replace(day=1) - timedelta(days=1)
    return akhir_bulan_lalu.replace(day=1)

# Request rentang lebar (>~30 hari) ke endpoint kpro-detail-funneling langsung
# ke-reset koneksinya (dikonfirmasi 2026-07-19: rentang 90 hari gagal total di
# page 1, padahal rentang 34 hari sukses) — kemungkinan ada batas ukuran query
# di sisi server. fetch_orders_range() di bawah otomatis memecah rentang lebar
# jadi beberapa request @ maksimal segini hari, supaya BACKLOG_LOOKBACK_DAYS
# (90 hari) tetap bisa di-fetch penuh tanpa kena reset.
CHUNK_DAYS = 30
# 30s dulu sering timeout untuk fetch rentang lebar (channel/daily-performance/
# export CSV /closingutoip, 1 bulan penuh) lewat VPN — dinaikkan + ditambah
# retry di _fetch_page() supaya satu request lambat tidak langsung
# menggagalkan seluruh laporan.
REQUEST_TIMEOUT  = 60
RETRY_ATTEMPTS   = 3   # percobaan pertama + 2 retry
RETRY_BACKOFF_S  = 4   # 4s, lalu 8s

if not FMC_VERIFY_SSL:
    # Sertifikat CA internal Telkomsel tidak ada di trust store certifi.
    # Tanpa ini, urllib3 spam InsecureRequestWarning tiap request.
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _headers() -> dict:
    if not FMC_XTOKEN or not FMC_COOKIE:
        raise RuntimeError(
            "FMC_XTOKEN / FMC_COOKIE belum diisi di config.py. "
            "Ambil dari browser DevTools > Network > request kpro-detail-funneling "
            "(header x-token & Cookie)."
        )
    for name, val in (("FMC_XTOKEN", FMC_XTOKEN), ("FMC_COOKIE", FMC_COOKIE)):
        try:
            val.encode("latin-1")
        except UnicodeEncodeError as e:
            raise RuntimeError(
                f"{name} di config.py mengandung karakter tidak valid "
                f"('{e.object[e.start:e.end]}' di posisi {e.start}) - biasanya "
                f"tanda token/cookie TERPOTONG saat disalin (mis. dari chat yang "
                f"mempersingkat teks panjang jadi '…'). Copy ulang LANGSUNG dari "
                f"DevTools browser > Network > header {name.replace('FMC_', 'x-').lower()}, "
                f"jangan dari chat/Telegram."
            ) from e
    now    = datetime.now(timezone.utc)
    x_time = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {
        "Accept"       : "application/json, text/plain, */*",
        "Content-Type" : "application/json",
        "Cookie"       : FMC_COOKIE,
        "Origin"       : FMC_BASE_URL,
        "Referer"      : f"{FMC_BASE_URL}/fmc-dashboard/detail-order-kpro/funneling",
        "X-Time"       : x_time,
        "x-token"      : FMC_XTOKEN,
    }


def _range_epoch(tgl_dari: date, tgl_sampai: date) -> tuple[int, int]:
    start = datetime(tgl_dari.year, tgl_dari.month, tgl_dari.day, 0, 0, 0, tzinfo=WIB)
    end   = datetime(tgl_sampai.year, tgl_sampai.month, tgl_sampai.day, 23, 59, 59, tzinfo=WIB)
    return int(start.timestamp()), int(end.timestamp())


def _fetch_page(tgl_dari: date, tgl_sampai: date, page: int, limit: int = PAGE_LIMIT) -> dict:
    start_ts, end_ts = _range_epoch(tgl_dari, tgl_sampai)
    body = {
        "filter": [
            {"label": "dateRange", "value": {"start": start_ts, "end": end_ts}},
            {"label": "Territory", "value": list(WOK_ORDER)},
            # Pencapaian (RE/PS) resminya memang cuma dihitung dari NEW SALES —
            # berlaku utk SEMUA laporan FMC (bukan cuma channel report), jadi
            # filter di level API ini sengaja dipertahankan utk semua fungsi
            # yang pakai fetch_orders_range()/fetch_orders().
            {"label": "Order Type", "value": ["NEW SALES"]},
            {
                "rows":    [{"value": "input_order", "column": "input_order"}],
                "columns": [{"value": "input_order", "column": "input_order"}],
            },
            {"label": "url", "value": "summary-provisioning"},
            {"label": "page", "value": page},
            {"label": "limit", "value": limit},
        ]
    }
    last_err = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.post(FUNNELING_URL, headers=_headers(), json=body,
                                  timeout=REQUEST_TIMEOUT, verify=FMC_VERIFY_SSL)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") != "success":
                raise RuntimeError(f"FMC API mengembalikan error: {payload}")
            return payload
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS:
                wait = RETRY_BACKOFF_S * attempt
                logger.warning(
                    f"FMC funneling page {page} timeout/connection error "
                    f"(percobaan {attempt}/{RETRY_ATTEMPTS}), retry dalam {wait}s: {e}"
                )
                time.sleep(wait)
            else:
                logger.error(f"FMC funneling page {page} gagal setelah {RETRY_ATTEMPTS}x: {e}")
    raise last_err


def _fetch_orders_chunk(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """Ambil semua order (semua halaman) untuk SATU chunk rentang tanggal (<= CHUNK_DAYS hari)."""
    orders = []
    page = 1
    while True:
        payload    = _fetch_page(tgl_dari, tgl_sampai, page)
        data       = payload.get("data") or []
        orders.extend(data)
        meta       = payload.get("meta") or {}
        total_page = meta.get("total_page", 1) or 1
        logger.info(f"FMC funneling {tgl_dari}~{tgl_sampai} page {page}/{total_page}: {len(data)} baris")
        if page >= total_page or not data:
            break
        page += 1
    return orders


def _add_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    y2, m2 = _add_month(year, month)
    end = date(y2, m2, 1) - timedelta(days=1)
    return start, end


# Cache antar-panggilan dalam satu proses bot: {(year, month): [order, ...]}.
# Satu closing report (/closingutoip) memanggil beberapa fungsi berbeda
# (Daily Performance WOK, Channel report, Raw export, tiap-tiap plus
# perbandingan bulan lalu) yang rentang tanggalnya banyak tumpang-tindih —
# tanpa cache ini, bulan yang sama bisa di-fetch ulang 3-4x dari FMC dalam
# satu laporan (2026-07-19: inilah penyebab /closingutoip lambat/timeout).
# HANYA bulan yang SUDAH LEWAT (bukan bulan berjalan) yang di-cache, karena
# datanya sudah final dan tidak berubah lagi — bulan berjalan selalu
# di-fetch ulang supaya order yang baru masuk hari ini tetap ke-tangkap.
_month_cache: dict[tuple[int, int], list[dict]] = {}


def _fetch_month(year: int, month: int) -> list[dict]:
    """Ambil semua order untuk satu bulan kalender, pakai cache utk bulan yang sudah lewat."""
    today = date.today()
    is_bulan_berjalan = (year, month) == (today.year, today.month)

    if not is_bulan_berjalan and (year, month) in _month_cache:
        return _month_cache[(year, month)]

    start, end = _month_bounds(year, month)
    if is_bulan_berjalan:
        end = min(end, today)

    orders = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end)
        orders.extend(_fetch_orders_chunk(chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)

    if not is_bulan_berjalan:
        _month_cache[(year, month)] = orders
    return orders


def fetch_orders_range_cached(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Setara fetch_orders_range(), tapi dipecah & di-cache per BULAN KALENDER
    (lihat _month_cache) — dipakai KHUSUS oleh fungsi yang butuh buffer
    mundur lebar (query_daily_performance_fmc, query_ordering_detail_fmc,
    fetch_orders_raw_for_export — semuanya dipanggil /closingutoip, dan
    rentangnya selalu dari awal bulan s/d suatu tanggal, jadi granularity
    bulan penuh ini pas, tidak ada yang kebuang percuma).

    JANGAN dipakai untuk fetch 1 hari spesifik (mis. query_re_ps() /
    /liveupdateutoip) — itu tetap pakai fetch_orders_range() biasa di bawah,
    supaya tidak ikut menarik satu bulan penuh cuma untuk kebutuhan 1 hari.
    """
    orders = []
    year, month = tgl_dari.year, tgl_dari.month
    while (year, month) <= (tgl_sampai.year, tgl_sampai.month):
        orders.extend(_fetch_month(year, month))
        year, month = _add_month(year, month)
    return orders


def fetch_orders_range(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Ambil semua order (semua halaman) untuk rentang tanggal tertentu dari FMC
    API. Rentang lebar dipecah otomatis jadi beberapa request @ maksimal
    CHUNK_DAYS hari (lihat CHUNK_DAYS) supaya query lebar tidak dikirim
    sebagai satu request raksasa yang rawan ConnectionReset. TIDAK di-cache
    (lihat fetch_orders_range_cached() untuk versi yang di-cache per bulan).
    """
    orders = []
    chunk_start = tgl_dari
    while chunk_start <= tgl_sampai:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), tgl_sampai)
        orders.extend(_fetch_orders_chunk(chunk_start, chunk_end))
        chunk_start = chunk_end + timedelta(days=1)
    return orders


def fetch_orders(tgl: date) -> list[dict]:
    """Ambil semua order (semua halaman) untuk satu tanggal dari FMC API."""
    return fetch_orders_range(tgl, tgl)


def _parse_ts(value):
    """Parse timestamp format FMC '12/Jul/2026 07:57'. '-'/''/None -> None."""
    if not value or value == "-":
        return None
    try:
        return datetime.strptime(value, "%d/%b/%Y %H:%M")
    except (ValueError, TypeError):
        return None


def query_re_ps(hari_ini: date) -> list[dict]:
    """
    Setara db.query_re_ps(hari_ini): kembalikan list of dicts
    wok, branch, activity_date, activity_hour, io_trx, re_trx, ps_trx.

    Data diambil dari FMC API (order-level) untuk hari_ini + kemarin + 7 hari
    lalu (dibutuhkan render_tabel() untuk kolom D-7), lalu diagregasi per WOK
    per jam berdasarkan order_ts (IO) / re_ts / ps_ts tiap order.

    NB: field "io_ts" ADA di payload FMC tapi ISINYA SELALU KOSONG (dicek
    langsung 2026-07-17, 7.630 order rentang 01-16 Jul 2026, 100% blank) —
    IO dihitung dari "order_ts" (timestamp order dibuat, 0% blank di sample
    yang sama, selalu <= re_ts/ps_ts order yang sama) sebagai gantinya.
    """
    kemarin         = hari_ini - timedelta(days=1)
    tujuh_hari_lalu = hari_ini - timedelta(days=7)
    orders_raw = (
        fetch_orders(hari_ini)
        + fetch_orders(kemarin)
        + fetch_orders(tujuh_hari_lalu)
    )

    # Dedup by order_id: kalau API tidak benar-benar membatasi hasil per
    # dateRange yang diminta (mis. balikin snapshot funnel yang sama untuk
    # hari_ini & kemarin), order yang sama bisa muncul di kedua fetch dan
    # ke-hitung dobel kalau tidak di-dedup.
    seen   = set()
    orders = []
    for o in orders_raw:
        oid = o.get("order_id")
        if oid:
            if oid in seen:
                continue
            seen.add(oid)
        orders.append(o)

    buckets = {}  # (wok, branch, activity_date, activity_hour) -> {io_trx, re_trx, ps_trx}

    def _bump(wok, branch, tgl, jam, field):
        key = (wok, branch, tgl, jam)
        if key not in buckets:
            buckets[key] = {"io_trx": 0, "re_trx": 0, "ps_trx": 0}
        buckets[key][field] += 1

    tanggal_dipakai = (hari_ini, kemarin, tujuh_hari_lalu)

    for o in orders:
        wok = (o.get("wok") or "").strip().upper()
        if not wok:
            continue
        branch = (o.get("branch") or "").strip().upper()

        io_ts = _parse_ts(o.get("order_ts"))
        if io_ts and io_ts.date() in tanggal_dipakai:
            _bump(wok, branch, io_ts.date(), io_ts.hour, "io_trx")

        re_ts = _parse_ts(o.get("re_ts"))
        if re_ts and re_ts.date() in tanggal_dipakai:
            _bump(wok, branch, re_ts.date(), re_ts.hour, "re_trx")

        ps_ts = _parse_ts(o.get("ps_ts"))
        if ps_ts and ps_ts.date() in tanggal_dipakai:
            _bump(wok, branch, ps_ts.date(), ps_ts.hour, "ps_trx")

    if not buckets:
        raise ValueError(f"Tidak ada data FMC untuk tanggal s/d {hari_ini}")

    rows = []
    for (wok, branch, tgl, jam), val in buckets.items():
        rows.append({
            "wok"          : wok,
            "branch"       : branch,
            "activity_date": tgl,
            "activity_hour": jam,
            "io_trx"       : val["io_trx"],
            "re_trx"       : val["re_trx"],
            "ps_trx"       : val["ps_trx"],
        })
    return rows


# ── Channel & ordering-detail (dipakai /closingutoip) ──────────────────────
# "channel_group" ADA sebagai key di payload FMC tapi ISINYA SELALU KOSONG
# (dicek langsung 2026-07-17, 21.360 order rentang 01-Jun s/d 16-Jul-2026,
# 100% blank) — makanya channel report /closingutoip sempat balik 0 baris
# walau fetch-nya sukses (semua order jatuh ke "OTHER" lalu dibuang).
# Diganti pakai "subchannel", yang terisi penuh (0 blank) di sample yang
# sama. Mapping di bawah dari NAMA field (belum dikonfirmasi definisi resmi
# ke tim FMC) — cross-check ke db.query_ordering_detail() (channel_group
# asli di MySQL) utk periode yang sama begitu DB & FMC bisa diakses
# bersamaan.
SUBCHANNEL_MAP = {
    "DIGIPOS SF"      : "AGENCY",
    "DIGIPOS OUTLET"  : "AGENCY",
    "GRAPARI DSC"     : "GRAPARI",
    "LP"              : "DIGITAL",       # Land Page (FMC - IndiHome Land Page)
    "MYTELKOMSEL APP" : "DIGITAL",
    "MYTELKOMSEL WEB" : "DIGITAL",
    "SOBI"            : "COMMUNITY",
}


def _map_channel(subchannel: str) -> str:
    return SUBCHANNEL_MAP.get((subchannel or "").strip().upper(), "OTHER")


def _dedup_by_order_id(orders: list[dict]) -> list[dict]:
    seen   = set()
    result = []
    for o in orders:
        oid = o.get("order_id")
        if oid:
            if oid in seen:
                continue
            seen.add(oid)
        result.append(o)
    return result


def query_ordering_detail_fmc(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Setara db.query_ordering_detail(tgl_dari, tgl_sampai): hitung IO/RE/PS per
    WOK per channel dari data order-level FMC (bukan tabel MySQL
    indihome_ordering_detail).

    Exclude produk WIRELESS (product_commercial_name) dan channel yang tidak
    dikenal ('OTHER'), mengikuti logic yang sama persis dengan
    db.query_ordering_detail(). (order_type='NEW SALES' sudah difilter di
    level API, lihat _fetch_page().)

    Returns list of dicts: wok, branch, channel, io_trx, re_trx, ps_trx.
    """
    fetch_dari = _lookback_start(tgl_dari)
    orders = _dedup_by_order_id(fetch_orders_range_cached(fetch_dari, tgl_sampai))

    buckets = {}  # (wok, branch, channel) -> {io_trx, re_trx, ps_trx}

    def _bump(wok, branch, channel, field):
        key = (wok, branch, channel)
        if key not in buckets:
            buckets[key] = {"io_trx": 0, "re_trx": 0, "ps_trx": 0}
        buckets[key][field] += 1

    for o in orders:
        product = (o.get("product_commercial_name") or "").upper()
        if "WIRELESS" in product:
            continue

        channel = _map_channel(o.get("subchannel"))
        if channel == "OTHER":
            continue

        wok = (o.get("wok") or "").strip().upper()
        if not wok:
            continue
        branch = (o.get("branch") or "").strip().upper()

        io_ts = _parse_ts(o.get("order_ts"))
        if io_ts and tgl_dari <= io_ts.date() <= tgl_sampai:
            _bump(wok, branch, channel, "io_trx")

        re_ts = _parse_ts(o.get("re_ts"))
        if re_ts and tgl_dari <= re_ts.date() <= tgl_sampai:
            _bump(wok, branch, channel, "re_trx")

        ps_ts = _parse_ts(o.get("ps_ts"))
        if ps_ts and tgl_dari <= ps_ts.date() <= tgl_sampai:
            _bump(wok, branch, channel, "ps_trx")

    rows = []
    for (wok, branch, channel), val in buckets.items():
        rows.append({
            "wok"    : wok,
            "branch" : branch,
            "channel": channel,
            "io_trx" : val["io_trx"],
            "re_trx" : val["re_trx"],
            "ps_trx" : val["ps_trx"],
        })
    return rows


def query_daily_performance_fmc(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Setara _query_dashboard() di calculator_daily.py, tapi dari data order-level
    FMC: hitung IO/RE/PS per WOK per tanggal (activity_date = tanggal order_ts
    (IO) / re_ts / ps_ts masing-masing — io_ts SELALU KOSONG di payload FMC,
    lihat catatan di query_re_ps()).

    CATATAN: dashboard_hourly_sales (sumber asli) punya kolom "kabupaten" dan
    "ps_rev" (revenue) yang TIDAK ADA di payload FMC funnel — sudah dicek
    langsung, field itu tidak dikirim API. Karena itu:
    - Daily Performance level City TIDAK BISA dibangun dari FMC (lihat
      calculator_daily.hitung_city_performance, tetap pakai DB).
    - Revenue/ARPU di Daily Performance WOK versi FMC akan selalu 0/None,
      bukan hasil kalkulasi asal-asalan dari field lain yang beda arti
      (mis. "price_package" itu harga list, bukan revenue realisasi).

    Returns list of dicts: wok, branch, activity_date, io_trx, re_trx, ps_trx.
    """
    fetch_dari = _lookback_start(tgl_dari)
    orders = _dedup_by_order_id(fetch_orders_range_cached(fetch_dari, tgl_sampai))

    buckets = {}  # (wok, branch, activity_date) -> {io_trx, re_trx, ps_trx}

    def _bump(wok, branch, tgl, field):
        key = (wok, branch, tgl)
        if key not in buckets:
            buckets[key] = {"io_trx": 0, "re_trx": 0, "ps_trx": 0}
        buckets[key][field] += 1

    for o in orders:
        wok = (o.get("wok") or "").strip().upper()
        if not wok:
            continue
        branch = (o.get("branch") or "").strip().upper()

        io_ts = _parse_ts(o.get("order_ts"))
        if io_ts and tgl_dari <= io_ts.date() <= tgl_sampai:
            _bump(wok, branch, io_ts.date(), "io_trx")

        re_ts = _parse_ts(o.get("re_ts"))
        if re_ts and tgl_dari <= re_ts.date() <= tgl_sampai:
            _bump(wok, branch, re_ts.date(), "re_trx")

        ps_ts = _parse_ts(o.get("ps_ts"))
        if ps_ts and tgl_dari <= ps_ts.date() <= tgl_sampai:
            _bump(wok, branch, ps_ts.date(), "ps_trx")

    rows = []
    for (wok, branch, tgl), val in buckets.items():
        rows.append({
            "wok"          : wok,
            "branch"       : branch,
            "activity_date": tgl,
            "io_trx"       : val["io_trx"],
            "re_trx"       : val["re_trx"],
            "ps_trx"       : val["ps_trx"],
        })
    return rows


def fetch_orders_raw_for_export(tgl_dari: date, tgl_sampai: date) -> list[dict]:
    """
    Ambil order mentah (semua kolom asli dari FMC, TIDAK di-remap ke skema
    indihome_ordering_detail) untuk keperluan /closingutoip export raw CSV.
    Hanya order yang order_ts (IO)/re_ts/ps_ts-nya jatuh di rentang
    tgl_dari~tgl_sampai yang disertakan (meniru filter WHERE ... BETWEEN di
    calculator_daily.export_raw_csv() — io_ts SELALU KOSONG di payload FMC,
    lihat catatan di query_re_ps()). (order_type='NEW SALES' sudah difilter
    di level API, lihat _fetch_page().)
    """
    fetch_dari = _lookback_start(tgl_dari)
    orders = _dedup_by_order_id(fetch_orders_range_cached(fetch_dari, tgl_sampai))

    def _in_range(value) -> bool:
        ts = _parse_ts(value)
        return ts is not None and tgl_dari <= ts.date() <= tgl_sampai

    return [
        o for o in orders
        if _in_range(o.get("order_ts")) or _in_range(o.get("re_ts")) or _in_range(o.get("ps_ts"))
    ]
