"""
calculator_dailyre.py — Monitoring (New) Daily RE (perintah /dailyre DD/MM/YYYY)

Sumber data:
  - Target base weekday/weekend per WOK
      tika/TEMPLATE REPORT TARGET RE BARU - fixed.xlsx
      sheet "REPORT TARGET", kolom "Target RE Daily Weekday" / "Target RE Daily Weekend"
  - RE aktual per WOK per hari
      db.query_re_ps()  ->  tabel dashboard_hourly_sales_YYYYMM  (sumber "hourly")
      untuk tanggal historis diambil FULL DAY (semua activity_hour).

Rumus (revisi 10-Sep-2026, ikut tampilan terbaru yg diminta user):

  base(d)          = Target RE Weekend  bila d Sabtu/Minggu, else Target RE Weekday
  TGT RE D  (kol)  = base(tgl)                                   # target harian polos (day-aware)
  RE D      (kol)  = RE(tgl)  full day
  GAP       (kol)  = RE D − TGT RE D                             # negatif = di bawah target
  ACH DAILY TGT    = RE D / TGT RE D * 100
  TGT RE D+1 (kol) = base(tgl+1) + (TGT RE D − RE D)  = base(tgl+1) − GAP
  ikon GAP         = ✓ hijau bila ACH ≥ 100 ; ! kuning bila 80 ≤ ACH < 100 ; ✕ merah bila ACH < 80

Baris BRANCH  = penjumlahan nilai per WOK; ACH = ΣRE D / ΣTGT RE D.
Baris REGION  = penjumlahan baris branch;  ACH = ΣRE D / ΣTGT RE D.
"""

from datetime import date, timedelta
from pathlib import Path

import openpyxl

import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

TEMPLATE_XLSX = Path(__file__).resolve().parents[2] / "resources" / "dailyre" / "TEMPLATE REPORT TARGET RE BARU - fixed.xlsx"
SHEET_TARGET  = "REPORT TARGET"

# Kolom di sheet REPORT TARGET (0-indexed):
#   1=BRANCH  2=WOK  5=Target RE Daily Weekday  6=Target RE Daily Weekend
COL_BRANCH = 1
COL_WOK    = 2
COL_RE_WD  = 5
COL_RE_WE  = 6

# Ambang ikon GAP berdasar %ACH
ACH_HIJAU  = 100.0
ACH_KUNING = 80.0


def _is_weekend(d: date) -> bool:
    """Sabtu (5) & Minggu (6) — sama dgn WEEKDAY(x,2)>5 di Excel."""
    return d.weekday() >= 5


def gap_status(ach) -> str:
    """'hijau' / 'kuning' / 'merah' / None (bila ach None)."""
    if ach is None:
        return None
    if ach >= ACH_HIJAU:
        return "hijau"
    if ach >= ACH_KUNING:
        return "kuning"
    return "merah"


