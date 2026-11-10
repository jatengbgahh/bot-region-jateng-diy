"""
calculator_homepass.py — Kalkulasi Homepass Report per WOK/BRANCH/REGION IndiHome Jateng-DIY
Periode: MtD (tanggal 1 bulan berjalan s/d tgl_closing), MoM vs tanggal yang sama bulan lalu.

Dua sumber data independen (dibandingkan untuk mengukur cakupan homepass_sales,
yang datanya tidak selalu lengkap dibanding indihome_ordering_detail):

1) indihome_ordering_detail_YYYYMM langsung, channel AGENCY (db.query_iod_io) —
   baseline "kebenaran":
   - Total IO     = COUNT io_ts valid, channel AGENCY
   - SF Active IO = unique sf_code, io_ts valid, channel AGENCY

2) homepass_sales_YYYYMM LEFT JOIN indihome_ordering_detail_YYYYMM (db.query_homepass):
   - IO (Home ID)  = COUNT(*) homepass_sales, filter created_at dalam periode
   - RE (Home ID)  = COUNT re_ts valid (hasil JOIN) dalam periode
   - RE Salah Homepass = RE di atas dengan fallout_reason (kolom dari
     indihome_ordering_detail, ikut ter-JOIN) mengandung "SALAH TAGGING"
     (regex, case-insensitive — fallout_reason adalah string gabungan bebas
     format, bukan kategori bersih, contoh:
     "INF008481034-WFM-Kendala Pelanggan-SALAH TAGGING-OrderLevelError--...")
     Divalidasi terhadap data riil (Homepass ID - Juli 2026.xlsx): match
     "SALAH TAGGING" cocok 11/16 WOK persis, sisanya selisih 1-2 (wajar,
     beda waktu snapshot) — jauh lebih akurat dibanding "SALAH HOMEPASS".
   - PS            = COUNT ps_ts valid (hasil JOIN) dalam periode
   - SF with IO Home ID = unique sf_code dari baris io_ts valid (hasil JOIN)

Metrik turunan:
- %IO Home ID           = IO (Home ID) / Total IO
- %Order Salah Homepass = RE Salah Homepass / RE (Home ID)
- RE/PS                 = PS / RE (Home ID)
- %SF with Home ID      = SF with IO Home ID / SF Active IO

Catatan agregasi: base count dihitung per WOK, BRANCH & REGION = SUM base count
WOK-WOK anggotanya (konsisten dengan calculator_pdd.py / calculator_sf.py) — bukan
hitung ulang unique()/COUNT dari data gabungan.
"""

import calendar
import logging
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import db
from config import (
    WOK_TO_BRANCH_BARU, BRANCH_ORDER, WOK_ORDER_BARU, REGION_NAME,
    WOK_TO_BRANCH as WOK_TO_BRANCH_LAMA, WOK_ORDER as WOK_ORDER_LAMA,
)


def _acuan_wok(wok_lama: bool):
    """(WOK_TO_BRANCH, WOK_ORDER) — struktur WOK lama (16 WOK) atau baru (14 WOK)."""
    if wok_lama:
        return WOK_TO_BRANCH_LAMA, WOK_ORDER_LAMA
    return WOK_TO_BRANCH_BARU, WOK_ORDER_BARU

logger = logging.getLogger(__name__)

# fallout_reason contoh: "INF008481034-WFM-Kendala Pelanggan-SALAH TAGGING-OrderLevelError--..."
# Bukan kategori bersih -> dicocokkan sebagai substring (regex), bukan exact match.
RE_SALAH_HOMEPASS = r"SALAH\s+TAGGING"

BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def _top(rows: list, key: str):
    """Nama row dengan nilai `key` terbesar (skip None)."""
    kandidat = [r for r in rows if r.get(key) is not None]
    if not kandidat:
        return None
    return max(kandidat, key=lambda r: r[key])["name"]


def _bottom(rows: list, key: str):
    """Nama row dengan nilai `key` terkecil (skip None)."""
    kandidat = [r for r in rows if r.get(key) is not None]
    if not kandidat:
        return None
    return min(kandidat, key=lambda r: r[key])["name"]


def _prep_sto(df: pd.DataFrame) -> pd.DataFrame:
    df["sto_co"] = df["sto_co"].fillna("-").astype(str).str.strip().str.upper()
    df.loc[df["sto_co"] == "", "sto_co"] = "-"
    return df


