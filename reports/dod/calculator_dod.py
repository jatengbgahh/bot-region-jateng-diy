"""
calculator_dod.py — Kalkulasi PS harian & %DoD (Day over Day) per BRANCH/WOK.

PS  = order dengan ps_ts valid (bukan NULL / '0000-00-00'),
      order_type = 'NEW SALES', package_cat <> 'HWA' (exclude produk
      hardware/Orbit — bukan product_commercial_name, itu tidak pernah
      berisi literal 'HWA'), product_commercial_name TIDAK mengandung
      'WIRELESS' (exclude, filter terpisah — lihat db.query_ps_daily).
%DoD tanggal-n = (PS[n] - PS[n-1]) / PS[n-1] * 100.
Tanggal 1 dibandingkan dengan tanggal terakhir bulan sebelumnya (di-query terpisah
dari tabel bulan sebelumnya, karena 1 tabel per bulan).

Kolom tanggal yang dihasilkan hanya 1 s/d tgl_closing.day (bukan 1 bulan penuh),
supaya tabel tidak terlalu panjang.
"""

import pandas as pd
from calendar import monthrange
from datetime import date, timedelta

import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Urutan & label baris breakdown produk (all territory JATENG-DIY)
PRODUCT_ORDER = ["IH REGULER", "EZNET", "TSEL ONE"]

# Whitelist CITY untuk report DoD Performance FMC City (report 3).
# Hanya 25 kabupaten/kota ini yang ditampilkan, dengan urutan & pengelompokan
# BRANCH persis seperti gambar (bukan diambil dinamis dari data).
# Nama city ditulis Title Case supaya cocok dengan df["kabupaten"] (.str.title()).
CITY_WHITELIST = [
    ("MAGELANG",   "Kebumen"),
    ("MAGELANG",   "Kota Magelang"),
    ("PEKALONGAN", "Batang"),
    ("PEKALONGAN", "Brebes"),
    ("PEKALONGAN", "Kota Pekalongan"),
    ("PEKALONGAN", "Kota Tegal"),
    ("PEKALONGAN", "Pekalongan"),
    ("PEKALONGAN", "Pemalang"),
    ("PEKALONGAN", "Tegal"),
    ("PURWOKERTO", "Banjarnegara"),
    ("PURWOKERTO", "Purbalingga"),   # pindah dari PEKALONGAN: struktur WOK baru (lihat wilayah.py)
    ("PURWOKERTO", "Cilacap"),
    ("SEMARANG",   "Jepara"),
    ("SEMARANG",   "Kendal"),
    ("SEMARANG",   "Kota Salatiga"),
    ("SEMARANG",   "Kota Semarang"),
    ("SEMARANG",   "Kudus"),
    ("SURAKARTA",  "Blora"),
    ("SURAKARTA",  "Boyolali"),
    ("SURAKARTA",  "Grobogan"),
    ("SURAKARTA",  "Klaten"),
    ("SURAKARTA",  "Kota Surakarta"),
    ("SURAKARTA",  "Sragen"),
    ("YOGYAKARTA", "Kulon Progo"),
    ("YOGYAKARTA", "Sleman"),
]


def _classify_product(name) -> str:
    """
    Tsel One   = product_commercial_name mengandung "one"
    EZnet      = product_commercial_name mengandung "eznet"
    IH reguler = sisanya
    """
    n = str(name or "").strip().lower()
    if "one" in n:
        return "TSEL ONE"
    if "eznet" in n:
        return "EZNET"
    return "IH REGULER"


def _pct_dod(cur: int, prev: int):
    if prev and prev > 0:
        return round((cur - prev) / prev * 100, 1)
    return None


