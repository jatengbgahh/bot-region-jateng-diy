"""
calculator_caps.py — Kalkulasi metrik CAPS (Churn) dari churn_dd_YYYYMM

Logic:
  - Nama tabel LITERAL: churn_dd_YYYYMM (bukan per-tanggal)
  - Filter region LIKE 'JATENG%' (penamaan region beda antar bulan: JATENG-DIY di
    churn_dd_202606, JATENG di churn_dd_202607, dst — LIKE prefix nangkep dua-duanya)
  - M   = COUNT(DISTINCT bb_id) dgn deactivation_date BETWEEN awal-bulan-closing s/d tgl_closing
  - M-1 = COUNT(DISTINCT bb_id) dgn deactivation_date BETWEEN awal-bulan-lalu s/d tgl (hari sama) bulan lalu
          (dari tabel churn_dd_<bulan-lalu>)
  - MoM = (M - M-1) / M-1 * 100   (persen perubahan; churn naik = positif = jelek)
  - Breakdown per grup pakai los_category
  - Target diambil dari sheet TARGET_CAPS (BULAN=YYYY-MM, WOK, TARGET_CAPS)
  - Ach = M / TARGET * 100
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

DB_REGION_CAPS = "JATENG"   # prefix; DB query pakai LIKE 'JATENG%' krn penamaan
                            # region beda antar bulan (JATENG-DIY vs JATENG)

# Mapping kode los_category (di DB) -> key grup internal
LOS_CODE_TO_GROUP = {
    "01. NEW_SALES"     : "new_sales",
    "02. 1 - 3 Months"  : "m1_3",
    "03. 4 - 6 Months"  : "m4_6",
    "04. 7 - 12 Months" : "m7_12",
    "05. 1 - 2 Years"   : "y1_2",
    "06. > 2 Years"     : "gt2y",
}

GROUP_ORDER  = ["new_sales", "m1_3", "m4_6", "m7_12", "y1_2", "gt2y"]
GROUP_LABELS = {
    "new_sales": "New Sales",
    "m1_3"     : "1-3 Bulan",
    "m4_6"     : "4-6 Bulan",
    "m7_12"    : "7-12 Bulan",
    "y1_2"     : "1-2 Tahun",
    "gt2y"     : ">2 Tahun",
}


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["wok"]              = df["wok"].str.strip().str.upper()
    df["branch"]           = df["branch"].str.strip().str.upper()
    df["los_category"]     = df["los_category"].str.strip()
    df["deactivation_date"] = pd.to_datetime(df["deactivation_date"], errors="coerce")
    df["group"]            = df["los_category"].map(LOS_CODE_TO_GROUP)
    return df


def _mom(m, m1):
    if m1 and m1 != 0:
        return round((m - m1) / m1 * 100, 2)
    return None


def _agg_wok(df: pd.DataFrame, tgl_awal: date, tgl_akhir: date) -> dict:
    """
    Aggregate per WOK dalam rentang MTD [tgl_awal, tgl_akhir].
    Return dict: {wok: {"total": n, "new_sales": n, "m1_3": n, ...}}
    """
    if df.empty:
        return {}

    mask = (df["deactivation_date"] >= pd.Timestamp(tgl_awal)) & \
           (df["deactivation_date"] <= pd.Timestamp(tgl_akhir))
    dfm = df[mask]

    result = {}
    for wok, grp in dfm.groupby("wok"):
        d = {"total": grp["bb_id"].nunique()}
        for g in GROUP_ORDER:
            d[g] = grp[grp["group"] == g]["bb_id"].nunique()
        result[wok] = d
    return result


def _build_row(name, branch, target, agg_ini, agg_lalu, woks_list):
    def _sum(agg, key):
        return sum(agg.get(w, {}).get(key, 0) for w in woks_list)

    m_total  = _sum(agg_ini,  "total")
    m1_total = _sum(agg_lalu, "total")

    row = {
        "name"  : name,
        "branch": branch,
        "target": target,
        "m1"    : m1_total,
        "m"     : m_total,
        "mom"   : _mom(m_total, m1_total),
        "ach"   : round(m_total / target * 100, 2) if target else None,
    }
    for g in GROUP_ORDER:
        gm  = _sum(agg_ini,  g)
        gm1 = _sum(agg_lalu, g)
        row[f"{g}_m1"]  = gm1
        row[f"{g}_m"]   = gm
        row[f"{g}_mom"] = _mom(gm, gm1)

    return row


def _target_lookup(target_df: pd.DataFrame, bulan_label: str) -> dict:
    """target_df: DataFrame sheet TARGET_CAPS (BULAN, WOK, TARGET_CAPS). Return {wok: target}"""
    if target_df is None or target_df.empty:
        return {}
    sub = target_df[target_df["BULAN"] == bulan_label]
    return dict(zip(sub["WOK"].str.strip().str.upper(), sub["TARGET_CAPS"]))


def hitung_caps(tgl_closing: date, target_df: pd.DataFrame = None) -> dict:
    bp_ini  = tgl_closing.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)

    tgl_mtd_lalu = tgl_closing - relativedelta(months=1)

    tabel_ini  = f"churn_dd_{bp_ini.strftime('%Y%m')}"
    tabel_lalu = f"churn_dd_{bp_lalu.strftime('%Y%m')}"

    rows_ini  = db.query_caps(tabel_ini,  DB_REGION_CAPS)
    rows_lalu = db.query_caps(tabel_lalu, DB_REGION_CAPS)

    df_ini  = _prep(pd.DataFrame(rows_ini)  if rows_ini  else pd.DataFrame())
    df_lalu = _prep(pd.DataFrame(rows_lalu) if rows_lalu else pd.DataFrame())

    # Tanggal data yang benar-benar terwakili di churn_dd (tabel kadang belum
    # terisi penuh s/d tgl_closing). Dipakai untuk keterangan sumber+tanggal di
    # caption & gambar, biar tidak salah persepsi dibanding report retensi
    # (by Channel / by Reason) yang bisa mundur lebih jauh.
    tgl_data = tgl_closing
    if not df_ini.empty and "deactivation_date" in df_ini.columns:
        _dmax = df_ini["deactivation_date"].max()
        if pd.notna(_dmax):
            tgl_data = min(_dmax.date(), tgl_closing)

    agg_ini  = _agg_wok(df_ini,  bp_ini.replace(day=1),  tgl_closing)
    agg_lalu = _agg_wok(df_lalu, bp_lalu.replace(day=1), tgl_mtd_lalu)

    semua_wok = set(list(agg_ini.keys()) + list(agg_lalu.keys())) | set(w.upper() for w in WOK_ORDER)

    target_map = _target_lookup(target_df, bp_ini.strftime("%Y-%m"))

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        canon = next((w for w in WOK_ORDER if w.upper() == wok), wok)
        branch = WOK_TO_BRANCH.get(canon, "LAINNYA")
        target = target_map.get(wok, 0)
        row = _build_row(canon, branch, target, agg_ini, agg_lalu, [wok])
        wok_rows.append(row)

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"].upper()) if r["name"].upper() in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    for branch in branch_names:
        bwoks = [r["name"] for r in wok_rows if r["branch"] == branch]
        if not bwoks:
            continue
        bwoks_upper = [w.upper() for w in bwoks]
        btarget = sum(target_map.get(w, 0) for w in bwoks_upper)
        row = _build_row(branch, None, btarget, agg_ini, agg_lalu, bwoks_upper)
        branch_rows.append(row)

    # ── REGION row ────────────────────────────────────────────────────────
    all_wok_upper = [w.upper() for w in semua_wok]
    region_target = sum(target_map.get(w, 0) for w in all_wok_upper)
    region_row = _build_row(REGION_NAME, None, region_target, agg_ini, agg_lalu, list(semua_wok))

    return {
        "tgl_closing" : tgl_closing,
        "tgl_data"    : tgl_data,          # tgl data churn_dd yang benar2 terisi
        "tgl_diminta" : tgl_closing,       # tgl di perintah /caps
        "src_label"   : "churn_dd",
        "tgl_mundur"  : tgl_data < tgl_closing,
        "bi_label"    : bp_ini.strftime("%b %Y").upper(),
        "bl_label"    : bp_lalu.strftime("%b %Y").upper(),
        "region"      : region_row,
        "branches"    : branch_rows,
        "woks"        : wok_rows,
        "group_order" : GROUP_ORDER,
        "group_labels": GROUP_LABELS,
    }
