def _safe_sum(vals):
    valid = [v for v in vals if v is not None]
    return sum(valid) if valid else None

"""
calculator_daily.py — Kalkulasi Daily Performance dari dashboard_hourly_sales
Source: dashboard_hourly_sales_YYYYMM (sudah pre-aggregated)
Kolom: region, branch, wok, kabupaten, activity_date, activity_hour,
       io_trx, re_trx, ps_trx, ps_rev
"""

import pandas as pd
import calendar
import io
import zipfile
import logging
import mysql.connector
import mysql.connector.conversion
from mysql.connector import Error
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import db
try:
    from utils import fmc_api
except ImportError:
    import fmc_api
import wilayah
from config import (DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME,
                    WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER,
                    WOK_ORDER_BARU as WOK_ORDER, REGION_NAME)

logger = logging.getLogger(__name__)


class RawMySQLConverter(mysql.connector.conversion.MySQLConverter):
    """
    Untuk export raw CSV: kembalikan DATETIME, TIMESTAMP, dan DATE apa adanya
    sebagai string dari MySQL (format 24-jam YYYY-MM-DD HH:MM:SS dan '0000-00-00 00:00:00'),
    tanpa diubah menjadi objek Python datetime (yang otomatis membuat 'NaT' di pandas).
    """
    def _datetime_to_python(self, value, dsc=None):
        return value.decode("ascii", errors="ignore") if value is not None else None

    def _timestamp_to_python(self, value, dsc=None):
        return value.decode("ascii", errors="ignore") if value is not None else None

    def _date_to_python(self, value, dsc=None):
        return value.decode("ascii", errors="ignore") if value is not None else None

TABLE_PREFIX  = "dashboard_hourly_sales_"
# Label region tidak konsisten antar-bulan di sumber data (lihat db.DB_REGION_LIKE) —
# pakai LIKE prefix yang sama, bukan exact match, biar tidak putus lagi.
REGION_FILTER = db.DB_REGION_LIKE


def get_connection():
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASS, database=DB_NAME, connect_timeout=10,
    )


def get_table(tgl: date) -> str:
    return f"{TABLE_PREFIX}{tgl.strftime('%Y%m')}"


