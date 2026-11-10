"""
djp_homepass.py — ubah file "detail-homepass_*.xlsx" menjadi tabel DJP (format djp_daily_user_detailed)
untuk 5SO/7SO, karena tabel DJP bulan berjalan di DB belum terisi.

Definisi kunjungan (pilih lewat `definisi`):
  "checkout" (default, disepakati 27-10-2026): kolom "Journey Status" = CHECKOUT ("Bisa Ditemui").
  "terakhir" (26-10-2026): kolom "Kunjungan Terakhir" terisi.
Satu baris DJP = kombinasi unik (Kode SF, Tanggal, ODP). WOK diambil dari master SF (kode -> wok).
"""
import glob
import json
import os

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FOLDER_SCRAPING_DEFAULT = os.path.join(BASE_DIR, "storage", "sela")
LEGACY_SCRAPING_DIR = r"D:\Kerjaan\hasil gabungan data"


def _folder_scraping():
    """'folder_scraping' dari storage/state/rajawali_auto.json — sama dgn yang dipakai runner untuk scraping SELA."""
    try:
        p = os.path.join(BASE_DIR, "storage", "state", "rajawali_auto.json")
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f).get("folder_scraping") or FOLDER_SCRAPING_DEFAULT
    except Exception:
        return FOLDER_SCRAPING_DEFAULT


FOLDER_CARI = [
    os.path.join(os.path.expanduser("~"), "Downloads"),
    os.path.join(_folder_scraping(), "data", "results"),
]
for _extra in (
    os.path.join(FOLDER_SCRAPING_DEFAULT, "data", "results"),
    os.path.join(LEGACY_SCRAPING_DIR, "data", "results"),
):
    if all(os.path.normcase(x) != os.path.normcase(_extra) for x in FOLDER_CARI):
        FOLDER_CARI.append(_extra)


def cari_terbaru():
    """File detail-homepass terbaru (Downloads atau folder hasil generator)."""
    c = []
    for f in FOLDER_CARI:
        c += glob.glob(os.path.join(f, "**", "detail-homepass_*.xlsx"), recursive=True)
    return max(c, key=os.path.getmtime) if c else None


def cari_file(tgl=None):
    """File detail-homepass untuk tanggal laporan tgl: yang namanya berakhiran _sd_<YYYY-MM-DD>.xlsx (paling baru
    diubah bila ada beberapa); tanpa yang cocok -> yang terbaru. tgl None -> terbaru."""
    c = []
    for f in FOLDER_CARI:
        c += glob.glob(os.path.join(f, "**", "detail-homepass_*.xlsx"), recursive=True)
    if tgl is not None:
        cocok = [p for p in c if p.endswith(f"_sd_{tgl:%Y-%m-%d}.xlsx")]
        if cocok:
            return max(cocok, key=os.path.getmtime)
    return max(c, key=os.path.getmtime) if c else None


def wok_dari_export_sfo(path_sfo_csv):
    e = pd.read_csv(path_sfo_csv, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    rows = [json.loads(j) for j in e.j[(e.q == "sf_ini") & (e.j != "")]]
    return {r[0].strip().upper(): r[2] for r in rows}


DEFINISI = ("checkout", "terakhir")


def buat_csv_djp(path_xlsx, path_out, wok_map, definisi="checkout"):
    x = pd.read_excel(path_xlsx, dtype=str)
    if definisi == "checkout":
        v = x[x["Journey Status"].fillna("").str.strip().str.upper() == "CHECKOUT"]
    elif definisi == "terakhir":
        v = x[x["Kunjungan Terakhir"].notna()]
    else:
        raise ValueError(f"definisi DJP tidak dikenal: {definisi} (pilih {DEFINISI})")
    t = v.drop_duplicates(["Kode", "Tanggal", "ODP"])
    d = pd.DataFrame({"user_code": t.Kode.str.strip(),
                      "wok": t.Kode.str.strip().str.upper().map(wok_map).fillna(""),
                      "odp_name": t.ODP, "tugas_date": t.Tanggal})
    with open(path_out, "w", encoding="utf-8-sig", newline="") as f:
        f.write("sep=;\n")
        d.to_csv(f, sep=";", index=False)
    t_max = None if (x.empty or "Tanggal" not in x or pd.isna(x.Tanggal.max())) else str(x.Tanggal.max())
    return {"definisi": definisi, "baris_homepass": len(x), "tugas": len(d), "sf": d.user_code.nunique(),
            "odp": d.odp_name.nunique(), "tgl_max": t_max}


# ── DJP M1 dari file SELA bulan lalu (sejak Okt 2026 DJP = SELA) ───────────────
# Tabel djp_daily_user_detailed_YYYYMM tidak diisi lagi sejak Oktober 2026 (DJP pindah ke SELA): export
# djp_lalu 1-8 Okt hanya 2 baris -> SF Aktif DJP M1 = 1, ODP Visited M1 = 2 di /5so /7so (09-11-2026).
# M1 diambil dari file detail-homepass bulan lalu yang SUDAH ADA dari scraping sebelumnya (tidak scraping ulang),
# difilter ke tanggal M1, definisi kunjungan sama dengan MTD.
import re as _re
from datetime import date as _date

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "cache", "homepass_djp")
_POLA = _re.compile(r"detail-homepass_(\d{4}-\d{2}-\d{2})_sd_(\d{4}-\d{2}-\d{2})\.xlsx$", _re.I)


