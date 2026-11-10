"""
calculator_djpprio.py — Kalkulasi report "DJP ODP Priority" (/djpprio), native
Python — reimplementasi dari logika JS di Willy/_djp_template.html (dulu
manual: buka HTML di browser, upload file, klik Generate, download PNG).

Konsep: setiap ODP di master "WL ODP DJP" (bulan berjalan) punya WOK + FINAL
FLAG prioritas (P1A..P3B). Approve-Tugas (upload user, WAJIB, berisi ODP yang
sudah dikerjakan SF tanggal berapa) dicocokkan ke master -> %Visit = ODP yang
sudah "visited" / total ODP target per WOK x FLAG, s/d tanggal cutoff.

Sumber master: file lokal "DJP ODP Priority - <Month> <Year>.xlsx" TERBARU di
folder Willy/ (auto-pick by mtime, sama pola dgn _find_latest_target_file di
bot.py) — sheet-nya BEDA nama tiap bulan ("WL ODP DJP" / "ODP DJP Priority
<Bulan>"), jadi dideteksi dari ISI KOLOM (ODP NAME + WOK + FINAL FLAG), bukan
nama sheet tetap.
"""
import glob
import os
import re
from datetime import date, datetime

import pandas as pd

FLAGS = ["P1A", "P1B", "P2A", "P2B", "P3A", "P3B"]
BRANCH_ORDER = ["MAGELANG", "PEKALONGAN", "PURWOKERTO", "SEMARANG", "SURAKARTA", "YOGYAKARTA"]
WOK_BRANCH = {
    "KEBUMEN": "MAGELANG", "MAGELANG TEMANGGUNG": "MAGELANG",
    "BATANG": "PEKALONGAN", "PEMALANG PURBALINGGA": "PEKALONGAN", "TEGAL BREBES": "PEKALONGAN",
    "CILACAP BANYUMAS": "PURWOKERTO", "WONOSOBO BANJARNEGARA": "PURWOKERTO",
    "DEMAK": "SEMARANG", "JEPARA KUDUS - PATI": "SEMARANG", "SEMARANG 1": "SEMARANG", "SEMARANG 2": "SEMARANG",
    "BOYOLALI": "SURAKARTA", "SRAGEN": "SURAKARTA", "SURAKARTA": "SURAKARTA",
    "YOGYA 1": "YOGYAKARTA", "YOGYA 2": "YOGYAKARTA",
}


# ==============================================================================
# LOOKUP KOLOM FLEKSIBEL (nama kolom beda-beda tiap file, sama pola dgn findCol JS)
# ==============================================================================
def _find_col(columns, candidates) -> str | None:
    norm = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand in norm:
            return norm[cand]
    for cand in candidates:
        for low, orig in norm.items():
            if cand in low:
                return orig
    return None


# ==============================================================================
# MASTER "WL ODP DJP" (bulan berjalan) — ODP NAME / WOK / FINAL FLAG
# ==============================================================================
def find_latest_master_file(folder: str) -> str | None:
    candidates = glob.glob(os.path.join(folder, "DJP ODP Priority*.xlsx"))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def load_master_from_file(path: str) -> dict:
    """Cari sheet yang punya kolom ODP NAME + WOK + FINAL FLAG (nama sheet beda
    tiap bulan, jadi dideteksi dari isi kolom, bukan nama tetap). Return
    {odp_name_upper: (wok_upper, flag_upper)}."""
    return load_master_full(path)[0]