def _query_dashboard_hourly_sales(tgl_closing: date):
    """
    Query dashboard_hourly_sales bulan ini (MtD) dan bulan lalu (MtD, tanggal sama).
    Return (df_ini, df_lalu).
    """
    tabel_ini  = get_table(tgl_closing)
    bulan_lalu = tgl_closing - relativedelta(months=1)
    tabel_lalu = get_table(bulan_lalu)

    awal_ini   = tgl_closing.replace(day=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    # MtD bulan lalu = tanggal yang sama dengan bulan ini, tidak boleh
    # melebihi hari terakhir bulan lalu. KECUALI tgl_closing adalah tanggal
    # terakhir bulannya (closing) — dibandingkan ke tanggal terakhir bulan
    # lalu juga, biar full month vs full month meski jumlah harinya beda
    # (mis. 30 April vs 31 Maret, bukan 30 Maret).
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_max_ini  = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]
    if tgl_closing.day == hari_max_ini:
        hari_mtd = hari_max_lalu
    else:
        hari_mtd = min(tgl_closing.day, hari_max_lalu)
    akhir_lalu    = date(bulan_lalu.year, bulan_lalu.month, hari_mtd)

    # WOK/BRANCH baru dipetakan dari kabupaten (wilayah.py); kabupaten kosong/NAN/
    # luar JATENG-DIY dibuang lewat _OK_KAB di WHERE.
    cols = (f"{db._WOK_KAB} AS wok, {db._BRANCH_KAB} AS branch, {db._KAB_NAMA} AS kabupaten, "
            "activity_date, SUM(io_trx) as io_trx, SUM(re_trx) as re_trx, "
            "SUM(ps_trx) as ps_trx, SUM(ps_rev) as ps_rev")

    def query(tabel, tgl_dari, tgl_sampai):
        sql = f"""
            SELECT {cols}
            FROM `{tabel}`
            WHERE region LIKE %s
              AND {db._OK_KAB}
              AND activity_date BETWEEN %s AND %s
            GROUP BY {db._WOK_KAB}, {db._BRANCH_KAB}, {db._KAB_NAMA}, activity_date
        """
        try:
            conn = get_connection()
            cur  = conn.cursor(dictionary=True)
            cur.execute(sql, (REGION_FILTER, tgl_dari, tgl_sampai))
            rows = cur.fetchall()
            cur.close(); conn.close()
            logger.info(f"Query {tabel}: {len(rows)} baris")
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        except Error as e:
            logger.warning(f"Query {tabel} gagal: {e}")
            return pd.DataFrame()

    df_ini  = query(tabel_ini,  awal_ini,   tgl_closing)
    df_lalu = query(tabel_lalu, awal_lalu,  akhir_lalu)

    for df in [df_ini, df_lalu]:
        if not df.empty:
            df["activity_date"] = pd.to_datetime(df["activity_date"]).dt.date
            for col in ["io_trx","re_trx","ps_trx"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
            df["ps_rev"] = pd.to_numeric(df["ps_rev"], errors="coerce").fillna(0).astype(int)
            df["wok"]       = df["wok"].str.strip().str.upper()
            df["branch"]    = df["branch"].str.strip().str.upper()
            df["kabupaten"] = df["kabupaten"].str.strip().str.upper()

    # df_today = filter hanya tanggal closing
    df_today = df_ini[df_ini["activity_date"] == tgl_closing].copy() if not df_ini.empty else pd.DataFrame()

    return df_ini, df_lalu, df_today


def _query_dashboard(tgl_closing: date):
    """
    Sumber Performance MtD by WOK / by City (/closingsql): tabel
    indihome_ordering_detail_YYYYMM (db.query_daily_city_raw), BUKAN lagi
    dashboard_hourly_sales. Angkanya dijaga sama: PS & revenue (SUM price_package
    order PS) persis sama dgn dashboard, IO/RE selisih <0,05%.

    MtD bulan ini s/d tgl_closing vs MtD bulan lalu pada tanggal yang sama
    (aturan akhir bulan sama seperti versi dashboard).
    Return (df_ini, df_lalu, df_today) — kolom: wok, branch, kabupaten,
    activity_date, io_trx, re_trx, ps_trx, ps_rev.
    Versi lama (dashboard_hourly_sales) disimpan di _query_dashboard_hourly_sales().
    """
    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_ini   = tgl_closing.replace(day=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_max_ini  = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]
    if tgl_closing.day == hari_max_ini:
        hari_mtd = hari_max_lalu
    else:
        hari_mtd = min(tgl_closing.day, hari_max_lalu)
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month, hari_mtd)

    def to_df(rows):
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["activity_date"] = pd.to_datetime(df["activity_date"]).dt.date
        for col in ["io_trx", "re_trx", "ps_trx", "ps_rev"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        for col in ["wok", "branch", "kabupaten"]:
            df[col] = df[col].astype(str).str.strip().str.upper()
        return df

    df_ini  = to_df(db.query_daily_city_raw(awal_ini,  tgl_closing))
    df_lalu = to_df(db.query_daily_city_raw(awal_lalu, akhir_lalu))
    df_today = (
        df_ini[df_ini["activity_date"] == tgl_closing].copy()
        if not df_ini.empty else pd.DataFrame()
    )
    return df_ini, df_lalu, df_today


def _query_dashboard_fmc(tgl_closing: date):
    """
    Setara _query_dashboard(), tapi dari fmc_api.query_daily_performance_fmc()
    (order-level FMC, bukan tabel dashboard_hourly_sales).

    CATATAN: revenue (ps_rev) selalu 0 di sini karena field itu tidak ada di
    payload FMC (sudah dicek langsung, lihat catatan di fmc_api.py) — jadi
    rev_mtd/rev_mom/arpu di hasil hitung_daily_performance(data_source="fmc")
    tidak bisa dipakai, cuma IO/RE/PS/achievement yang valid.
    """
    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_ini   = tgl_closing.replace(day=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_max_ini  = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]
    if tgl_closing.day == hari_max_ini:
        hari_mtd = hari_max_lalu
    else:
        hari_mtd = min(tgl_closing.day, hari_max_lalu)
    akhir_lalu    = date(bulan_lalu.year, bulan_lalu.month, hari_mtd)

    def to_df(rows):
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["ps_rev"] = 0
        return df

    df_ini  = to_df(fmc_api.query_daily_performance_fmc(awal_ini,  tgl_closing))
    df_lalu = to_df(fmc_api.query_daily_performance_fmc(awal_lalu, akhir_lalu))
    df_today = (
        df_ini[df_ini["activity_date"] == tgl_closing].copy()
        if not df_ini.empty else pd.DataFrame()
    )
    return df_ini, df_lalu, df_today


def _query_dashboard_raw(tgl_closing: date):
    """
    Setara _query_dashboard(), tapi dari db.query_daily_performance_raw()
    (tabel raw indihome_ordering_detail_YYYYMM, bukan dashboard_hourly_sales).
    Dipakai /closingbk.

    CATATAN: revenue (ps_rev) selalu 0 di sini — sama seperti
    _query_dashboard_fmc(), kolom revenue di raw table belum terverifikasi
    namanya jadi tidak ditebak (lihat db.query_daily_performance_raw()).
    Jadi rev_mtd/rev_mom/arpu di hasil
    hitung_daily_performance(data_source="raw") tidak bisa dipakai, cuma
    IO/RE/PS/achievement yang valid.
    """
    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_ini   = tgl_closing.replace(day=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_max_ini  = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]
    if tgl_closing.day == hari_max_ini:
        hari_mtd = hari_max_lalu
    else:
        hari_mtd = min(tgl_closing.day, hari_max_lalu)
    akhir_lalu    = date(bulan_lalu.year, bulan_lalu.month, hari_mtd)

    def to_df(rows):
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["ps_rev"] = 0
        return df

    df_ini  = to_df(db.query_daily_performance_raw(awal_ini,  tgl_closing))
    df_lalu = to_df(db.query_daily_performance_raw(awal_lalu, akhir_lalu))
    df_today = (
        df_ini[df_ini["activity_date"] == tgl_closing].copy()
        if not df_ini.empty else pd.DataFrame()
    )
    return df_ini, df_lalu, df_today


def _agg_by(df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    """Agregasi IO/RE/PS/Revenue per group."""
    if df.empty:
        return pd.DataFrame()
    return df.groupby(group_cols).agg(
        io=("io_trx","sum"), re=("re_trx","sum"),
        ps=("ps_trx","sum"), revenue=("ps_rev","sum")
    ).reset_index()


def _build_row(name, io_mtd, io_mom, io_today, re_mtd, re_mom, re_today,
               ps_mtd, ps_mom, ps_today, rev_mtd, rev_mom,
               tgt_io, tgt_re, tgt_ps, hari_mtd, total_hari) -> dict:
    def _tgt_val(v):  return round(v) if v is not None and v > 0 else None
    def pct(a,b):     return round(a/b*100,2) if a is not None and b and b>0 else None
    def mom_pct(a,b): return round((a-b)/b*100,2) if a is not None and b is not None and b>0 else None
    def drr(mtd,tgt): return round((mtd/hari_mtd)/(tgt/total_hari)*100,2) if mtd is not None and tgt and hari_mtd else None
    def arpu(rev,ps): return round(rev/ps) if rev is not None and ps and ps>0 else None
    def dev(a,b):     return round(a-b,2) if a is not None and b is not None else None

    io_re_lalu = pct(re_mom,io_mom); io_re_mtd = pct(re_mtd,io_mtd)
    re_ps_lalu = pct(ps_mom,re_mom); re_ps_mtd = pct(ps_mtd,re_mtd)

    return {
        "name"       : name,
        "io_tgt"     : _tgt_val(tgt_io), "io_mtd_lalu": io_mom, "io_today": io_today, "io_mtd": io_mtd,
        "io_mom"     : mom_pct(io_mtd,io_mom),
        "io_drr"     : drr(io_mtd,tgt_io),
        "io_ach"     : pct(io_mtd,tgt_io),
        "re_tgt"     : _tgt_val(tgt_re), "re_mtd_lalu": re_mom, "re_today": re_today, "re_mtd": re_mtd,
        "re_mom"     : mom_pct(re_mtd,re_mom),
        "re_drr"     : drr(re_mtd,tgt_re),
        "re_ach"     : pct(re_mtd,tgt_re),
        "ps_tgt"     : _tgt_val(tgt_ps), "ps_mtd_lalu": ps_mom, "ps_today": ps_today, "ps_mtd": ps_mtd,
        "ps_mom"     : mom_pct(ps_mtd,ps_mom),
        "ps_drr"     : drr(ps_mtd,tgt_ps),
        "ps_ach"     : pct(ps_mtd,tgt_ps),
        "io_re_lalu" : io_re_lalu, "io_re_mtd": io_re_mtd,
        "io_re_dev"  : dev(io_re_mtd,io_re_lalu),
        "re_ps_lalu" : re_ps_lalu, "re_ps_mtd": re_ps_mtd,
        "re_ps_dev"  : dev(re_ps_mtd,re_ps_lalu),
        "rev_mom"    : rev_mom, "rev_mtd": rev_mtd,
        "arpu_mom"   : arpu(rev_mom,ps_mom), "arpu_mtd": arpu(rev_mtd,ps_mtd),
        "mom_rev"    : mom_pct(rev_mtd,rev_mom),
        "mom_arpu"   : mom_pct(arpu(rev_mtd,ps_mtd),arpu(rev_mom,ps_mom)),
    }


def _get_target(target_monthly_df, tgl_closing):
    """Ambil target IO/RE/PS per WOK untuk bulan closing."""
    tgt_io = {}; tgt_re = {}; tgt_ps = {}
    if target_monthly_df is not None and not target_monthly_df.empty:
        tdf = target_monthly_df.copy()
        tdf.columns = tdf.columns.str.strip().str.upper()
        bulan_key = tgl_closing.strftime("%Y-%m")
        if "BULAN" in tdf.columns:
            tdf = tdf[tdf["BULAN"].astype(str).str.strip() == bulan_key]
        for _, row in tdf.iterrows():
            wok = str(row.get("WOK","")).strip().upper()
            if not wok: continue
            tgt_io[wok] = float(row.get("TARGET_IO",0) or 0)
            tgt_re[wok] = float(row.get("TARGET_RE",0) or 0)
            tgt_ps[wok] = float(row.get("TARGET_PS",0) or 0)
    return tgt_io, tgt_re, tgt_ps


def _get_target_city(target_city_df, tgl_closing):
    """Ambil target IO/RE/PS per City (kabupaten) untuk bulan closing."""
    tgt_io = {}; tgt_re = {}; tgt_ps = {}
    if target_city_df is not None and not target_city_df.empty:
        tdf = target_city_df.copy()
        tdf.columns = tdf.columns.str.strip().str.upper()
        bulan_key = tgl_closing.strftime("%Y-%m")
        if "BULAN" in tdf.columns:
            tdf = tdf[tdf["BULAN"].astype(str).str.strip() == bulan_key]
        for _, row in tdf.iterrows():
            wok  = str(row.get("WOK","")).strip().upper()
            city = str(row.get("CITY","")).strip().upper()
            if not wok or not city: continue
            key = (wok, city)
            tgt_io[key] = float(row.get("TARGET_IO",0) or 0)
            tgt_re[key] = float(row.get("TARGET_RE",0) or 0)
            tgt_ps[key] = float(row.get("TARGET_PS",0) or 0)
    return tgt_io, tgt_re, tgt_ps


def hitung_daily_performance(target_monthly_df, tgl_closing: date,
                              data_source: str = "db") -> dict:
    """
    Kalkulasi Daily Performance level WOK.
    data_source="fmc" -> pakai FMC API (lihat _query_dashboard_fmc, revenue/ARPU
    tidak tersedia dari sumber ini).
    data_source="raw" -> pakai tabel raw indihome_ordering_detail langsung
    (lihat _query_dashboard_raw, revenue/ARPU juga tidak tersedia).
    """
    if data_source == "fmc":
        df_ini, df_lalu, df_today = _query_dashboard_fmc(tgl_closing)
    elif data_source == "raw":
        df_ini, df_lalu, df_today = _query_dashboard_raw(tgl_closing)
    else:
        df_ini, df_lalu, df_today = _query_dashboard(tgl_closing)

    hari_mtd   = tgl_closing.day
    total_hari = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]

    tgt_io, tgt_re, tgt_ps = _get_target(target_monthly_df, tgl_closing)

    # Agregasi per WOK
    ag_ini   = _agg_by(df_ini,   ["wok","branch"])
    ag_lalu  = _agg_by(df_lalu,  ["wok","branch"])
    ag_today = _agg_by(df_today, ["wok","branch"])

    def get(df, wok, col):
        r = df[df["wok"]==wok]
        return int(r[col].values[0]) if not r.empty else 0

    semua_wok = set()
    if not ag_ini.empty:  semua_wok |= set(ag_ini["wok"])
    if not ag_lalu.empty: semua_wok |= set(ag_lalu["wok"])
    # WOK dari sheet target hanya ikut kalau termasuk 14 WOK baru (target lama v7 yang
    # masih tersimpan tidak boleh memunculkan baris WOK lama berisi 0 / branch LAINNYA).
    wok_baru = {w.upper() for w in WOK_ORDER}
    semua_wok |= wok_baru

    def branch_for(wok):
        return WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper()==wok), wok), "LAINNYA")

    wok_rows = []
    for wok in semua_wok:
        branch = branch_for(wok)
        row = _build_row(
            name=wok,
            io_mtd=get(ag_ini,wok,"io"),      io_mom=get(ag_lalu,wok,"io"),   io_today=get(ag_today,wok,"io"),
            re_mtd=get(ag_ini,wok,"re"),       re_mom=get(ag_lalu,wok,"re"),   re_today=get(ag_today,wok,"re"),
            ps_mtd=get(ag_ini,wok,"ps"),       ps_mom=get(ag_lalu,wok,"ps"),   ps_today=get(ag_today,wok,"ps"),
            rev_mtd=get(ag_ini,wok,"revenue"), rev_mom=get(ag_lalu,wok,"revenue"),
            tgt_io=tgt_io.get(wok,0), tgt_re=tgt_re.get(wok,0), tgt_ps=tgt_ps.get(wok,0),
            hari_mtd=hari_mtd, total_hari=total_hari
        )
        row["branch"] = branch
        wok_rows.append(row)

    wok_order_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_order_up.index(r["name"])
                  if r["name"] in wok_order_up else 999)

    # Branch rows
    branch_rows = []
    for branch in BRANCH_ORDER:
        bw = [r for r in wok_rows if r["branch"]==branch]
        if not bw: continue
        def sb(f): return sum(r[f] for r in bw)
        # Pakai float asli untuk total target branch
        bw_names = [r["name"] for r in bw]
        row = _build_row(
            name=branch,
            io_mtd=sb("io_mtd"),  io_mom=sb("io_mtd_lalu"),  io_today=sb("io_today"),
            re_mtd=sb("re_mtd"),  re_mom=sb("re_mtd_lalu"),  re_today=sb("re_today"),
            ps_mtd=sb("ps_mtd"),  ps_mom=sb("ps_mtd_lalu"),  ps_today=sb("ps_today"),
            rev_mtd=sb("rev_mtd"), rev_mom=sb("rev_mom"),
            tgt_io=_safe_sum(tgt_io.get(w) for w in bw_names),
            tgt_re=_safe_sum(tgt_re.get(w) for w in bw_names),
            tgt_ps=_safe_sum(tgt_ps.get(w) for w in bw_names),
            hari_mtd=hari_mtd, total_hari=total_hari
        )
        row["branch"] = branch
        branch_rows.append(row)

    # Region row — sum float asli dulu baru round di _build_row
    def sr(f): return sum(r[f] for r in wok_rows)
    region_row = _build_row(
        name=REGION_NAME,
        io_mtd=sr("io_mtd"),  io_mom=sr("io_mtd_lalu"),  io_today=sr("io_today"),
        re_mtd=sr("re_mtd"),  re_mom=sr("re_mtd_lalu"),  re_today=sr("re_today"),
        ps_mtd=sr("ps_mtd"),  ps_mom=sr("ps_mtd_lalu"),  ps_today=sr("ps_today"),
        rev_mtd=sr("rev_mtd"), rev_mom=sr("rev_mom"),
        tgt_io=_safe_sum(tgt_io.values()), tgt_re=_safe_sum(tgt_re.values()), tgt_ps=_safe_sum(tgt_ps.values()),
        hari_mtd=hari_mtd, total_hari=total_hari
    )
    region_row["branch"] = ""

    return {
        "tgl_closing": tgl_closing, "hari_mtd": hari_mtd,
        "total_hari": total_hari,
        "region": region_row, "branches": branch_rows, "woks": wok_rows,
    }