def load_target_base(path: Path = TEMPLATE_XLSX) -> dict:
    """Baca base target RE per WOK dari sheet REPORT TARGET.

    Return: {WOK_UPPER: {"branch": str, "wd": float, "we": float}}
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb[SHEET_TARGET]
        woks_valid = {w.upper() for w in WOK_ORDER}
        out = {}
        for row in ws.iter_rows(values_only=True):
            if len(row) <= COL_RE_WE or not row[COL_WOK]:
                continue
            wok = str(row[COL_WOK]).strip().upper()
            if wok not in woks_valid:
                continue
            try:
                wd = float(row[COL_RE_WD])
                we = float(row[COL_RE_WE])
            except (TypeError, ValueError):
                continue
            branch = (str(row[COL_BRANCH]).strip().upper()
                      if row[COL_BRANCH] else WOK_TO_BRANCH.get(wok, "LAINNYA"))
            out[wok] = {"branch": branch, "wd": wd, "we": we}
        if not out:
            raise ValueError(
                f"Tidak ada baris WOK terbaca di sheet '{SHEET_TARGET}' ({path.name})"
            )
        return out
    finally:
        wb.close()


def _re_fullday_by_wok(rows: list, d: date) -> dict:
    """SUM re_trx per WOK untuk activity_date == d (semua jam)."""
    agg = {}
    for r in rows:
        rd = r.get("activity_date")
        if hasattr(rd, "date"):
            rd = rd.date()
        if rd != d:
            continue
        w = str(r.get("wok", "")).strip().upper()
        if not w:
            continue
        try:
            v = int(r.get("re_trx") or 0)
        except (TypeError, ValueError):
            v = 0
        agg[w] = agg.get(w, 0) + v
    return agg


def _agg_rows(rows_in: list, name: str, level: str) -> dict:
    s_wd  = sum(r["base_wd"]   for r in rows_in)
    s_we  = sum(r["base_we"]   for r in rows_in)
    s_td  = sum(r["tgt_d"]     for r in rows_in)
    s_rd  = sum(r["re_d"]      for r in rows_in)
    s_td1 = sum(r["tgt_d1"]    for r in rows_in)
    ach   = (s_rd / s_td * 100) if s_td > 0 else None
    return {
        "level"    : level,
        "name"     : name,
        "branch"   : name if level == "BRANCH" else "",
        "base_wd"  : s_wd,
        "base_we"  : s_we,
        "tgt_d"    : s_td,
        "re_d"     : s_rd,
        "gap"      : s_rd - s_td,
        "ach"      : ach,
        "gap_stat" : gap_status(ach),
        "tgt_d1"   : s_td1,
    }


def hitung_dailyre(tgl: date, template_path: Path = TEMPLATE_XLSX) -> dict:
    """Hitung tabel Monitoring (New) Daily RE untuk tanggal `tgl`."""
    base    = load_target_base(template_path)
    kemarin = tgl - timedelta(days=1)
    besok   = tgl + timedelta(days=1)

    rows = db.query_re_ps(tgl)
    re_d_map = _re_fullday_by_wok(rows, tgl)

    # Cutoff data terakhir di DB (buat ditempel di gambar — template Excel tak punya).
    try:
        _lu = db.query_last_update().get("last_update")
        cutoff = _lu.strftime("%d-%m-%Y %H:%M") if _lu else None
    except Exception:
        cutoff = None

    we_d  = _is_weekend(tgl)
    we_d1 = _is_weekend(besok)

    wok_rows = []
    for wok in WOK_ORDER:
        w = wok.upper()
        b = base.get(w)
        if not b:
            continue
        wd, we = b["wd"], b["we"]

        tgt_d  = we if we_d  else wd
        base_d1 = we if we_d1 else wd
        re_d   = int(re_d_map.get(w, 0))
        gap    = re_d - tgt_d
        ach    = (re_d / tgt_d * 100) if tgt_d > 0 else None
        tgt_d1 = base_d1 - gap                       # = base(besok) + (TGT RE D − RE D)

        wok_rows.append({
            "level"    : "WOK",
            "name"     : wok,
            "branch"   : b["branch"],
            "base_wd"  : wd,
            "base_we"  : we,
            "tgt_d"    : tgt_d,
            "re_d"     : re_d,
            "gap"      : gap,
            "ach"      : ach,
            "gap_stat" : gap_status(ach),
            "tgt_d1"   : tgt_d1,
        })

    branch_rows = []
    for br in BRANCH_ORDER:
        brs = [r for r in wok_rows if r["branch"] == br]
        if brs:
            branch_rows.append(_agg_rows(brs, br, "BRANCH"))

    region_row = _agg_rows(wok_rows, REGION_NAME, "REGION")

    return {
        "tanggal"    : tgl,
        "kemarin"    : kemarin,
        "besok"      : besok,
        "is_weekend" : we_d,
        "cutoff"     : cutoff,
        "region"     : region_row,
        "branches"   : branch_rows,
        "woks"       : wok_rows,
    }