def load_master_full(path: str) -> tuple:
    """Sama seperti load_master_from_file(), TAPI juga mengembalikan DataFrame
    mentah sheet aslinya (semua kolom apa adanya, TIDAK diseragamkan upper/strip)
    — dipakai utk export "Raw Data" (mirror tombol "Download Raw Data (A:AX)"
    di djp_report_generator.html: master asli + kolom Flag Visit).
    Return (dict {odp_name_upper: (wok_upper, flag_upper)}, df_master_asli)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if not header:
            continue
        cols = [str(c) if c is not None else "" for c in header]
        c_name = _find_col(cols, ["odp name", "odp"])
        c_wok = _find_col(cols, ["wok"])
        c_flag = _find_col(cols, ["final flag"])
        if not (c_name and c_wok and c_flag):
            continue
        i_name, i_wok, i_flag = cols.index(c_name), cols.index(c_wok), cols.index(c_flag)
        out = {}
        raw_rows = []
        for row in rows_iter:
            if row is None or len(row) <= max(i_name, i_wok, i_flag):
                continue
            name = str(row[i_name] or "").strip().upper()
            wok = str(row[i_wok] or "").strip().upper()
            flag = str(row[i_flag] or "").strip().upper()
            if not name or not wok or flag not in FLAGS:
                continue
            out.setdefault(name, (wok, flag))   # baris pertama menang, sama spt JS
            raw_rows.append(row)
        if out:
            df = pd.DataFrame(raw_rows, columns=header)
            return out, df
    raise RuntimeError(
        f"Master '{os.path.basename(path)}' tidak punya sheet dengan kolom "
        f"ODP NAME + WOK + FINAL FLAG lengkap."
    )


def build_raw_export_df(master_df: pd.DataFrame, visited: set) -> pd.DataFrame:
    """Master asli + kolom 'Flag Visit' (1 kalau ODP ada di `visited`, else 0)
    — persis downloadRaw() JS: raw A:AX + Flag Visit dihitung ULANG dari
    approve-tugas + cutoff yang dipakai (bukan kolom Flag Visit lama di file,
    kalau ada)."""
    cols = list(master_df.columns)
    c_name = _find_col(cols, ["odp name", "odp"])
    out = master_df.copy()
    names = out[c_name].astype(str).str.strip().str.upper()
    out["Flag Visit"] = names.isin(visited).astype(int)
    return out


# ==============================================================================
# APPROVE-TUGAS (upload user) -> set ODP yang sudah "visited" s/d cutoff
# ==============================================================================
def _parse_date_key(v) -> int | None:
    """Tanggal (Timestamp/datetime/str) -> int yyyymmdd, atau None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return v.year * 10000 + v.month * 100 + v.day
    s = str(v).strip()
    if not s or s == "-":
        return None
    s = re.split(r"[ T]", s)[0]
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
    if m:
        return int(m[1]) * 10000 + int(m[2]) * 100 + int(m[3])
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", s)
    if m:
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        if d > 12 and mo <= 12:
            pass
        elif mo > 12:
            d, mo = mo, d
        return y * 10000 + mo * 100 + d
    try:
        dt = pd.to_datetime(s)
        if pd.isna(dt):
            return None
        return dt.year * 10000 + dt.month * 100 + dt.day
    except Exception:
        return None


def build_visited_set(df_tugas: pd.DataFrame, cutoff: date) -> tuple:
    """Replikasi buildVisited() JS: cocokkan approve-tugas ke bulan report +
    cutoff. Return (visited_set, meta:dict)."""
    cols = list(df_tugas.columns)
    c_odp = _find_col(cols, ["odp", "tugas name", "odp name", "nama odp"])
    c_date = _find_col(cols, ["tugas date", "tanggal finish", "tanggal start", "checkin", "tanggal", "date"])
    c_status = _find_col(cols, ["status"])
    if c_odp is None:
        raise RuntimeError(
            f"Kolom ODP tidak ditemukan di approve-tugas. Header terbaca: {', '.join(str(c) for c in cols)}"
        )

    cutoff_key = cutoff.year * 10000 + cutoff.month * 100 + cutoff.day
    report_month = cutoff.year * 100 + cutoff.month

    visited = set()
    used = skipped_date = skipped_month = skipped_status = 0
    min_key = max_key = None
    status_ok_re = re.compile(r"approve|selesai|done|complete|visit|checkin|hadir", re.I)

    for row in df_tugas.itertuples(index=False, name=None):
        d = dict(zip(cols, row))
        odp = str(d.get(c_odp) or "").strip()
        if not odp or odp == "-":
            continue
        k = _parse_date_key(d.get(c_date)) if c_date else None
        if k is not None:
            if max_key is None or k > max_key:
                max_key = k
            if min_key is None or k < min_key:
                min_key = k
        if k is None:
            skipped_date += 1
            continue
        if k > cutoff_key:
            skipped_date += 1
            continue
        if k // 100 != report_month:
            skipped_month += 1
            continue
        if c_status:
            status_txt = str(d.get(c_status) or "").strip()
            if status_txt and not status_ok_re.search(status_txt):
                skipped_status += 1
                continue
        visited.add(odp)
        used += 1

    meta = {"used": used, "skipped_date": skipped_date, "skipped_month": skipped_month,
            "skipped_status": skipped_status, "min_key": min_key, "max_key": max_key}
    return visited, meta


