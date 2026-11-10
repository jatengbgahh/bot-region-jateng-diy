"""
agresif_lite.py — Versi LITE report /agresif.

Cuma 2 tabel, kolom dipangkas jadi (persis mockup yg diminta user 08-Sep-2026):
  NO | BRANCH | CITY | KECAMATAN | RE M-1 | RE M | MoM RE | PS M-1 | PS M | MoM PS | TARGET | ACH

  1) REPORT NEW SALES LOKASI AGRESIF  — 47 kecamatan + 4 Agresif city (kolom
     KECAMATAN diisi; baris Agresif city KECAMATAN kosong)
  2) REPORT NEW SALES ALL FMC CITY    — FMC City v.1 (12) + v.2 (13) + v.3 (12) (kolom
     KECAMATAN tidak ada / kosong)

Angka dihitung ULANG di sini TAPI pakai helper yg SAMA PERSIS dgn
calculator_agresif.py (_count/_mom/_ach/periods) supaya definisi metrik
identik dgn report /agresif penuh — cuma level TOTAL (tanpa split Low/Mid
High), plus RE M-1 (bulan sebelumnya) yg di report PS penuh tidak ditampilkan.

  RE M-1 / RE M = COUNT baris kab2/kec2 cocok, order AO*, bulan_re == bulan
                  (prev / now), tgl_re <= hari cutoff        (TANPA filter MIDLOW)
  PS M-1 / PS M = sama, tapi kolom bulan_ps/tgl_ps
  MoM          = (M - M1) / M1                (guard 0 kalau M1 0/kosong)
  TARGET       = TARGET_PS_LOW + TARGET_PS_MIDHIGH (dari sheet target yg sama
                 dgn /agresif — TARGET_KEC AGRESIF utk report 1, TARGET_CITY
                 FMC utk report 2)
  ACH          = PS M / TARGET               (None kalau TARGET 0/kosong)

Baris subtotal branch & JATENG-DIY = SUM angka mentah anggota, lalu MoM/ACH
dihitung ULANG dari angka yg sudah dijumlah (bukan rata-rata %-metric) —
sama pola dgn calculator_agresif.

Report 2 (FMC) SENGAJA tidak pakai hasil geocoding (kolom kab2) — city
di-match dari kolom `kabupaten` mentah DB, persis seperti
calculator_agresif.hitung_agresif_fmc.
"""
from datetime import date

import pandas as pd

from calculator_agresif import _count, _mom, _ach, periods, _target_kec_lookup, _target_fmc_lookup
from agresif_refdata import (
    KEC_47, AGRESIF_CITY_4, FMC_V1, FMC_V2, FMC_V3, BRANCH_ORDER_AGRESIF,
)

_RAW_KEYS = ["re_m1", "re_m", "ps_m1", "ps_m", "target"]


def _row_counts(df, kab2, kec2, bulan_now, bulan_prev, day_max):
    return {
        "re_m1": _count(df, "bulan_re", "tgl_re", bulan_prev, day_max, kab2, kec2),
        "re_m":  _count(df, "bulan_re", "tgl_re", bulan_now,  day_max, kab2, kec2),
        "ps_m1": _count(df, "bulan_ps", "tgl_ps", bulan_prev, day_max, kab2, kec2),
        "ps_m":  _count(df, "bulan_ps", "tgl_ps", bulan_now,  day_max, kab2, kec2),
    }


def _finalize(row):
    row["mom_re"] = _mom(row["re_m"], row["re_m1"])
    row["mom_ps"] = _mom(row["ps_m"], row["ps_m1"])
    tgt = row.get("target") or 0
    row["ach"] = _ach(row["ps_m"], tgt if tgt else None)
    return row


def _aggregate(members, **extra):
    summed = {k: sum((m.get(k) or 0) for m in members) for k in _RAW_KEYS}
    return _finalize({**summed, **extra})


def _build(df, entries, target_of, cutoff, has_kec):
    """entries: list {branch, city, [kec]}. target_of(entry) -> target total (float|None)."""
    bulan_now, bulan_prev, day_max = periods(cutoff)

    rows = []
    for e in entries:
        kab2 = e["city"].strip().upper()
        kec2 = e["kec"].strip().upper() if has_kec and e.get("kec") else None
        rc = _row_counts(df, kab2, kec2, bulan_now, bulan_prev, day_max)
        rows.append(_finalize({
            "branch": e["branch"], "city": e["city"],
            "kec": e.get("kec", "") if has_kec else "",
            "target": target_of(e), **rc,
        }))

    branch_rows = []
    for b in BRANCH_ORDER_AGRESIF:
        members = [r for r in rows if r["branch"] == b]
        if members:
            branch_rows.append(_aggregate(members, branch=b, city="", kec=""))

    jateng_row = _aggregate(rows, branch="JATENG-DIY", city="", kec="")
    return rows, branch_rows, jateng_row


def hitung_lite_lokasi(cutoff: date, df_calc: pd.DataFrame, target_kec_df: pd.DataFrame) -> dict:
    bulan_now, _, _ = periods(cutoff)
    tlook = _target_kec_lookup(target_kec_df, bulan_now)

    def target_of(e):
        key = (e["city"].strip().upper(),
               e["kec"].strip().upper() if e.get("kec") else "")
        t = tlook.get(key)
        if not t:
            return None
        return (t.get("ps_low") or 0) + (t.get("ps_mid") or 0)

    entries = KEC_47 + AGRESIF_CITY_4
    rows, branch_rows, jateng_row = _build(df_calc, entries, target_of, cutoff, has_kec=True)
    return {"cutoff": cutoff, "rows": rows, "branch_rows": branch_rows,
            "jateng_row": jateng_row, "has_kec": True}


