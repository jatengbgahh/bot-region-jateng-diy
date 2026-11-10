"""
calculator_sf.py — Kalkulasi metrics SF (Sales Force) channel AGENCY
Source: indihome_ordering_detail_YYYYMM (filter channel_group = 'AGENCY')

Metrics:
  SF REG           = jumlah SF terdaftar per WOK (dari template target sheet SF_AKTIF)
  SF Aktif PS      = COUNT(DISTINCT sf_code) yang punya PS >= 1 pada periode
  Total PS         = COUNT(order) dengan PS sah pada periode (sama seperti PS by Channel)
  %M               = SF Aktif PS (M) / SF REG (M) x 100
  SF Productivity  = Total PS / SF Aktif PS

Periode:
  TODAY = tanggal input (single day)
  M     = MtD bulan berjalan (1 s/d tanggal input)
  M-1   = MtD bulan lalu (same date range)
  MoM   = growth % (M vs M-1)
"""

import pandas as pd
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME
# WOK dari sheet target HANYA ikut kalau termasuk 14 WOK baru — target lama (v7)
# yang masih tersimpan di bot tidak boleh memunculkan baris WOK lama berisi 0.
_WOK_BARU = {w.upper() for w in WOK_ORDER}


def hitung_sf(tgl: date, sf_aktif_df=None) -> dict:
    """
    Query & kalkulasi metrics SF AGENCY.

    Args:
        tgl         : tanggal laporan (date)
        sf_aktif_df : DataFrame sheet SF_AKTIF (kolom: BRANCH, WOK, 2026-01, 2026-02, ...)
                      Jika None, SF REG & %M akan "-"

    Returns dict siap pakai untuk renderer_sf.render_sf()
    """
    bulan_ini = tgl.strftime("%Y-%m")

    def _build_sf_map(df_sf_raw, bulan_key):
        m = {}
        if df_sf_raw is None or df_sf_raw.empty:
            return m
        df_sf = df_sf_raw.copy()
        df_sf.columns = df_sf.columns.str.strip().str.upper()
        wok_valid = [w.upper() for w in WOK_ORDER]
        df_sf = df_sf[df_sf["WOK"].astype(str).str.strip().str.upper().isin(wok_valid)]
        col = bulan_key.upper()
        if col in df_sf.columns:
            for _, row in df_sf.iterrows():
                wok = str(row.get("WOK", "")).strip().upper()
                try:
                    sf = int(row.get(col, 0) or 0)
                except (ValueError, TypeError):
                    sf = 0
                if wok:
                    m[wok] = sf
        return m

    sf_reg_map = _build_sf_map(sf_aktif_df, bulan_ini)  # SF Reg bulan berjalan

    # ── Rentang periode (sama pola dengan calculator_djp.py) ──────────────
    awal_ini     = tgl.replace(day=1)
    hari_mtd_ini = tgl.day

    bulan_lalu    = tgl - relativedelta(months=1)
    awal_lalu     = bulan_lalu.replace(day=1)
    hari_max      = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_mtd_lalu = min(tgl.day, hari_max)
    akhir_lalu    = date(bulan_lalu.year, bulan_lalu.month, hari_mtd_lalu)

    # ── Query DB (ps_ts DATETIME → +1 hari di batas atas) ─────────────────
    rows_today = db.query_sf_agency(tgl,       tgl       + timedelta(days=1))
    rows_mtd   = db.query_sf_agency(awal_ini,  tgl       + timedelta(days=1))
    rows_lalu  = db.query_sf_agency(awal_lalu, akhir_lalu + timedelta(days=1))

    def to_df(rows):
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["wok"]    = df["wok"].str.strip().str.upper()
        df["branch"] = df["branch"].str.strip().str.upper()
        return df

    df_today = to_df(rows_today)
    df_mtd   = to_df(rows_mtd)
    df_lalu  = to_df(rows_lalu)

    def agg_wok(df) -> dict:
        """Aggregate per WOK. Return: {wok: {sf_aktif_ps, total_ps}}"""
        if df.empty:
            return {}
        result = {}
        for wok, grp in df.groupby("wok"):
            result[wok] = {
                "sf_aktif_ps": int(grp["sf_code"].nunique()),
                "total_ps"   : int(len(grp)),
            }
        return result

    agg_today = agg_wok(df_today)
    agg_mtd   = agg_wok(df_mtd)
    agg_lalu  = agg_wok(df_lalu)

    semua_wok = set(
        list(agg_today.keys()) +
        list(agg_mtd.keys())   +
        list(agg_lalu.keys())  +
        [w for w in sf_reg_map.keys() if w in _WOK_BARU]
    )

    def g(agg, wok, key): return agg.get(wok, {}).get(key, 0)

    def mom(cur, prev):
        if prev and prev > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    def pct_m(sf_aktif, sf_reg):
        if sf_reg and sf_reg > 0:
            return round(sf_aktif / sf_reg * 100, 1)
        return None

    def productivity(total_ps, sf_aktif):
        if sf_aktif and sf_aktif > 0:
            return round(total_ps / sf_aktif, 1)
        return None

    # ── WOK rows ────────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )

        t_sf = g(agg_today, wok, "sf_aktif_ps")
        t_ps = g(agg_today, wok, "total_ps")

        m_sf = g(agg_mtd, wok, "sf_aktif_ps")
        m_ps = g(agg_mtd, wok, "total_ps")

        l_sf = g(agg_lalu, wok, "sf_aktif_ps")
        l_ps = g(agg_lalu, wok, "total_ps")

        sf_reg = sf_reg_map.get(wok, 0)
        prod_m  = productivity(m_ps, m_sf)
        prod_l  = productivity(l_ps, l_sf)

        wok_rows.append({
            "level"  : "WOK",
            "name"   : wok,
            "branch" : branch,
            "sf_reg" : sf_reg,
            # TODAY
            "today_sf_aktif_ps": t_sf,
            "today_total_ps"   : t_ps,
            # SF Aktif PS (M-1, M, %M, MoM)
            "sf_aktif_m1"  : l_sf,
            "sf_aktif_m"   : m_sf,
            "sf_aktif_pctm": pct_m(m_sf, sf_reg),
            "sf_aktif_mom" : mom(m_sf, l_sf),
            # Total PS (M-1, M, MoM)
            "total_ps_m1" : l_ps,
            "total_ps_m"  : m_ps,
            "total_ps_mom": mom(m_ps, l_ps),
            # SF Productivity (M-1, M, MoM)
            "prod_m1" : prod_l,
            "prod_m"  : prod_m,
            "prod_mom": mom(prod_m, prod_l),
        })

    # Sort sesuai WOK_ORDER
    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ─────────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )

    for branch in branch_names:
        brows = [r for r in wok_rows if r["branch"] == branch]
        if not brows:
            continue

        bt_sf = sum(g(agg_today, r["name"], "sf_aktif_ps") for r in brows)
        bt_ps = sum(g(agg_today, r["name"], "total_ps")    for r in brows)
        bm_sf = sum(g(agg_mtd,   r["name"], "sf_aktif_ps") for r in brows)
        bm_ps = sum(g(agg_mtd,   r["name"], "total_ps")    for r in brows)
        bl_sf = sum(g(agg_lalu,  r["name"], "sf_aktif_ps") for r in brows)
        bl_ps = sum(g(agg_lalu,  r["name"], "total_ps")    for r in brows)
        sf_reg_b = sum(sf_reg_map.get(r["name"], 0) for r in brows)

        bprod_m = productivity(bm_ps, bm_sf)
        bprod_l = productivity(bl_ps, bl_sf)

        branch_rows.append({
            "level"  : "BRANCH",
            "name"   : branch,
            "sf_reg" : sf_reg_b,
            "today_sf_aktif_ps": bt_sf,
            "today_total_ps"   : bt_ps,
            "sf_aktif_m1"  : bl_sf,
            "sf_aktif_m"   : bm_sf,
            "sf_aktif_pctm": pct_m(bm_sf, sf_reg_b),
            "sf_aktif_mom" : mom(bm_sf, bl_sf),
            "total_ps_m1" : bl_ps,
            "total_ps_m"  : bm_ps,
            "total_ps_mom": mom(bm_ps, bl_ps),
            "prod_m1" : bprod_l,
            "prod_m"  : bprod_m,
            "prod_mom": mom(bprod_m, bprod_l),
        })

    # ── REGION row ──────────────────────────────────────────────────────────
    rt_sf = sum(g(agg_today, w, "sf_aktif_ps") for w in semua_wok)
    rt_ps = sum(g(agg_today, w, "total_ps")    for w in semua_wok)
    rm_sf = sum(g(agg_mtd,   w, "sf_aktif_ps") for w in semua_wok)
    rm_ps = sum(g(agg_mtd,   w, "total_ps")    for w in semua_wok)
    rl_sf = sum(g(agg_lalu,  w, "sf_aktif_ps") for w in semua_wok)
    rl_ps = sum(g(agg_lalu,  w, "total_ps")    for w in semua_wok)
    sf_reg_total = sum(sf_reg_map.values())

    rprod_m = productivity(rm_ps, rm_sf)
    rprod_l = productivity(rl_ps, rl_sf)

    region_row = {
        "level"  : "REGION",
        "name"   : REGION_NAME,
        "sf_reg" : sf_reg_total,
        "today_sf_aktif_ps": rt_sf,
        "today_total_ps"   : rt_ps,
        "sf_aktif_m1"  : rl_sf,
        "sf_aktif_m"   : rm_sf,
        "sf_aktif_pctm": pct_m(rm_sf, sf_reg_total),
        "sf_aktif_mom" : mom(rm_sf, rl_sf),
        "total_ps_m1" : rl_ps,
        "total_ps_m"  : rm_ps,
        "total_ps_mom": mom(rm_ps, rl_ps),
        "prod_m1" : rprod_l,
        "prod_m"  : rprod_m,
        "prod_mom": mom(rprod_m, rprod_l),
    }

    return {
        "tgl"      : tgl,
        "bl_label" : bulan_lalu.strftime("%b %Y").upper(),
        "bi_label" : tgl.strftime("%b %Y").upper(),
        "region"   : region_row,
        "branches" : branch_rows,
        "woks"     : wok_rows,
    }
