"""
calculator_c3mr10s.py — Kalkulasi C3MR per Customer Segment

Logic:
  - Query bwmp_c3mr_dd (semua baris bulan, termasuk belum bayar)
  - Query ih_ten_segment_detail → mapping bb_id → customer_segment
  - JOIN di Python: account_num (c3mr) = bb_id (segment)
  - Yang tidak ketemu segment → 'Unmapped'
  - Metrik per segment per WOK:
      Subs, Bill Amount, %C3MR (MtD), MoM, Saldo, Unpaid
  - Segment order sesuai SEGMENT_ORDER (12 segment)
"""

import logging
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

logger = logging.getLogger(__name__)

SEGMENT_ORDER = [
    "Early Tenure Customer",
    "Network Stability Issue",
    "Billing & Service Complainant",
    "Dormant User",
    "Late Payer",
    "Declined Usage",
    "Competitor Explorer",
    "Stable Usage",
    "Increased Usage",
    "Non-Optimal Experience",
    "Non HSI",
    "Unmapped",
]

SEGMENT_LABEL = {s: f"{i+1:02d}. {s}" for i, s in enumerate(SEGMENT_ORDER)}


def _prep_c3mr(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    # Susun kolom-per-kolom lalu buang list mentah. pd.DataFrame(list[dict])
    # untuk ~900rb baris lewat jalur maybe_convert_objects yang makan RAM 2-3x
    # lipat — pernah OOM di mesin 8GB saat 2 bulan data dimuat sekaligus.
    # Ambil hanya kolom yang benar-benar dipakai (account_num & los_category
    # tidak dipakai di calculator ini).
    _cols = ("wok", "branch", "bb_id", "bill_amount", "clearing_amount",
             "paid_flag", "payment_date")
    _data = {c: [r.get(c) for r in rows] for c in _cols}
    rows.clear()
    df = pd.DataFrame(_data)
    del _data
    df["wok"]             = df["wok"].str.strip().str.upper()
    df["branch"]          = df["branch"].str.strip().str.upper()
    df["bb_id"]           = df["bb_id"].astype(str).str.strip()
    df["bill_amount"]     = pd.to_numeric(df["bill_amount"],     errors="coerce").fillna(0)
    df["clearing_amount"] = pd.to_numeric(df["clearing_amount"], errors="coerce").fillna(0)
    df["paid_flag"]       = pd.to_numeric(df["paid_flag"],       errors="coerce").fillna(0).astype(int)
    df["payment_date"]    = pd.to_datetime(df["payment_date"],   errors="coerce")
    return df


def _prep_segment(seg_map) -> dict:
    """
    Normalisasi mapping {bb_id: customer_segment} dari db.query_c3mr_segment().

    db.query_c3mr_segment() sekarang langsung mengembalikan dict (sudah di-strip
    & unik per bb_id) — dulu list[dict] lalu diproses lewat pandas, dan itu
    memakan ±28 detik sendiri untuk 1,3 juta baris. Bentuk list[dict] lama tetap
    diterima supaya pemanggil/tes lama tidak pecah.
    """
    if not seg_map:
        return {}
    if isinstance(seg_map, dict):
        return seg_map
    # Bentuk lama: list of dict
    df = pd.DataFrame(seg_map)
    df["bb_id"] = df["bb_id"].astype(str).str.strip()
    df = df.drop_duplicates(subset="bb_id", keep="first")
    return dict(zip(df["bb_id"], df["customer_segment"].str.strip()))


def _agg_segment_wok(df: pd.DataFrame, seg_map: dict, tgl_mtd: date) -> dict:
    """
    Aggregate per (wok, segment).
    Return: {wok: {segment: {subs, bill, clearing, unpaid}}}
    """
    if df.empty:
        return {}

    df = df.copy()
    df["segment"] = df["bb_id"].map(seg_map).fillna("Unmapped")

    # clearing MtD
    tgl_mtd_ts = pd.Timestamp(tgl_mtd)
    df_clr = df[df["payment_date"].notna() & (df["payment_date"] <= tgl_mtd_ts)]

    result = {}
    for wok, grp in df.groupby("wok"):
        grp_clr = df_clr[df_clr["wok"] == wok]
        result[wok] = {}

        for seg in SEGMENT_ORDER:
            sg     = grp[grp["segment"] == seg]
            sg_clr = grp_clr[grp_clr["segment"] == seg]
            result[wok][seg] = {
                "subs"     : len(sg),
                "bill"     : sg["bill_amount"].sum(),
                "clearing" : sg_clr["clearing_amount"].sum(),
                "unpaid"   : int((sg["paid_flag"] == 0).sum()),
            }
    return result


def _pct(clearing, bill):
    if bill and bill > 0:
        return round(clearing / bill * 100, 2)
    return None


def _mom(a, b):
    if a is not None and b is not None:
        return round(a - b, 2)
    return None


def _cek_mutu_segment(seg_map: dict, bp_date: date, wajib: bool = True):
    """
    Pastikan isi kolom customer_segment memang nama segmen, bukan sampah.

    Pernah kejadian tabel segment ke-load dengan nilai '0'/'1'/'' (bukan nama
    segmen). Semua bb_id lalu jatuh ke "Unmapped" dan laporan tampil NOL SEMUA
    tanpa error — kelihatan seperti "tidak ada data", padahal datanya ada tapi
    kolomnya rusak. Lebih baik gagal dengan pesan jelas daripada mengirim
    laporan kosong yang menyesatkan.

    NB: nama tabel di pesan mengikuti aturan CVM M-1 (lihat db.query_c3mr_segment).
    """
    bulan_cvm = bp_date - relativedelta(months=1)
    tabel = f"ih_cb_cvm_prfl_mm_{bulan_cvm.strftime('%Y%m')}"

    if not seg_map:
        pesan = f"Tabel {tabel} kosong / tidak bisa dibaca — mapping segment tidak tersedia."
        if wajib:
            raise ValueError(pesan)
        logger.warning(f"[c3mr10s] {pesan}")
        return

    dikenal = {s for s in SEGMENT_ORDER if s != "Unmapped"}
    n_cocok = sum(1 for v in seg_map.values() if v in dikenal)
    rasio   = n_cocok / len(seg_map)

    if rasio == 0:
        contoh = sorted({str(v) for v in list(seg_map.values())[:2000]})[:5]
        pesan = (
            f"Kolom customer_segment di {tabel} TIDAK berisi nama segmen "
            f"(contoh isinya: {contoh}). Semua pelanggan jadi tidak terpetakan, "
            f"sehingga laporan akan nol semua.\n"
            f"Kemungkinan tabel salah ter-load. Perlu diperbaiki di sisi data."
        )
        if wajib:
            raise ValueError(pesan)
        logger.warning(f"[c3mr10s] {pesan}")
    elif rasio < 0.5:
        logger.warning(
            f"[c3mr10s] Hanya {rasio*100:.1f}% bb_id di {tabel} terpetakan ke segmen "
            f"— angka laporan kemungkinan tidak lengkap."
        )


def hitung_c3mr10s(tgl_closing: date) -> dict:
    # Kelonggaran 5 hari tiap ganti bulan — SAMA persis dgn calculator_c3mr.py
    # & calculator_c3mrnew.py (report bwmp_c3mr_dd bulan berjalan baru lengkap
    # terisi beberapa hari setelah tanggal 1). Tgl 1-5 masih pakai bill period
    # BULAN LALU; tgl 6 ke atas baru pindah ke bill period bulan berjalan.
    # SEBELUM fix ini (04-Aug-2026) c3mr10s TIDAK punya kelonggaran ini —
    # langsung ganti tabel tiap tanggal 1, beda dari 2 report c3mr lainnya.
    if tgl_closing.day <= 5:
        bp_ini = (tgl_closing - relativedelta(months=1)).replace(day=1)
    else:
        bp_ini = tgl_closing.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)

    # MoM: tanggal yang sama persis di bulan bp_lalu
    # Misal tgl_closing=1 Juli, bp_ini=Juni → tgl_mtd_lalu=1 Juni (bukan 1 Mei)
    tgl_mtd_lalu = tgl_closing - relativedelta(months=1)

    # ── Query ─────────────────────────────────────────────────────────────
    df_ini  = _prep_c3mr(db.query_c3mr(bp_ini))
    df_lalu = _prep_c3mr(db.query_c3mr(bp_lalu))

    seg_ini  = _prep_segment(db.query_c3mr_segment(bp_ini))
    seg_lalu = _prep_segment(db.query_c3mr_segment(bp_lalu))
    _cek_mutu_segment(seg_ini, bp_ini)
    _cek_mutu_segment(seg_lalu, bp_lalu, wajib=False)

    # ── Aggregate ─────────────────────────────────────────────────────────
    agg_ini  = _agg_segment_wok(df_ini,  seg_ini,  tgl_closing)
    agg_lalu = _agg_segment_wok(df_lalu, seg_lalu, tgl_mtd_lalu)

    semua_wok = set(list(agg_ini.keys()) + list(agg_lalu.keys()))

    def _ini(wok, seg, key):  return agg_ini.get(wok,  {}).get(seg, {}).get(key, 0)
    def _lalu(wok, seg, key): return agg_lalu.get(wok, {}).get(seg, {}).get(key, 0)

    def _make_seg_metrics(wok_or_woks, is_list=False):
        """Buat dict metrik per segment untuk satu WOK atau list WOK."""
        segs = {}
        for seg in SEGMENT_ORDER:
            if is_list:
                bill_i  = sum(_ini(w,  seg, "bill")      for w in wok_or_woks)
                clr_i   = sum(_ini(w,  seg, "clearing")  for w in wok_or_woks)
                bill_l  = sum(_lalu(w, seg, "bill")      for w in wok_or_woks)
                clr_l   = sum(_lalu(w, seg, "clearing")  for w in wok_or_woks)
                subs_i  = sum(_ini(w,  seg, "subs")      for w in wok_or_woks)
                unpaid_i= sum(_ini(w,  seg, "unpaid")    for w in wok_or_woks)
            else:
                w       = wok_or_woks
                bill_i  = _ini(w,  seg, "bill")
                clr_i   = _ini(w,  seg, "clearing")
                bill_l  = _lalu(w, seg, "bill")
                clr_l   = _lalu(w, seg, "clearing")
                subs_i  = _ini(w,  seg, "subs")
                unpaid_i= _ini(w,  seg, "unpaid")

            pct_i = _pct(clr_i, bill_i)
            pct_l = _pct(clr_l, bill_l)
            segs[seg] = {
                "subs"   : subs_i,
                "bill"   : bill_i,
                "pct"    : pct_i,
                "mom"    : _mom(pct_i, pct_l),
                "saldo"  : bill_i - clr_i,
                "unpaid" : unpaid_i,
            }
        return segs

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        branch = WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok), "LAINNYA"
        )
        wok_rows.append({
            "level"   : "WOK",
            "name"    : wok,
            "branch"  : branch,
            "segments": _make_seg_metrics(wok),
        })

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
        branch_rows.append({
            "level"   : "BRANCH",
            "name"    : branch,
            "segments": _make_seg_metrics(bwoks, is_list=True),
        })

    # ── REGION row ────────────────────────────────────────────────────────
    region_row = {
        "level"   : "REGION",
        "name"    : REGION_NAME,
        "segments": _make_seg_metrics(list(semua_wok), is_list=True),
    }

    return {
        "tgl_closing"    : tgl_closing,
        "bl_label"       : bp_lalu.strftime("%b %Y").upper(),
        "bi_label"       : bp_ini.strftime("%b %Y").upper(),
        "bp_ini"         : bp_ini,
        "is_closing_mode": tgl_closing.day <= 5,
        "region"         : region_row,
        "branches"       : branch_rows,
        "woks"           : wok_rows,
        "segment_order"  : SEGMENT_ORDER,
        "segment_label"  : SEGMENT_LABEL,
    }
