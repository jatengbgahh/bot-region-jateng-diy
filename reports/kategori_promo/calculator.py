"""
reports/kategori_promo/calculator.py — Kalkulasi Sales (PS) by Kategori Promo Paket IndiHome.
Source & filter PS SAMA dengan reports/kategori_paket/calculator.py (db.query_ps_by_wok_product);
bedanya Tsel One dan EZnet dipecah jadi biasa vs promo.

Kategori (dicek berurutan, nama produk = product_commercial_name, case-insensitive):
  Tsel One Promo = mengandung "dynamic" DAN "promo"
  Tsel One       = mengandung "dynamic" (tanpa "promo")
  EZnet Promo    = mengandung "eznet" DAN "promo"
  EZnet          = mengandung "eznet" (tanpa "promo")
  IH Reguler     = sisanya (termasuk yg mengandung "promo" tapi bukan dynamic/eznet)

Metrik per kategori per WOK/Branch/Region:
  MtD      = jumlah PS bulan berjalan
  MoM      = growth MtD vs MtD bulan lalu (tanggal yg sama)
  Cont     = kontribusi kategori thd total PS baris tsb (MtD) * 100
  MoM Cont = selisih (pp) Cont bulan M dikurangi Cont bulan M-1
"""

import calendar
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

CATEGORIES = ["TSEL_ONE", "TSEL_ONE_PROMO", "EZNET", "EZNET_PROMO", "IH_REGULER"]
CATEGORY_LABEL = {
    "TSEL_ONE"      : "Tsel One",
    "TSEL_ONE_PROMO": "Tsel One Promo",
    "EZNET"         : "EZnet",
    "EZNET_PROMO"   : "EZnet Promo",
    "IH_REGULER"    : "IH Reguler",
}


def _classify(name) -> str:
    n = str(name or "").strip().lower()
    promo = "promo" in n
    if "dynamic" in n:
        return "TSEL_ONE_PROMO" if promo else "TSEL_ONE"
    if "eznet" in n:
        return "EZNET_PROMO" if promo else "EZNET"
    return "IH_REGULER"


def _growth(cur, prev):
    if prev:
        return round((cur - prev) / prev * 100, 1)
    return None


def hitung_kategori_promo(tgl_closing: date) -> dict:
    """Return dict siap pakai untuk renderer.render_kategori_promo()."""
    # ── Rentang tanggal (identik dgn calculator_kategori_paket) ────────────
    awal_ini = tgl_closing.replace(day=1)

    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max   = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_max_ini = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]
    if tgl_closing.day == hari_max_ini:
        hari_mtd = hari_max
    else:
        hari_mtd = min(tgl_closing.day, hari_max)
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month, hari_mtd)

    rows_ini  = db.query_ps_by_wok_product(awal_ini,  tgl_closing)
    rows_lalu = db.query_ps_by_wok_product(awal_lalu, akhir_lalu)

    return hitung_dari_rows(rows_ini, rows_lalu, tgl_closing, bulan_lalu)


def hitung_dari_rows(rows_ini: list, rows_lalu: list, tgl_closing: date, bulan_lalu: date) -> dict:
    """Bagian murni (tanpa DB): agregasi rows query -> dict renderer. Dipisah supaya bisa dites."""

    def prep(rows: list[dict]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["wok"]      = df["wok"].fillna("").astype(str).str.strip().str.upper()
        df["branch"]   = df["branch"].fillna("").astype(str).str.strip().str.upper()
        df["ps_count"] = pd.to_numeric(df["ps_count"], errors="coerce").fillna(0).astype(int)
        df["category"] = df["product_commercial_name"].apply(_classify)
        return df

    df_ini  = prep(rows_ini)
    df_lalu = prep(rows_lalu)

    def agg(df: pd.DataFrame) -> dict:
        """{wok: {"total": n, <kategori>: n, ...}}"""
        if df.empty:
            return {}
        result = {}
        for wok, grp in df.groupby("wok"):
            d = {"total": int(grp["ps_count"].sum())}
            for cat in CATEGORIES:
                d[cat] = int(grp[grp["category"] == cat]["ps_count"].sum())
            result[wok] = d
        return result

    agg_ini  = agg(df_ini)
    agg_lalu = agg(df_lalu)

    semua_wok = (set(agg_ini.keys()) | set(agg_lalu.keys()) |
                 {w.upper() for w in WOK_ORDER})
    semua_wok.discard("")

    def make_metrics(woks_list: list) -> tuple[dict, int]:
        def _sum(a, key):
            return sum(a.get(w, {}).get(key, 0) for w in woks_list)

        tot_i = _sum(agg_ini,  "total")
        tot_l = _sum(agg_lalu, "total")

        cats = {}
        for cat in CATEGORIES:
            ci = _sum(agg_ini,  cat)
            cl = _sum(agg_lalu, cat)
            cont_i = round(ci / tot_i * 100, 1) if tot_i else None
            cont_l = round(cl / tot_l * 100, 1) if tot_l else None
            cats[cat] = {
                "mtd"     : ci,
                "mom"     : _growth(ci, cl),
                "cont"    : cont_i,
                # selisih poin persentase (pp), BUKAN growth
                "mom_cont": round(cont_i - cont_l, 1) if cont_i is not None and cont_l is not None else None,
            }
        return cats, tot_i

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        canon  = next((w for w in WOK_ORDER if w.upper() == wok), wok)
        branch = WOK_TO_BRANCH.get(canon, "LAINNYA")
        cats, tot_i = make_metrics([wok])
        wok_rows.append({
            "level": "WOK", "name": canon, "branch": branch,
            "categories": cats, "total": tot_i,
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"].upper()) if r["name"].upper() in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    for branch in branch_names:
        bwoks = [r["name"].upper() for r in wok_rows if r["branch"] == branch]
        if not bwoks:
            continue
        cats, tot_i = make_metrics(bwoks)
        branch_rows.append({
            "level": "BRANCH", "name": branch,
            "categories": cats, "total": tot_i,
        })

    # ── REGION row ────────────────────────────────────────────────────────
    cats, tot_i = make_metrics(list(semua_wok))
    region_row = {
        "level": "REGION", "name": REGION_NAME,
        "categories": cats, "total": tot_i,
    }

    return {
        "tgl_closing"    : tgl_closing,
        "bl_label"       : bulan_lalu.strftime("%b %Y").upper(),
        "bi_label"       : tgl_closing.strftime("%b %Y").upper(),
        "region"         : region_row,
        "branches"       : branch_rows,
        "woks"           : wok_rows,
        "category_order" : CATEGORIES,
        "category_label" : CATEGORY_LABEL,
    }
