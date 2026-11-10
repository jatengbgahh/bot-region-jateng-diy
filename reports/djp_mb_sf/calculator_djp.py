"""
calculator_djp.py — Kalkulasi metrics DJP (Door to Door Journey Performance)
Source: djp_daily_user_detailed_YYYYMM
Filter: regional = 'JATENG'

Metrics:
  Visit DJP        = COUNT(tugas_id) per WOK
  Unique ODP DJP   = COUNT(DISTINCT odp_name) per WOK
  SF DJP           = COUNT(DISTINCT user_code) per WOK
  %SF ActiveDJP    = SF DJP / SF Aktif (dari template target sheet SF_AKTIF)
  DJP/SF           = Visit DJP / SF DJP

Periode:
  TODAY  = tanggal input
  MtD    = 1 s/d tanggal input bulan berjalan
  MoM    = MtD current vs MtD same date bulan lalu
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER, REGION_NAME


def hitung_djp(tgl: date, sf_aktif_df=None) -> dict:
    """
    Query & kalkulasi metrics DJP.

    Args:
        tgl          : tanggal laporan (date)
        sf_aktif_df  : DataFrame sheet SF_AKTIF (kolom: BRANCH, WOK, 2026-01, 2026-02, ...)
                       Jika None, %SF ActiveDJP akan "-"

    Returns dict siap pakai untuk renderer_djp.render_djp()
    """
    # ── Bangun sf_aktif_map (N-1) & sf_reg_map (bulan berjalan) ───────────
    from dateutil.relativedelta import relativedelta as _rdelta
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

    sf_aktif_map = _build_sf_map(sf_aktif_df, bulan_n1)   # SF Reg bulan N-1 (untuk %SF prev/MoM)
    sf_reg_map   = _build_sf_map(sf_aktif_df, bulan_ini)  # SF Reg bulan N (kolom SF REG + pembagi %SF current)

    # ── Rentang tanggal ───────────────────────────────────────────────────
    awal_ini   = tgl.replace(day=1)
    hari_mtd_ini = tgl.day   # jumlah hari MtD bulan berjalan (1 s/d tgl)

    bulan_lalu = tgl - relativedelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max   = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_mtd_lalu = min(tgl.day, hari_max)   # jumlah hari MtD bulan lalu (same date)
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month, hari_mtd_lalu)

    # ── Query DB ──────────────────────────────────────────────────────────
    rows_today = db.query_djp(tgl,       tgl)
    rows_mtd   = db.query_djp(awal_ini,  tgl)
    rows_lalu  = db.query_djp(awal_lalu, akhir_lalu)

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
        """
        Aggregate per WOK.
        Return: {wok: {visit, unique_odp, sf_djp}}
        """
        if df.empty:
            return {}
        result = {}
        for wok, grp in df.groupby("wok"):
            result[wok] = {
                "visit"      : int(len(grp)),
                "unique_odp" : int(grp["odp_name"].nunique()),
                "sf_djp"     : int(grp["user_code"].nunique()),
            }
        return result

    agg_today = agg_wok(df_today)
    agg_mtd   = agg_wok(df_mtd)
    agg_lalu  = agg_wok(df_lalu)

    semua_wok = set(
        list(agg_today.keys()) +
        list(agg_mtd.keys())   +
        list(agg_lalu.keys())  +
        list(sf_aktif_map.keys())
    )

    def g(agg, wok, key): return agg.get(wok, {}).get(key, 0)

    def mom(cur, prev):
        if prev and prev > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    def pct_sf(sf_djp, wok):
        sf_reg = sf_reg_map.get(wok, 0)
        if sf_reg and sf_reg > 0:
            return round(sf_djp / sf_reg * 100, 1)
        return None

    def djp_per_sf_day(visit, sf_djp, n_hari):
        if sf_djp and sf_djp > 0 and n_hari and n_hari > 0:
            return round(visit / sf_djp / n_hari, 1)
        return None

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )

        # TODAY
        t_visit = g(agg_today, wok, "visit")
        t_odp   = g(agg_today, wok, "unique_odp")
        t_sf    = g(agg_today, wok, "sf_djp")

        # MtD ini
        m_visit = g(agg_mtd, wok, "visit")
        m_odp   = g(agg_mtd, wok, "unique_odp")
        m_sf    = g(agg_mtd, wok, "sf_djp")

        # MtD lalu
        l_visit = g(agg_lalu, wok, "visit")
        l_odp   = g(agg_lalu, wok, "unique_odp")
        l_sf    = g(agg_lalu, wok, "sf_djp")

        wok_rows.append({
            "level"  : "WOK",
            "name"   : wok,
            "branch" : branch,
            "sf_reg" : sf_reg_map.get(wok, 0),
            # TODAY
            "today_visit"      : t_visit,
            "today_unique_odp" : t_odp,
            "today_sf_djp"     : t_sf,
            # MtD
            "mtd_visit"        : m_visit,
            "mtd_visit_mom"    : mom(m_visit, l_visit),
            "mtd_unique_odp"   : m_odp,
            "mtd_unique_odp_mom": mom(m_odp, l_odp),
            "mtd_sf_djp"       : m_sf,
            "mtd_sf_djp_mom"   : mom(m_sf, l_sf),
            "mtd_pct_sf"       : pct_sf(m_sf, wok),
            "mtd_pct_sf_mom"   : _pct_sf_mom(m_sf, l_sf, wok, sf_reg_map, sf_aktif_map),
            "mtd_djp_per_sf"   : djp_per_sf_day(m_visit, m_sf, hari_mtd_ini),
            "mtd_djp_per_sf_mom": _djp_per_sf_mom(
                m_visit, l_visit, m_sf, l_sf, hari_mtd_ini, hari_mtd_lalu
            ),
        })

    # Sort sesuai WOK_ORDER
    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )

    for branch in branch_names:
        brows = [r for r in wok_rows if r["branch"] == branch]
        if not brows:
            continue

        bt_visit = sum(g(agg_today, r["name"], "visit")      for r in brows)
        bt_odp   = sum(g(agg_today, r["name"], "unique_odp") for r in brows)
        bt_sf    = sum(g(agg_today, r["name"], "sf_djp")     for r in brows)

        bm_visit = sum(g(agg_mtd, r["name"], "visit")      for r in brows)
        bm_odp   = sum(g(agg_mtd, r["name"], "unique_odp") for r in brows)
        bm_sf    = sum(g(agg_mtd, r["name"], "sf_djp")     for r in brows)

        bl_visit = sum(g(agg_lalu, r["name"], "visit")      for r in brows)
        bl_odp   = sum(g(agg_lalu, r["name"], "unique_odp") for r in brows)
        bl_sf    = sum(g(agg_lalu, r["name"], "sf_djp")     for r in brows)

        # SF Reg total branch: bulan N (current) dan N-1 (prev/MoM)
        sf_aktif_branch = sum(sf_aktif_map.get(r["name"], 0) for r in brows)  # N-1
        sf_reg_branch   = sum(sf_reg_map.get(r["name"], 0)   for r in brows)  # N

        def pct_sf_agg(sf_djp):
            if sf_reg_branch and sf_reg_branch > 0:
                return round(sf_djp / sf_reg_branch * 100, 1)
            return None

        def pct_sf_agg_mom(sf_djp_cur, sf_djp_prev):
            if not sf_reg_branch or sf_reg_branch <= 0:
                return None
            if not sf_aktif_branch or sf_aktif_branch <= 0:
                return None
            cur  = round(sf_djp_cur  / sf_reg_branch   * 100, 1)
            prev = round(sf_djp_prev / sf_aktif_branch * 100, 1)
            if prev > 0:
                return round(cur - prev, 1)  # dev in ppt
            return None

        branch_rows.append({
            "level"  : "BRANCH",
            "name"   : branch,
            "sf_reg" : sf_reg_branch,
            "today_visit"       : bt_visit,
            "today_unique_odp"  : bt_odp,
            "today_sf_djp"      : bt_sf,
            "mtd_visit"         : bm_visit,
            "mtd_visit_mom"     : mom(bm_visit, bl_visit),
            "mtd_unique_odp"    : bm_odp,
            "mtd_unique_odp_mom": mom(bm_odp, bl_odp),
            "mtd_sf_djp"        : bm_sf,
            "mtd_sf_djp_mom"    : mom(bm_sf, bl_sf),
            "mtd_pct_sf"        : pct_sf_agg(bm_sf),
            "mtd_pct_sf_mom"    : pct_sf_agg_mom(bm_sf, bl_sf),
            "mtd_djp_per_sf"    : djp_per_sf_day(bm_visit, bm_sf, hari_mtd_ini),
            "mtd_djp_per_sf_mom": _djp_per_sf_mom(
                bm_visit, bl_visit, bm_sf, bl_sf, hari_mtd_ini, hari_mtd_lalu
            ),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    rt_visit = sum(g(agg_today, w, "visit")      for w in semua_wok)
    rt_odp   = sum(g(agg_today, w, "unique_odp") for w in semua_wok)
    rt_sf    = sum(g(agg_today, w, "sf_djp")     for w in semua_wok)

    rm_visit = sum(g(agg_mtd, w, "visit")      for w in semua_wok)
    rm_odp   = sum(g(agg_mtd, w, "unique_odp") for w in semua_wok)
    rm_sf    = sum(g(agg_mtd, w, "sf_djp")     for w in semua_wok)

    rl_visit = sum(g(agg_lalu, w, "visit")      for w in semua_wok)
    rl_odp   = sum(g(agg_lalu, w, "unique_odp") for w in semua_wok)
    rl_sf    = sum(g(agg_lalu, w, "sf_djp")     for w in semua_wok)

    sf_aktif_total = sum(sf_aktif_map.values())
    sf_reg_total   = sum(sf_reg_map.values())

    def pct_sf_reg(sf_djp):
        if sf_reg_total and sf_reg_total > 0:
            return round(sf_djp / sf_reg_total * 100, 1)
        return None

    def pct_sf_reg_mom(sf_cur, sf_prev):
        if not sf_reg_total or sf_reg_total <= 0:
            return None
        if not sf_aktif_total or sf_aktif_total <= 0:
            return None
        cur  = round(sf_cur  / sf_reg_total   * 100, 1)
        prev = round(sf_prev / sf_aktif_total * 100, 1)
        if prev > 0:
            return round(cur - prev, 1)
        return None

    region_row = {
        "level"  : "REGION",
        "name"   : REGION_NAME,
        "sf_reg" : sf_reg_total,
        "today_visit"       : rt_visit,
        "today_unique_odp"  : rt_odp,
        "today_sf_djp"      : rt_sf,
        "mtd_visit"         : rm_visit,
        "mtd_visit_mom"     : mom(rm_visit, rl_visit),
        "mtd_unique_odp"    : rm_odp,
        "mtd_unique_odp_mom": mom(rm_odp, rl_odp),
        "mtd_sf_djp"        : rm_sf,
        "mtd_sf_djp_mom"    : mom(rm_sf, rl_sf),
        "mtd_pct_sf"        : pct_sf_reg(rm_sf),
        "mtd_pct_sf_mom"    : pct_sf_reg_mom(rm_sf, rl_sf),
        "mtd_djp_per_sf"    : djp_per_sf_day(rm_visit, rm_sf, hari_mtd_ini),
        "mtd_djp_per_sf_mom": _djp_per_sf_mom(
            rm_visit, rl_visit, rm_sf, rl_sf, hari_mtd_ini, hari_mtd_lalu
        ),
    }

    return {
        "tgl"      : tgl,
        "bl_label" : bulan_lalu.strftime("%b %Y").upper(),
        "bi_label" : tgl.strftime("%b %Y").upper(),
        "region"   : region_row,
        "branches" : branch_rows,
        "woks"     : wok_rows,
    }


# ── Helper private ────────────────────────────────────────────────────────────

def _pct_sf_mom(sf_djp_cur, sf_djp_prev, wok, sf_reg_map_n, sf_reg_map_n1):
    """
    MoM untuk %SF: selisih ppt (cur% - prev%).
    cur%  = sf_djp_cur  / SF Reg bulan N   (sf_reg_map_n)
    prev% = sf_djp_prev / SF Reg bulan N-1 (sf_reg_map_n1)
    """
    sf_reg_n  = sf_reg_map_n.get(wok, 0)
    sf_reg_n1 = sf_reg_map_n1.get(wok, 0)
    if not sf_reg_n or sf_reg_n <= 0 or not sf_reg_n1 or sf_reg_n1 <= 0:
        return None
    cur  = sf_djp_cur  / sf_reg_n  * 100
    prev = sf_djp_prev / sf_reg_n1 * 100
    if prev <= 0:
        return None
    return round(cur - prev, 1)


def _djp_per_sf_mom(visit_cur, visit_prev, sf_cur, sf_prev, hari_cur, hari_prev):
    """MoM untuk DJP/SF/DAY: % growth."""
    cur  = (visit_cur  / sf_cur  / hari_cur)  if (sf_cur  > 0 and hari_cur  > 0) else 0
    prev = (visit_prev / sf_prev / hari_prev) if (sf_prev > 0 and hari_prev > 0) else 0
    if prev > 0:
        return round((cur - prev) / prev * 100, 1)
    return None


def hitung_djp_csv(tgl: date, djp_df: pd.DataFrame, sf_aktif_df=None) -> dict:
    """
    Kalkulasi metrics DJP dari CSV manual (sudah difilter DJP+APPROVED oleh bot).

    Args:
        tgl         : tanggal laporan
        djp_df      : DataFrame CSV DJP (kolom: WOK, BRANCH, TUGAS DATE,
                      USER CODE, ODP, TUGAS ID — sudah uppercase)
        sf_aktif_df : DataFrame sheet SF_AKTIF (opsional, untuk %SF ActiveDJP)

    Returns dict format sama dengan hitung_djp() → bisa pakai renderer_djp.render_djp()
    """
    # ── Bangun sf_aktif_map (N-1) & sf_reg_map (bulan berjalan) ───────────
    from dateutil.relativedelta import relativedelta as _rdelta
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

    sf_aktif_map = _build_sf_map(sf_aktif_df, bulan_n1)
    sf_reg_map   = _build_sf_map(sf_aktif_df, bulan_ini)

    # ── Persiapan DataFrame ───────────────────────────────────────────────
    df = djp_df.copy()
    df["WOK"]        = df["WOK"].str.strip().str.upper()
    df["BRANCH"]     = df["BRANCH"].str.strip().str.upper()
    df["TUGAS DATE"] = pd.to_datetime(df["TUGAS DATE"], errors="coerce").dt.date
    df = df.dropna(subset=["TUGAS DATE"])

    # ── Rentang periode ───────────────────────────────────────────────────
    awal_ini   = tgl.replace(day=1)
    hari_mtd_ini = tgl.day
    bulan_lalu = tgl - _rdelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    import calendar as _cal
    hari_max   = _cal.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_mtd_lalu = min(tgl.day, hari_max)
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month, hari_mtd_lalu)

    def filter_df(tgl_dari, tgl_sampai):
        return df[(df["TUGAS DATE"] >= tgl_dari) & (df["TUGAS DATE"] <= tgl_sampai)]

    df_today = filter_df(tgl,       tgl)
    df_mtd   = filter_df(awal_ini,  tgl)
    df_lalu  = filter_df(awal_lalu, akhir_lalu)

    def agg_wok(dff) -> dict:
        if dff.empty:
            return {}
        result = {}
        for wok, grp in dff.groupby("WOK"):
            result[wok] = {
                "visit"      : int(len(grp)),
                "unique_odp" : int(grp["ODP"].nunique()),
                "sf_djp"     : int(grp["USER CODE"].nunique()),
            }
        return result

    agg_today = agg_wok(df_today)
    agg_mtd   = agg_wok(df_mtd)
    agg_lalu  = agg_wok(df_lalu)

    semua_wok = set(
        list(agg_today.keys()) + list(agg_mtd.keys()) +
        list(agg_lalu.keys())  + list(sf_aktif_map.keys())
    )

    def g(agg, wok, key): return agg.get(wok, {}).get(key, 0)

    def mom(cur, prev):
        if prev and prev > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    def pct_sf(sf_djp, wok):
        sf_r = sf_reg_map.get(wok, 0)
        return round(sf_djp / sf_r * 100, 1) if sf_r > 0 else None

    def djp_per_sf_day(visit, sf_djp, n_hari):
        if sf_djp and sf_djp > 0 and n_hari and n_hari > 0:
            return round(visit / sf_djp / n_hari, 1)
        return None

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok), "LAINNYA"
        )
        t_v = g(agg_today, wok, "visit");      t_o = g(agg_today, wok, "unique_odp"); t_s = g(agg_today, wok, "sf_djp")
        m_v = g(agg_mtd,   wok, "visit");      m_o = g(agg_mtd,   wok, "unique_odp"); m_s = g(agg_mtd,   wok, "sf_djp")
        l_v = g(agg_lalu,  wok, "visit");      l_o = g(agg_lalu,  wok, "unique_odp"); l_s = g(agg_lalu,  wok, "sf_djp")

        wok_rows.append({
            "level": "WOK", "name": wok, "branch": branch,
            "sf_reg": sf_reg_map.get(wok, 0),
            "today_visit": t_v, "today_unique_odp": t_o, "today_sf_djp": t_s,
            "mtd_visit": m_v,        "mtd_visit_mom": mom(m_v, l_v),
            "mtd_unique_odp": m_o,   "mtd_unique_odp_mom": mom(m_o, l_o),
            "mtd_sf_djp": m_s,       "mtd_sf_djp_mom": mom(m_s, l_s),
            "mtd_pct_sf": pct_sf(m_s, wok),
            "mtd_pct_sf_mom": _pct_sf_mom(m_s, l_s, wok, sf_reg_map, sf_aktif_map),
            "mtd_djp_per_sf": djp_per_sf_day(m_v, m_s, hari_mtd_ini),
            "mtd_djp_per_sf_mom": _djp_per_sf_mom(m_v, l_v, m_s, l_s, hari_mtd_ini, hari_mtd_lalu),
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    for branch in BRANCH_ORDER + sorted({r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}):
        brows = [r for r in wok_rows if r["branch"] == branch]
        if not brows:
            continue
        bt_v = sum(g(agg_today, r["name"], "visit")      for r in brows)
        bt_o = sum(g(agg_today, r["name"], "unique_odp") for r in brows)
        bt_s = sum(g(agg_today, r["name"], "sf_djp")     for r in brows)
        bm_v = sum(g(agg_mtd,   r["name"], "visit")      for r in brows)
        bm_o = sum(g(agg_mtd,   r["name"], "unique_odp") for r in brows)
        bm_s = sum(g(agg_mtd,   r["name"], "sf_djp")     for r in brows)
        bl_v = sum(g(agg_lalu,  r["name"], "visit")      for r in brows)
        bl_o = sum(g(agg_lalu,  r["name"], "unique_odp") for r in brows)
        bl_s = sum(g(agg_lalu,  r["name"], "sf_djp")     for r in brows)
        sf_aktif_b = sum(sf_aktif_map.get(r["name"], 0) for r in brows)
        sf_reg_b   = sum(sf_reg_map.get(r["name"], 0)   for r in brows)

        def _pct_b(sf_d): return round(sf_d / sf_reg_b * 100, 1) if sf_reg_b > 0 else None
        def _pct_b_mom(sc, sp):
            if sf_reg_b <= 0 or sf_aktif_b <= 0: return None
            c = round(sc / sf_reg_b   * 100, 1)
            p = round(sp / sf_aktif_b * 100, 1)
            return round(c - p, 1) if p > 0 else None

        branch_rows.append({
            "level": "BRANCH", "name": branch,
            "sf_reg": sf_reg_b,
            "today_visit": bt_v, "today_unique_odp": bt_o, "today_sf_djp": bt_s,
            "mtd_visit": bm_v,        "mtd_visit_mom": mom(bm_v, bl_v),
            "mtd_unique_odp": bm_o,   "mtd_unique_odp_mom": mom(bm_o, bl_o),
            "mtd_sf_djp": bm_s,       "mtd_sf_djp_mom": mom(bm_s, bl_s),
            "mtd_pct_sf": _pct_b(bm_s),
            "mtd_pct_sf_mom": _pct_b_mom(bm_s, bl_s),
            "mtd_djp_per_sf": djp_per_sf_day(bm_v, bm_s, hari_mtd_ini),
            "mtd_djp_per_sf_mom": _djp_per_sf_mom(bm_v, bl_v, bm_s, bl_s, hari_mtd_ini, hari_mtd_lalu),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    rt_v = sum(g(agg_today, w, "visit")      for w in semua_wok)
    rt_o = sum(g(agg_today, w, "unique_odp") for w in semua_wok)
    rt_s = sum(g(agg_today, w, "sf_djp")     for w in semua_wok)
    rm_v = sum(g(agg_mtd,   w, "visit")      for w in semua_wok)
    rm_o = sum(g(agg_mtd,   w, "unique_odp") for w in semua_wok)
    rm_s = sum(g(agg_mtd,   w, "sf_djp")     for w in semua_wok)
    rl_v = sum(g(agg_lalu,  w, "visit")      for w in semua_wok)
    rl_o = sum(g(agg_lalu,  w, "unique_odp") for w in semua_wok)
    rl_s = sum(g(agg_lalu,  w, "sf_djp")     for w in semua_wok)
    sf_aktif_total = sum(sf_aktif_map.values())
    sf_reg_total   = sum(sf_reg_map.values())

    def _pct_r(sf_d): return round(sf_d / sf_reg_total * 100, 1) if sf_reg_total > 0 else None
    def _pct_r_mom(sc, sp):
        if sf_reg_total <= 0 or sf_aktif_total <= 0: return None
        c = round(sc / sf_reg_total  * 100, 1)
        p = round(sp / sf_aktif_total * 100, 1)
        return round(c - p, 1) if p > 0 else None

    region_row = {
        "level": "REGION", "name": REGION_NAME,
        "sf_reg": sf_reg_total,
        "today_visit": rt_v, "today_unique_odp": rt_o, "today_sf_djp": rt_s,
        "mtd_visit": rm_v,        "mtd_visit_mom": mom(rm_v, rl_v),
        "mtd_unique_odp": rm_o,   "mtd_unique_odp_mom": mom(rm_o, rl_o),
        "mtd_sf_djp": rm_s,       "mtd_sf_djp_mom": mom(rm_s, rl_s),
        "mtd_pct_sf": _pct_r(rm_s),
        "mtd_pct_sf_mom": _pct_r_mom(rm_s, rl_s),
        "mtd_djp_per_sf": djp_per_sf_day(rm_v, rm_s, hari_mtd_ini),
        "mtd_djp_per_sf_mom": _djp_per_sf_mom(rm_v, rl_v, rm_s, rl_s, hari_mtd_ini, hari_mtd_lalu),
    }

    return {
        "tgl"      : tgl,
        "bl_label" : bulan_lalu.strftime("%b %Y").upper(),
        "bi_label" : tgl.strftime("%b %Y").upper(),
        "region"   : region_row,
        "branches" : branch_rows,
        "woks"     : wok_rows,
    }
