"""
reports/wireless2/calculator.py - Performance MtD IO/RE/PS EZNet Wireless per WOK TANPA
produk tertentu (mis. Murmer) - /wireless2.

Cara hitung SAMA dengan calculator_wireless.hitung_wireless (/wireless); bedanya
sumber datanya query.query_wireless_performance yang meng-exclude exclude_keyword.
Helper (_rentang_mtd, _to_df, _branch_for) dipakai ulang dari calculator_wireless.
"""

import calendar
import logging
from datetime import date

import calculator_daily as cd
from calculator_wireless import _rentang_mtd, _to_df, _branch_for
from config import BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

from . import query

logger = logging.getLogger(__name__)


def hitung_wireless2(target_wireless_df, tgl: date, exclude_keyword: str) -> dict:
    """
    Hitung Performance MtD EZNet Wireless (tanpa produk `exclude_keyword`) per WOK/BRANCH/REGION s/d `tgl`.

    Semua WOK di config.WOK_ORDER SELALU muncul (angka 0 kalau tidak ada
    transaksi wireless), supaya tabel lengkap seperti report by WOK utama.
    """
    awal_ini, awal_lalu, akhir_lalu = _rentang_mtd(tgl)

    df_ini   = _to_df(query.query_wireless_performance(awal_ini, tgl, exclude_keyword))
    df_lalu  = _to_df(query.query_wireless_performance(awal_lalu, akhir_lalu, exclude_keyword))
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
        "exclude_keyword": exclude_keyword,
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
        f"Performance MtD Sales EZNet Wireless JATENG-DIY by WOK (tanpa {result['exclude_keyword'].title()})",
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