def hitung_lite_fmc(cutoff: date, df_calc: pd.DataFrame, target_fmc_df: pd.DataFrame) -> dict:
    bulan_now, _, _ = periods(cutoff)
    tlook = _target_fmc_lookup(target_fmc_df, bulan_now)

    # City di-match dari kolom `kabupaten` mentah DB (BUKAN kab2 hasil
    # geocoding) — persis calculator_agresif.hitung_agresif_fmc. View ramping
    # supaya copy tidak menggandakan seluruh kolom raw.
    _cols = ["order_id", "bulan_re", "tgl_re", "bulan_ps", "tgl_ps", "kec2"]
    df_fmc = df_calc[[c for c in _cols if c in df_calc.columns]].copy()
    df_fmc["kab2"] = (df_calc["kabupaten"].astype(str).str.strip().str.upper()
                      .replace({"NAN": "", "NONE": ""}))

    def target_of(e):
        t = tlook.get(e["city"].strip().upper())
        if not t:
            return None
        return (t.get("ps_low") or 0) + (t.get("ps_mid") or 0)

    # Urutan seksi: FMC City v.1, v.2, v.3 (sejak 04-Nov-2026).
    n1, n2 = len(FMC_V1), len(FMC_V2)
    entries = FMC_V1 + FMC_V2 + FMC_V3
    rows, branch_rows, jateng_row = _build(df_fmc, entries, target_of, cutoff, has_kec=False)
    v1, v2, v3 = rows[:n1], rows[n1:n1 + n2], rows[n1 + n2:]
    # new_rows/old_rows dipertahankan utk kompatibilitas caption (new+old = semua).
    return {"cutoff": cutoff, "rows": rows,
            "v1_rows": v1, "v2_rows": v2, "v3_rows": v3,
            "new_rows": v2 + v3, "old_rows": v1, "branch_rows": branch_rows,
            "jateng_row": jateng_row, "has_kec": False, "n_new": len(v2) + len(v3)}


# ==============================================================================
# CAPTION LITE — dari hasil calculator_agresif PENUH (butuh field %-metric
# total_ach/total_mom + branch_rows/rows-nya), TAPI blok "Growth Total PS /
# MoM PS Low / MoM PS Mid High" DIHILANGKAN (permintaan user 09-Sep-2026).
# Yang dipertahankan: TOP ACH PS, TOP MoM PS, Worst MoM PS (level BRANCH +
# item kecamatan/city). Dipakai /agresif (kini = report LITE).
# ==============================================================================
def _cap_pct(v):
    return "-" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v * 100:.1f}%"


def _cap_best(items, field, want_max):
    valid = [r for r in items if r.get(field) is not None]
    if not valid:
        return None
    return (max if want_max else min)(valid, key=lambda r: r[field])


def _cap_block(title, date_label, items, branch_rows, name_key, name_label):
    def bn(r):
        return r["branch"] if r else "-"

    def nm(r):
        v = r.get(name_key) if r else None
        return str(v).title() if v else "-"

    def vv(r, f):
        return _cap_pct(r[f]) if r else "-"

    ta_b = _cap_best(branch_rows, "total_ach", True)
    ta_i = _cap_best(items, "total_ach", True)
    tm_b = _cap_best(branch_rows, "total_mom", True)
    tm_i = _cap_best(items, "total_mom", True)
    wm_b = _cap_best(branch_rows, "total_mom", False)
    wm_i = _cap_best(items, "total_mom", False)
    return "\n".join([
        title, date_label, "",
        "TOP ACH PS:",
        f"- BRANCH {bn(ta_b)} = {vv(ta_b, 'total_ach')}",
        f"- {name_label} {nm(ta_i)} = {vv(ta_i, 'total_ach')}", "",
        "TOP MoM PS:",
        f"- BRANCH {bn(tm_b)} = {vv(tm_b, 'total_mom')}",
        f"- {name_label} {nm(tm_i)} = {vv(tm_i, 'total_mom')}", "",
        "Worst MoM PS:",
        f"- BRANCH {bn(wm_b)} = {vv(wm_b, 'total_mom')}",
        f"- {name_label} {nm(wm_i)} = {vv(wm_i, 'total_mom')}",
    ])


def build_lite_captions(cutoff: date, r_ps_full: dict, r_fmc_full: dict) -> tuple:
    """(caption_lokasi, caption_fmc). r_ps_full/r_fmc_full = hasil
    calculator_agresif.hitung_agresif_ps / hitung_agresif_fmc.

    LOKASI: nominasi item HANYA kecamatan asli (baris ber-`kec`), 4 "Agresif
    city" dikecualikan dari nominasi — sama pola hitung_agresif_ps."""
    date_label = cutoff.strftime("%d-%b-%Y").upper()

    ps_items = [r for r in r_ps_full["rows"] if r.get("kec")]
    cap1 = _cap_block("REPORT NEW SALES LOKASI AGRESIF", date_label,
                      ps_items, r_ps_full["branch_rows"], "kec", "Kecamatan")

    fmc_items = r_fmc_full.get("new_rows", []) + r_fmc_full.get("old_rows", [])
    cap2 = _cap_block("REPORT NEW SALES ALL FMC CITY", date_label,
                      fmc_items, r_fmc_full["branch_rows"], "city", "City")
    return cap1, cap2
