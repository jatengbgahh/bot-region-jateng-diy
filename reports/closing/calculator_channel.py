"""
calculator_channel.py — Kalkulasi IO, RE, PS per Channel
Source: indihome_ordering_detail_YYYYMM
Channel: AGENCY, GRAPARI, DIGITAL, COMMUNITY (mapping di db.query_ordering_detail)
Metrik: MtD bulan ini + MoM vs MtD bulan lalu (same date)
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
try:
    from utils import fmc_api
except ImportError:
    import fmc_api
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

CHANNELS = ["AGENCY", "GRAPARI", "DIGITAL", "COMMUNITY"]


def hitung_channel(tgl_closing: date, data_source: str = "db") -> dict:
    """
    Hitung IO/RE/PS per channel per WOK dari indihome_ordering_detail (MySQL,
    default) atau dari FMC API (data_source="fmc", dipakai /closingutoip).
    Return dict siap pakai untuk renderer_channel.render_channel().
    """
    # ── Rentang tanggal ───────────────────────────────────────────────────
    awal_ini   = tgl_closing.replace(day=1)

    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max   = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    # MtD bulan lalu = tanggal yg sama. KECUALI tgl_closing adalah tanggal
    # terakhir bulannya (closing) — di situ dibandingkan ke tanggal terakhir
    # bulan lalu juga, biar full month vs full month meski jumlah harinya
    # beda (mis. 30 April vs 31 Maret, bukan 30 Maret).
    hari_max_ini = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]
    if tgl_closing.day == hari_max_ini:
        hari_mtd = hari_max
    else:
        hari_mtd = min(tgl_closing.day, hari_max)
    akhir_lalu = date(bulan_lalu.year, bulan_lalu.month, hari_mtd)

    if data_source == "fmc":
        # fmc_api.query_ordering_detail_fmc() sudah filter io_ts/re_ts/ps_ts
        # per tanggal (bukan DATETIME BETWEEN di SQL), jadi tidak perlu +1 hari.
        rows_ini  = fmc_api.query_ordering_detail_fmc(awal_ini,  tgl_closing)
        rows_lalu = fmc_api.query_ordering_detail_fmc(awal_lalu, akhir_lalu)
    else:
        # ── Query DB ──────────────────────────────────────────────────────
        # +1 hari karena io_ts/re_ts/ps_ts bertipe DATETIME:
        # BETWEEN '2026-06-01' AND '2026-06-07' hanya ambil s/d 07 00:00:00
        # harus pakai '2026-06-08' agar semua data tanggal 7 masuk
        from datetime import timedelta as _td
        rows_ini  = db.query_ordering_detail(awal_ini,  tgl_closing + _td(days=1))
        rows_lalu = db.query_ordering_detail(awal_lalu, akhir_lalu  + _td(days=1))

    df_ini  = pd.DataFrame(rows_ini)  if rows_ini  else pd.DataFrame()
    df_lalu = pd.DataFrame(rows_lalu) if rows_lalu else pd.DataFrame()

    def prep(df):
        if df.empty:
            return df
        df = df.copy()
        df["wok"]     = df["wok"].str.strip().str.upper()
        df["branch"]  = df["branch"].str.strip().str.upper()
        df["channel"] = df["channel"].str.strip().str.upper()
        for col in ["io_trx", "re_trx", "ps_trx"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        return df

    df_ini  = prep(df_ini)
    df_lalu = prep(df_lalu)

    def agg(df) -> dict:
        """
        Aggregate per WOK.
        Return: {wok: {total_io, total_re, total_ps,
                        ch_AGENCY_io, ch_AGENCY_re, ch_AGENCY_ps, ...}}
        """
        if df.empty:
            return {}
        result = {}
        for wok, grp in df.groupby("wok"):
            d = {
                "total_io": int(grp["io_trx"].sum()),
                "total_re": int(grp["re_trx"].sum()),
                "total_ps": int(grp["ps_trx"].sum()),
            }
            for ch in CHANNELS:
                sub = grp[grp["channel"] == ch]
                d[f"ch_{ch}_io"] = int(sub["io_trx"].sum()) if not sub.empty else 0
                d[f"ch_{ch}_re"] = int(sub["re_trx"].sum()) if not sub.empty else 0
                d[f"ch_{ch}_ps"] = int(sub["ps_trx"].sum()) if not sub.empty else 0
            result[wok] = d
        return result

    agg_ini  = agg(df_ini)
    agg_lalu = agg(df_lalu)

    semua_wok = set(list(agg_ini.keys()) + list(agg_lalu.keys()))

    def growth(cur, prev):
        if prev and prev > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    def ini(wok, key):  return agg_ini.get(wok,  {}).get(key, 0)
    def lalu(wok, key): return agg_lalu.get(wok, {}).get(key, 0)

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )
        row = {
            "level": "WOK", "name": wok, "branch": branch,
            "total_io": ini(wok, "total_io"),
            "total_re": ini(wok, "total_re"),
            "total_ps": ini(wok, "total_ps"),
            "mom_io": growth(ini(wok, "total_io"), lalu(wok, "total_io")),
            "mom_re": growth(ini(wok, "total_re"), lalu(wok, "total_re")),
            "mom_ps": growth(ini(wok, "total_ps"), lalu(wok, "total_ps")),
        }
        for ch in CHANNELS:
            for m in ["io", "re", "ps"]:
                k = f"ch_{ch}_{m}"
                row[f"{ch}_{m}"]     = ini(wok, k)
                row[f"{ch}_{m}_mom"] = growth(ini(wok, k), lalu(wok, k))
        wok_rows.append(row)

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

        def bini(key):  return sum(ini(r["name"],  key) for r in brows)
        def blalu(key): return sum(lalu(r["name"], key) for r in brows)

        row = {
            "level": "BRANCH", "name": branch,
            "total_io": bini("total_io"),
            "total_re": bini("total_re"),
            "total_ps": bini("total_ps"),
            "mom_io": growth(bini("total_io"), blalu("total_io")),
            "mom_re": growth(bini("total_re"), blalu("total_re")),
            "mom_ps": growth(bini("total_ps"), blalu("total_ps")),
        }
        for ch in CHANNELS:
            for m in ["io", "re", "ps"]:
                k = f"ch_{ch}_{m}"
                iv = bini(k); lv = blalu(k)
                row[f"{ch}_{m}"]     = iv
                row[f"{ch}_{m}_mom"] = growth(iv, lv)
        branch_rows.append(row)

    # ── REGION row ────────────────────────────────────────────────────────
    def rini(key):  return sum(ini(w,  key) for w in semua_wok)
    def rlalu(key): return sum(lalu(w, key) for w in semua_wok)

    reg_row = {
        "level": "REGION", "name": REGION_NAME,
        "total_io": rini("total_io"),
        "total_re": rini("total_re"),
        "total_ps": rini("total_ps"),
        "mom_io": growth(rini("total_io"), rlalu("total_io")),
        "mom_re": growth(rini("total_re"), rlalu("total_re")),
        "mom_ps": growth(rini("total_ps"), rlalu("total_ps")),
    }
    for ch in CHANNELS:
        for m in ["io", "re", "ps"]:
            k = f"ch_{ch}_{m}"
            iv = rini(k); lv = rlalu(k)
            reg_row[f"{ch}_{m}"]     = iv
            reg_row[f"{ch}_{m}_mom"] = growth(iv, lv)

    return {
        "tgl_closing": tgl_closing,
        "bl_label"   : bulan_lalu.strftime("%b %Y").upper(),
        "bi_label"   : tgl_closing.strftime("%b %Y").upper(),
        "region"     : reg_row,
        "branches"   : branch_rows,
        "woks"       : wok_rows,
    }
