"""
calculator_klaim.py — Rekap Data Pelanggan Klaim per Nama Program
Source: Meta/Rekap Data Pelanggan Klaim.xlsx, sheet 'All Klaim' (Nomor
Internet, Nama Program, WOK, Product Commercial Name — dari sistem klaim,
bukan DB. Dibaca langsung dari file, tidak perlu upload ke bot).

Paid Flag di-refresh LIVE dari bwmp_c3mr_dd_YYYYMM by Nomor Internet setiap
/klaim dijalankan (db.query_c3mr_paid_status) — jadi tidak lagi bergantung
VLOOKUP manual, selalu sesuai kondisi DB saat command dijalankan.
Bb_id yang tidak ketemu di bwmp_c3mr_dd bulan berjalan (misal belum masuk
billing) fallback ke kolom 'Paid Flag' yang sudah ada di file (kalau ada).

Paid Flag: 1 = paid, selain itu (0 / 'X' / kosong) dihitung unpaid.
%C3MR = Jml Paid / Jml Pelanggan * 100.

hitung_klaim() juga mengembalikan 'raw_unpaid_df': raw data (kolom & bentuk
sama seperti sheet 'All Klaim') yang sudah difilter baris UNPAID saja
(Paid Flag live == 0, termasuk yang asalnya 'X') — baris yang sudah paid
dihilangkan. Dipakai bot.py utk export raw file per /klaim.
"""

import os
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLAIM_XLSX_PATH = os.path.join(_ROOT_DIR,
                                "resources", "klaim", "Rekap Data Pelanggan Klaim.xlsx")
REGION_LABEL = "JATENG DIY"


def _bill_period_now(today: date = None) -> date:
    """Tgl 1-5: bill_period bulan lalu (masih periode closing). Tgl 6+: bulan berjalan."""
    today = today or date.today()
    if today.day <= 5:
        return (today - relativedelta(months=1)).replace(day=1)
    return today.replace(day=1)


def _pct(paid: int, total: int):
    if total:
        return round(paid / total * 100, 1)
    return None


def _agg(df: pd.DataFrame, group_cols: list) -> list:
    rows = []
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        total  = len(g)
        paid   = int((g["_paid"] == 1).sum())
        unpaid = total - paid
        row = dict(zip(group_cols, keys))
        row.update(
            jml_pelanggan=total,
            jml_paid=paid,
            jml_unpaid=unpaid,
            pct_c3mr=_pct(paid, total),
        )
        rows.append(row)
    return rows


