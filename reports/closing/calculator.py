def _safe_sum(vals):
    valid = [v for v in vals if v is not None]
    return sum(valid) if valid else None

"""
calculator.py — Kalkulasi semua metrik RE
mode='hourly' : D = hari ini dengan cutoff jam, D-1 Hourly pakai cutoff jam
mode='closing': D = tanggal tertentu full day, D-1 = sehari sebelumnya full day
"""

import pandas as pd
from datetime import datetime, date
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME
# WOK dari sheet target HANYA ikut kalau termasuk 14 WOK baru — target lama (v7)
# yang masih tersimpan di bot tidak boleh memunculkan baris WOK lama berisi 0.
_WOK_BARU = {w.upper() for w in WOK_ORDER}


def hitung_re(df: pd.DataFrame, target_df: pd.DataFrame,
              upload_time: datetime, mode: str = "hourly",
              tgl_closing: date = None) -> dict:

    df = df.copy()
    df["DATECREATED"] = pd.to_datetime(df["DATECREATED"], errors="coerce")

    if mode == "closing" and tgl_closing:
        hari_ini = tgl_closing
    else:
        hari_ini = df["DATECREATED"].dt.date.max()

    kemarin     = (pd.Timestamp(hari_ini) - pd.Timedelta(days=1)).date()
    df_hari_ini = df[df["DATECREATED"].dt.date == hari_ini]
    df_kemarin  = df[df["DATECREATED"].dt.date == kemarin]

    # D = semua baris hari ini / tanggal closing
    re_d_wok = df_hari_ini.groupby("WOK").size().to_dict()

    # D-1 Full Day = sehari sebelumnya sepanjang hari
    re_d1fd_wok = df_kemarin.groupby("WOK").size().to_dict()

    # D-1 Hourly:
    # - mode hourly : kemarin dengan jam <= jam terbaru hari ini
    # - mode closing: sama dengan D-1 FD (full day)
    if mode == "closing":
        d1_hourly_wok = re_d1fd_wok.copy()
    else:
        jam_cutoff = df_hari_ini["DATECREATED"].max()
        cutoff_kemarin = pd.Timestamp(
            kemarin.year, kemarin.month, kemarin.day,
            jam_cutoff.hour, jam_cutoff.minute, jam_cutoff.second
        )
        df_d1h = df_kemarin[df_kemarin["DATECREATED"] <= cutoff_kemarin]
        d1_hourly_wok = df_d1h.groupby("WOK").size().to_dict()

    # Target
    target_map = {}
    if target_df is not None and not target_df.empty:
        target_df.columns = target_df.columns.str.strip().str.upper()
        for _, row in target_df.iterrows():
            wok = str(row.get("WOK", "")).strip().upper()
            try:
                tgt = int(row.get("TARGET_RE", 0) or 0)
            except (ValueError, TypeError):
                tgt = 0
            if wok:
                target_map[wok] = tgt

    re_d_wok_up    = {k.upper(): v for k, v in re_d_wok.items()}
    re_d1fd_wok_up = {k.upper(): v for k, v in re_d1fd_wok.items()}
    d1h_wok_up     = {k.upper(): v for k, v in d1_hourly_wok.items()}

    semua_wok = set(
        list(re_d_wok_up.keys()) +
        list(re_d1fd_wok_up.keys()) +
        [w for w in target_map.keys() if w in _WOK_BARU]
    )

    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )
        d    = re_d_wok_up.get(wok, 0)
        d1fd = re_d1fd_wok_up.get(wok, 0)
        d1h  = d1h_wok_up.get(wok, 0)
        tgt  = target_map.get(wok, 0)

        wok_rows.append({
            "level"      : "WOK",
            "name"       : wok,
            "branch"     : branch,
            "target"     : int(tgt) if tgt and tgt > 0 else None,
            "d1_fd"      : int(d1fd),
            "d1_hourly"  : int(d1h),
            "d"          : int(d),
            "pct_hourly" : _pct_growth(d, d1h),
            "gap_hourly" : int(d - d1h),
            "pct_fd"     : _pct_growth(d, d1fd),
            "gap_fd"     : int(d - d1fd),
            "pct_ach"    : _pct(d, tgt) if tgt is not None and tgt > 0 else None,
        })

    wok_order_up = [w.upper() for w in WOK_ORDER]
    def wok_sort_key(r):
        try:
            return wok_order_up.index(r["name"].upper())
        except ValueError:
            return 999
    wok_rows.sort(key=wok_sort_key)

    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(set(
        r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER
    ))

    for branch in branch_names:
        rows = [r for r in wok_rows if r["branch"] == branch]
        if not rows:
            continue
        d    = sum(r["d"]         for r in rows)
        d1fd = sum(r["d1_fd"]     for r in rows)
        d1h  = sum(r["d1_hourly"] for r in rows)
        tgt  = _safe_sum(r["target"] for r in rows)

        branch_rows.append({
            "level"      : "BRANCH",
            "name"       : branch,
            "target"     : int(tgt) if tgt and tgt > 0 else None,
            "d1_fd"      : int(d1fd),
            "d1_hourly"  : int(d1h),
            "d"          : int(d),
            "pct_hourly" : _pct_growth(d, d1h),
            "gap_hourly" : int(d - d1h),
            "pct_fd"     : _pct_growth(d, d1fd),
            "gap_fd"     : int(d - d1fd),
            "pct_ach"    : _pct(d, tgt) if tgt is not None and tgt > 0 else None,
        })

    d    = sum(r["d"]         for r in branch_rows)
    d1fd = sum(r["d1_fd"]     for r in branch_rows)
    d1h  = sum(r["d1_hourly"] for r in branch_rows)
    tgt  = _safe_sum(r["target"] for r in branch_rows)

    region_row = {
        "level"      : "REGION",
        "name"       : REGION_NAME,
        "target"     : int(tgt) if tgt and tgt > 0 else None,
        "d1_fd"      : int(d1fd),
        "d1_hourly"  : int(d1h),
        "d"          : int(d),
        "pct_hourly" : _pct_growth(d, d1h),
        "gap_hourly" : int(d - d1h),
        "pct_fd"     : _pct_growth(d, d1fd),
        "gap_fd"     : int(d - d1fd),
        "pct_ach"    : _pct(d, tgt) if tgt is not None and tgt > 0 else None,
    }

    return {
        "upload_time" : upload_time,
        "hari_ini"    : hari_ini,
        "region"      : region_row,
        "branches"    : branch_rows,
        "woks"        : wok_rows,
        "mode"        : mode,
    }