def hitung_city_performance(target_monthly_df, tgl_closing: date,
                             target_city_df=None) -> dict:
    """
    Kalkulasi Daily Performance level City (kabupaten).

    Selalu dari DB (dashboard_hourly_sales) — TIDAK ADA versi FMC. Payload FMC
    funnel tidak mengirim field kabupaten (sudah dicek langsung), dan WOK di
    Jateng-DIY sendiri gabungan beberapa kabupaten (mis. "JEPARA KUDUS - PATI")
    jadi tidak bisa didekati dari WOK. Dipakai apa adanya oleh /closingutoip.
    """
    df_ini, df_lalu, df_today = _query_dashboard(tgl_closing)

    hari_mtd   = tgl_closing.day
    total_hari = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]

    # Target per city (prioritas) atau fallback ke target WOK
    tgt_io_wok, tgt_re_wok, tgt_ps_wok = _get_target(target_monthly_df, tgl_closing)
    tgt_io_city, tgt_re_city, tgt_ps_city = _get_target_city(target_city_df, tgl_closing)

    # Agregasi per kabupaten-wok-branch
    ag_ini   = _agg_by(df_ini,   ["kabupaten","wok","branch"])
    ag_lalu  = _agg_by(df_lalu,  ["kabupaten","wok","branch"])
    ag_today = _agg_by(df_today, ["kabupaten","wok","branch"])

    def get(df, kab, wok, col):
        r = df[(df["kabupaten"]==kab) & (df["wok"]==wok)]
        return int(r[col].values[0]) if not r.empty else 0

    # Kumpulkan semua kombinasi
    semua = set()
    for df in [ag_ini, ag_lalu]:
        if not df.empty:
            for _, r in df.iterrows():
                semua.add((r["kabupaten"], r["wok"], r["branch"]))

    city_rows = []
    for (kab, wok, branch) in semua:
        key = (wok, kab)
        t_io = tgt_io_city.get(key, tgt_io_wok.get(wok, 0))
        t_re = tgt_re_city.get(key, tgt_re_wok.get(wok, 0))
        t_ps = tgt_ps_city.get(key, tgt_ps_wok.get(wok, 0))

        row = _build_row(
            name=kab,
            io_mtd=get(ag_ini,kab,wok,"io"),      io_mom=get(ag_lalu,kab,wok,"io"),   io_today=get(ag_today,kab,wok,"io"),
            re_mtd=get(ag_ini,kab,wok,"re"),       re_mom=get(ag_lalu,kab,wok,"re"),   re_today=get(ag_today,kab,wok,"re"),
            ps_mtd=get(ag_ini,kab,wok,"ps"),       ps_mom=get(ag_lalu,kab,wok,"ps"),   ps_today=get(ag_today,kab,wok,"ps"),
            rev_mtd=get(ag_ini,kab,wok,"revenue"), rev_mom=get(ag_lalu,kab,wok,"revenue"),
            tgt_io=t_io, tgt_re=t_re, tgt_ps=t_ps,
            hari_mtd=hari_mtd, total_hari=total_hari
        )
        row["wok"]    = wok
        row["branch"] = branch
        city_rows.append(row)

    # Sort: branch → wok → kabupaten
    branch_order_up = [b.upper() for b in BRANCH_ORDER]
    wok_order_up    = [w.upper() for w in WOK_ORDER]
    city_rows.sort(key=lambda r: (
        branch_order_up.index(r["branch"]) if r["branch"] in branch_order_up else 999,
        wok_order_up.index(r["wok"])       if r["wok"]    in wok_order_up    else 999,
        r["name"]
    ))

    # Region row
    def sc(f): return sum(r[f] for r in city_rows)
    total_tgt_io = _safe_sum(tgt_io_city.values()) if tgt_io_city else _safe_sum(tgt_io_wok.values())
    total_tgt_re = _safe_sum(tgt_re_city.values()) if tgt_re_city else _safe_sum(tgt_re_wok.values())
    total_tgt_ps = _safe_sum(tgt_ps_city.values()) if tgt_ps_city else _safe_sum(tgt_ps_wok.values())

    region_row = _build_row(
        name=REGION_NAME,
        io_mtd=sc("io_mtd"),  io_mom=sc("io_mtd_lalu"),  io_today=sc("io_today"),
        re_mtd=sc("re_mtd"),  re_mom=sc("re_mtd_lalu"),  re_today=sc("re_today"),
        ps_mtd=sc("ps_mtd"),  ps_mom=sc("ps_mtd_lalu"),  ps_today=sc("ps_today"),
        rev_mtd=sc("rev_mtd"), rev_mom=sc("rev_mom"),
        tgt_io=total_tgt_io, tgt_re=total_tgt_re, tgt_ps=total_tgt_ps,
        hari_mtd=hari_mtd, total_hari=total_hari
    )
    region_row["wok"] = ""; region_row["branch"] = ""

    return {
        "tgl_closing": tgl_closing, "hari_mtd": hari_mtd,
        "total_hari": total_hari,
        "region": region_row, "cities": city_rows,
    }


