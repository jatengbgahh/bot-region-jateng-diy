"""
calculator_wireless.py — Performance MtD IO/RE/PS EZNet Wireless per WOK (/wireless).

Sumber: tabel raw indihome_ordering_detail_YYYYMM, hanya produk yang
product_commercial_name-nya mengandung WIRELESS (db.query_wireless_performance).
Target: sheet TARGET_WIRELESS (BULAN, WOK, TARGET_IO, TARGET_RE, TARGET_PS).

Bentuk hasil SAMA dengan calculator_daily.hitung_daily_performance (woks /
branches / region, field io_*/re_*/ps_*/io_re_*/re_ps_*), jadi kolom-kolomnya
identik dengan report "Performance MtD Sales IndiHome JATENG-DIY by WOK"; yang
tidak dipakai di sini cuma field revenue (selalu 0).
"""

import calendar
import logging
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

import calculator_daily as cd
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

logger = logging.getLogger(__name__)

_KOLOM = ["wok", "branch", "activity_date", "io_trx", "re_trx", "ps_trx", "ps_rev"]


def _rentang_mtd(tgl: date):
    """(awal_ini, awal_lalu, akhir_lalu) — logika sama dgn calculator_daily._query_dashboard."""
    bulan_lalu = tgl - relativedelta(months=1)
    awal_ini   = tgl.replace(day=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_max_ini  = calendar.monthrange(tgl.year, tgl.month)[1]
    if tgl.day == hari_max_ini:
        hari_mtd_lalu = hari_max_lalu
    else:
        hari_mtd_lalu = min(tgl.day, hari_max_lalu)
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month, hari_mtd_lalu)
    return awal_ini, awal_lalu, akhir_lalu


def _to_df(rows: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_KOLOM)
    df = pd.DataFrame(rows)
    df["activity_date"] = pd.to_datetime(df["activity_date"]).dt.date
    for col in ("io_trx", "re_trx", "ps_trx"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df["ps_rev"] = 0
    df["wok"]    = df["wok"].fillna("").astype(str).str.strip().str.upper().replace("", "TANPA WOK")
    df["branch"] = df["branch"].fillna("").astype(str).str.strip().str.upper()
    return df


def _branch_for(wok: str) -> str:
    return WOK_TO_BRANCH.get(
        next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok), "LAINNYA")


