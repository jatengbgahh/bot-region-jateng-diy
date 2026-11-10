"""
calculator_c3mrnew.py — Kalkulasi C3MR per BILL-N (New Sales Cohort)

BILL-N = pelanggan yang ps_ts di bulan M-N dari bill_period aktif.
Metrik per BILL per WOK: Subs, Bill Amount, %C3MR, MoM, Unpaid
MoM = %C3MR bill_period M vs bill_period M-1 (same tgl_closing)
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

BILL_LABELS = {1:"BILL-1", 2:"BILL-2", 3:"BILL-3", 4:"BILL-4", 5:"BILL-5", 6:"BILL-6"}
BILL_ORDER  = [1, 2, 3, 4, 5, 6]


def _prep(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "wok" not in df.columns:
        return pd.DataFrame()
    # Buang baris yang bb_id tidak ketemu di bwmp (wok NULL)
    df = df[df["wok"].notna() & (df["wok"].astype(str).str.strip() != "")].copy()
    if df.empty:
        return pd.DataFrame()
    df["wok"]                      = df["wok"].str.strip().str.upper()
    df["branch"]                   = df["branch"].str.strip().str.upper()
    df["bill_n"]                   = pd.to_numeric(df["bill_n"], errors="coerce").fillna(0).astype(int)
    df["bill_amount"]              = pd.to_numeric(df["bill_amount"],     errors="coerce").fillna(0)
    df["clearing_amount"]          = pd.to_numeric(df["clearing_amount"], errors="coerce").fillna(0)
    df["paid_flag"]                = pd.to_numeric(df["paid_flag"],       errors="coerce").fillna(0).astype(int)
    df["payment_date"]             = pd.to_datetime(df["payment_date"],   errors="coerce")
    df["ps_ts"]                    = pd.to_datetime(df.get("ps_ts"),      errors="coerce")
    df["channel_group"]            = df.get("channel_group", "").fillna("")
    df["sf_code"]                  = df.get("sf_code", "").fillna("")
    df["sf_company_name"]          = df.get("sf_company_name", "").fillna("")
    df["product_commercial_name"]  = df.get("product_commercial_name", "").fillna("")
    df["los_category"]             = df.get("los_category", "").fillna("")
    return df


def _pct(clearing, bill):
    if bill and bill > 0:
        return round(clearing / bill * 100, 2)
    return None


def _mom(a, b):
    if a is not None and b is not None:
        return round(a - b, 2)
    return None


def _agg_wok(df: pd.DataFrame, tgl_mtd: date) -> dict:
    """
    Aggregate per (wok, bill_n).
    Return: {wok: {bill_n: {subs, bill, clearing, unpaid}}}
    """
    if df.empty:
        return {}

    tgl_mtd_ts = pd.Timestamp(tgl_mtd)
    df_clr = df[df["payment_date"].notna() & (df["payment_date"] <= tgl_mtd_ts)]

    result = {}
    for wok, grp in df.groupby("wok"):
        grp_clr = df_clr[df_clr["wok"] == wok]
        result[wok] = {}
        for n in BILL_ORDER:
            sg  = grp[grp["bill_n"] == n]
            sgc = grp_clr[grp_clr["bill_n"] == n]
            result[wok][n] = {
                "subs"    : len(sg),
                "bill"    : sg["bill_amount"].sum(),
                "clearing": sgc["clearing_amount"].sum(),
                "unpaid"  : int((sg["paid_flag"] == 0).sum()),
            }
    return result


def _build_row(level, name, branch, agg_ini, agg_lalu, woks_list):
    row = {"level": level, "name": name}
    if branch is not None:
        row["branch"] = branch

    total_bill_i = 0; total_clr_i = 0
    total_bill_l = 0; total_clr_l = 0
    total_subs   = 0; total_unpaid = 0

    for n in BILL_ORDER:
        bill_i = sum(agg_ini.get(w,  {}).get(n, {}).get("bill",     0) for w in woks_list)
        clr_i  = sum(agg_ini.get(w,  {}).get(n, {}).get("clearing", 0) for w in woks_list)
        bill_l = sum(agg_lalu.get(w, {}).get(n, {}).get("bill",     0) for w in woks_list)
        clr_l  = sum(agg_lalu.get(w, {}).get(n, {}).get("clearing", 0) for w in woks_list)
        pct_i  = _pct(clr_i, bill_i)
        pct_l  = _pct(clr_l, bill_l)
        subs_i  = sum(agg_ini.get(w, {}).get(n, {}).get("subs",   0) for w in woks_list)
        unpaid_i= sum(agg_ini.get(w, {}).get(n, {}).get("unpaid", 0) for w in woks_list)

        row[f"b{n}_subs"]  = subs_i
        row[f"b{n}_bill"]  = bill_i
        row[f"b{n}_pct"]   = pct_i
        row[f"b{n}_mom"]   = _mom(pct_i, pct_l)
        row[f"b{n}_unpaid"]= unpaid_i

        total_bill_i += bill_i;  total_clr_i += clr_i
        total_bill_l += bill_l;  total_clr_l += clr_l
        total_subs   += subs_i;  total_unpaid += unpaid_i

    # Total semua BILL
    total_pct_i = _pct(total_clr_i, total_bill_i)
    total_pct_l = _pct(total_clr_l, total_bill_l)
    row["total_subs"]   = total_subs
    row["total_bill"]   = total_bill_i
    row["total_pct"]    = total_pct_i
    row["total_mom"]    = _mom(total_pct_i, total_pct_l)
    row["total_unpaid"] = total_unpaid

    return row


def hitung_c3mrnew(tgl_closing: date) -> dict:
    # Tgl 1-5: bill_period = bulan sebelumnya
    if tgl_closing.day <= 5:
        bp_ini = (tgl_closing - relativedelta(months=1)).replace(day=1)
    else:
        bp_ini = tgl_closing.replace(day=1)

    bp_lalu = bp_ini - relativedelta(months=1)

    # MoM: tanggal yang sama persis di bulan bp_lalu
    # Misal tgl_closing=1 Juli, bp_ini=Juni → tgl_mtd_lalu=1 Juni (bukan 1 Mei)
    tgl_mtd_lalu = tgl_closing - relativedelta(months=1)

    rows_ini  = db.query_c3mrnew(bp_ini)
    rows_lalu = db.query_c3mrnew(bp_lalu)

    df_ini  = _prep(rows_ini)
    df_lalu = _prep(rows_lalu)

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

    # ── Query & kalkulasi AGENCY only ─────────────────────────────────────
    rows_ini_ag  = db.query_c3mrnew(bp_ini,  channel_group="AGENCY")
    rows_lalu_ag = db.query_c3mrnew(bp_lalu, channel_group="AGENCY")

    df_ini_ag  = _prep(rows_ini_ag)
    df_lalu_ag = _prep(rows_lalu_ag)

    agg_ini_ag  = _agg_wok(df_ini_ag,  tgl_closing)
    agg_lalu_ag = _agg_wok(df_lalu_ag, tgl_mtd_lalu)

    semua_wok_ag = set(list(agg_ini_ag.keys()) + list(agg_lalu_ag.keys()))

    wok_rows_ag = []
    for wok in semua_wok_ag:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok), "LAINNYA"
        )
        row = _build_row("WOK", wok, branch, agg_ini_ag, agg_lalu_ag, [wok])
        wok_rows_ag.append(row)
    wok_rows_ag.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    branch_rows_ag = []
    for branch in branch_names:
        bwoks = [r["name"] for r in wok_rows_ag if r["branch"] == branch]
        if not bwoks:
            continue
        row = _build_row("BRANCH", branch, None, agg_ini_ag, agg_lalu_ag, bwoks)
        branch_rows_ag.append(row)

    region_row_ag = _build_row("REGION", REGION_NAME, None, agg_ini_ag, agg_lalu_ag, list(semua_wok_ag))

    # ── Raw data unpaid untuk CSV (kolom lengkap) ──────────────────────────
    CSV_COLS = [
        "bb_id", "ps_ts", "channel_group", "sf_code", "sf_company_name",
        "product_commercial_name", "wok", "branch", "los_category", "bill_n",
        "bill_amount", "clearing_amount", "paid_flag", "payment_date"
    ]
    if not df_ini.empty:
        df_unpaid = df_ini[df_ini["paid_flag"] == 0][CSV_COLS].copy()
        df_unpaid["bill_n"] = df_unpaid["bill_n"].map(
            lambda n: BILL_LABELS.get(n, f"BILL-{n}")
        )
    else:
        df_unpaid = pd.DataFrame()

    return {
        "tgl_closing"    : tgl_closing,
        "bl_label"       : bp_lalu.strftime("%b %Y").upper(),
        "bi_label"       : bp_ini.strftime("%b %Y").upper(),
        "bp_ini"         : bp_ini,
        "is_closing_mode": tgl_closing.day <= 5,
        # All channel
        "region"         : region_row,
        "branches"       : branch_rows,
        "woks"           : wok_rows,
        # Agency only
        "region_ag"      : region_row_ag,
        "branches_ag"    : branch_rows_ag,
        "woks_ag"        : wok_rows_ag,
        "bill_order"     : BILL_ORDER,
        "bill_labels"    : BILL_LABELS,
        "df_unpaid"      : df_unpaid,
    }
