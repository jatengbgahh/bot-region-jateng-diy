"""
reports/market_share/calculator.py — Kalkulasi Market Share FBB per City Region Jateng-DIY.

Pemain di report : TSEL Group, CBN Network, ICON PLN, XL Home, First Media, Indosat,
                   My Republic, MNC Play, Biznet, Others.
TSEL Group = indihome + tsel_orbit (kolom tabel).

WoW / MoM / YoY = SELISIH share TSEL Group (poin persentase, bukan growth relatif)
terhadap event_date pembanding. Data tabel mingguan (tiap Minggu), jadi:
  WoW = event_date - 7 hari   MoM = event_date - 28 hari   YoY = event_date - 364 hari
Kalau tanggal persis itu tidak ada, dipakai event_date terdekat yang <= tanggal itu
(maks 6 hari lebih lama); kalau tetap tidak ada -> None (tampil "-").

Tabel kedua (MOM Growth) = selisih share MoM untuk SETIAP pemain (TSEL Group dst).
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

import wilayah
from . import query

logger = logging.getLogger(__name__)

PEMAIN = [
    ("tsel",        "TSEL Group"),
    ("cbn_network", "CBN Network"),
    ("icon_pln",    "ICON PLN"),
    ("xl_home",     "XL Home"),
    ("first_media", "First Media"),
    ("indosat",     "Indosat"),
    ("myrepublic",  "My Republic"),
    ("mnc_play",    "MNC Play"),
    ("biznet",      "Biznet"),
    ("others",      "Others"),
]
KEYS = [k for k, _ in PEMAIN]

# Urutan city di report (mengikuti contoh); city di luar daftar ditaruh paling bawah.
URUTAN_CITY = [
    "CILACAP", "BANYUMAS", "PURBALINGGA", "BANJARNEGARA", "KEBUMEN", "PURWOREJO",
    "WONOSOBO", "MAGELANG", "BOYOLALI", "KLATEN", "SUKOHARJO", "WONOGIRI",
    "KARANGANYAR", "SRAGEN", "GROBOGAN", "BLORA", "REMBANG", "PATI", "KUDUS",
    "JEPARA", "DEMAK", "SEMARANG", "TEMANGGUNG", "KENDAL", "BATANG", "PEKALONGAN",
    "PEMALANG", "TEGAL", "BREBES", "KOTA MAGELANG", "KOTA SURAKARTA", "KOTA SALATIGA",
    "KOTA SEMARANG", "KOTA PEKALONGAN", "KOTA TEGAL", "KULON PROGO", "BANTUL",
    "GUNUNG KIDUL", "SLEMAN", "KOTA YOGYAKARTA",
]

# Jarak hari pembanding (data mingguan)
SELISIH_HARI = {"wow": 7, "mom": 28, "yoy": 364}
TOLERANSI_HARI = 6


def _n(v) -> Decimal:
    return Decimal(v) if v is not None else Decimal("0")


def _share_row(r: dict) -> dict:
    """Satu baris DB -> {tsel, cbn_network, ..., others} (Decimal)."""
    d = {"tsel": _n(r["indihome"]) + _n(r["tsel_orbit"])}
    for k in KEYS[1:]:
        d[k] = _n(r[k])
    return d


def _peta_share(event_date: date | None, region: bool = False, branch: bool = False) -> dict:
    if event_date is None:
        return {}
    if branch:
        rows = query.query_share_branch(event_date)
    else:
        rows = query.query_share_region(event_date) if region else query.query_share(event_date)
    return {str(r["city"]).strip().upper(): _share_row(r) for r in rows}


def _selisih(sekarang: dict, lalu: dict | None, key: str):
    if not lalu:
        return None
    return float(sekarang[key] - lalu[key])


def _referensi(event_date: date, tabel: str, region: bool, branch: bool = False):
    """{wow/mom/yoy: (tanggal pembanding, {territory: share})} dari tabel tertentu."""
    ref_dates, ref_maps = {}, {}
    for nama, hari in SELISIH_HARI.items():
        target = event_date - timedelta(days=hari)
        ref = query.query_event_date_sebelum(target, target - timedelta(days=TOLERANSI_HARI), tabel)
        ref_dates[nama] = ref
        ref_maps[nama] = _peta_share(ref, region, branch)
    return ref_dates, ref_maps


def _susun_baris(r: dict, ref_maps: dict) -> dict:
    nama = str(r["city"]).strip().upper()
    now = _share_row(r)
    peta = wilayah.petakan_kab(nama)        # (wok baru, branch) via kabupaten; None utk baris region
    return {
        "city": nama,
        "wok": peta[0] if peta else "-",
        "branch": peta[1] if peta else "-",
        "share": {k: float(now[k]) for k in KEYS},
        "wow": _selisih(now, ref_maps["wow"].get(nama), "tsel"),
        "mom": _selisih(now, ref_maps["mom"].get(nama), "tsel"),
        "yoy": _selisih(now, ref_maps["yoy"].get(nama), "tsel"),
        "mom_pemain": {k: _selisih(now, ref_maps["mom"].get(nama), k) for k in KEYS},
        "status": r["status"] or "-",
        "closest": r["closest_competitor"] or "-",
    }


def hitung_market_share(tgl: date = None) -> dict | None:
    """
    tgl=None -> update terakhir tabel; tgl=tanggal -> event_date terbaru yang <= tgl.
    Return None kalau tidak ada data. Hasil siap pakai untuk renderer.

    data["kota"]   : baris per city (fixed_ms_city)
    data["region"] : baris region JATENG-DIY (fixed_ms_region), None kalau tidak ada datanya
    """
    event_date = query.query_event_date_terakhir(tgl)
    if event_date is None:
        return None

    ref_dates, ref_maps = _referensi(event_date, query.TABEL, region=False)
    kota = [_susun_baris(r, ref_maps) for r in query.query_share(event_date)]
    # Urut Branch -> WOK (urutan lampiran WOK baru) -> city (urutan URUTAN_CITY)
    urut = {c: i for i, c in enumerate(URUTAN_CITY)}
    n_br, n_wok = len(wilayah.BRANCH_ORDER), len(wilayah.WOK_ORDER)
    kota.sort(key=lambda x: (
        wilayah.BRANCH_ORDER.index(x["branch"]) if x["branch"] in wilayah.BRANCH_ORDER else n_br,
        wilayah.WOK_ORDER.index(x["wok"]) if x["wok"] in wilayah.WOK_ORDER else n_wok,
        urut.get(x["city"], len(URUTAN_CITY))))

    # Baris region: tanggalnya bisa beda tipis dgn tabel city -> pakai event_date region
    # terbaru yang <= event_date city (maks TOLERANSI_HARI hari lebih lama).
    region = None
    ed_region = query.query_event_date_sebelum(
        event_date, event_date - timedelta(days=TOLERANSI_HARI), query.TABEL_REGION)
    if ed_region is not None:
        baris = query.query_share_region(ed_region)
        if baris:
            _, ref_maps_r = _referensi(ed_region, query.TABEL_REGION, region=True)
            region = _susun_baris(baris[0], ref_maps_r)
    else:
        logger.warning(f"[ms] fixed_ms_region tidak punya data {query.REGION} "
                       f"<= {event_date} — baris region dilewati")

    return {
        "event_date": event_date,
        "ref_dates": ref_dates,
        "pemain": PEMAIN,
        "kota": kota,
        "region": region,
    }


def hitung_market_share_branch(tgl: date = None) -> dict | None:
    """
    Market share per BRANCH (tabel fixed_ms_branch, angka resmi) + baris region
    (fixed_ms_region). Bentuk hasil sama dengan hitung_market_share(): data["kota"]
    berisi baris per branch. WoW/MoM/YoY = selisih share TSEL Group vs pembanding.
    Catatan: pengelompokan branch mengikuti tabel fixed_ms_branch (bisa beda dgn WOK baru).
    """
    event_date = query.query_event_date_terakhir(tgl, query.TABEL_BRANCH)
    if event_date is None:
        return None
    ref_dates, ref_maps = _referensi(event_date, query.TABEL_BRANCH, region=False, branch=True)
    baris = [_susun_baris(r, ref_maps) for r in query.query_share_branch(event_date)]
    import wilayah
    urut = {b: i for i, b in enumerate(wilayah.BRANCH_ORDER)}
    baris.sort(key=lambda x: urut.get(x["city"], len(urut)))

    region = None
    ed_region = query.query_event_date_sebelum(
        event_date, event_date - timedelta(days=TOLERANSI_HARI), query.TABEL_REGION)
    if ed_region is not None:
        r_rows = query.query_share_region(ed_region)
        if r_rows:
            _, ref_maps_r = _referensi(ed_region, query.TABEL_REGION, region=True)
            region = _susun_baris(r_rows[0], ref_maps_r)
    return {"event_date": event_date, "ref_dates": ref_dates, "pemain": PEMAIN,
            "kota": baris, "region": region}


def top_wow(data: dict, n: int = 3):
    """(tertinggi, terendah): n city dgn WoW TSEL Group tertinggi / terendah, list (city, wow)."""
    ada = [(k["city"], k["wow"]) for k in data["kota"] if k["wow"] is not None]
    urut = sorted(ada, key=lambda x: x[1], reverse=True)
    return urut[:n], sorted(urut[-n:], key=lambda x: x[1])