def _prep_homepass(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["wok"]    = df["wok"].astype(str).str.strip().str.upper()
    df["branch"] = df["branch"].astype(str).str.strip().str.upper()
    for col in ["created_at", "io_ts", "re_ts", "ps_ts"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["fallout_reason"] = df["fallout_reason"].astype(str).str.upper()
    df = _prep_sto(df)
    return df


def _prep_iod(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["wok"]    = df["wok"].astype(str).str.strip().str.upper()
    df["branch"] = df["branch"].astype(str).str.strip().str.upper()
    df = _prep_sto(df)
    return df


def _base_counts_homepass(df: pd.DataFrame, awal, akhir) -> dict:
    """Base count dari sisi homepass_sales JOIN ordering_detail, untuk 1 WOK & 1 periode."""
    b = {"io": 0, "re": 0, "re_salah": 0, "ps": 0, "sf_home_id": 0}
    if df.empty:
        return b

    akhir_excl = pd.Timestamp(akhir) + pd.Timedelta(days=1)
    awal_ts    = pd.Timestamp(awal)

    def in_range(col):
        return df[col].notna() & (df[col] >= awal_ts) & (df[col] < akhir_excl)

    m_created = in_range("created_at")
    m_re      = in_range("re_ts")
    m_ps      = in_range("ps_ts")
    m_io      = in_range("io_ts")

    m_salah = df["fallout_reason"].str.contains(RE_SALAH_HOMEPASS, regex=True, na=False)

    b["io"]         = int(m_created.sum())
    b["re"]         = int(m_re.sum())
    b["re_salah"]   = int((m_re & m_salah).sum())
    b["ps"]         = int(m_ps.sum())
    b["sf_home_id"] = int(df.loc[m_io, "sf_code"].dropna().nunique())

    return b


def _base_counts_iod(df: pd.DataFrame) -> dict:
    """
    Base count dari sisi indihome_ordering_detail langsung, untuk 1 WOK
    (sudah difilter tanggal & channel AGENCY di SQL — db.query_iod_io).
    """
    b = {"total_io": 0, "sf_active_io": 0}
    if df.empty:
        return b
    b["total_io"]     = int(len(df))
    b["sf_active_io"] = int(df["sf_code"].dropna().nunique())
    return b


def _sum_counts(rows: list, keys: list) -> dict:
    return {k: sum(r.get(k, 0) for r in rows) for k in keys}


def _growth(cur, prev):
    if prev and prev > 0:
        return round((cur - prev) / prev * 100, 1)
    return None


def _derived(hp_now: dict, hp_prev: dict, iod_now: dict) -> dict:
    m = {**hp_now, **iod_now}
    m["pct_io_home_id"] = (
        hp_now["io"] / iod_now["total_io"] * 100 if iod_now["total_io"] > 0 else None
    )
    m["pct_salah_homepass"] = (
        hp_now["re_salah"] / hp_now["re"] * 100 if hp_now["re"] > 0 else None
    )
    m["re_ps"] = (
        hp_now["ps"] / hp_now["re"] * 100 if hp_now["re"] > 0 else None
    )
    m["pct_sf_home_id"] = (
        hp_now["sf_home_id"] / iod_now["sf_active_io"] * 100
        if iod_now["sf_active_io"] > 0 else None
    )
    m["mom_re"]         = _growth(hp_now["re"], hp_prev["re"])
    m["mom_ps"]         = _growth(hp_now["ps"], hp_prev["ps"])
    m["mom_sf_home_id"] = _growth(hp_now["sf_home_id"], hp_prev["sf_home_id"])
    return m


def load_sumber(tgl_closing: date, wok_lama: bool = False) -> dict:
    """
    Ambil & siapkan data mentah 2 sumber (homepass_sales JOIN ordering_detail +
    ordering_detail langsung) SEKALI saja.

    query_homepass() itu LEFT JOIN 2 bulan homepass_sales x 2 tabel
    ordering_detail tanpa filter tanggal — query paling berat di bot ini. Dulu
    hitung_homepass(), hitung_homepass_sto() & export_raw_csv() masing-masing
    memanggilnya sendiri-sendiri, jadi 1x /homepass menjalankannya 3x dan
    laporan ke-2 dst baru muncul lama setelah laporan ke-1. Sekarang hasilnya
    di-load sekali lalu dioper ke semua fungsi lewat parameter `sumber`.
    """
    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_ini   = tgl_closing.replace(day=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_mtd_lalu = min(tgl_closing.day, hari_max_lalu)
    akhir_lalu    = date(bulan_lalu.year, bulan_lalu.month, hari_mtd_lalu)

    from datetime import timedelta as _td

    rows_hp_ini  = db.query_homepass(tgl_closing, wok_lama=wok_lama)
    rows_hp_lalu = db.query_homepass(bulan_lalu, wok_lama=wok_lama)
    # +1 hari: io_ts bertipe DATETIME, BETWEEN perlu batas atas esok hari agar
    # tanggal tgl_closing ikut penuh (sama seperti query_sf_agency dkk)
    rows_iod = db.query_iod_io(awal_ini, tgl_closing + _td(days=1), wok_lama=wok_lama)

    return {
        "tgl_closing": tgl_closing,
        "awal_ini"   : awal_ini,
        "awal_lalu"  : awal_lalu,
        "akhir_lalu" : akhir_lalu,
        "bulan_lalu" : bulan_lalu,
        "rows_hp_ini" : rows_hp_ini,
        "rows_hp_lalu": rows_hp_lalu,
        "rows_iod"    : rows_iod,
        "df_hp_ini" : _prep_homepass(pd.DataFrame(rows_hp_ini)  if rows_hp_ini  else pd.DataFrame()),
        "df_hp_lalu": _prep_homepass(pd.DataFrame(rows_hp_lalu) if rows_hp_lalu else pd.DataFrame()),
        "df_iod"    : _prep_iod(pd.DataFrame(rows_iod) if rows_iod else pd.DataFrame()),
    }


def hitung_homepass(tgl_closing: date, sumber: dict = None, wok_lama: bool = False) -> dict:
    """
    Query & hitung Homepass Report MtD s/d tgl_closing, MoM vs tanggal sama bulan lalu.
    `sumber` = hasil load_sumber() (opsional) supaya query berat tidak diulang.
    Return dict siap pakai untuk renderer_homepass.render_homepass().
    """
    WOK_TO_BRANCH, WOK_ORDER = _acuan_wok(wok_lama)
    s = sumber or load_sumber(tgl_closing, wok_lama)
    awal_ini, awal_lalu, akhir_lalu = s["awal_ini"], s["awal_lalu"], s["akhir_lalu"]
    df_hp_ini, df_hp_lalu, df_iod = s["df_hp_ini"], s["df_hp_lalu"], s["df_iod"]

    def branch_of(wok: str) -> str:
        return WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )

    semua_wok_raw = (
        set(df_hp_ini["wok"].unique()  if not df_hp_ini.empty  else []) |
        set(df_hp_lalu["wok"].unique() if not df_hp_lalu.empty else []) |
        set(df_iod["wok"].unique()     if not df_iod.empty     else [])
    )
    # Batasi ke WOK yang dikenal (config.WOK_ORDER) — data JOIN mentah dari
    # homepass_sales/ordering_detail bisa saja mengandung WOK asing/kotor
    # (typo, region lain yang lolos filter, dsb) yang kalau tidak disaring
    # bisa bikin jumlah baris meledak & gambar jadi raksasa.
    wok_dikenal = {w.upper() for w in WOK_ORDER}
    wok_asing   = semua_wok_raw - wok_dikenal
    if wok_asing:
        logger.warning(f"[homepass] WOK tidak dikenal, dilewati: {sorted(wok_asing)}")
    semua_wok = sorted(semua_wok_raw & wok_dikenal)

    HP_KEYS  = ["io", "re", "re_salah", "ps", "sf_home_id"]
    IOD_KEYS = ["total_io", "sf_active_io"]

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    wok_hp_now, wok_hp_prev, wok_iod = {}, {}, {}
    for wok in semua_wok:
        sub_hp_now  = df_hp_ini[df_hp_ini["wok"] == wok]   if not df_hp_ini.empty  else df_hp_ini
        sub_hp_prev = df_hp_lalu[df_hp_lalu["wok"] == wok] if not df_hp_lalu.empty else df_hp_lalu
        sub_iod     = df_iod[df_iod["wok"] == wok]         if not df_iod.empty     else df_iod

        base_hp_now  = _base_counts_homepass(sub_hp_now,  awal_ini,  tgl_closing)
        base_hp_prev = _base_counts_homepass(sub_hp_prev, awal_lalu, akhir_lalu)
        base_iod     = _base_counts_iod(sub_iod)

        wok_hp_now[wok]  = base_hp_now
        wok_hp_prev[wok] = base_hp_prev
        wok_iod[wok]     = base_iod

        wok_rows.append({
            "level": "WOK", "name": wok, "branch": branch_of(wok),
            **_derived(base_hp_now, base_hp_prev, base_iod),
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    branch_rows = []
    for branch in branch_names:
        member_woks = [r["name"] for r in wok_rows if r["branch"] == branch]
        if not member_woks:
            continue
        base_hp_now  = _sum_counts([wok_hp_now[w]  for w in member_woks], HP_KEYS)
        base_hp_prev = _sum_counts([wok_hp_prev[w] for w in member_woks], HP_KEYS)
        base_iod     = _sum_counts([wok_iod[w]     for w in member_woks], IOD_KEYS)
        branch_rows.append({
            "level": "BRANCH", "name": branch,
            **_derived(base_hp_now, base_hp_prev, base_iod),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    reg_hp_now  = _sum_counts(list(wok_hp_now.values()),  HP_KEYS)
    reg_hp_prev = _sum_counts(list(wok_hp_prev.values()), HP_KEYS)
    reg_iod     = _sum_counts(list(wok_iod.values()),     IOD_KEYS)
    reg_row = {
        "level": "REGION", "name": REGION_NAME,
        **_derived(reg_hp_now, reg_hp_prev, reg_iod),
    }

    top_alerts = {
        "branch": {
            "pct_io_top":    _top(branch_rows,    "pct_io_home_id"),
            "pct_io_bottom": _bottom(branch_rows, "pct_io_home_id"),
            "pct_sf_top":    _top(branch_rows,    "pct_sf_home_id"),
            "pct_sf_bottom": _bottom(branch_rows, "pct_sf_home_id"),
        },
        "wok": {
            "pct_io_top":    _top(wok_rows,    "pct_io_home_id"),
            "pct_io_bottom": _bottom(wok_rows, "pct_io_home_id"),
            "pct_sf_top":    _top(wok_rows,    "pct_sf_home_id"),
            "pct_sf_bottom": _bottom(wok_rows, "pct_sf_home_id"),
        },
    }

    return {
        "tgl_closing": tgl_closing,
        "bi_label"   : tgl_closing.strftime("%B %Y"),
        "tgl_label"  : f"{tgl_closing.day} {BULAN_ID[tgl_closing.month]} {tgl_closing.year}",
        "region"     : reg_row,
        "branches"   : branch_rows,
        "woks"       : wok_rows,
        "top_alerts" : top_alerts,
    }


def hitung_homepass_sto(tgl_closing: date, sumber: dict = None, wok_lama: bool = False) -> dict:
    """
    Sama seperti hitung_homepass(), tapi dipecah lebih detail per STO (di
    dalam tiap WOK) — supaya kelihatan STO mana yang adoption Home ID-nya
    (%IO Home ID) paling tinggi/rendah. STO diurutkan descending berdasar
    %IO Home ID di dalam tiap WOK (paling tinggi paling atas, paling rendah
    paling bawah). WOK/Branch/Region tetap dihitung (dipakai untuk
    sto_rank_by_branch — top3/bottom3 STO per branch — bukan buat ditampilkan
    sebagai baris subtotal di gambar).
    `sumber` = hasil load_sumber() (opsional) supaya query berat tidak diulang.
    Return dict siap pakai untuk renderer_homepass.render_homepass_sto().
    """
    WOK_TO_BRANCH, WOK_ORDER = _acuan_wok(wok_lama)
    s = sumber or load_sumber(tgl_closing, wok_lama)
    awal_ini, awal_lalu, akhir_lalu = s["awal_ini"], s["awal_lalu"], s["akhir_lalu"]
    df_hp_ini, df_hp_lalu, df_iod = s["df_hp_ini"], s["df_hp_lalu"], s["df_iod"]

    def branch_of(wok: str) -> str:
        return WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )

    semua_wok_raw = (
        set(df_hp_ini["wok"].unique()  if not df_hp_ini.empty  else []) |
        set(df_hp_lalu["wok"].unique() if not df_hp_lalu.empty else []) |
        set(df_iod["wok"].unique()     if not df_iod.empty     else [])
    )
    wok_dikenal = {w.upper() for w in WOK_ORDER}
    wok_asing   = semua_wok_raw - wok_dikenal
    if wok_asing:
        logger.warning(f"[homepass_sto] WOK tidak dikenal, dilewati: {sorted(wok_asing)}")
    semua_wok = sorted(semua_wok_raw & wok_dikenal)

    HP_KEYS  = ["io", "re", "re_salah", "ps", "sf_home_id"]
    IOD_KEYS = ["total_io", "sf_active_io"]

    sto_rows = []
    wok_rows = []
    wok_hp_now, wok_hp_prev, wok_iod = {}, {}, {}
    for wok in semua_wok:
        sub_hp_now_w  = df_hp_ini[df_hp_ini["wok"] == wok]   if not df_hp_ini.empty  else df_hp_ini
        sub_hp_prev_w = df_hp_lalu[df_hp_lalu["wok"] == wok] if not df_hp_lalu.empty else df_hp_lalu
        sub_iod_w     = df_iod[df_iod["wok"] == wok]         if not df_iod.empty     else df_iod

        stos = sorted(
            set(sub_hp_now_w["sto_co"].unique()  if not sub_hp_now_w.empty  else []) |
            set(sub_hp_prev_w["sto_co"].unique() if not sub_hp_prev_w.empty else []) |
            set(sub_iod_w["sto_co"].unique()     if not sub_iod_w.empty     else [])
        )

        base_now_list, base_prev_list, base_iod_list = [], [], []
        wok_sto_rows = []
        for sto in stos:
            sub_hp_now  = sub_hp_now_w[sub_hp_now_w["sto_co"] == sto]   if not sub_hp_now_w.empty  else sub_hp_now_w
            sub_hp_prev = sub_hp_prev_w[sub_hp_prev_w["sto_co"] == sto] if not sub_hp_prev_w.empty else sub_hp_prev_w
            sub_iod     = sub_iod_w[sub_iod_w["sto_co"] == sto]         if not sub_iod_w.empty     else sub_iod_w

            base_hp_now  = _base_counts_homepass(sub_hp_now,  awal_ini,  tgl_closing)
            base_hp_prev = _base_counts_homepass(sub_hp_prev, awal_lalu, akhir_lalu)
            base_iod     = _base_counts_iod(sub_iod)

            base_now_list.append(base_hp_now)
            base_prev_list.append(base_hp_prev)
            base_iod_list.append(base_iod)

            wok_sto_rows.append({
                "level": "STO", "name": sto, "wok": wok, "branch": branch_of(wok),
                **_derived(base_hp_now, base_hp_prev, base_iod),
            })

        # Baris STO "-" (sto_co NULL/kosong di sumber data) tidak ditampilkan —
        # bukan STO beneran, cuma order yang tidak ter-tag STO. Totalnya tetap
        # ikut terhitung di agregat WOK/Branch/Region di bawah.
        wok_sto_rows = [r for r in wok_sto_rows if r["name"] != "-"]

        # Paling tinggi %IO Home ID di atas, paling rendah di bawah; None
        # (data kosong) ditaruh paling bawah.
        wok_sto_rows.sort(
            key=lambda r: (r["pct_io_home_id"] is None, -(r["pct_io_home_id"] or 0))
        )
        sto_rows.append({"wok": wok, "branch": branch_of(wok), "stos": wok_sto_rows})

        base_hp_now_wok  = _sum_counts(base_now_list,  HP_KEYS)
        base_hp_prev_wok = _sum_counts(base_prev_list, HP_KEYS)
        base_iod_wok     = _sum_counts(base_iod_list,  IOD_KEYS)
        wok_hp_now[wok]  = base_hp_now_wok
        wok_hp_prev[wok] = base_hp_prev_wok
        wok_iod[wok]     = base_iod_wok
        wok_rows.append({
            "level": "WOK", "name": wok, "branch": branch_of(wok),
            **_derived(base_hp_now_wok, base_hp_prev_wok, base_iod_wok),
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)
    sto_rows.sort(key=lambda g: wok_up.index(g["wok"]) if g["wok"] in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    branch_rows = []
    for branch in branch_names:
        member_woks = [r["name"] for r in wok_rows if r["branch"] == branch]
        if not member_woks:
            continue
        base_hp_now  = _sum_counts([wok_hp_now[w]  for w in member_woks], HP_KEYS)
        base_hp_prev = _sum_counts([wok_hp_prev[w] for w in member_woks], HP_KEYS)
        base_iod     = _sum_counts([wok_iod[w]     for w in member_woks], IOD_KEYS)
        branch_rows.append({
            "level": "BRANCH", "name": branch,
            **_derived(base_hp_now, base_hp_prev, base_iod),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    reg_hp_now  = _sum_counts(list(wok_hp_now.values()),  HP_KEYS)
    reg_hp_prev = _sum_counts(list(wok_hp_prev.values()), HP_KEYS)
    reg_iod     = _sum_counts(list(wok_iod.values()),     IOD_KEYS)
    reg_row = {
        "level": "REGION", "name": REGION_NAME,
        **_derived(reg_hp_now, reg_hp_prev, reg_iod),
    }

    # ── Top 3 / Bottom 3 STO %IO Home ID per BRANCH ──────────────────────────
    branch_sto = {}
    for group in sto_rows:
        branch_sto.setdefault(group["branch"], []).extend(group["stos"])

    sto_rank_by_branch = {}
    for branch in branch_names:
        valid = [r for r in branch_sto.get(branch, []) if r.get("pct_io_home_id") is not None]
        sto_rank_by_branch[branch] = {
            "top3":    sorted(valid, key=lambda r: r["pct_io_home_id"], reverse=True)[:3],
            "bottom3": sorted(valid, key=lambda r: r["pct_io_home_id"])[:3],
        }

    return {
        "tgl_closing": tgl_closing,
        "bi_label"   : tgl_closing.strftime("%B %Y"),
        "tgl_label"  : f"{tgl_closing.day} {BULAN_ID[tgl_closing.month]} {tgl_closing.year}",
        "region"     : reg_row,
        "branches"   : branch_rows,
        "woks"       : wok_rows,
        "sto_groups" : sto_rows,
        "sto_rank_by_branch": sto_rank_by_branch,
    }


def export_raw_csv(tgl_closing: date, sumber: dict = None, wok_lama: bool = False) -> tuple:
    """
    Export data mentah (row-level, belum diagregasi) dari 2 sumber yang dipakai
    Homepass Report, supaya bisa dicek manual:
    - homepass_raw_*.csv   : hasil db.query_homepass() (homepass_sales JOIN
                              indihome_ordering_detail) — bulan ini + bulan lalu
    - iod_agency_raw_*.csv : hasil db.query_iod_io() (indihome_ordering_detail
                              langsung, channel AGENCY) — MtD bulan ini saja

    `sumber` = hasil load_sumber() (opsional) supaya query berat tidak diulang.
    Return (zip_bytes, zip_filename).
    """
    import io
    import zipfile

    s = sumber or load_sumber(tgl_closing, wok_lama)
    rows_hp  = s["rows_hp_ini"]
    rows_iod = s["rows_iod"]

    if not rows_hp and not rows_iod:
        raise ValueError("Tidak ada data untuk diekspor")

    def _to_csv_bytes(rows: list) -> bytes:
        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("0000-00-00 00:00:00")
            elif col.endswith("_ts") and df[col].dtype == object:
                df[col] = df[col].fillna("0000-00-00 00:00:00")
        df = df.replace({"NaT": "0000-00-00 00:00:00"})
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8-sig")
        return buf.getvalue().encode("utf-8-sig")

    tgl_str = tgl_closing.strftime("%Y%m%d")
    name_hp  = f"homepass_raw_JATENGDIY_{tgl_str}.csv"
    name_iod = f"iod_agency_raw_JATENGDIY_{tgl_str}.csv"

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name_hp,  _to_csv_bytes(rows_hp))
        zf.writestr(name_iod, _to_csv_bytes(rows_iod))
    zip_buf.seek(0)

    zip_name = f"homepass_raw_{tgl_str}.zip"
    logger.info(
        f"Export raw homepass selesai: {len(rows_hp)} baris homepass_joined, "
        f"{len(rows_iod)} baris iod_agency -> {zip_name}"
    )
    return zip_buf.read(), zip_name
