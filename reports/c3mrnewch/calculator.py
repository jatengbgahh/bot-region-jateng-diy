"""
reports/c3mrnewch/calculator.py — Kalkulasi C3MR per BILL-N, dikelompokkan per
CHANNEL GROUP (bukan per WOK seperti /c3mrnew).

Sumber data, definisi BILL-N (BILL-1 = ps_ts bulan M-1 dari bill period aktif,
dst s/d BILL-6), dan rumus %C3MR/MoM/Unpaid PERSIS SAMA dengan
calculator_c3mrnew.py — TIDAK diduplikasi, langsung reuse:
  - db.query_c3mrnew(bp_date)   — query mentah (kolom channel_group ikut ada)
  - calculator_c3mrnew._prep    — bersihkan & tipekan kolom
  - calculator_c3mrnew._agg_wok — agregasi per BILL-N (generik: cuma butuh
    kolom "wok" ada di df, tidak peduli isinya WOK atau bukan)
  - calculator_c3mrnew._build_row — susun 1 baris (Total + tiap BILL-N)

Trik reuse: sebelum panggil _agg_wok, kolom "channel_group" di-alias jadi
"wok" (di dataframe SALINAN, bukan mengubah aslinya) — supaya _agg_wok
mengelompokkan per channel tanpa perlu ditulis ulang.
"""

from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

import calculator_c3mrnew as base
from config import REGION_NAME

# Urutan tampil sesuai nilai channel_group mentah di DB (lihat db.py:409-412).
CHANNEL_ORDER = ["AGENCY", "GRAPARI", "B2B2C&OTHERS", "SOBI AFFILIATE", "WEB&APP"]

# Label tampilan (Title Case) untuk caption Telegram — tabel PNG tetap huruf
# besar semua (lihat renderer.py), cuma caption yang pakai bentuk ini.
CHANNEL_LABEL = {
    "AGENCY"        : "Agency",
    "GRAPARI"       : "Grapari",
    "B2B2C&OTHERS"  : "B2B2C&Others",
    "SOBI AFFILIATE": "Sobi Affiliate",
    "WEB&APP"       : "Web&App",
}


def _agg_by_channel(df: pd.DataFrame, tgl_mtd: date) -> dict:
    """{channel_group: {bill_n: {subs,bill,clearing,unpaid}}} — reuse base._agg_wok
    dengan kolom channel_group di-alias jadi "wok"."""
    if df.empty:
        return {}
    df2 = df.copy()
    df2["wok"] = df2["channel_group"].astype(str).str.strip().str.upper()
    df2.loc[df2["wok"] == "", "wok"] = "LAINNYA"
    return base._agg_wok(df2, tgl_mtd)


def hitung_c3mrnewch(tgl_closing: date) -> dict:
    """Setara calculator_c3mrnew.hitung_c3mrnew(), tapi baris = channel_group,
    bukan WOK/BRANCH."""
    # Tgl 1-5: bill_period = bulan sebelumnya (sama persis aturan /c3mrnew)
    if tgl_closing.day <= 5:
        bp_ini = (tgl_closing - relativedelta(months=1)).replace(day=1)
    else:
        bp_ini = tgl_closing.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)
    tgl_mtd_lalu = tgl_closing - relativedelta(months=1)

    rows_ini  = base.db.query_c3mrnew(bp_ini)
    rows_lalu = base.db.query_c3mrnew(bp_lalu)

    df_ini  = base._prep(rows_ini)
    df_lalu = base._prep(rows_lalu)

    agg_ini  = _agg_by_channel(df_ini,  tgl_closing)
    agg_lalu = _agg_by_channel(df_lalu, tgl_mtd_lalu)

    semua_channel = set(agg_ini) | set(agg_lalu) | set(CHANNEL_ORDER)
    urut = list(CHANNEL_ORDER) + sorted(semua_channel - set(CHANNEL_ORDER))

    # Semua channel di CHANNEL_ORDER SELALU tampil (0/"-" kalau tidak ada
    # data hari itu) supaya layout tabel konsisten tiap hari — sama pola
    # dengan /wireless yang selalu menampilkan semua WOK_ORDER.
    channel_rows = [
        base._build_row("CHANNEL", ch, None, agg_ini, agg_lalu, [ch])
        for ch in urut
    ]

    region_row = base._build_row("REGION", REGION_NAME, None, agg_ini, agg_lalu, list(semua_channel))

    return {
        "tgl_closing"    : tgl_closing,
        "bl_label"       : bp_lalu.strftime("%b %Y").upper(),
        "bi_label"       : bp_ini.strftime("%b %Y").upper(),
        "is_closing_mode": tgl_closing.day <= 5,
        "region"         : region_row,
        "channels"       : channel_rows,
        "bill_order"     : base.BILL_ORDER,
        "bill_labels"    : base.BILL_LABELS,
    }