def cari_file_periode(awal, akhir):
    """File detail-homepass yang mencakup awal..akhir (mulai <= awal, s/d >= akhir). Pilih yang s/d-nya paling
    akhir (data paling lengkap), lalu yang paling baru diubah. None bila tidak ada (-> pakai tabel DB)."""
    c = []
    for f in FOLDER_CARI:
        for p in glob.glob(os.path.join(f, "**", "detail-homepass_*.xlsx"), recursive=True):
            m = _POLA.search(os.path.basename(p))
            if not m:
                continue
            a, b = _date.fromisoformat(m[1]), _date.fromisoformat(m[2])
            if a <= awal and b >= akhir:
                c.append((b, os.path.getmtime(p), p))
    return max(c)[2] if c else None


def _kunjungan(path_xlsx, definisi="checkout"):
    """Baris kunjungan unik (Kode, Tanggal, ODP) dari file homepass, di-cache sebagai CSV per file+definisi
    (dibuat ulang bila file xlsx lebih baru). Parse xlsx 13 MB ±1-2 menit, cache ±1 detik."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{os.path.splitext(os.path.basename(path_xlsx))[0]}_{definisi}.csv")
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(path_xlsx):
        return pd.read_csv(cache, dtype=str, keep_default_na=False)
    x = pd.read_excel(path_xlsx, dtype=str, usecols=lambda c: c in ("Kode", "Tanggal", "ODP", "Journey Status",
                                                                     "Kunjungan Terakhir"))
    if definisi == "checkout":
        v = x[x["Journey Status"].fillna("").str.strip().str.upper() == "CHECKOUT"]
    elif definisi == "terakhir":
        v = x[x["Kunjungan Terakhir"].notna()]
    else:
        raise ValueError(f"definisi DJP tidak dikenal: {definisi} (pilih {DEFINISI})")
    t = v.drop_duplicates(["Kode", "Tanggal", "ODP"])[["Kode", "Tanggal", "ODP"]].fillna("")
    t["Tanggal"] = t["Tanggal"].str[:10]
    tmp = f"{cache}.{os.getpid()}.tmp"
    t.to_csv(tmp, index=False, encoding="utf-8")
    os.replace(tmp, cache)
    return t


def buat_csv_djp_periode(path_xlsx, path_out, wok_map, awal, akhir, definisi="checkout"):
    """Seperti buat_csv_djp tapi hanya tanggal awal..akhir (untuk DJP M1 dari file SELA bulan lalu)."""
    t = _kunjungan(path_xlsx, definisi)
    t = t[(t.Tanggal >= f"{awal:%Y-%m-%d}") & (t.Tanggal <= f"{akhir:%Y-%m-%d}")]
    d = pd.DataFrame({"user_code": t.Kode.str.strip(),
                      "wok": t.Kode.str.strip().str.upper().map(wok_map).fillna(""),
                      "odp_name": t.ODP, "tugas_date": t.Tanggal})
    with open(path_out, "w", encoding="utf-8-sig", newline="") as f:
        f.write("sep=;\n")
        d.to_csv(f, sep=";", index=False)
    return {"file": os.path.basename(path_xlsx), "periode": f"{awal:%d-%m}..{akhir:%d-%m-%Y}", "tugas": len(d),
            "sf": d.user_code.nunique(), "odp": d.odp_name.nunique()}
