def _safe_sum(vals):
    valid = [v for v in vals if v is not None]
    return sum(valid) if valid else None

def _tgt_val(v):
    return v if v is not None and v > 0 else None

"""
calculator_sql.py — Kalkulasi metrik IO, RE & PS dari data SQL (dashboard_hourly_sales)
Berbeda dari calculator.py (Hadoop/KPRO), di sini data sudah pre-aggregated per jam per WOK.
Jadi kita SUM(io_trx), SUM(re_trx) dan SUM(ps_trx) bukan COUNT(*).

mode='hourly'  : D = hari ini dengan cutoff jam terbaru
mode='closing' : D = tanggal tertentu full day
"""

import calendar
import pandas as pd
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME
# WOK dari sheet target HANYA ikut kalau termasuk 14 WOK baru — target lama (v7)
# yang masih tersimpan di bot tidak boleh memunculkan baris WOK lama berisi 0.
_WOK_BARU = {w.upper() for w in WOK_ORDER}
import db
try:
    from utils import fmc_api
except ImportError:
    import fmc_api


def hitung_re_ps_sql(target_df: pd.DataFrame,
                     upload_time: datetime,
                     mode: str = "hourly",
                     tgl_closing: date = None,
                     data_source: str = "db") -> dict:
    """
    Ambil data (dari MySQL atau FMC API, tergantung data_source) lalu hitung
    metrik IO, RE & PS. Output dict sama persis dengan hitung_re_ps() di
    calculator.py sehingga bisa langsung dipakai oleh renderer_daily.render_daily().

    data_source: "db" (default: mode hourly = MySQL dashboard_hourly_sales;
                 mode closing = MySQL indihome_ordering_detail, sejak 08-Okt-2026),
                 "fmc" (backup,
                 dashboard FMC Telkomsel via HTTP API), atau "raw" (backup,
                 dihitung ulang langsung dari tabel mentah
                 indihome_ordering_detail — lihat db.query_re_ps_raw()).
    """
    # ── Tentukan hari_ini ──────────────────────────────────────────────────
    if mode == "closing" and tgl_closing:
        hari_ini = tgl_closing
    else:
        hari_ini = datetime.now().date()

    # ── Ambil data ─────────────────────────────────────────────────────────
    if data_source == "fmc":
        rows = fmc_api.query_re_ps(hari_ini)
    elif data_source == "raw":
        rows = db.query_re_ps_raw(hari_ini)
    elif mode == "closing":
        # Closing (/closingsql): sumber = indihome_ordering_detail, bukan lagi
        # dashboard_hourly_sales (angka PS identik, IO/RE selisih <0,05%).
        rows = db.query_re_ps_raw(hari_ini)
    else:
        # Live (/liveupdate, /liveupdate_wa, jadwal otomatis): tetap
        # dashboard_hourly_sales, WOK/branch baru via kolom kabupaten.
        rows = db.query_re_ps(hari_ini, fallback_wok_lama=True)
    df   = pd.DataFrame(rows)

    if df.empty:
        raise ValueError(f"Tidak ada data di DB untuk tanggal s/d {hari_ini}")

    df["activity_date"] = pd.to_datetime(df["activity_date"]).dt.date
    df["wok"]           = df["wok"].str.strip().str.upper()
    df["branch"]        = df["branch"].str.strip().str.upper()
    # io_trx mungkin belum ada di sumber lama — default 0 kalau kolomnya absen
    if "io_trx" not in df.columns:
        df["io_trx"] = 0
    df["io_trx"]        = pd.to_numeric(df["io_trx"], errors="coerce").fillna(0).astype(int)
    df["re_trx"]        = pd.to_numeric(df["re_trx"], errors="coerce").fillna(0).astype(int)
    df["ps_trx"]        = pd.to_numeric(df["ps_trx"], errors="coerce").fillna(0).astype(int)

    # ── Cutoff jam (mode hourly) ───────────────────────────────────────────
    # activity_hour = int (0-23), ambil jam terbaru dari hari ini
    if mode == "hourly":
        df_hari     = df[df["activity_date"] == hari_ini]
        cutoff_hour = int(df_hari["activity_hour"].max()) if not df_hari.empty else 23
    else:
        cutoff_hour = 23  # closing = full day

    # ── Helper SUM io_trx/re_trx/ps_trx per WOK untuk rentang tanggal ──────
    def sum_col(col: str, tgl_start: date, tgl_end: date,
                max_hour: int = 23) -> dict:
        """SUM kolom per WOK untuk tgl_start s/d tgl_end dengan batas jam."""
        mask = (
            (df["activity_date"] >= tgl_start) &
            (df["activity_date"] <= tgl_end)
        )
        sub = df[mask].copy()
        # Untuk hari terakhir, nol-kan baris yang melewati cutoff
        mask_last = sub["activity_date"] == tgl_end
        sub.loc[mask_last & (sub["activity_hour"] > max_hour), col] = 0
        return sub.groupby("wok")[col].sum().to_dict()

    # ── Rentang periode ────────────────────────────────────────────────────
    # WoW: 7 hari rolling
    wow_cur_start  = hari_ini - timedelta(days=6)
    wow_cur_end    = hari_ini
    wow_prev_start = hari_ini - timedelta(days=13)
    wow_prev_end   = hari_ini - timedelta(days=7)

    # MoM: MtD bulan ini vs MtD bulan lalu (tanggal yang sama).
    # Kecuali kalau hari_ini adalah tanggal terakhir bulannya (closing) —
    # di situ dibandingkan ke tanggal terakhir bulan lalu juga, biar full
    # month vs full month meski jumlah harinya beda (mis. 30 Apr vs 31 Mar).
    awal_bulan_ini  = hari_ini.replace(day=1)
    awal_bulan_lalu = (hari_ini - relativedelta(months=1)).replace(day=1)

    _, last_day_ini = calendar.monthrange(hari_ini.year, hari_ini.month)
    if hari_ini.day == last_day_ini:
        _, last_day_lalu = calendar.monthrange(awal_bulan_lalu.year, awal_bulan_lalu.month)
        hari_bulan_lalu = awal_bulan_lalu.replace(day=last_day_lalu)
    else:
        hari_bulan_lalu = hari_ini - relativedelta(months=1)

    ch = cutoff_hour  # shorthand

    # ── Kemarin (untuk DoD) ───────────────────────────────────────────────
    kemarin = hari_ini - timedelta(days=1)

    # D-1 Full Day = kemarin sepanjang hari
    re_d1fd = sum_col("re_trx", kemarin, kemarin, 23)

    # D-1 Hourly = kemarin s/d jam yang sama dengan cutoff hari ini
    re_d1h  = sum_col("re_trx", kemarin, kemarin, ch)

    # ── 7 hari lalu (untuk Perbandingan mingguan/WoW hourly) ───────────────
    tujuh_hari_lalu = hari_ini - timedelta(days=7)

    # D-7 Full Day = 7 hari lalu sepanjang hari
    re_d7fd = sum_col("re_trx", tujuh_hari_lalu, tujuh_hari_lalu, 23)

    # D-7 Hourly = 7 hari lalu s/d jam yang sama dengan cutoff hari ini
    re_d7h  = sum_col("re_trx", tujuh_hari_lalu, tujuh_hari_lalu, ch)

    # ── IO counts ─────────────────────────────────────────────────────────
    io_d1       = sum_col("io_trx", kemarin,        kemarin,         ch)
    io_today    = sum_col("io_trx", hari_ini,        hari_ini,        ch)
    io_wow_cur  = sum_col("io_trx", wow_cur_start,   wow_cur_end,     ch)
    io_wow_prev = sum_col("io_trx", wow_prev_start,  wow_prev_end,    23)
    io_mom_cur  = sum_col("io_trx", awal_bulan_ini,  hari_ini,        ch)
    io_mom_prev = sum_col("io_trx", awal_bulan_lalu, hari_bulan_lalu, 23)
    # D-7 Hourly (dipakai panel D-1/Gap/D-7/Gap di renderer_simple.py) — io_d1
    # di atas sudah hourly-cutoff, cuma io_d7 yang belum ada.
    io_d7h      = sum_col("io_trx", tujuh_hari_lalu,   tujuh_hari_lalu,  ch)

    # ── RE counts ─────────────────────────────────────────────────────────
    re_today    = sum_col("re_trx", hari_ini,        hari_ini,        ch)
    re_wow_cur  = sum_col("re_trx", wow_cur_start,   wow_cur_end,     ch)
    re_wow_prev = sum_col("re_trx", wow_prev_start,  wow_prev_end,    23)
    re_mom_cur  = sum_col("re_trx", awal_bulan_ini,  hari_ini,        ch)
    re_mom_prev = sum_col("re_trx", awal_bulan_lalu, hari_bulan_lalu, 23)

    # ── PS counts ─────────────────────────────────────────────────────────
    ps_d1       = sum_col("ps_trx", kemarin,        kemarin,         ch)
    ps_today    = sum_col("ps_trx", hari_ini,        hari_ini,        ch)
    ps_wow_cur  = sum_col("ps_trx", wow_cur_start,   wow_cur_end,     ch)
    ps_wow_prev = sum_col("ps_trx", wow_prev_start,  wow_prev_end,    23)
    ps_mom_cur  = sum_col("ps_trx", awal_bulan_ini,  hari_ini,        ch)
    ps_mom_prev = sum_col("ps_trx", awal_bulan_lalu, hari_bulan_lalu, 23)
    # D-7 Hourly (dipakai panel D-1/Gap/D-7/Gap di renderer_simple.py) — ps_d1
    # di atas sudah hourly-cutoff, cuma ps_d7 yang belum ada.
    ps_d7h      = sum_col("ps_trx", tujuh_hari_lalu,   tujuh_hari_lalu,  ch)

    # ── Target ────────────────────────────────────────────────────────────
    target_io_map = {}
    target_re_map = {}
    target_ps_map = {}
    if target_df is not None and not target_df.empty:
        tdf = target_df.copy()
        tdf.columns = tdf.columns.str.strip().str.upper()

        # Format baru: ada kolom BULAN → filter sesuai bulan hari_ini
        if "BULAN" in tdf.columns:
            bulan_key = hari_ini.strftime("%Y-%m")
            tdf = tdf[tdf["BULAN"].astype(str).str.strip() == bulan_key]

        for _, row in tdf.iterrows():
            wok = str(row.get("WOK", "")).strip().upper()
            if not wok:
                continue
            try:
                target_io_map[wok] = int(row.get("TARGET_IO", 0) or 0)
            except (ValueError, TypeError):
                target_io_map[wok] = 0
            try:
                target_re_map[wok] = int(row.get("TARGET_RE", 0) or 0)
            except (ValueError, TypeError):
                target_re_map[wok] = 0
            try:
                target_ps_map[wok] = int(row.get("TARGET_PS", 0) or 0)
            except (ValueError, TypeError):
                target_ps_map[wok] = 0

    # ── Kumpulkan semua WOK ────────────────────────────────────────────────
    semua_wok = set(
        list(io_today)    + list(io_wow_cur)  + list(io_wow_prev) +
        list(io_mom_cur)  + list(io_mom_prev) +
        list(re_today)    + list(re_wow_cur)  + list(re_wow_prev) +
        list(re_mom_cur)  + list(re_mom_prev) +
        list(ps_today)    + list(ps_wow_cur)  + list(ps_wow_prev) +
        list(ps_mom_cur)  + list(ps_mom_prev) +
        [w for w in list(target_io_map) + list(target_re_map) + list(target_ps_map) if w in _WOK_BARU]
    )

    # KABUPATEN UNMAPPED hanya ditampilkan bila ada angkanya di kolom yang tampil
    # (hari ini / D-1 / D-7, IO-RE-PS); kalau semua nol, baris (dan branch
    # UNMAPPED-nya) tidak dibuat.
    _UNM = "KABUPATEN UNMAPPED"
    if _UNM in semua_wok:
        _tampil = (io_today, io_d1, io_d7h, re_today, re_d1fd, re_d1h, re_d7fd, re_d7h,
                   ps_today, ps_d1, ps_d7h)
        if not any(d.get(_UNM, 0) for d in _tampil):
            semua_wok.discard(_UNM)

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "UNMAPPED" if wok == "KABUPATEN UNMAPPED" else "LAINNYA"
        )
        io_t   = io_today.get(wok, 0)
        io_tgt = _tgt_val(target_io_map.get(wok))
        io_d1_v = io_d1.get(wok, 0)
        re_t   = re_today.get(wok, 0)
        re_tgt = _tgt_val(target_re_map.get(wok))
        re_d1fd_v = re_d1fd.get(wok, 0)
        re_d1h_v  = re_d1h.get(wok, 0)
        re_d7fd_v = re_d7fd.get(wok, 0)
        re_d7h_v  = re_d7h.get(wok, 0)
        ps_t   = ps_today.get(wok, 0)
        ps_tgt = _tgt_val(target_ps_map.get(wok))
        ps_d1_v = ps_d1.get(wok, 0)

        wok_rows.append({
            "level"      : "WOK",
            "name"       : wok,
            "branch"     : branch,
            # IO
            "io_target"  : io_tgt,
            "io_today"   : io_t,
            "io_d1"      : io_d1_v,
            "io_d7_hourly": io_d7h.get(wok, 0),
            "io_pct_ach" : _pct(io_t, io_tgt),
            "io_dod"     : _pct_growth(io_t, io_d1_v),
            "io_wow"     : _pct_growth(io_wow_cur.get(wok, 0), io_wow_prev.get(wok, 0)),
            "io_mom"     : _pct_growth(io_mom_cur.get(wok, 0), io_mom_prev.get(wok, 0)),
            # RE
            "re_target"  : re_tgt,
            "re_today"   : re_t,
            "re_d1_fd"   : re_d1fd_v,
            "re_d1_hourly": re_d1h_v,
            "re_d7_fd"   : re_d7fd_v,
            "re_d7_hourly": re_d7h_v,
            "re_pct_ach" : _pct(re_t, re_tgt),
            "re_dod"     : _pct_growth(re_t, re_d1h_v),
            "re_wow"     : _pct_growth(re_wow_cur.get(wok, 0), re_wow_prev.get(wok, 0)),
            "re_mom"     : _pct_growth(re_mom_cur.get(wok, 0), re_mom_prev.get(wok, 0)),
            # PS
            "ps_target"  : ps_tgt,
            "ps_today"   : ps_t,
            "ps_d1"      : ps_d1_v,
            "ps_d7_hourly": ps_d7h.get(wok, 0),
            "ps_pct_ach" : _pct(ps_t, ps_tgt),
            "ps_dod"     : _pct_growth(ps_t, ps_d1_v),
            "ps_wow"     : _pct_growth(ps_wow_cur.get(wok, 0), ps_wow_prev.get(wok, 0)),
            "ps_mom"     : _pct_growth(ps_mom_cur.get(wok, 0), ps_mom_prev.get(wok, 0)),
        })

    # Sort sesuai WOK_ORDER
    wok_order_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_order_up.index(r["name"])
                  if r["name"] in wok_order_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )

    for branch in branch_names:
        brows  = [r for r in wok_rows if r["branch"] == branch]
        if not brows:
            continue

        io_t    = sum(r["io_today"]   for r in brows)
        io_tgt  = _safe_sum(r["io_target"] for r in brows)
        io_d1_b = sum(io_d1.get(r["name"], 0) for r in brows)
        io_d7h_b  = sum(io_d7h.get(r["name"], 0) for r in brows)
        re_t    = sum(r["re_today"]   for r in brows)
        re_tgt  = _safe_sum(r["re_target"] for r in brows)
        re_d1fd_b = sum(re_d1fd.get(r["name"], 0) for r in brows)
        re_d1h_b  = sum(re_d1h.get(r["name"],  0) for r in brows)
        re_d7fd_b = sum(re_d7fd.get(r["name"], 0) for r in brows)
        re_d7h_b  = sum(re_d7h.get(r["name"],  0) for r in brows)
        ps_t    = sum(r["ps_today"]   for r in brows)
        ps_tgt  = _safe_sum(r["ps_target"] for r in brows)
        ps_d1_b = sum(ps_d1.get(r["name"], 0) for r in brows)
        ps_d7h_b  = sum(ps_d7h.get(r["name"], 0) for r in brows)

        io_wc = sum(io_wow_cur.get(r["name"], 0)  for r in brows)
        io_wp = sum(io_wow_prev.get(r["name"], 0) for r in brows)
        io_mc = sum(io_mom_cur.get(r["name"], 0)  for r in brows)
        io_mp = sum(io_mom_prev.get(r["name"], 0) for r in brows)
        re_wc = sum(re_wow_cur.get(r["name"], 0)  for r in brows)
        re_wp = sum(re_wow_prev.get(r["name"], 0) for r in brows)
        re_mc = sum(re_mom_cur.get(r["name"], 0)  for r in brows)
        re_mp = sum(re_mom_prev.get(r["name"], 0) for r in brows)
        ps_wc = sum(ps_wow_cur.get(r["name"], 0)  for r in brows)
        ps_wp = sum(ps_wow_prev.get(r["name"], 0) for r in brows)
        ps_mc = sum(ps_mom_cur.get(r["name"], 0)  for r in brows)
        ps_mp = sum(ps_mom_prev.get(r["name"], 0) for r in brows)

        branch_rows.append({
            "level"        : "BRANCH",
            "name"         : branch,
            # IO
            "io_target"  : io_tgt,
            "io_today"     : io_t,
            "io_d1"        : io_d1_b,
            "io_d7_hourly" : io_d7h_b,
            "io_pct_ach" : _pct(io_t, io_tgt),
            "io_dod"       : _pct_growth(io_t, io_d1_b),
            "io_wow"       : _pct_growth(io_wc, io_wp),
            "io_mom"       : _pct_growth(io_mc, io_mp),
            # RE
            "re_target"  : re_tgt,
            "re_today"     : re_t,
            "re_d1_fd"     : re_d1fd_b,
            "re_d1_hourly" : re_d1h_b,
            "re_d7_fd"     : re_d7fd_b,
            "re_d7_hourly" : re_d7h_b,
            "re_pct_ach" : _pct(re_t, re_tgt),
            "re_dod"       : _pct_growth(re_t, re_d1h_b),
            "re_wow"       : _pct_growth(re_wc, re_wp),
            "re_mom"       : _pct_growth(re_mc, re_mp),
            # PS
            "ps_target"  : ps_tgt,
            "ps_today"     : ps_t,
            "ps_d1"        : ps_d1_b,
            "ps_d7_hourly" : ps_d7h_b,
            "ps_pct_ach" : _pct(ps_t, ps_tgt),
            "ps_dod"       : _pct_growth(ps_t, ps_d1_b),
            "ps_wow"       : _pct_growth(ps_wc, ps_wp),
            "ps_mom"       : _pct_growth(ps_mc, ps_mp),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    io_t_reg    = sum(r["io_today"]  for r in branch_rows)
    io_tgt_reg  = _safe_sum(r["io_target"] for r in branch_rows)
    io_d1_reg   = sum(io_d1.get(w, 0) for w in semua_wok)
    io_d7h_reg  = sum(io_d7h.get(w, 0) for w in semua_wok)
    re_t_reg    = sum(r["re_today"]  for r in branch_rows)
    re_tgt_reg  = _safe_sum(r["re_target"] for r in branch_rows)
    re_d1fd_reg = sum(re_d1fd.get(w, 0) for w in semua_wok)
    re_d1h_reg  = sum(re_d1h.get(w, 0)  for w in semua_wok)
    re_d7fd_reg = sum(re_d7fd.get(w, 0) for w in semua_wok)
    re_d7h_reg  = sum(re_d7h.get(w, 0)  for w in semua_wok)
    ps_t_reg    = sum(r["ps_today"]  for r in branch_rows)
    ps_tgt_reg  = _safe_sum(r["ps_target"] for r in branch_rows)
    ps_d1_reg   = sum(ps_d1.get(w, 0) for w in semua_wok)
    ps_d7h_reg  = sum(ps_d7h.get(w, 0) for w in semua_wok)

    io_wc_reg = sum(io_wow_cur.get(w, 0)  for w in semua_wok)
    io_wp_reg = sum(io_wow_prev.get(w, 0) for w in semua_wok)
    io_mc_reg = sum(io_mom_cur.get(w, 0)  for w in semua_wok)
    io_mp_reg = sum(io_mom_prev.get(w, 0) for w in semua_wok)
    re_wc_reg = sum(re_wow_cur.get(w, 0)  for w in semua_wok)
    re_wp_reg = sum(re_wow_prev.get(w, 0) for w in semua_wok)
    re_mc_reg = sum(re_mom_cur.get(w, 0)  for w in semua_wok)
    re_mp_reg = sum(re_mom_prev.get(w, 0) for w in semua_wok)
    ps_wc_reg = sum(ps_wow_cur.get(w, 0)  for w in semua_wok)
    ps_wp_reg = sum(ps_wow_prev.get(w, 0) for w in semua_wok)
    ps_mc_reg = sum(ps_mom_cur.get(w, 0)  for w in semua_wok)
    ps_mp_reg = sum(ps_mom_prev.get(w, 0) for w in semua_wok)

    region_row = {
        "level"        : "REGION",
        "name"         : REGION_NAME,
        # IO
        "io_target"    : io_tgt_reg,
        "io_today"     : io_t_reg,
        "io_d1"        : io_d1_reg,
        "io_d7_hourly" : io_d7h_reg,
        "io_pct_ach"   : _pct(io_t_reg, io_tgt_reg),
        "io_dod"       : _pct_growth(io_t_reg, io_d1_reg),
        "io_wow"       : _pct_growth(io_wc_reg, io_wp_reg),
        "io_mom"       : _pct_growth(io_mc_reg, io_mp_reg),
        # RE
        "re_target"    : re_tgt_reg,
        "re_today"     : re_t_reg,
        "re_d1_fd"     : re_d1fd_reg,
        "re_d1_hourly" : re_d1h_reg,
        "re_d7_fd"     : re_d7fd_reg,
        "re_d7_hourly" : re_d7h_reg,
        "re_pct_ach"   : _pct(re_t_reg, re_tgt_reg),
        "re_dod"       : _pct_growth(re_t_reg, re_d1h_reg),
        "re_wow"       : _pct_growth(re_wc_reg, re_wp_reg),
        "re_mom"       : _pct_growth(re_mc_reg, re_mp_reg),
        # PS
        "ps_target"    : ps_tgt_reg,
        "ps_today"     : ps_t_reg,
        "ps_d1"        : ps_d1_reg,
        "ps_d7_hourly" : ps_d7h_reg,
        "ps_pct_ach"   : _pct(ps_t_reg, ps_tgt_reg),
        "ps_dod"       : _pct_growth(ps_t_reg, ps_d1_reg),
        "ps_wow"       : _pct_growth(ps_wc_reg, ps_wp_reg),
        "ps_mom"       : _pct_growth(ps_mc_reg, ps_mp_reg),
    }

    return {
        "upload_time" : upload_time,
        "hari_ini"    : hari_ini,
        "region"      : region_row,
        "branches"    : branch_rows,
        "woks"        : wok_rows,
        "mode"        : mode,
    }


def _pct_growth(cur, prev):
    if prev and prev > 0:
        return round((cur - prev) / prev * 100, 1)
    return None


def _pct(bagian, total):
    if total and total > 0:
        return round(bagian / total * 100, 1)
    return None
