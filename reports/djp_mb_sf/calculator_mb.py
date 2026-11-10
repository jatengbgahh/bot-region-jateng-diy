"""
calculator_mb.py — Kalkulasi metrics Morning Briefing (MB)
Filter: SCHEDULE CATEGORY = 'BRIEFING', STATUS = 'APPROVED', REGION = 'JATENG-DIY'
SF MB = COUNT(DISTINCT user_code) per WOK per periode
%SF MB = SF MB (MtD) / SF REG bulan N × 100%
MoM %SF MB = selisih ppt: (cur/sf_reg_N) - (prev/sf_reg_N1)
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
from config import WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER, REGION_NAME


def hitung_mb_csv(tgl: date, mb_df: pd.DataFrame, sf_aktif_df=None) -> dict:
    """
    Kalkulasi metrics MB dari CSV.
    mb_df: sudah difilter BRIEFING+APPROVED+JATENG-DIY, kolom uppercase.
    sf_aktif_df: sheet SF_AKTIF dari template target.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    # ── SF REG maps ───────────────────────────────────────────────────────
    bulan_n1  = (tgl.replace(day=1) - _rdelta(months=1)).strftime("%Y-%m")
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

    sf_reg_map   = _build_sf_map(sf_aktif_df, bulan_ini)   # bulan N — SF REG & pembagi cur
    sf_aktif_map = _build_sf_map(sf_aktif_df, bulan_n1)    # bulan N-1 — pembagi prev MoM

    # ── Persiapan DF ──────────────────────────────────────────────────────
    df = mb_df.copy()
    df["WOK"]        = df["WOK"].str.strip().str.upper()
    df["BRANCH"]     = df["BRANCH"].str.strip().str.upper()
    df["TUGAS DATE"] = pd.to_datetime(df["TUGAS DATE"], errors="coerce").dt.date
    df = df.dropna(subset=["TUGAS DATE"])

    # ── Rentang ───────────────────────────────────────────────────────────
    awal_ini   = tgl.replace(day=1)
    bulan_lalu = tgl - _rdelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max   = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month, min(tgl.day, hari_max))

    def filter_df(d1, d2):
        return df[(df["TUGAS DATE"] >= d1) & (df["TUGAS DATE"] <= d2)]

    df_today = filter_df(tgl,      tgl)
    df_mtd   = filter_df(awal_ini, tgl)
    df_lalu  = filter_df(awal_lalu, akhir_lalu)

    def agg_wok(dff) -> dict:
        if dff.empty:
            return {}
        return {wok: int(grp["USER CODE"].nunique())
                for wok, grp in dff.groupby("WOK")}

    agg_today = agg_wok(df_today)
    agg_mtd   = agg_wok(df_mtd)
    agg_lalu  = agg_wok(df_lalu)

    semua_wok = set(list(agg_today) + list(agg_mtd) + list(agg_lalu) + list(sf_reg_map))

    def g(agg, wok): return agg.get(wok, 0)

    def mom(cur, prev):
        if prev and prev > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    def pct_sf(sf_mb, wok):
        sf_r = sf_reg_map.get(wok, 0)
        return round(sf_mb / sf_r * 100, 1) if sf_r > 0 else None

    def pct_sf_mom(sf_cur, sf_prev, wok):
        sf_n  = sf_reg_map.get(wok, 0)
        sf_n1 = sf_aktif_map.get(wok, 0)
        if not sf_n or sf_n <= 0 or not sf_n1 or sf_n1 <= 0:
            return None
        cur  = sf_cur  / sf_n  * 100
        prev = sf_prev / sf_n1 * 100
        return round(cur - prev, 1) if prev > 0 else None

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok), "LAINNYA"
        )
        t_s = g(agg_today, wok)
        m_s = g(agg_mtd,   wok)
        l_s = g(agg_lalu,  wok)
        wok_rows.append({
            "level": "WOK", "name": wok, "branch": branch,
            "sf_reg":           sf_reg_map.get(wok, 0),
            "today_sf_mb":      t_s,
            "mtd_sf_mb":        m_s,
            "mtd_sf_mb_mom":    mom(m_s, l_s),
            "mtd_pct_sf_mb":    pct_sf(m_s, wok),
            "mtd_pct_sf_mb_mom": pct_sf_mom(m_s, l_s, wok),
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    for branch in BRANCH_ORDER + sorted({r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}):
        brows = [r for r in wok_rows if r["branch"] == branch]
        if not brows:
            continue
        sf_reg_b = sum(sf_reg_map.get(r["name"], 0)   for r in brows)
        sf_n1_b  = sum(sf_aktif_map.get(r["name"], 0) for r in brows)
        bt = sum(g(agg_today, r["name"]) for r in brows)
        bm = sum(g(agg_mtd,   r["name"]) for r in brows)
        bl = sum(g(agg_lalu,  r["name"]) for r in brows)

        def pct_b(sf_d): return round(sf_d / sf_reg_b * 100, 1) if sf_reg_b > 0 else None
        def pct_b_mom(sc, sp):
            if sf_reg_b <= 0 or sf_n1_b <= 0: return None
            c = round(sc / sf_reg_b * 100, 1); p = round(sp / sf_n1_b * 100, 1)
            return round(c - p, 1) if p > 0 else None

        branch_rows.append({
            "level": "BRANCH", "name": branch,
            "sf_reg":            sf_reg_b,
            "today_sf_mb":       bt,
            "mtd_sf_mb":         bm,
            "mtd_sf_mb_mom":     mom(bm, bl),
            "mtd_pct_sf_mb":     pct_b(bm),
            "mtd_pct_sf_mb_mom": pct_b_mom(bm, bl),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    sf_reg_tot = sum(sf_reg_map.values())
    sf_n1_tot  = sum(sf_aktif_map.values())
    rt = sum(g(agg_today, w) for w in semua_wok)
    rm = sum(g(agg_mtd,   w) for w in semua_wok)
    rl = sum(g(agg_lalu,  w) for w in semua_wok)

    def pct_r(sf_d): return round(sf_d / sf_reg_tot * 100, 1) if sf_reg_tot > 0 else None
    def pct_r_mom(sc, sp):
        if sf_reg_tot <= 0 or sf_n1_tot <= 0: return None
        c = round(sc / sf_reg_tot * 100, 1); p = round(sp / sf_n1_tot * 100, 1)
        return round(c - p, 1) if p > 0 else None

    region_row = {
        "level": "REGION", "name": REGION_NAME,
        "sf_reg":            sf_reg_tot,
        "today_sf_mb":       rt,
        "mtd_sf_mb":         rm,
        "mtd_sf_mb_mom":     mom(rm, rl),
        "mtd_pct_sf_mb":     pct_r(rm),
        "mtd_pct_sf_mb_mom": pct_r_mom(rm, rl),
    }

    bulan_lalu_obj = tgl - _rdelta(months=1)
    return {
        "tgl"      : tgl,
        "bl_label" : bulan_lalu_obj.strftime("%b %Y").upper(),
        "bi_label" : tgl.strftime("%b %Y").upper(),
        "region"   : region_row,
        "branches" : branch_rows,
        "woks"     : wok_rows,
    }
