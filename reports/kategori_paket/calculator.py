"""
reports/kategori_paket/calculator.py — Kalkulasi Sales (PS) by Kategori Paket IndiHome
Source: indihome_ordering_detail_YYYYMM (query & filter PS sama seperti calculator_dod.py)

PS = order_id dengan ps_ts valid (bukan NULL / '0000-00-00'),
     order_type = 'NEW SALES', package_cat <> 'HWA' (exclude produk
     hardware/Orbit — bukan product_commercial_name, itu tidak pernah
     berisi literal 'HWA'), product_commercial_name TIDAK mengandung
     'WIRELESS' (exclude, filter terpisah — lihat db.query_ps_by_wok_product).

Kategori paket:
  Tsel One   = product_commercial_name mengandung "dynamic"
  EZnet      = product_commercial_name mengandung "eznet"
  IH Reguler = sisanya

Metrik per kategori per WOK/Branch/Region:
  MtD      = jumlah PS bulan berjalan
  MoM      = growth MtD vs MtD bulan lalu (tanggal yg sama)
  Cont     = kontribusi kategori thd total PS baris tsb (MtD) * 100
  MoM Cont = selisih (pp) Cont bulan M dikurangi Cont bulan M-1
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

CATEGORIES = ["TSEL_ONE", "EZNET", "IH_REGULER"]
CATEGORY_LABEL = {
    "TSEL_ONE"  : "Tsel One",
    "EZNET"     : "EZnet",
    "IH_REGULER": "IH Reguler",
}


def _classify(name) -> str:
    n = str(name or "").strip().lower()
    if "dynamic" in n:
        return "TSEL_ONE"
    if "eznet" in n:
        return "EZNET"
    return "IH_REGULER"


def _growth(cur, prev):
    if prev:
        return round((cur - prev) / prev * 100, 1)
    return None


def hitung_kategori_paket(tgl_closing: date) -> dict:
    """
    Return dict siap pakai untuk renderer.render_kategori_paket().
    """
    # ── Rentang tanggal (identik dgn calculator_channel.hitung_channel) ────
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
        """{wok: {"total": n, "TSEL_ONE": n, "EZNET": n, "IH_REGULER": n}}"""
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
        def _sum(agg, key):
            return sum(agg.get(w, {}).get(key, 0) for w in woks_list)

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
                # selisih poin persentase (pp), BUKAN growth: Cont bulan M - Cont bulan M-1
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
            "level"     : "WOK", "name": canon, "branch": branch,
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