def _pct_growth(d, d1):
    if d1 and d1 > 0:
        return round((d - d1) / d1 * 100, 1)
    return None


def _pct(bagian, total):
    if total and total > 0:
        return round(bagian / total * 100, 1)
    return None


def hitung_re_ps(df: pd.DataFrame, target_df: pd.DataFrame,
                 upload_time: datetime, mode: str = "hourly",
                 tgl_closing: date = None) -> dict:
    """
    Hitung metrik RE dan PS secara bersamaan dari data Hadoop.
    RE  → re_ts (sudah di-rename ke DATECREATED di bot.py)
    PS  → ps_ts
    Kolom output per metrik: target, today, pct_ach, wow, mom
    """
    df = df.copy()

    # DATECREATED sudah di-rename dari re_ts di bot.py
    df["DATECREATED"] = pd.to_datetime(df["DATECREATED"], errors="coerce")

    # ps_ts — parse jika belum datetime
    if "ps_ts" in df.columns:
        df["ps_ts"] = pd.to_datetime(df["ps_ts"], errors="coerce")
    elif "PS_TS" in df.columns:
        df["ps_ts"] = pd.to_datetime(df["PS_TS"], errors="coerce")
    else:
        df["ps_ts"] = pd.NaT

    if mode == "closing" and tgl_closing:
        hari_ini = tgl_closing
    else:
        hari_ini = df["DATECREATED"].dt.date.max()

    hari_ini_ts = pd.Timestamp(hari_ini)

    # WoW: rolling 7 hari
    # Minggu ini  = (hari ini - 6) s/d hari ini
    # Minggu lalu = (hari ini - 13) s/d (hari ini - 7)
    wow_cur_start  = (hari_ini_ts - pd.Timedelta(days=6)).date()
    wow_cur_end    = hari_ini
    wow_prev_start = (hari_ini_ts - pd.Timedelta(days=13)).date()
    wow_prev_end   = (hari_ini_ts - pd.Timedelta(days=7)).date()

    # MoM: tanggal 1 s/d hari ini bulan ini vs tanggal 1 s/d tanggal sama bulan lalu
    awal_bulan_ini  = hari_ini_ts.replace(day=1).date()
    awal_bulan_lalu = (hari_ini_ts - pd.DateOffset(months=1)).replace(day=1).date()
    hari_bulan_lalu = (hari_ini_ts - pd.DateOffset(months=1)).date()

    # ── Target ────────────────────────────────────────────────────────────
    target_re_map = {}
    target_ps_map = {}
    if target_df is not None and not target_df.empty:
        tdf = target_df.copy()
        tdf.columns = tdf.columns.str.strip().str.upper()
        for _, row in tdf.iterrows():
            wok = str(row.get("WOK", "")).strip().upper()
            if not wok:
                continue
            try:
                target_re_map[wok] = int(row.get("TARGET_RE", 0) or 0)
            except (ValueError, TypeError):
                target_re_map[wok] = 0
            try:
                target_ps_map[wok] = int(row.get("TARGET_PS", 0) or 0)
            except (ValueError, TypeError):
                target_ps_map[wok] = 0

    # ── Helper: count per WOK untuk range tanggal ────────────────────────
    def count_range(src_col: str, tgl_start: date, tgl_end: date,
                    cutoff_time=None) -> dict:
        """Hitung count per WOK untuk periode tgl_start s/d tgl_end (inklusif)."""
        mask = (df[src_col].dt.date >= tgl_start) & (df[src_col].dt.date <= tgl_end)
        sub  = df[mask]
        if cutoff_time is not None:
            # Untuk hari terakhir saja, batasi jam
            mask_last = sub[src_col].dt.date == tgl_end
            sub_other = sub[~mask_last]
            sub_last  = sub[mask_last]
            sub_last  = sub_last[sub_last[src_col].dt.time <= cutoff_time]
            sub = pd.concat([sub_other, sub_last])
        return sub.groupby("WOK").size().to_dict()

    def count_range_ps(tgl_start: date, tgl_end: date, cutoff_time=None) -> dict:
        mask = (df_ps["ps_ts"].dt.date >= tgl_start) & (df_ps["ps_ts"].dt.date <= tgl_end)
        sub  = df_ps[mask]
        if cutoff_time is not None:
            mask_last = sub["ps_ts"].dt.date == tgl_end
            sub_other = sub[~mask_last]
            sub_last  = sub[mask_last]
            sub_last  = sub_last[sub_last["ps_ts"].dt.time <= cutoff_time]
            sub = pd.concat([sub_other, sub_last])
        return sub.groupby("WOK").size().to_dict()

    # PS dataframe (ps_ts tidak null)
    df_ps = df[df["ps_ts"].notna()]

    # Cutoff jam untuk mode hourly (batas jam terbaru hari ini)
    if mode == "closing":
        cutoff_re = None
        cutoff_ps = None
    else:
        jam_re = df[df["DATECREATED"].dt.date == hari_ini]["DATECREATED"].max()
        cutoff_re = jam_re.time() if pd.notna(jam_re) else None
        jam_ps = df_ps[df_ps["ps_ts"].dt.date == hari_ini]["ps_ts"].max()
        cutoff_ps = jam_ps.time() if pd.notna(jam_ps) else None

    # ── RE counts ─────────────────────────────────────────────────────────
    # TODAY: hari ini saja
    re_today = count_range("DATECREATED", hari_ini, hari_ini, cutoff_re)

    # WoW: rolling 7 hari cur vs prev
    re_wow_cur  = count_range("DATECREATED", wow_cur_start,  wow_cur_end,  cutoff_re)
    re_wow_prev = count_range("DATECREATED", wow_prev_start, wow_prev_end)

    # MoM: MtD bulan ini vs MtD bulan lalu
    re_mom_cur  = count_range("DATECREATED", awal_bulan_ini,  hari_ini,       cutoff_re)
    re_mom_prev = count_range("DATECREATED", awal_bulan_lalu, hari_bulan_lalu)

    # ── PS counts ─────────────────────────────────────────────────────────
    ps_today = count_range_ps(hari_ini, hari_ini, cutoff_ps)

    ps_wow_cur  = count_range_ps(wow_cur_start,  wow_cur_end,  cutoff_ps)
    ps_wow_prev = count_range_ps(wow_prev_start, wow_prev_end)

    ps_mom_cur  = count_range_ps(awal_bulan_ini,  hari_ini,       cutoff_ps)
    ps_mom_prev = count_range_ps(awal_bulan_lalu, hari_bulan_lalu)

    def up(d):
        return {k.upper(): v for k, v in d.items()}

    re_today_u    = up(re_today)
    re_wow_cur_u  = up(re_wow_cur)
    re_wow_prev_u = up(re_wow_prev)
    re_mom_cur_u  = up(re_mom_cur)
    re_mom_prev_u = up(re_mom_prev)
    ps_today_u    = up(ps_today)
    ps_wow_cur_u  = up(ps_wow_cur)
    ps_wow_prev_u = up(ps_wow_prev)
    ps_mom_cur_u  = up(ps_mom_cur)
    ps_mom_prev_u = up(ps_mom_prev)

    semua_wok = set(
        list(re_today_u) + list(re_wow_cur_u) + list(re_wow_prev_u) +
        list(re_mom_cur_u) + list(re_mom_prev_u) +
        list(ps_today_u) + list(ps_wow_cur_u) + list(ps_wow_prev_u) +
        list(ps_mom_cur_u) + list(ps_mom_prev_u) +
        [w for w in list(target_re_map) + list(target_ps_map) if w in _WOK_BARU]
    )

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )
        # RE
        re_t        = re_today_u.get(wok, 0)
        re_wc       = re_wow_cur_u.get(wok, 0)
        re_wp       = re_wow_prev_u.get(wok, 0)
        re_mc       = re_mom_cur_u.get(wok, 0)
        re_mp       = re_mom_prev_u.get(wok, 0)
        re_tgt      = target_re_map.get(wok, 0)

        # PS
        ps_t        = ps_today_u.get(wok, 0)
        ps_wc       = ps_wow_cur_u.get(wok, 0)
        ps_wp       = ps_wow_prev_u.get(wok, 0)
        ps_mc       = ps_mom_cur_u.get(wok, 0)
        ps_mp       = ps_mom_prev_u.get(wok, 0)
        ps_tgt      = target_ps_map.get(wok, 0)

        wok_rows.append({
            "level"      : "WOK",
            "name"       : wok,
            "branch"     : branch,
            # RE
            "re_target"  : re_tgt if re_tgt and re_tgt > 0 else None,
            "re_today"   : re_t,
            "re_pct_ach" : _pct(re_t, re_tgt) if re_tgt is not None and re_tgt > 0 else None,
            "re_wow"     : _pct_growth(re_wc, re_wp),
            "re_mom"     : _pct_growth(re_mc, re_mp),
            # PS
            "ps_target"  : ps_tgt if ps_tgt and ps_tgt > 0 else None,
            "ps_today"   : ps_t,
            "ps_pct_ach" : _pct(ps_t, ps_tgt) if ps_tgt is not None and ps_tgt > 0 else None,
            "ps_wow"     : _pct_growth(ps_wc, ps_wp),
            "ps_mom"     : _pct_growth(ps_mc, ps_mp),
        })

    wok_order_up = [w.upper() for w in WOK_ORDER]
    def wok_sort_key(r):
        try:
            return wok_order_up.index(r["name"].upper())
        except ValueError:
            return 999
    wok_rows.sort(key=wok_sort_key)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(set(
        r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER
    ))

    for branch in branch_names:
        rows = [r for r in wok_rows if r["branch"] == branch]
        if not rows:
            continue

        def s(key):
            return sum(r[key] for r in rows)

        re_t   = s("re_today")
        re_tgt = s("re_target")
        ps_t   = s("ps_today")
        ps_tgt = s("ps_target")

        re_wc = sum(re_wow_cur_u.get(r["name"], 0)  for r in rows)
        re_wp = sum(re_wow_prev_u.get(r["name"], 0) for r in rows)
        re_mc = sum(re_mom_cur_u.get(r["name"], 0)  for r in rows)
        re_mp = sum(re_mom_prev_u.get(r["name"], 0) for r in rows)
        ps_wc = sum(ps_wow_cur_u.get(r["name"], 0)  for r in rows)
        ps_wp = sum(ps_wow_prev_u.get(r["name"], 0) for r in rows)
        ps_mc = sum(ps_mom_cur_u.get(r["name"], 0)  for r in rows)
        ps_mp = sum(ps_mom_prev_u.get(r["name"], 0) for r in rows)

        branch_rows.append({
            "level"      : "BRANCH",
            "name"       : branch,
            "re_target"  : re_tgt if re_tgt and re_tgt > 0 else None,
            "re_today"   : re_t,
            "re_pct_ach" : _pct(re_t, re_tgt) if re_tgt is not None and re_tgt > 0 else None,
            "re_wow"     : _pct_growth(re_wc, re_wp),
            "re_mom"     : _pct_growth(re_mc, re_mp),
            "ps_target"  : ps_tgt if ps_tgt and ps_tgt > 0 else None,
            "ps_today"   : ps_t,
            "ps_pct_ach" : _pct(ps_t, ps_tgt) if ps_tgt is not None and ps_tgt > 0 else None,
            "ps_wow"     : _pct_growth(ps_wc, ps_wp),
            "ps_mom"     : _pct_growth(ps_mc, ps_mp),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    def sb(key):
        return sum(r[key] for r in branch_rows)

    re_t_reg   = sb("re_today")
    re_tgt_reg = _safe_sum(r.get("re_target") for r in branch_rows)
    ps_t_reg   = sb("ps_today")
    ps_tgt_reg = _safe_sum(r.get("ps_target") for r in branch_rows)

    re_wc_reg = sum(re_wow_cur_u.get(w, 0)  for w in semua_wok)
    re_wp_reg = sum(re_wow_prev_u.get(w, 0) for w in semua_wok)
    re_mc_reg = sum(re_mom_cur_u.get(w, 0)  for w in semua_wok)
    re_mp_reg = sum(re_mom_prev_u.get(w, 0) for w in semua_wok)
    ps_wc_reg = sum(ps_wow_cur_u.get(w, 0)  for w in semua_wok)
    ps_wp_reg = sum(ps_wow_prev_u.get(w, 0) for w in semua_wok)
    ps_mc_reg = sum(ps_mom_cur_u.get(w, 0)  for w in semua_wok)
    ps_mp_reg = sum(ps_mom_prev_u.get(w, 0) for w in semua_wok)

    region_row = {
        "level"      : "REGION",
        "name"       : REGION_NAME,
        "re_target"  : re_tgt_reg,
        "re_today"   : re_t_reg,
        "re_pct_ach" : _pct(re_t_reg, re_tgt_reg) if re_tgt_reg is not None and re_tgt_reg > 0 else None,
        "re_wow"     : _pct_growth(re_wc_reg, re_wp_reg),
        "re_mom"     : _pct_growth(re_mc_reg, re_mp_reg),
        "ps_target"  : ps_tgt_reg,
        "ps_today"   : ps_t_reg,
        "ps_pct_ach" : _pct(ps_t_reg, ps_tgt_reg) if ps_tgt_reg is not None and ps_tgt_reg > 0 else None,
        "ps_wow"     : _pct_growth(ps_wc_reg, ps_wp_reg),
        "ps_mom"     : _pct_growth(ps_mc_reg, ps_mp_reg),
    }

    return {
        "upload_time" : upload_time,
        "hari_ini"    : hari_ini,
        "region"      : region_row,
        "branches"    : branch_rows,
        "woks"        : wok_rows,
        "mode"        : mode,
    }