def hitung_wireless(target_wireless_df, tgl: date) -> dict:
    """
    Hitung Performance MtD EZNet Wireless per WOK/BRANCH/REGION s/d `tgl`.

    Semua WOK di config.WOK_ORDER SELALU muncul (angka 0 kalau tidak ada
    transaksi wireless), supaya tabel lengkap seperti report by WOK utama.
    """
    awal_ini, awal_lalu, akhir_lalu = _rentang_mtd(tgl)

    df_ini   = _to_df(db.query_wireless_performance(awal_ini, tgl))
    df_lalu  = _to_df(db.query_wireless_performance(awal_lalu, akhir_lalu))
    df_today = df_ini[df_ini["activity_date"] == tgl]

    hari_mtd   = tgl.day
    total_hari = calendar.monthrange(tgl.year, tgl.month)[1]

    tgt_io, tgt_re, tgt_ps = cd._get_target(target_wireless_df, tgl)

    def agg(df):
        if df.empty:
            return {}
        g = df.groupby("wok")[["io_trx", "re_trx", "ps_trx"]].sum()
        return {w: (int(r.io_trx), int(r.re_trx), int(r.ps_trx)) for w, r in g.iterrows()}

    a_ini, a_lalu, a_today = agg(df_ini), agg(df_lalu), agg(df_today)

    semua_wok = {w.upper() for w in WOK_ORDER}
    # WOK dari sheet target hanya ikut kalau termasuk 14 WOK baru (lihat calculator_sql)
    wok_baru = {w.upper() for w in WOK_ORDER}
    semua_wok |= set(a_ini) | set(a_lalu) | {w for w in set(tgt_io) | set(tgt_re) | set(tgt_ps) if w in wok_baru}

    def ambil(d, wok, i):
        return d.get(wok, (0, 0, 0))[i]

    wok_rows = []
    for wok in semua_wok:
        row = cd._build_row(
            name=wok,
            io_mtd=ambil(a_ini, wok, 0),  io_mom=ambil(a_lalu, wok, 0),  io_today=ambil(a_today, wok, 0),
            re_mtd=ambil(a_ini, wok, 1),  re_mom=ambil(a_lalu, wok, 1),  re_today=ambil(a_today, wok, 1),
            ps_mtd=ambil(a_ini, wok, 2),  ps_mom=ambil(a_lalu, wok, 2),  ps_today=ambil(a_today, wok, 2),
            rev_mtd=0, rev_mom=0,
            tgt_io=tgt_io.get(wok, 0), tgt_re=tgt_re.get(wok, 0), tgt_ps=tgt_ps.get(wok, 0),
            hari_mtd=hari_mtd, total_hari=total_hari,
        )
        row["branch"] = _branch_for(wok)
        wok_rows.append(row)

    wok_order_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_order_up.index(r["name"]) if r["name"] in wok_order_up else 999)

    branch_rows = []
    for branch in BRANCH_ORDER:
        bw = [r for r in wok_rows if r["branch"] == branch]
        if not bw:
            continue
        def sb(f): return sum(r[f] for r in bw)
        names = [r["name"] for r in bw]
        row = cd._build_row(
            name=branch,
            io_mtd=sb("io_mtd"), io_mom=sb("io_mtd_lalu"), io_today=sb("io_today"),
            re_mtd=sb("re_mtd"), re_mom=sb("re_mtd_lalu"), re_today=sb("re_today"),
            ps_mtd=sb("ps_mtd"), ps_mom=sb("ps_mtd_lalu"), ps_today=sb("ps_today"),
            rev_mtd=0, rev_mom=0,
            tgt_io=sum(tgt_io.get(w, 0) for w in names),
            tgt_re=sum(tgt_re.get(w, 0) for w in names),
            tgt_ps=sum(tgt_ps.get(w, 0) for w in names),
            hari_mtd=hari_mtd, total_hari=total_hari,
        )
        row["branch"] = branch
        branch_rows.append(row)

    def sr(f): return sum(r[f] for r in wok_rows)
    region_row = cd._build_row(
        name=REGION_NAME,
        io_mtd=sr("io_mtd"), io_mom=sr("io_mtd_lalu"), io_today=sr("io_today"),
        re_mtd=sr("re_mtd"), re_mom=sr("re_mtd_lalu"), re_today=sr("re_today"),
        ps_mtd=sr("ps_mtd"), ps_mom=sr("ps_mtd_lalu"), ps_today=sr("ps_today"),
        rev_mtd=0, rev_mom=0,
        tgt_io=sum(tgt_io.values()), tgt_re=sum(tgt_re.values()), tgt_ps=sum(tgt_ps.values()),
        hari_mtd=hari_mtd, total_hari=total_hari,
    )
    region_row["branch"] = ""

    return {
        "tgl_closing": tgl, "hari_mtd": hari_mtd, "total_hari": total_hari,
        "region": region_row, "branches": branch_rows, "woks": wok_rows,
        "target_terisi": bool(sum(tgt_io.values()) or sum(tgt_re.values()) or sum(tgt_ps.values())),
    }


def build_caption(result: dict) -> str:
    """Caption Telegram: Top/Bottom ACH RE & PS per BRANCH dan WOK (sama pola report by WOK)."""
    tgl = result["tgl_closing"]

    def top_bottom(rows, field):
        valid = [r for r in rows if r.get(field) is not None]
        if not valid:
            return "-", "-"
        return (max(valid, key=lambda r: r[field])["name"],
                min(valid, key=lambda r: r[field])["name"])

    baris = [
        "Performance MtD Sales EZNet Wireless JATENG-DIY by WOK",
        f"Update {tgl.strftime('%d-%m-%Y')}",
        "",
    ]
    if not result["target_terisi"]:
        baris.append("⚠️ Target IO/RE/PS EZNet Wireless belum diisi (sheet TARGET_WIRELESS) — "
                     "kolom TGT/DRR/ACH kosong.")
        return "\n".join(baris)

    b_re = top_bottom(result["branches"], "re_ach"); b_ps = top_bottom(result["branches"], "ps_ach")
    w_re = top_bottom(result["woks"], "re_ach");     w_ps = top_bottom(result["woks"], "ps_ach")
    baris += [
        "BRANCH",
        f"🥇 Top Ach RE - {b_re[0]}",
        f"🏳️ Bottom Ach RE - {b_re[1]}",
        "",
        f"🥇 Top Ach PS - {b_ps[0]}",
        f"🏳️ Bottom Ach PS - {b_ps[1]}",
        "",
        "WOK",
        f"🥇 Top Ach RE - {w_re[0]}",
        f"🏳️ Bottom Ach RE - {w_re[1]}",
        "",
        f"🥇 Top Ach PS - {w_ps[0]}",
        f"🏳️ Bottom Ach PS - {w_ps[1]}",
    ]
    return "\n".join(baris)
