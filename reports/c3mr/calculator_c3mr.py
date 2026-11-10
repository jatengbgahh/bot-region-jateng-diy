"""
calculator_c3mr.py — Kalkulasi metrik C3MR dari bwmp_c3mr_dd_YYYYMM

Logic:
  - Ambil semua baris bulan M (filter bill_period), termasuk yang belum bayar
  - Subs, Bill Amount, Unpaid → semua baris bulan M
  - clearing_amount untuk %C3MR & Saldo → hanya baris payment_date <= tgl_closing (MtD)
  - MoM → %C3MR MtD bulan M - %C3MR MtD bulan M-1

Grup 1 — Early Tenure vs All LOS:
  Early Tenure: '0-3 bulan','4-6 bulan','PSB 01-10','PSB 11-20','PSB 21-31'
  All LOS      : semua los_category

Grup 2 — Per LOS group:
  0-3 bulan : '0-3 bulan','PSB 01-10','PSB 11-20','PSB 21-31'
  4-6 bulan : '4-6 bulan'
  7-12 bulan: '7-12 bulan'
  12-24 bulan: '12-24 bulan'
  >24 bulan  : '>24 bulan'
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
import wilayah
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

EARLY_TENURE_LOS = {"0-3 bulan", "4-6 bulan", "PSB 01-10", "PSB 11-20", "PSB 21-31"}

LOS_GROUPS = {
    "0-3 bulan" : {"0-3 bulan", "PSB 01-10", "PSB 11-20", "PSB 21-31"},
    "4-6 bulan" : {"4-6 bulan"},
    "7-12 bulan": {"7-12 bulan"},
    "12-24 bulan": {"12-24 bulan"},
    ">24 bulan" : {">24 bulan"},
}
LOS_ORDER = ["0-3 bulan", "4-6 bulan", "7-12 bulan", "12-24 bulan", ">24 bulan"]


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["wok"]             = df["wok"].str.strip().str.upper()
    df["branch"]          = df["branch"].str.strip().str.upper()
    df["los_category"]    = df["los_category"].str.strip()
    if "city" in df:
        df["city"]        = df["city"].astype(str).str.strip().str.upper()
    df["bill_amount"]     = pd.to_numeric(df["bill_amount"],     errors="coerce").fillna(0)
    df["clearing_amount"] = pd.to_numeric(df["clearing_amount"], errors="coerce").fillna(0)
    df["paid_flag"]       = pd.to_numeric(df["paid_flag"],       errors="coerce").fillna(0).astype(int)
    df["payment_date"]    = pd.to_datetime(df["payment_date"],   errors="coerce")
    return df


def _pct(clearing, bill):
    if bill and bill > 0:
        return round(clearing / bill * 100, 2)
    return None


def _mom(a, b):
    if a is not None and b is not None:
        return round(a - b, 2)
    return None


def _agg_wok(df: pd.DataFrame, tgl_mtd: date, by: str = "wok") -> dict:
    """
    Aggregate per WOK (by="wok") atau per City (by="city"). Return dict:
    {wok: {
        et_subs, et_bill, et_clearing, et_unpaid,
        al_subs, al_bill, al_clearing, al_unpaid,
        los_{g}_subs, los_{g}_bill, los_{g}_clearing, los_{g}_unpaid  (per LOS group g)
    }}
    """
    if df.empty:
        return {}

    tgl_mtd_ts = pd.Timestamp(tgl_mtd)
    df_clr = df[df["payment_date"].notna() & (df["payment_date"] <= tgl_mtd_ts)]

    result = {}
    for wok, grp in df.groupby(by):
        grp_clr = df_clr[df_clr[by] == wok]

        def _m(mask, mask_clr=None):
            s  = grp[mask]
            sc = grp_clr[mask_clr if mask_clr is not None else mask]
            return {
                "subs"    : len(s),
                "bill"    : s["bill_amount"].sum(),
                "clearing": sc["clearing_amount"].sum(),
                "unpaid"  : int((s["paid_flag"] == 0).sum()),
            }

        et_mask  = grp["los_category"].isin(EARLY_TENURE_LOS)
        etc_mask = grp_clr["los_category"].isin(EARLY_TENURE_LOS)

        d = {}
        # Early Tenure
        et  = grp[et_mask];  etc = grp_clr[etc_mask]
        d["et_subs"]     = len(et)
        d["et_bill"]     = et["bill_amount"].sum()
        d["et_clearing"] = etc["clearing_amount"].sum()
        d["et_unpaid"]   = int((et["paid_flag"] == 0).sum())
        # All LOS
        d["al_subs"]     = len(grp)
        d["al_bill"]     = grp["bill_amount"].sum()
        d["al_clearing"] = grp_clr["clearing_amount"].sum()
        d["al_unpaid"]   = int((grp["paid_flag"] == 0).sum())
        # Per LOS group
        for g, los_set in LOS_GROUPS.items():
            gm  = grp["los_category"].isin(los_set)
            gcm = grp_clr["los_category"].isin(los_set)
            sg  = grp[gm];  sgc = grp_clr[gcm]
            key = g.replace(" ", "_").replace(">", "gt")
            d[f"los_{key}_subs"]     = len(sg)
            d[f"los_{key}_bill"]     = sg["bill_amount"].sum()
            d[f"los_{key}_clearing"] = sgc["clearing_amount"].sum()
            d[f"los_{key}_unpaid"]   = int((sg["paid_flag"] == 0).sum())

        result[wok] = d
    return result


def _build_row(level, name, branch, agg_ini, agg_lalu, woks_list):
    """Build satu row dengan semua metrik ET, AL, dan per LOS group."""
    def _sum_ini(key):
        return sum(agg_ini.get(w, {}).get(key, 0) for w in woks_list)
    def _sum_lalu(key):
        return sum(agg_lalu.get(w, {}).get(key, 0) for w in woks_list)

    row = {"level": level, "name": name}
    if branch is not None:
        row["branch"] = branch

    # Early Tenure
    et_bill_i = _sum_ini("et_bill");  et_clr_i = _sum_ini("et_clearing")
    et_bill_l = _sum_lalu("et_bill"); et_clr_l = _sum_lalu("et_clearing")
    et_pct_i  = _pct(et_clr_i, et_bill_i)
    et_pct_l  = _pct(et_clr_l, et_bill_l)
    row.update({
        "et_subs"  : _sum_ini("et_subs"),
        "et_bill"  : et_bill_i,
        "et_pct"   : et_pct_i,
        "et_mom"   : _mom(et_pct_i, et_pct_l),
        "et_saldo" : et_bill_i - et_clr_i,
        "et_unpaid": _sum_ini("et_unpaid"),
    })

    # All LOS
    al_bill_i = _sum_ini("al_bill");  al_clr_i = _sum_ini("al_clearing")
    al_bill_l = _sum_lalu("al_bill"); al_clr_l = _sum_lalu("al_clearing")
    al_pct_i  = _pct(al_clr_i, al_bill_i)
    al_pct_l  = _pct(al_clr_l, al_bill_l)
    row.update({
        "al_subs"  : _sum_ini("al_subs"),
        "al_bill"  : al_bill_i,
        "al_pct"   : al_pct_i,
        "al_mom"   : _mom(al_pct_i, al_pct_l),
        "al_saldo" : al_bill_i - al_clr_i,
        "al_unpaid": _sum_ini("al_unpaid"),
    })

    # Per LOS group
    for g in LOS_ORDER:
        key = g.replace(" ", "_").replace(">", "gt")
        bill_i = _sum_ini(f"los_{key}_bill");  clr_i = _sum_ini(f"los_{key}_clearing")
        bill_l = _sum_lalu(f"los_{key}_bill"); clr_l = _sum_lalu(f"los_{key}_clearing")
        pct_i  = _pct(clr_i, bill_i)
        pct_l  = _pct(clr_l, bill_l)
        row.update({
            f"los_{key}_subs"  : _sum_ini(f"los_{key}_subs"),
            f"los_{key}_bill"  : bill_i,
            f"los_{key}_pct"   : pct_i,
            f"los_{key}_mom"   : _mom(pct_i, pct_l),
            f"los_{key}_saldo" : bill_i - clr_i,
            f"los_{key}_unpaid": _sum_ini(f"los_{key}_unpaid"),
        })

    return row


def urutkan_city(city_rows: list) -> None:
    """Urutkan in-place: urutan WOK (sudah per branch) → nama city."""
    wok_up = [w.upper() for w in WOK_ORDER]
    city_rows.sort(key=lambda r: (wok_up.index(r["wok"]) if r["wok"] in wok_up else 999, r["name"]))


def hitung_c3mr(tgl_closing: date) -> dict:
    # ── Tentukan bill_period berdasarkan tanggal closing ──────────────────
    # Tgl 1-5: bill_period = bulan sebelumnya (masih dalam periode closing)
    # Tgl 6+: bill_period = bulan berjalan
    if tgl_closing.day <= 5:
        bp_ini = (tgl_closing - relativedelta(months=1)).replace(day=1)
    else:
        bp_ini = tgl_closing.replace(day=1)

    bp_lalu = (bp_ini - relativedelta(months=1))

    # MtD lalu: tanggal yang sama di bulan bp_lalu
    # Misal tgl_closing = 5 Juli, bp_ini = Juni → MtD lalu = 5 Juni
    # MoM: tanggal yang sama persis di bulan bp_lalu
    # Misal tgl_closing=1 Juli, bp_ini=Juni → tgl_mtd_lalu=1 Juni (bukan 1 Mei)
    tgl_mtd_lalu = tgl_closing - relativedelta(months=1)

    rows_ini  = db.query_c3mr(bp_ini,  with_city=True)
    rows_lalu = db.query_c3mr(bp_lalu, with_city=True)

    df_ini  = _prep(pd.DataFrame(rows_ini)  if rows_ini  else pd.DataFrame())
    df_lalu = _prep(pd.DataFrame(rows_lalu) if rows_lalu else pd.DataFrame())

    agg_ini  = _agg_wok(df_ini,  tgl_closing)
    agg_lalu = _agg_wok(df_lalu, tgl_mtd_lalu)

    semua_wok = set(list(agg_ini.keys()) + list(agg_lalu.keys()))

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok), "LAINNYA"
        )
        row = _build_row("WOK", wok, branch, agg_ini, agg_lalu, [wok])
        wok_rows.append(row)

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    for branch in branch_names:
        bwoks = [r["name"] for r in wok_rows if r["branch"] == branch]
        if not bwoks:
            continue
        row = _build_row("BRANCH", branch, None, agg_ini, agg_lalu, bwoks)
        branch_rows.append(row)

    # ── REGION row ────────────────────────────────────────────────────────
    region_row = _build_row("REGION", REGION_NAME, None, agg_ini, agg_lalu, list(semua_wok))

    # ── CITY rows (kabupaten) — report "per City" ─────────────────────────
    city_ini  = _agg_wok(df_ini,  tgl_closing,  by="city")
    city_lalu = _agg_wok(df_lalu, tgl_mtd_lalu, by="city")
    city_rows = []
    for city in set(city_ini) | set(city_lalu):
        row = _build_row("CITY", city, None, city_ini, city_lalu, [city])
        row["wok"], row["branch"] = wilayah.petakan_kab(city) or ("LAINNYA", "LAINNYA")
        city_rows.append(row)
    urutkan_city(city_rows)

    return {
        "tgl_closing"  : tgl_closing,
        "bl_label"     : bp_lalu.strftime("%b %Y").upper(),
        "bi_label"     : bp_ini.strftime("%b %Y").upper(),
        "bp_ini"       : bp_ini,        # bill_period aktif
        "is_closing_mode": tgl_closing.day <= 5,  # True jika pakai bill_period bulan lalu
        "region"       : region_row,
        "branches"     : branch_rows,
        "woks"         : wok_rows,
        "cities"       : city_rows,
        "los_order"    : LOS_ORDER,
    }