def hitung_dod(tgl_closing: date, full_month: bool = False) -> dict:
    """
    Hitung PS harian (angka) & %DoD per WOK, per BRANCH (agregat WOK), grand
    total JATENG-DIY, dan breakdown PRODUK (all territory).
    Return dict siap pakai untuk renderer_dod.render_dod_count() / render_dod_pct().

    full_month=False (default): kolom tanggal hanya 1 s/d tgl_closing.day.
    full_month=True: kolom tanggal 1 s/d akhir bulan (tabel selalu selebar 1
    bulan penuh, lebar kolom tidak berubah tiap hari), tapi tanggal setelah
    tgl_closing tetap dikosongkan ("-") karena datanya memang belum ada —
    bukan 0. `hari_efektif` (hari terakhir yang punya data) disertakan di
    hasil supaya renderer tahu hari mana yang jadi acuan kolom %DoD ringkas
    (bukan ikut kolom tanggal terakhir kalau itu masih hari yang belum lewat).
    """
    awal_bulan   = tgl_closing.replace(day=1)
    hari_prev    = awal_bulan - timedelta(days=1)   # tanggal terakhir bulan sebelumnya
    hari_efektif = tgl_closing.day                  # hari terakhir yang punya data valid
    if full_month:
        n_days = monthrange(tgl_closing.year, tgl_closing.month)[1]
    else:
        n_days = hari_efektif

    rows      = db.query_ps_daily(awal_bulan, tgl_closing)
    rows_prev = db.query_ps_daily(hari_prev, hari_prev)   # pembanding %DoD tanggal 1
    df   = pd.DataFrame(rows + rows_prev)
    if not df.empty:
        df["wok"]      = df["wok"].str.strip().str.upper()
        df["branch"]   = df["branch"].str.strip().str.upper()
        df["ps_date"]  = pd.to_datetime(df["ps_date"]).dt.date
        df["ps_count"] = pd.to_numeric(df["ps_count"], errors="coerce").fillna(0).astype(int)

    def counts_for(wok: str) -> dict:
        if df.empty:
            return {}
        sub = df[df["wok"] == wok]
        return dict(zip(sub["ps_date"], sub["ps_count"]))

    def daily_count(counts_list: list) -> dict:
        """counts_list: list of {date: count} dicts yang dijumlahkan per tanggal."""
        out = {}
        for d in range(1, n_days + 1):
            if d > hari_efektif:
                out[d] = None   # belum lewat / belum ada data, bukan 0
                continue
            cur_date = date(tgl_closing.year, tgl_closing.month, d)
            out[d] = sum(c.get(cur_date, 0) for c in counts_list)
        return out

    def daily_pct(counts_list: list) -> dict:
        """counts_list: list of {date: count} dicts yang dijumlahkan per tanggal."""
        out = {}
        for d in range(1, n_days + 1):
            if d > hari_efektif:
                out[d] = None
                continue
            if d == 1:
                cur_date  = date(tgl_closing.year, tgl_closing.month, 1)
                prev = sum(c.get(hari_prev, 0) for c in counts_list)
                cur  = sum(c.get(cur_date, 0)  for c in counts_list)
                out[d] = _pct_dod(cur, prev)
                continue
            cur_date  = date(tgl_closing.year, tgl_closing.month, d)
            prev_date = date(tgl_closing.year, tgl_closing.month, d - 1)
            cur  = sum(c.get(cur_date, 0)  for c in counts_list)
            prev = sum(c.get(prev_date, 0) for c in counts_list)
            out[d] = _pct_dod(cur, prev)
        return out

    # ── Baris WOK ────────────────────────────────────────────────────────────
    wok_rows = []
    for wok in WOK_ORDER:
        branch = WOK_TO_BRANCH.get(wok, "LAINNYA")
        counts = counts_for(wok)
        wok_rows.append({
            "name"       : wok,
            "branch"     : branch,
            "counts"     : counts,
            "count_daily": daily_count([counts]),
            "daily"      : daily_pct([counts]),
        })

    # ── Baris ringkasan BRANCH (agregat WOK anggotanya) ─────────────────────
    branch_rows = []
    for branch in BRANCH_ORDER:
        members = [w["counts"] for w in wok_rows if w["branch"] == branch]
        branch_rows.append({
            "name"       : branch,
            "count_daily": daily_count(members),
            "daily"      : daily_pct(members),
        })

    # ── Grand total JATENG-DIY ────────────────────────────────────────────────
    all_counts = [w["counts"] for w in wok_rows]
    total = {
        "name"       : REGION_NAME,
        "count_daily": daily_count(all_counts),
        "daily"      : daily_pct(all_counts),
    }

    # ── Breakdown PRODUK (all territory, digabung seluruh WOK) ──────────────
    rows_prod      = db.query_ps_daily_by_product(awal_bulan, tgl_closing)
    rows_prod_prev = db.query_ps_daily_by_product(hari_prev, hari_prev)
    df_prod   = pd.DataFrame(rows_prod + rows_prod_prev)
    if not df_prod.empty:
        df_prod["ps_date"]  = pd.to_datetime(df_prod["ps_date"]).dt.date
        df_prod["ps_count"] = pd.to_numeric(df_prod["ps_count"], errors="coerce").fillna(0).astype(int)
        df_prod["category"] = df_prod["product_commercial_name"].apply(_classify_product)

    def counts_for_category(cat: str) -> dict:
        if df_prod.empty:
            return {}
        sub = df_prod[df_prod["category"] == cat]
        return sub.groupby("ps_date")["ps_count"].sum().to_dict()

    product_rows = []
    product_counts_all = []
    for cat in PRODUCT_ORDER:
        counts = counts_for_category(cat)
        product_counts_all.append(counts)
        product_rows.append({
            "name"       : cat,
            "count_daily": daily_count([counts]),
            "daily"      : daily_pct([counts]),
        })

    product_total = {
        "name"       : REGION_NAME,
        "count_daily": daily_count(product_counts_all),
        "daily"      : daily_pct(product_counts_all),
    }

    return {
        "tgl_closing"  : tgl_closing,
        "bulan_label"  : f"{BULAN_ID[tgl_closing.month]} {tgl_closing.year}",
        "n_days"       : n_days,
        "hari_efektif" : hari_efektif,
        "woks"         : wok_rows,
        "branches"     : branch_rows,
        "total"        : total,
        "products"     : product_rows,
        "product_total": product_total,
    }