def export_raw_csv(tgl_closing: date, data_source: str = "db") -> tuple:
    """
    Export data raw bulan ini (MtD) + bulan lalu (FM).
    data_source="fmc" -> pakai FMC API, lihat _export_raw_csv_fmc() (kolom
    native FMC, BEDA dari skema indihome_ordering_detail).
    Return (zip_bytes, csv_filename).

    Filter WAJIB disamakan dgn db.query_ordering_detail() (report IO RE PS by
    Channel) — exclude WIRELESS — supaya angka raw ini bisa dicocokkan ke
    tabel Channel (04-Aug-2026: sebelumnya filter WIRELESS tidak ada di sini,
    row count raw > total tabel Channel). CATATAN: TIDAK exclude package_cat
    'HWA' — beda dgn report DoD/Kategori Paket yg PS-only, raw ini dipakai
    juga utk audit IO/RE (bukan cuma PS), jadi disamakan ke Channel (tabel
    IO/RE/PS utama /closingsql), bukan ke DoD/Kategori Paket.
    """
    if data_source == "fmc":
        return _export_raw_csv_fmc(tgl_closing)

    tabel_prefix = "indihome_ordering_detail_"
    tabel_ini    = f"{tabel_prefix}{tgl_closing.strftime('%Y%m')}"
    bulan_lalu   = tgl_closing - relativedelta(months=1)
    tabel_lalu   = f"{tabel_prefix}{bulan_lalu.strftime('%Y%m')}"

    awal_ini   = tgl_closing.replace(day=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month,
                      calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1])

    rows_all = []

    for tabel, tgl_dari, tgl_sampai in [
        (tabel_lalu, awal_lalu, akhir_lalu),
        (tabel_ini,  awal_ini,  tgl_closing),
    ]:
        # io_ts/re_ts/ps_ts bertipe DATETIME: BETWEEN tgl_dari AND tgl_sampai
        # cuma ambil s/d tgl_sampai 00:00:00, MEMBUANG SELURUH transaksi hari
        # itu (sama persis kasus di db.query_ordering_detail, lihat komentar
        # di sana). Sebelum fix ini (04-Aug-2026) raw export SELALU kehilangan
        # hari terakhir tiap periode (akhir bulan lalu utk FM, tgl_closing
        # sendiri utk MtD) -> row count-nya lebih SEDIKIT dari tabel Channel,
        # bukan lebih banyak spt yg dikira dari sisi filter WIRELESS.
        tgl_sampai_query = tgl_sampai + timedelta(days=1)
        sql = f"""
            SELECT *, {db._WOK_KAB} AS wok_baru, {db._BRANCH_KAB} AS branch_baru
            FROM `{tabel}`
            WHERE region LIKE %s
              AND order_type = 'NEW SALES'
              AND (
                io_ts BETWEEN %s AND %s
                OR re_ts BETWEEN %s AND %s
                OR ps_ts BETWEEN %s AND %s
              )
            ORDER BY wok
        """
        try:
            conn = get_connection()
            if hasattr(conn, "set_converter_class"):
                conn.set_converter_class(RawMySQLConverter)
            cur  = conn.cursor(dictionary=True)
            cur.execute(sql, (db.DB_REGION_LIKE,
                              tgl_dari, tgl_sampai_query,
                              tgl_dari, tgl_sampai_query,
                              tgl_dari, tgl_sampai_query))
            rows = cur.fetchall()
            cur.close(); conn.close()
            # kabupaten tak terpetakan -> isi wok_baru/branch_baru dari geotag/STO
            diisi = []
            for r in rows:
                if r.get("wok_baru") is None:
                    h = wilayah.selesaikan_wilayah(r.get("longitude"), r.get("latitude"),
                                                   r.get("kabupaten_sto"))
                    if h is None:
                        continue
                    r["wok_baru"], r["branch_baru"] = h[0], h[1]
                diisi.append(r)
            rows = diisi
            rows_all += rows
            logger.info(f"Export {tabel}: {len(rows)} baris")
        except Error as e:
            logger.warning(f"Export {tabel} gagal: {e}")

    if not rows_all:
        raise ValueError("Tidak ada data untuk diekspor")

    df = pd.DataFrame(rows_all)
    for col in df.columns:
        if col.endswith("_ts") or col.endswith("_date") or "time" in col:
            def _clean_ts(v):
                if v is None or pd.isna(v):
                    return "0000-00-00 00:00:00"
                if isinstance(v, (datetime, pd.Timestamp)):
                    return v.strftime("%Y-%m-%d %H:%M:%S")
                s = str(v).strip()
                if s in ("", "0", "None", "NaT", "nan", "NULL", "null"):
                    return "0000-00-00 00:00:00"
                return s
            df[col] = df[col].map(_clean_ts)

    df = df.replace({"NaT": "0000-00-00 00:00:00"})

    csv_buf   = io.StringIO()
    df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
    csv_bytes = csv_buf.getvalue().encode("utf-8-sig")

    bl       = bulan_lalu.strftime("%Y%m")
    bi       = tgl_closing.strftime("%Y%m%d")
    csv_name = f"ordering_detail_JATENGDIY_FM{bl}_MTD{bi}.csv"

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_name, csv_bytes)
    zip_buf.seek(0)

    logger.info(f"Export selesai: {len(rows_all)} baris → {csv_name}.zip")
    return zip_buf.read(), csv_name


