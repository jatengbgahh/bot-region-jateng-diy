"""
reports/c3mrsvp/calculator.py — Kalkulasi C3MR Fokus SVP (Pelanggan LOS <=24 Bulan).

Sumber data & rumus SAMA dengan calculator_c3mr.py (/c3mr):
  - db.query_c3mr(bp) → semua baris bwmp_c3mr_dd bulan itu (termasuk belum bayar)
  - Filter: los_category SELAIN '>24 bulan' (0-3 + PSB, 4-6, 7-12, 12-24 bulan)
  - Subs, Bill Amount, Unpaid       → semua baris bulan M
  - Paid Subs, Bill Paid (clearing) → hanya baris payment_date <= tgl closing (MtD)
  - %C3MR = Bill Paid / Bill Amount, Saldo = Bill Amount - Bill Paid
  - MoM   = %C3MR MtD bulan M - %C3MR MtD (tanggal sama) bulan M-1
  - Tgl 1-5 masih pakai bill period bulan lalu (kelonggaran closing, sama dgn /c3mr)
Rumus _pct/_mom & mapping WOK→Branch di-reuse dari calculator_c3mr (tanpa duplikasi).
"""

from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

import db
import wilayah
from calculator_c3mr import _pct, _mom, urutkan_city
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

LOS_EXCLUDE = {">24 bulan"}

_METRIK = ("subs", "bill", "paid_subs", "clearing", "unpaid")


def _prep(rows: list[dict]) -> pd.DataFrame:
    """List baris query → DataFrame bersih, sudah dibuang LOS >24 bulan.
    Disusun kolom-per-kolom (bukan pd.DataFrame(list[dict])) — sama alasan
    hemat RAM seperti calculator_c3mr10s._prep_c3mr."""
    if not rows:
        return pd.DataFrame()
    _cols = ("wok", "city", "los_category", "bill_amount", "clearing_amount",
             "paid_flag", "payment_date")
    _data = {c: [r.get(c) for r in rows] for c in _cols}
    rows.clear()
    df = pd.DataFrame(_data)
    del _data
    df["los_category"] = df["los_category"].astype(str).str.strip()
    df = df[~df["los_category"].isin(LOS_EXCLUDE)].copy()
    df["wok"]             = df["wok"].astype(str).str.strip().str.upper()
    df["city"]            = df["city"].astype(str).str.strip().str.upper()
    df["bill_amount"]     = pd.to_numeric(df["bill_amount"],     errors="coerce").fillna(0)
    df["clearing_amount"] = pd.to_numeric(df["clearing_amount"], errors="coerce").fillna(0)
    df["paid_flag"]       = pd.to_numeric(df["paid_flag"],       errors="coerce").fillna(0).astype(int)
    df["payment_date"]    = pd.to_datetime(df["payment_date"],   errors="coerce")
    return df


def _agg_wok(df: pd.DataFrame, tgl_mtd: date, by: str = "wok") -> dict:
    """{wok|city: {subs, bill, paid_subs, clearing, unpaid}} — by="wok" atau "city"."""
    if df.empty:
        return {}
    df = df.copy()
    df["_mtd"] = df["payment_date"].notna() & (df["payment_date"] <= pd.Timestamp(tgl_mtd))
    df["_clr"] = df["clearing_amount"].where(df["_mtd"], 0)
    g = df.groupby(by).agg(
        subs=("bill_amount", "size"),
        bill=("bill_amount", "sum"),
        paid_subs=("_mtd", "sum"),
        clearing=("_clr", "sum"),
        unpaid=("paid_flag", lambda s: int((s == 0).sum())),
    )
    return {wok: {k: r[k] for k in _METRIK} for wok, r in g.iterrows()}


def _build_row(level, name, branch, agg_ini, agg_lalu, woks_list):
    def _sum(agg, key):
        return sum(agg.get(w, {}).get(key, 0) for w in woks_list)

    bill_i = _sum(agg_ini, "bill");  clr_i = _sum(agg_ini, "clearing")
    pct_i  = _pct(clr_i, bill_i)
    pct_l  = _pct(_sum(agg_lalu, "clearing"), _sum(agg_lalu, "bill"))
    row = {
        "level"    : level,
        "name"     : name,
        "subs"     : int(_sum(agg_ini, "subs")),
        "bill"     : bill_i,
        "paid_subs": int(_sum(agg_ini, "paid_subs")),
        "bill_paid": clr_i,
        "pct"      : pct_i,
        "mom"      : _mom(pct_i, pct_l),
        "unpaid"   : int(_sum(agg_ini, "unpaid")),
        "saldo"    : bill_i - clr_i,
    }
    if branch is not None:
        row["branch"] = branch
    return row


def hitung_c3mrsvp(tgl_closing: date) -> dict:
    if tgl_closing.day <= 5:
        bp_ini = (tgl_closing - relativedelta(months=1)).replace(day=1)
    else:
        bp_ini = tgl_closing.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)
    tgl_mtd_lalu = tgl_closing - relativedelta(months=1)

    df_ini  = _prep(db.query_c3mr(bp_ini,  with_city=True))
    df_lalu = _prep(db.query_c3mr(bp_lalu, with_city=True))
    agg_ini  = _agg_wok(df_ini,  tgl_closing)
    agg_lalu = _agg_wok(df_lalu, tgl_mtd_lalu)
    city_ini  = _agg_wok(df_ini,  tgl_closing,  by="city")
    city_lalu = _agg_wok(df_lalu, tgl_mtd_lalu, by="city")
    del df_ini, df_lalu

    semua_wok = set(agg_ini) | set(agg_lalu)

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok), "LAINNYA"
        )
        wok_rows.append(_build_row("WOK", wok, branch, agg_ini, agg_lalu, [wok]))

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    for branch in branch_names:
        bwoks = [r["name"] for r in wok_rows if r["branch"] == branch]
        if bwoks:
            branch_rows.append(_build_row("BRANCH", branch, None, agg_ini, agg_lalu, bwoks))

    # ── REGION row ────────────────────────────────────────────────────────
    region_row = _build_row("REGION", REGION_NAME, None, agg_ini, agg_lalu, list(semua_wok))

    # ── CITY rows (kabupaten) — report "per City" ─────────────────────────
    city_rows = []
    for city in set(city_ini) | set(city_lalu):
        row = _build_row("CITY", city, None, city_ini, city_lalu, [city])
        row["wok"], row["branch"] = wilayah.petakan_kab(city) or ("LAINNYA", "LAINNYA")
        city_rows.append(row)
    urutkan_city(city_rows)

    return {
        "tgl_closing"    : tgl_closing,
        "bl_label"       : bp_lalu.strftime("%b %Y").upper(),
        "bi_label"       : bp_ini.strftime("%b %Y").upper(),
        "bp_ini"         : bp_ini,
        "is_closing_mode": tgl_closing.day <= 5,
        "region"         : region_row,
        "branches"       : branch_rows,
        "woks"           : wok_rows,
        "cities"         : city_rows,
    }