def hitung_dod_city(tgl_closing: date) -> dict:
    """
    Report 3 — PS harian & %DoD per CITY (kabupaten). HANYA 25 city whitelist
    (CITY_WHITELIST) yang ditampilkan, urutan & grup BRANCH persis seperti
    gambar. Ringkasan per BRANCH TIDAK ditampilkan — setelah baris city langsung
    grand total JATENG-DIY lalu breakdown PRODUK (all territory, untuk grafik),
    supaya layout-nya tetap seperti report 1 (render_dod_count).

    Definisi PS & %DoD identik dengan hitung_dod (NEW SALES, exclude HWA).
    Baris city dikemas pada key "woks" agar bisa langsung dipakai renderer_dod
    yang sama.
    """
    awal_bulan = tgl_closing.replace(day=1)
    n_days     = tgl_closing.day

    rows = db.query_ps_daily_by_city(awal_bulan, tgl_closing)
    df   = pd.DataFrame(rows)
    if not df.empty:
        df["branch"]    = df["branch"].astype(str).str.strip().str.upper()
        df["kabupaten"] = df["kabupaten"].astype(str).str.strip().str.upper().str.title()
        df["ps_date"]   = pd.to_datetime(df["ps_date"]).dt.date
        df["ps_count"]  = pd.to_numeric(df["ps_count"], errors="coerce").fillna(0).astype(int)

    def counts_for_city(city: str) -> dict:
        if df.empty:
            return {}
        sub = df[df["kabupaten"] == city]
        return dict(zip(sub["ps_date"], sub["ps_count"]))

    def daily_count(counts_list: list) -> dict:
        out = {}
        for d in range(1, n_days + 1):
            cur_date = date(tgl_closing.year, tgl_closing.month, d)
            out[d] = sum(c.get(cur_date, 0) for c in counts_list)
        return out

    def daily_pct(counts_list: list) -> dict:
        out = {}
        for d in range(1, n_days + 1):
            if d == 1:
                out[d] = None
                continue
            cur_date  = date(tgl_closing.year, tgl_closing.month, d)
            prev_date = date(tgl_closing.year, tgl_closing.month, d - 1)
            cur  = sum(c.get(cur_date, 0)  for c in counts_list)
            prev = sum(c.get(prev_date, 0) for c in counts_list)
            out[d] = _pct_dod(cur, prev)
        return out

    # ── Baris CITY: HANYA whitelist (25 city), urutan & grup BRANCH persis
    #    seperti gambar. City di luar whitelist tidak ditampilkan. ─────────────
    city_rows = []
    for branch, city in CITY_WHITELIST:
        counts = counts_for_city(city)
        city_rows.append({
            "name"       : city,
            "branch"     : branch,
            "counts"     : counts,
            "count_daily": daily_count([counts]),
            "daily"      : daily_pct([counts]),
        })

    # ── Ringkasan per BRANCH TIDAK ditampilkan (permintaan): langsung product ──
    branch_rows = []

    # ── Grand total JATENG-DIY = seluruh territory (all city), supaya angkanya
    #    konsisten dengan baris total PRODUCT di bawahnya. ──────────────────────
    if df.empty:
        region_counts = {}
    else:
        region_counts = df.groupby("ps_date")["ps_count"].sum().to_dict()
    total = {
        "name"       : REGION_NAME,
        "count_daily": daily_count([region_counts]),
        "daily"      : daily_pct([region_counts]),
    }

    # ── Breakdown PRODUK (all territory) untuk grafik — sama dgn report 1 ─────
    rows_prod = db.query_ps_daily_by_product(awal_bulan, tgl_closing)
    df_prod   = pd.DataFrame(rows_prod)
    if not df_prod.empty:
        df_prod["ps_date"]  = pd.to_datetime(df_prod["ps_date"]).dt.date
        df_prod["ps_count"] = pd.to_numeric(df_prod["ps_count"], errors="coerce").fillna(0).astype(int)
        df_prod["category"] = df_prod["product_commercial_name"].apply(_classify_product)

    def counts_for_category(cat: str) -> dict:
        if df_prod.empty:
            return {}
        sub = df_prod[df_prod["category"] == cat]
        return sub.groupby("ps_date")["ps_count"].sum().to_dict()

    product_rows = []
    product_counts_all = []
    for cat in PRODUCT_ORDER:
        counts = counts_for_category(cat)
        product_counts_all.append(counts)
        product_rows.append({
            "name"       : cat,
            "count_daily": daily_count([counts]),
            "daily"      : daily_pct([counts]),
        })

    product_total = {
        "name"       : REGION_NAME,
        "count_daily": daily_count(product_counts_all),
        "daily"      : daily_pct(product_counts_all),
    }

    return {
        "tgl_closing"  : tgl_closing,
        "bulan_label"  : f"{BULAN_ID[tgl_closing.month]} {tgl_closing.year}",
        "n_days"       : n_days,
        "woks"         : city_rows,      # baris city dipakai sebagai baris utama
        "branches"     : branch_rows,
        "total"        : total,
        "products"     : product_rows,
        "product_total": product_total,
    }