# ==============================================================================
# AGREGASI + MODEL TABEL (setara buildModel() JS)
# ==============================================================================
def _empty_cell():
    return {"odp": 0, "visit": 0}


def _pct_of(odp, visit):
    return (visit / odp) if odp else None


def _sum_rows(rows: list) -> dict:
    tot = {f: _empty_cell() for f in FLAGS}
    grand = _empty_cell()
    for r in rows:
        for f in FLAGS:
            c = r["cells"][f]
            tot[f]["odp"] += c["odp"]
            tot[f]["visit"] += c["visit"]
            grand["odp"] += c["odp"]
            grand["visit"] += c["visit"]
    return {"flags": tot, "total": grand}


def _make_row(branch, wok, agg) -> dict:
    cells = {f: {"odp": agg["flags"][f]["odp"], "visit": agg["flags"][f]["visit"],
                 "pct": _pct_of(agg["flags"][f]["odp"], agg["flags"][f]["visit"])} for f in FLAGS}
    total = {"odp": agg["total"]["odp"], "visit": agg["total"]["visit"],
             "pct": _pct_of(agg["total"]["odp"], agg["total"]["visit"])}
    return {"branch": branch, "wok": wok, "cells": cells, "total": total}


def build_result(master: dict, visited: set) -> dict:
    """master: {odp_name: (wok, flag)}. Return model siap-render:
    {"detail":[...per WOK...], "subtotals":[...per branch...], "grand":{...},
     "branch_rank":{"top":row,"bottom":row}, "wok_rank":{"top":row,"bottom":row}}."""
    per_wok_flag: dict = {}   # (wok,flag) -> {"odp":n,"visit":n}
    for name, (wok, flag) in master.items():
        key = (wok, flag)
        c = per_wok_flag.setdefault(key, _empty_cell())
        c["odp"] += 1
        if name in visited:
            c["visit"] += 1

    woks = sorted({wok for wok, _ in per_wok_flag.keys()})
    by_branch: dict = {}
    for wok in woks:
        branch = WOK_BRANCH.get(wok, "LAINNYA")
        by_branch.setdefault(branch, []).append(wok)

    ordered_branches = [b for b in BRANCH_ORDER if b in by_branch] + \
                       sorted(b for b in by_branch if b not in BRANCH_ORDER)

    detail, subtotals = [], []
    for branch in ordered_branches:
        wok_list = sorted(by_branch[branch])
        branch_rows = []
        for wok in wok_list:
            agg = {"flags": {f: per_wok_flag.get((wok, f), _empty_cell()) for f in FLAGS}, "total": _empty_cell()}
            for f in FLAGS:
                agg["total"]["odp"] += agg["flags"][f]["odp"]
                agg["total"]["visit"] += agg["flags"][f]["visit"]
            row = _make_row(branch, wok, agg)
            detail.append(row)
            branch_rows.append(row)
        subtotals.append(_make_row("", branch, _sum_rows(branch_rows)))

    grand = _make_row("", "JATENG DIY", _sum_rows(detail))

    def rank(rows):
        valid = [r for r in rows if r["total"]["pct"] is not None]
        if not valid:
            return {"top": None, "bottom": None}
        s = sorted(valid, key=lambda r: r["total"]["pct"])
        return {"top": s[-1], "bottom": s[0]}

    return {
        "detail": detail, "subtotals": subtotals, "grand": grand,
        "branch_rank": rank(subtotals), "wok_rank": rank(detail),
    }
