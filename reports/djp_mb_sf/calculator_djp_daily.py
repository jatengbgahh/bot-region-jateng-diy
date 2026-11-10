"""
calculator_djp_daily.py — Daily grid DJP: unique SF per WOK per tanggal dalam 1 bulan
"""
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
from config import WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER, REGION_NAME


def hitung_djp_daily(tgl: date, djp_df: pd.DataFrame, sf_aktif_df=None) -> dict:
    """
    Hitung unique SF DJP per tanggal (1 s/d akhir bulan tgl).
    Tanggal setelah tgl = None (blank).
    Total MtD = COUNT(DISTINCT user_code) dari tgl 1 s/d tgl.
    sf_reg per WOK dari bulan N.
    """
    from dateutil.relativedelta import relativedelta as _rdelta

    bulan_ini = tgl.strftime("%Y-%m")
    awal      = tgl.replace(day=1)
    akhir_bln = calendar.monthrange(tgl.year, tgl.month)[1]
    semua_tgl = [date(tgl.year, tgl.month, d) for d in range(1, akhir_bln + 1)]

    # ── SF REG map (bulan N) ─────────────────────────────────────────────
    sf_reg_map = {}
    if sf_aktif_df is not None and not sf_aktif_df.empty:
        df_sf = sf_aktif_df.copy()
        df_sf.columns = df_sf.columns.str.strip().str.upper()
        wok_valid = [w.upper() for w in WOK_ORDER]
        df_sf = df_sf[df_sf["WOK"].astype(str).str.strip().str.upper().isin(wok_valid)]
        col = bulan_ini.upper()
        if col in df_sf.columns:
            for _, row in df_sf.iterrows():
                wok = str(row.get("WOK", "")).strip().upper()
                try:
                    sf = int(row.get(col, 0) or 0)
                except (ValueError, TypeError):
                    sf = 0
                if wok:
                    sf_reg_map[wok] = sf

    # ── Prep DF ───────────────────────────────────────────────────────────
    df = djp_df.copy()
    df["WOK"]        = df["WOK"].str.strip().str.upper()
    df["TUGAS DATE"] = pd.to_datetime(df["TUGAS DATE"], errors="coerce").dt.date
    df = df.dropna(subset=["TUGAS DATE"])
    # Hanya bulan ini
    df = df[(df["TUGAS DATE"] >= awal) & (df["TUGAS DATE"] <= tgl)]

    # ── Agg per WOK per tanggal ───────────────────────────────────────────
    def daily_per_wok(wok_filter=None):
        """Return dict {wok: {tgl: int_or_None}}"""
        d = df if wok_filter is None else df[df["WOK"] == wok_filter]
        result = {}
        for wok_name, grp in d.groupby("WOK"):
            day_map = {}
            for t in semua_tgl:
                if t > tgl:
                    day_map[t] = None
                else:
                    sub = grp[grp["TUGAS DATE"] == t]
                    day_map[t] = int(sub["USER CODE"].nunique()) if not sub.empty else 0
            result[wok_name] = day_map
        return result

    agg_daily = daily_per_wok()

    # Total MtD unique SF per WOK (1 s/d tgl)
    def mtd_unique(wok):
        sub = df[df["WOK"] == wok]
        return int(sub["USER CODE"].nunique()) if not sub.empty else 0

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in WOK_ORDER:
        wok_u = wok.upper()
        branch = WOK_TO_BRANCH.get(wok, "LAINNYA")
        day_vals = agg_daily.get(wok_u, {})
        # Fill missing tanggal
        daily = {t: day_vals.get(t, (None if t > tgl else 0)) for t in semua_tgl}
        wok_rows.append({
            "level"   : "WOK",
            "name"    : wok_u,
            "branch"  : branch.upper(),
            "sf_reg"  : sf_reg_map.get(wok_u, 0),
            "daily"   : daily,
            "mtd_total": mtd_unique(wok_u),
        })

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    for branch in BRANCH_ORDER:
        brows = [r for r in wok_rows if r["branch"] == branch.upper()]
        if not brows:
            continue
        # Per tanggal: SUM unique SF (branch level bukan distinct, tapi sum WOK)
        daily_b = {}
        for t in semua_tgl:
            vals = [r["daily"].get(t) for r in brows if r["daily"].get(t) is not None]
            daily_b[t] = sum(vals) if vals and t <= tgl else (None if t > tgl else 0)
        # MtD unique SF branch
        sub_b = df[df["WOK"].isin([r["name"] for r in brows])]
        mtd_b = int(sub_b["USER CODE"].nunique()) if not sub_b.empty else 0
        branch_rows.append({
            "level"    : "BRANCH",
            "name"     : branch.upper(),
            "sf_reg"   : sum(r["sf_reg"] for r in brows),
            "daily"    : daily_b,
            "mtd_total": mtd_b,
        })

    # ── REGION row ────────────────────────────────────────────────────────
    daily_reg = {}
    for t in semua_tgl:
        vals = [r["daily"].get(t) for r in wok_rows if r["daily"].get(t) is not None]
        daily_reg[t] = sum(vals) if vals and t <= tgl else (None if t > tgl else 0)
    mtd_reg = int(df["USER CODE"].nunique()) if not df.empty else 0

    region_row = {
        "level"    : "REGION",
        "name"     : REGION_NAME,
        "sf_reg"   : sum(sf_reg_map.values()),
        "daily"    : daily_reg,
        "mtd_total": mtd_reg,
    }

    return {
        "tgl"      : tgl,
        "bi_label" : tgl.strftime("%b %Y").upper(),
        "semua_tgl": semua_tgl,
        "region"   : region_row,
        "branches" : branch_rows,
        "woks"     : wok_rows,
    }