def hitung_klaim(path: str = KLAIM_XLSX_PATH) -> dict:
    """
    Baca sheet 'All Klaim' dari path (default: Meta/Rekap Data Pelanggan
    Klaim.xlsx). Kolom minimal: 'Nomor Internet', 'Nama Program', 'WOK'
    ('Product Commercial Name' & 'Paid Flag' opsional).
    """
    df = pd.read_excel(path, sheet_name="All Klaim")
    df.columns = df.columns.str.strip()
    raw_columns = list(df.columns)  # kolom asli sheet "All Klaim", dipakai lagi utk export raw unpaid

    df["Nomor Internet"] = pd.to_numeric(df["Nomor Internet"], errors="coerce")
    df = df.dropna(subset=["Nomor Internet"])
    df["Nomor Internet"] = df["Nomor Internet"].astype("int64")

    df["Nama Program"] = df["Nama Program"].astype(str).str.strip()
    df["WOK"] = df["WOK"].astype(str).str.strip().str.upper()
    if "Product Commercial Name" in df.columns:
        df["Product Commercial Name"] = df["Product Commercial Name"].astype(str).str.strip()
    else:
        df["Product Commercial Name"] = "-"

    # ── Refresh Paid Flag live dari bwmp_c3mr_dd ───────────────────────────
    bp = _bill_period_now()
    db_last_update = db.query_c3mr_last_update(bp)
    bb_ids = df["Nomor Internet"].tolist()
    rows_db = db.query_c3mr_paid_status(bb_ids, bp)
    df_db = pd.DataFrame(rows_db)

    if not df_db.empty:
        df_db["bb_id"] = pd.to_numeric(df_db["bb_id"], errors="coerce").astype("int64")
        df_db["paid_flag"] = pd.to_numeric(df_db["paid_flag"], errors="coerce")
        df_db = df_db.drop_duplicates(subset="bb_id", keep="first")
        df = df.merge(
            df_db[["bb_id", "paid_flag", "wok"]].rename(columns={"wok": "wok_db"}),
            left_on="Nomor Internet", right_on="bb_id", how="left"
        )
    else:
        df["paid_flag"] = pd.NA
        df["wok_db"] = pd.NA

    n_total    = len(df)
    n_found_db = int(df["paid_flag"].notna().sum())

    # Fallback ke Paid Flag file upload untuk bb_id yang tidak ketemu di DB bulan ini
    if "Paid Flag" in df.columns:
        fallback = pd.to_numeric(df["Paid Flag"], errors="coerce").fillna(0)
    else:
        fallback = pd.Series(0, index=df.index)
    df["_paid"] = df["paid_flag"].fillna(fallback)
    df["_paid"] = pd.to_numeric(df["_paid"], errors="coerce").fillna(0).astype(int)

    # WOK: pakai hasil live DB kalau ketemu, else WOK dari file upload
    df["WOK"] = df["wok_db"].where(df["wok_db"].notna(), df["WOK"])
    df["WOK"] = df["WOK"].astype(str).str.strip().str.upper()
    df["Branch"] = df["WOK"].map(lambda w: WOK_TO_BRANCH.get(w, "LAINNYA"))

    # Paid Flag utk raw export: live dari DB (0/1) kalau bb_id ketemu, else nilai
    # asli dari file upload (bisa 0 / 1 / 'X') — jadi raw file tetap menunjukkan
    # 'X' apa adanya, bukan dipaksa jadi 0.
    def _clean_flag(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return v

    if "Paid Flag" in df.columns:
        df["Paid Flag"] = df["paid_flag"].where(df["paid_flag"].notna(), df["Paid Flag"])
        df["Paid Flag"] = df["Paid Flag"].map(_clean_flag)

    # ── Raw export: baris UNPAID saja (Paid Flag live == 0, termasuk asal 'X') ─
    raw_cols_present = [c for c in raw_columns if c in df.columns]
    df_raw_unpaid = df.loc[df["_paid"] == 0, raw_cols_present].copy()
    df_raw_unpaid = df_raw_unpaid.sort_values("Nomor Internet").reset_index(drop=True)

    total  = len(df)
    paid   = int((df["_paid"] == 1).sum())
    unpaid = total - paid

    # ── Tabel 1: Nama Program x Product Commercial Name (detail) ──────────
    detail_rows = _agg(df, ["Nama Program", "Product Commercial Name"])
    detail_rows.sort(key=lambda r: (r["Nama Program"], r["Product Commercial Name"]))

    # ── Tabel 2: Branch x WOK x Nama Program (geografis) ───────────────────
    geo_rows = _agg(df, ["Branch", "WOK", "Nama Program"])
    branch_idx = {b: i for i, b in enumerate(BRANCH_ORDER)}
    wok_idx    = {w: i for i, w in enumerate(WOK_ORDER)}
    geo_rows.sort(key=lambda r: (
        branch_idx.get(r["Branch"], 999),
        wok_idx.get(r["WOK"], 999),
        r["Nama Program"],
    ))

    # ── Tabel 3: Nama Program (ringkasan) ──────────────────────────────────
    program_rows = _agg(df, ["Nama Program"])
    program_rows.sort(key=lambda r: r["Nama Program"])

    grand_total = {
        "jml_pelanggan": total,
        "jml_paid": paid,
        "jml_unpaid": unpaid,
        "pct_c3mr": _pct(paid, total),
    }

    return {
        "bill_period": bp,
        "cutoff": date.today(),
        "db_last_update": db_last_update,
        "n_total": n_total,
        "n_found_db": n_found_db,
        "region_label": REGION_LABEL,
        "detail_rows": detail_rows,
        "geo_rows": geo_rows,
        "program_rows": program_rows,
        "grand_total": grand_total,
        "raw_unpaid_df": df_raw_unpaid,
    }