def hitung_dod_city_product(tgl_closing: date) -> dict:
    """
    Report DoD FMC City — dibreakdown PER CITY sekaligus PER PAKET dalam 1 tabel.
    Tiap city (25 whitelist) dipecah jadi 3 baris kategori paket:
    IH REGULER / EZNET / TSEL ONE. %DoD dihitung per baris (per city per paket).

    Grand total JATENG-DIY juga dipecah per paket (jumlah 25 city whitelist),
    dan disediakan `chart_products` (total harian per paket, all 25 city) untuk
    grafik stacked bar di atas tabel.
    """
    awal_bulan = tgl_closing.replace(day=1)
    n_days     = tgl_closing.day

    rows = db.query_ps_daily_by_city_product(awal_bulan, tgl_closing)
    df   = pd.DataFrame(rows)
    if not df.empty:
        df["kabupaten"] = df["kabupaten"].astype(str).str.strip().str.upper().str.title()
        df["ps_date"]   = pd.to_datetime(df["ps_date"]).dt.date
        df["ps_count"]  = pd.to_numeric(df["ps_count"], errors="coerce").fillna(0).astype(int)
        df["category"]  = df["product_commercial_name"].apply(_classify_product)

    def counts_city_cat(city: str, cat: str) -> dict:
        """{date: count} PS untuk city + kategori paket tertentu."""
        if df.empty:
            return {}
        sub = df[(df["kabupaten"] == city) & (df["category"] == cat)]
        return sub.groupby("ps_date")["ps_count"].sum().to_dict()

    def daily_count(counts_list: list) -> dict:
        out = {}
        for d in range(1, n_days + 1):
            cur_date = date(tgl_closing.year, tgl_closing.month, d)
            out[d] = sum(c.get(cur_date, 0) for c in counts_list)
        return out

    def daily_pct(counts_list: list) -> dict:
        out = {}
        for d in range(1, n_days + 1):
            if d == 1:
                out[d] = None
                continue
            cur_date  = date(tgl_closing.year, tgl_closing.month, d)
            prev_date = date(tgl_closing.year, tgl_closing.month, d - 1)
            cur  = sum(c.get(cur_date, 0)  for c in counts_list)
            prev = sum(c.get(prev_date, 0) for c in counts_list)
            out[d] = _pct_dod(cur, prev)
        return out

    # ── Baris CITY × PAKET (25 city whitelist, tiap city 3 baris paket) ───────
    city_blocks     = []
    cat_counts_all  = {cat: [] for cat in PRODUCT_ORDER}   # utk grand total per paket
    for branch, city in CITY_WHITELIST:
        prod_rows = []
        for cat in PRODUCT_ORDER:
            counts = counts_city_cat(city, cat)
            cat_counts_all[cat].append(counts)
            prod_rows.append({
                "product"    : cat,
                "counts"     : counts,
                "count_daily": daily_count([counts]),
                "daily"      : daily_pct([counts]),
            })
        city_blocks.append({
            "branch"   : branch,
            "city"     : city,
            "products" : prod_rows,
        })

    # ── Grand total JATENG-DIY per paket (jumlah 25 city) ────────────────────
    total_products = []
    for cat in PRODUCT_ORDER:
        total_products.append({
            "product"    : cat,
            "count_daily": daily_count(cat_counts_all[cat]),
            "daily"      : daily_pct(cat_counts_all[cat]),
        })

    # ── Data grafik: total harian per paket (all 25 city) ────────────────────
    chart_products = [
        {"name": cat, "count_daily": daily_count(cat_counts_all[cat])}
        for cat in PRODUCT_ORDER
    ]

    return {
        "tgl_closing"   : tgl_closing,
        "bulan_label"   : f"{BULAN_ID[tgl_closing.month]} {tgl_closing.year}",
        "n_days"        : n_days,
        "city_blocks"   : city_blocks,
        "total_products": total_products,
        "chart_products": chart_products,
    }
