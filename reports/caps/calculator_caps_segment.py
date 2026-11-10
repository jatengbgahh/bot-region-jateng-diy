"""
calculator_caps_segment.py — Kalkulasi CAPS (Churn) per Customer Segment

Logic:
  - Sama seperti calculator_caps.py: churn_dd_YYYYMM (bulan N, nama tabel LITERAL),
    filter region LIKE 'JATENG%' (label region beda antar bulan: JATENG-DIY vs JATENG).
  - customer_segment didapat dari LEFT JOIN ke ih_cb_cvm_prfl_mm_YYYYMM bulan N-1
    (snapshot profil SEBELUM churn — bulan N pelanggan yg sudah churn tidak akan
    punya profil lagi di tabel bulan N). bb_id yang tidak ketemu segment -> 'Unmapped'.
  - Jml   = COUNT(DISTINCT bb_id) per segment, MtD [awal-bulan-closing, tgl_closing]
  - Cont. = Jml segment / Jml total churn (semua segment, termasuk Unmapped) baris
            tsb * 100
  - MoM   = (Jml - Jml M-1) / Jml M-1 * 100   (churn naik = positif = jelek)
  - M-1 (utk MoM) pakai churn_dd bulan sebelumnya, di-join ke ih_cb_cvm_prfl_mm
    bulan sebelum ITU (N-2) — pola pergeseran sama dgn M/N.
  - Territory: WOK/Branch/Region JATENG-DIY (mengikuti calculator_caps.py).
  - Segment order & label reuse dari calculator_c3mr10s (SEGMENT_ORDER), supaya
    konsisten dgn report /c3mr10s.
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME
from calculator_c3mr10s import SEGMENT_ORDER, SEGMENT_LABEL

DB_REGION_CAPS = "JATENG"   # prefix; DB query pakai LIKE 'JATENG%' krn penamaan
                            # region beda antar bulan (JATENG-DIY vs JATENG)

# Segment yang ditampilkan sbg kolom (Unmapped tetap dihitung di "total"
# utk basis Cont.%, tapi tidak punya kolom sendiri di report)
DISPLAY_SEGMENTS = [s for s in SEGMENT_ORDER if s != "Unmapped"]


def _prep(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["wok"]              = df["wok"].str.strip().str.upper()
    df["branch"]           = df["branch"].str.strip().str.upper()
    df["bb_id"]             = df["bb_id"].astype(str).str.strip()
    df["deactivation_date"] = pd.to_datetime(df["deactivation_date"], errors="coerce")
    df["segment"] = df["customer_segment"].fillna("Unmapped").astype(str).str.strip()
    df.loc[~df["segment"].isin(SEGMENT_ORDER), "segment"] = "Unmapped"
    return df


def _agg_wok(df: pd.DataFrame, tgl_awal: date, tgl_akhir: date) -> dict:
    """Aggregate per WOK dalam rentang MTD. Return {wok: {"total": n, seg: n, ...}}"""
    if df.empty:
        return {}

    mask = (df["deactivation_date"] >= pd.Timestamp(tgl_awal)) & \
           (df["deactivation_date"] <= pd.Timestamp(tgl_akhir))
    dfm = df[mask]

    result = {}
    for wok, grp in dfm.groupby("wok"):
        d = {"total": grp["bb_id"].nunique()}
        for seg in SEGMENT_ORDER:
            d[seg] = grp[grp["segment"] == seg]["bb_id"].nunique()
        result[wok] = d
    return result


def _mom(m, m1):
    if m1:
        return round((m - m1) / m1 * 100, 2)
    return None


def _make_seg_metrics(agg_ini: dict, agg_lalu: dict, woks_list: list) -> tuple[dict, int]:
    def _sum(agg, key):
        return sum(agg.get(w, {}).get(key, 0) for w in woks_list)

    total_i = _sum(agg_ini, "total")
    segs = {}
    for seg in DISPLAY_SEGMENTS:
        jml_i = _sum(agg_ini,  seg)
        jml_l = _sum(agg_lalu, seg)
        segs[seg] = {
            "jml"  : jml_i,
            "cont" : round(jml_i / total_i * 100, 2) if total_i else None,
            "mom"  : _mom(jml_i, jml_l),
        }
    return segs, total_i


def hitung_caps_segment(tgl_closing: date) -> dict:
    bp_ini  = tgl_closing.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)

    tgl_mtd_lalu = tgl_closing - relativedelta(months=1)

    tabel_churn_ini  = f"churn_dd_{bp_ini.strftime('%Y%m')}"
    tabel_churn_lalu = f"churn_dd_{bp_lalu.strftime('%Y%m')}"
    tabel_seg_ini    = f"ih_cb_cvm_prfl_mm_{(bp_ini  - relativedelta(months=1)).strftime('%Y%m')}"
    tabel_seg_lalu   = f"ih_cb_cvm_prfl_mm_{(bp_lalu - relativedelta(months=1)).strftime('%Y%m')}"

    rows_ini  = db.query_caps_segment(tabel_churn_ini,  tabel_seg_ini,  DB_REGION_CAPS)
    rows_lalu = db.query_caps_segment(tabel_churn_lalu, tabel_seg_lalu, DB_REGION_CAPS)

    df_ini  = _prep(rows_ini)
    df_lalu = _prep(rows_lalu)

    # Tgl data churn_dd yang benar2 terisi (lihat catatan di calculator_caps.py).
    tgl_data = tgl_closing
    if not df_ini.empty and "deactivation_date" in df_ini.columns:
        _dmax = df_ini["deactivation_date"].max()
        if pd.notna(_dmax):
            tgl_data = min(_dmax.date(), tgl_closing)

    agg_ini  = _agg_wok(df_ini,  bp_ini.replace(day=1),  tgl_closing)
    agg_lalu = _agg_wok(df_lalu, bp_lalu.replace(day=1), tgl_mtd_lalu)

    semua_wok = set(list(agg_ini.keys()) + list(agg_lalu.keys())) | set(w.upper() for w in WOK_ORDER)

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        canon  = next((w for w in WOK_ORDER if w.upper() == wok), wok)
        branch = WOK_TO_BRANCH.get(canon, "LAINNYA")
        segs, total_i = _make_seg_metrics(agg_ini, agg_lalu, [wok])
        wok_rows.append({
            "level"   : "WOK",
            "name"    : canon,
            "branch"  : branch,
            "segments": segs,
            "total"   : total_i,
        })

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
        segs, total_i = _make_seg_metrics(agg_ini, agg_lalu, bwoks_upper)
        branch_rows.append({
            "level"   : "BRANCH",
            "name"    : branch,
            "segments": segs,
            "total"   : total_i,
        })

    # ── REGION row ────────────────────────────────────────────────────────
    segs, total_i = _make_seg_metrics(agg_ini, agg_lalu, list(semua_wok))
    region_row = {
        "level"   : "REGION",
        "name"    : REGION_NAME,
        "segments": segs,
        "total"   : total_i,
    }

    return {
        "tgl_closing"  : tgl_closing,
        "tgl_data"     : tgl_data,
        "tgl_diminta"  : tgl_closing,
        "src_label"    : "churn_dd",
        "tgl_mundur"   : tgl_data < tgl_closing,
        "bi_label"     : bp_ini.strftime("%b %Y").upper(),
        "bl_label"     : bp_lalu.strftime("%b %Y").upper(),
        "region"       : region_row,
        "branches"     : branch_rows,
        "woks"         : wok_rows,
        "segment_order": DISPLAY_SEGMENTS,
        "segment_label": SEGMENT_LABEL,
    }