def _export_raw_csv_fmc(tgl_closing: date) -> tuple:
    """
    Export raw order-level dari FMC API untuk bulan lalu (FM) + bulan ini
    (MtD), rentangnya bersambung (akhir_lalu = H-1 dari awal_ini) jadi cukup
    1 seri fetch dari awal_lalu s/d tgl_closing.

    CATATAN: kolomnya kolom NATIVE dari FMC (order_id, wok, branch, io_ts,
    re_ts, ps_ts, channel_group, product_commercial_name, dst) — BEDA dari
    skema tabel indihome_ordering_detail di MySQL (nama & jumlah kolom tidak
    sama persis), karena ini dump mentah dari API, bukan hasil SELECT * ke
    tabel yang sama.
    """
    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)

    rows_all = fmc_api.fetch_orders_raw_for_export(awal_lalu, tgl_closing)

    if not rows_all:
        raise ValueError("Tidak ada data FMC untuk diekspor")

    df = pd.DataFrame(rows_all)
    for col in df.columns:
        if col.endswith("_ts") or col.endswith("_date") or "time" in col:
            def _clean_ts(v):
                if v is None or pd.isna(v):
                    return "0000-00-00 00:00:00"
                if isinstance(v, (datetime, pd.Timestamp)):
                    return v.strftime("%Y-%m-%d %H:%M:%S")
                s = str(v).strip()
                if s in ("", "0", "None", "NaT", "nan", "NULL", "null"):
                    return "0000-00-00 00:00:00"
                return s
            df[col] = df[col].map(_clean_ts)

    df = df.replace({"NaT": "0000-00-00 00:00:00"})
    csv_buf   = io.StringIO()
    df.to_csv(csv_buf, index=False, encoding="utf-8-sig")
    csv_bytes = csv_buf.getvalue().encode("utf-8-sig")

    bl       = bulan_lalu.strftime("%Y%m")
    bi       = tgl_closing.strftime("%Y%m%d")
    csv_name = f"ordering_detail_JATENGDIY_FM{bl}_MTD{bi}_fmc.csv"

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(csv_name, csv_bytes)
    zip_buf.seek(0)

    logger.info(f"Export FMC selesai: {len(rows_all)} baris → {csv_name}.zip")
    return zip_buf.read(), csv_name
