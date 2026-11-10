"""
Kalkulator report /agresif native (tanpa Excel): LOKASI AGRESIF (PS),
RE KECAMATAN AGRESIF (RE), ALL FMC CITY (FMC). Formula direplikasi persis dari
audit langsung ke master Excel (lihat memory agresif-fullauto-geocoding /
plan proud-squishing-flurry.md):

  MTD        = COUNT baris kab2/kec2 cocok, bulan_x == bulan cutoff, tgl_x <= hari cutoff
  MTD-1      = sama tapi bulan SEBELUMNYA, tgl cutoff SAMA (bukan 1 bulan penuh)
  MoM        = (MTD - MTD-1) / MTD-1  (guard: 0 kalau MTD-1 0/kosong)
  ACH        = MTD / TARGET           (guard: None kalau TARGET 0/kosong)
  CONTR (report PS/FMC, PS-lens) = pembagian PS baris ITU SENDIRI antara Low
    vs Mid High, BUKAN share thd total region. Cth: PS Low=3, Mid High=2,
    total=5 -> Cont Low=60%, Cont High=40% (lihat _derive_ps_metrics).
  CONTR (report RE) = MTD_grup / MTD_total_semua_grup periode itu (guard: 0)
    — definisi lama, TIDAK diubah (scope perubahan cuma "PS kontribusi").
  GAP CONTR  = (CONTR_MTD - CONTR_MTD-1) * 100   (ppt)
  Baris agregat (branch subtotal, JATENG-DIY) = SUM raw count dari baris anggota,
  lalu %-metric (ACH/MoM/CONTR) dihitung ULANG dari angka yang sudah dijumlahkan
  — BUKAN rata-rata dari %-metric per baris.
  TOP ACH   = ranking MAX ACH%. TOP MoM = ranking MAX MoM%. Worst MoM = ranking MIN MoM%.
  Nominasi TOP ACH/TOP MoM (caption) report PS SENGAJA tidak menyertakan 4
  "Agresif city" (BATANG/KOTA TEGAL/CILACAP/REMBANG, tanpa kecamatan) — baris
  itu tetap tampil di tabel, cuma dikecualikan dari nominasi.

Catatan:
  - [FIXED 04-Aug-2026] 4 baris "Agresif city" (BATANG/KOTA TEGAL/CILACAP/
    REMBANG, report PS) sekarang dapat TARGET dari sheet TARGET_KEC AGRESIF
    yang sama (baris city-only, kolom KEC dikosongkan di Excel). Root cause
    lama: sel KEC kosong dibaca pandas sbg NaN, str(nan).upper()=="NAN"
    (bukan string kosong) -> key lookup (CITY,"NAN") tak pernah cocok dgn
    (CITY,"") yang dipakai baris Agresif city -> target selalu kosong. Fix
    di _target_kec_lookup(): KEC NaN dinormalkan ke "" sebelum dipakai key.
  - Kolom "SF AKTIF RE MTD" DIHAPUS (04-Aug-2026, permintaan user) — sempat
    ada sbg aproksimasi (COUNT DISTINCT sf_code) tapi tak pernah tervalidasi
    ke master, dan user minta dihilangkan dari report.
"""
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

from agresif_refdata import KEC_47, AGRESIF_CITY_4, FMC_NEW_13, FMC_OLD_12, BRANCH_ORDER_AGRESIF

# Daftar nama produk persis untuk kolom helper "JML RE MTD"/"JML PS MTD" —
# BEDA per report (dikonfirmasi 04-Aug-2026 lewat query DISTINCT
# product_commercial_name ke DB indihome_ordering_detail_202606/07/08).
#
# Report 1 (Lokasi Agresif) label kolom "EZnet Promo 20 Mbps" -> 3 varian
# (polos + "BAYAR SEKALIGUS -" + "BAYAR DI DEPAN -") — user konfirmasi
# (06-Aug-2026) ketiganya MEMANG harus ikut dihitung.
#
# CATATAN BELUM SELESAI (06-Aug-2026): dgn 3 varian ini, hasil JATENG-DIY
# cutoff 05-Aug-2026 = RE 383 / PS 316 — TIDAK cocok ke laporan manual
# master yg user kasih (RE 332 / PS 275). Kalau HANYA pakai varian polos
# "EZNET PROMO 20 MBPS", hasilnya cocok PERSIS 332/275. User tetap minta
# 3 varian dihitung, jadi dipakai apa adanya di sini — TAPI gap ke laporan
# manual itu MASIH BELUM ketemu sumbernya (bukan soal nama produk, berarti
# ada penyebab lain: kemungkinan laporan manual itu sendiri generated
# dgn logika lama/beda, atau ada filter lain yg belum ketemu). Jangan
# anggap sudah tervalidasi ke master sampai gap ini dijelaskan.
EZNET_PROMO_NAMES = {
    "EZNET PROMO 20 MBPS",
    "BAYAR SEKALIGUS - EZNET PROMO 20 MBPS",
    "BAYAR DI DEPAN - EZNET PROMO 20 MBPS",
}

# Report 3 (FMC) label kolom "One Dynamic Promo 20Mbps 30GB" -> HANYA SATU
# produk itu spesifik. Di DB ada 3 produk "One Dynamic Promo" berbeda:
# "...20Mbps 15GB", "...20Mbps 30GB", "...20Mbps+15GB" — label report
# eksplisit sebut "30GB" doang, jadi 2 varian 15GB SENGAJA dikecualikan
# (produk beda, bukan typo/salah ketik). Juga TIDAK termasuk varian "One
# Dynamic 20Mbps+30GB" non-promo (volume jauh lebih besar, produk beda).
ONE_DYNAMIC_PROMO_30GB_NAMES = {
    "ONE DYNAMIC PROMO 20MBPS 30GB",
}


# ── Helper hitung dasar (setara COUNTIFS) ───────────────────────────────────────

def _count(df: pd.DataFrame, bulan_col: str, tgl_col: str, bulan: str, day_max: int,
           kab2: str = None, kec2: str = None, midlow: str = None) -> int:
    m = (df[bulan_col] == bulan) & df[tgl_col].notna() & (df[tgl_col] <= day_max)
    if "order_id" in df.columns:
        m &= df["order_id"].astype(str).str.upper().str.startswith("AO")
    if kab2 is not None:
        m &= (df["kab2"] == kab2)
    if kec2 is not None:
        m &= (df["kec2"] == kec2)
    if midlow is not None:
        m &= (df["MIDLOW"] == midlow)
    return int(m.sum())


def _mom(cur, prev):
    """MoM growth. Guard: 0 kalau prev 0/None (setara IFERROR(...,0) Excel)."""
    if prev:
        return (cur - prev) / prev
    return 0.0


def _ach(cur, target):
    """Achievement. Guard: None kalau target 0/None (tak dianggap 0%, tapi 'n/a')."""
    if target:
        return cur / target
    return None


def _contr(cur, total):
    if total:
        return cur / total
    return 0.0


def _gap_ppt(contr_now, contr_prev):
    return (contr_now - contr_prev) * 100


def periods(cutoff: date):
    bulan_now = cutoff.replace(day=1)
    bulan_prev = bulan_now - relativedelta(months=1)
    return bulan_now.strftime("%Y-%m"), bulan_prev.strftime("%Y-%m"), cutoff.day


# ── Target lookup ────────────────────────────────────────────────────────────

def _target_kec_lookup(target_df: pd.DataFrame, bulan_now: str) -> dict:
    """target_df: sheet TARGET_KEC AGRESIF (BULAN,CITY,KEC,...,TARGET_PS_LOW,
    TARGET_PS_MIDHIGH[,TARGET_RE_LOW,TARGET_RE_MIDHIGH]). Return
    {(CITY,KEC): {"ps_low":.., "ps_mid":.., "re_low":.., "re_mid":..}}."""
    if target_df is None or target_df.empty:
        return {}
    sub = target_df[target_df["BULAN"].astype(str).str.strip() == bulan_now]
    out = {}
    for _, r in sub.iterrows():
        # Baris "Agresif city" (4 city TANPA kecamatan, mis. BATANG/KOTA
        # TEGAL/CILACAP/REMBANG) di sheet TARGET_KEC AGRESIF punya sel KEC
        # KOSONG -> pandas baca sbg NaN (float). str(nan).upper() == "NAN"
        # (bukan string kosong!), jadi kalau dipakai apa adanya key-nya JADI
        # (CITY,"NAN") -- TIDAK PERNAH match key_fn di hitung_agresif_ps yang
        # pakai (CITY,"") utk city tanpa kecamatan -> target selalu kosong
        # ("-" di report) walau baris targetnya sudah ada di file. Fix: KEC
        # kosong/NaN dinormalkan ke "" (bukan "NAN").
        kec_val = r["KEC"]
        kec_norm = str(kec_val).strip().upper() if pd.notna(kec_val) else ""
        key = (str(r["CITY"]).strip().upper(), kec_norm)
        out[key] = {
            "ps_low": float(r.get("TARGET_PS_LOW", 0) or 0),
            "ps_mid": float(r.get("TARGET_PS_MIDHIGH", 0) or 0),
            "re_low": float(r["TARGET_RE_LOW"]) if "TARGET_RE_LOW" in r and pd.notna(r["TARGET_RE_LOW"]) else None,
            "re_mid": float(r["TARGET_RE_MIDHIGH"]) if "TARGET_RE_MIDHIGH" in r and pd.notna(r["TARGET_RE_MIDHIGH"]) else None,
        }
    return out


def _target_fmc_lookup(target_df: pd.DataFrame, bulan_now: str) -> dict:
    """target_df: sheet TARGET_CITY FMC. Return {CITY: {"ps_low":.., "ps_mid":..}}."""
    if target_df is None or target_df.empty:
        return {}
    sub = target_df[target_df["BULAN"].astype(str).str.strip() == bulan_now]
    out = {}
    for _, r in sub.iterrows():
        key = str(r["CITY"]).strip().upper()
        out[key] = {
            "ps_low": float(r.get("TARGET_PS_LOW", 0) or 0),
            "ps_mid": float(r.get("TARGET_PS_MIDHIGH", 0) or 0),
        }
    return out


def _count_promo(df: pd.DataFrame, bulan_col: str, tgl_col: str, bulan: str, day_max: int,
                 kab2: str = None, kec2: str = None, promo_names: set = None) -> int:
    m = (df[bulan_col] == bulan) & df[tgl_col].notna() & (df[tgl_col] <= day_max)
    if "order_id" in df.columns:
        m &= df["order_id"].astype(str).str.upper().str.startswith("AO")
    if kab2 is not None:
        m &= (df["kab2"] == kab2)
    if kec2 is not None:
        m &= (df["kec2"] == kec2)
    if "product_commercial_name" in df.columns:
        p_str = df["product_commercial_name"].astype(str).str.strip().str.upper()
        m &= p_str.isin(promo_names)
    return int(m.sum())


def _ps_row(df, kab2, kec2, bulan_now, bulan_prev, day_max, target_low, target_mid, promo_names):
    """Satu baris metrik PS (dipakai report PS & FMC, keduanya PS-lens).
    kec2=None -> hitung level city saja (dipakai FMC & 4 Agresif-city).
    promo_names: set nama produk EXACT (upper) utk kolom helper JML RE/PS MTD
    — BEDA per report, lihat EZNET_PROMO_NAMES / ONE_DYNAMIC_PROMO_30GB_NAMES."""
    re_mtd = _count_promo(df, "bulan_re", "tgl_re", bulan_now, day_max, kab2, kec2, promo_names=promo_names)
    ps_mtd_helper = _count_promo(df, "bulan_ps", "tgl_ps", bulan_now, day_max, kab2, kec2, promo_names=promo_names)

    re_mtd_low = _count(df, "bulan_re", "tgl_re", bulan_now, day_max, kab2, kec2, "low")
    ps_mtd1_low = _count(df, "bulan_ps", "tgl_ps", bulan_prev, day_max, kab2, kec2, "low")
    ps_mtd_low = _count(df, "bulan_ps", "tgl_ps", bulan_now, day_max, kab2, kec2, "low")

    re_mtd_mid = _count(df, "bulan_re", "tgl_re", bulan_now, day_max, kab2, kec2, "MID HIGH")
    ps_mtd1_mid = _count(df, "bulan_ps", "tgl_ps", bulan_prev, day_max, kab2, kec2, "MID HIGH")
    ps_mtd_mid = _count(df, "bulan_ps", "tgl_ps", bulan_now, day_max, kab2, kec2, "MID HIGH")

    ps_mtd1_total = _count(df, "bulan_ps", "tgl_ps", bulan_prev, day_max, kab2, kec2)
    ps_mtd_total = _count(df, "bulan_ps", "tgl_ps", bulan_now, day_max, kab2, kec2)

    return {
        "re_mtd_helper": re_mtd, "ps_mtd_helper": ps_mtd_helper,
        "target_low": target_low, "target_mid": target_mid,
        "re_mtd_low": re_mtd_low,
        "ps_mtd1_low": ps_mtd1_low, "ps_mtd_low": ps_mtd_low,
        "re_mtd_mid": re_mtd_mid,
        "ps_mtd1_mid": ps_mtd1_mid, "ps_mtd_mid": ps_mtd_mid,
        "ps_mtd1_total": ps_mtd1_total, "ps_mtd_total": ps_mtd_total,
        "re_mtd_total": re_mtd_low + re_mtd_mid,
    }


def _derive_ps_metrics(row):
    """Dari row mentah (counts), hitung semua %-metric.

    CONTR (Low/High) = pembagian PS baris ITU SENDIRI antara paket Low vs
    Mid High, BUKAN kontribusi baris tsb thd total region (beda dari definisi
    lama). Contoh: PS MTD Low=3, Mid High=2, total=5 -> Cont Low=3/5=60%,
    Cont High=2/5=40%. CONTR MTD-1 = pembagian yg sama tapi bulan lalu (basis
    GAP CONTR = pergeseran komposisi produk row itu, bukan pergeseran share
    thd region)."""
    low_mom = _mom(row["ps_mtd_low"], row["ps_mtd1_low"])
    low_ach = _ach(row["ps_mtd_low"], row["target_low"])
    low_contr_mtd1 = _contr(row["ps_mtd1_low"], row["ps_mtd1_total"])
    low_contr_mtd = _contr(row["ps_mtd_low"], row["ps_mtd_total"])

    mid_mom = _mom(row["ps_mtd_mid"], row["ps_mtd1_mid"])
    mid_ach = _ach(row["ps_mtd_mid"], row["target_mid"])
    mid_contr_mtd1 = _contr(row["ps_mtd1_mid"], row["ps_mtd1_total"])
    mid_contr_mtd = _contr(row["ps_mtd_mid"], row["ps_mtd_total"])

    target_total = (row["target_low"] or 0) + (row["target_mid"] or 0)
    total_mom = _mom(row["ps_mtd_total"], row["ps_mtd1_total"])
    total_ach = _ach(row["ps_mtd_total"], target_total if target_total else None)

    return {
        **row,
        "low_re_to_ps": (row["ps_mtd_low"] / row["re_mtd_low"]) if row["re_mtd_low"] else None,
        "low_mom": low_mom, "low_ach": low_ach,
        "low_contr_mtd1": low_contr_mtd1, "low_contr_mtd": low_contr_mtd,
        "low_gap_contr": _gap_ppt(low_contr_mtd, low_contr_mtd1),
        "mid_re_to_ps": (row["ps_mtd_mid"] / row["re_mtd_mid"]) if row["re_mtd_mid"] else None,
        "mid_mom": mid_mom, "mid_ach": mid_ach,
        "mid_contr_mtd1": mid_contr_mtd1, "mid_contr_mtd": mid_contr_mtd,
        "mid_gap_contr": _gap_ppt(mid_contr_mtd, mid_contr_mtd1),
        "target_total": target_total,
        "total_re_to_ps": (row["ps_mtd_total"] / row["re_mtd_total"]) if row["re_mtd_total"] else None,
        "total_mom": total_mom, "total_ach": total_ach,
    }


def _sum_group(rows: list[dict], keys: list[str]) -> dict:
    """Jumlahkan field numerik antar baris. None (mis. target tak ketemu di
    file target) diperlakukan sbg 0 saat dijumlah -> agregat branch/JATENG-DIY
    tetap terhitung dari target anggota yg ADA, bukan ikut jadi None semua."""
    return {k: sum((r[k] or 0) for r in rows) for k in keys}


_PS_RAW_KEYS = ["re_mtd_helper", "ps_mtd_helper", "target_low", "target_mid",
                "re_mtd_low", "ps_mtd1_low", "ps_mtd_low",
                "re_mtd_mid", "ps_mtd1_mid", "ps_mtd_mid",
                "ps_mtd1_total", "ps_mtd_total", "re_mtd_total"]


def _build_ps_like_table(df, entries, target_lookup_fn, cutoff, key_fn, promo_names):
    """entries: list of {"branch","city","kec"(optional)}. key_fn(entry)->target key.
    Return (rows_with_metrics, branch_subtotal_rows, jateng_row)."""
    bulan_now, bulan_prev, day_max = periods(cutoff)

    raw_rows = []
    for e in entries:
        kab2 = e["city"].strip().upper()
        kec2 = e.get("kec", "").strip().upper() if e.get("kec") else None
        tgt = target_lookup_fn(key_fn(e))
        raw = _ps_row(df, kab2, kec2, bulan_now, bulan_prev, day_max,
                      tgt["ps_low"] if tgt else None, tgt["ps_mid"] if tgt else None,
                      promo_names)
        raw_rows.append({"branch": e["branch"], "city": e["city"], "kec": e.get("kec"), **raw})

    rows = [_derive_ps_metrics(r) for r in raw_rows]

    branch_rows = []
    for b in BRANCH_ORDER_AGRESIF:
        members = [r for r in raw_rows if r["branch"] == b]
        if not members:
            continue
        summed = _sum_group(members, _PS_RAW_KEYS)
        branch_rows.append(_derive_ps_metrics({**summed, "branch": b, "city": None, "kec": None}))

    summed_all = _sum_group(raw_rows, _PS_RAW_KEYS)
    jateng_row = _derive_ps_metrics({**summed_all, "branch": "JATENG-DIY", "city": None, "kec": None})

    return rows, branch_rows, jateng_row


def _top_bottom_caption(rows, branch_rows, key_field, label_fn, ach_field="total_ach",
                         mom_field="total_mom", include_worst=False):
    """Bangun bagian TOP ACH / TOP MoM / (Worst MoM) dari rows kec/city + branch_rows."""
    def best(items, field, want_max=True):
        valid = [r for r in items if r.get(field) is not None]
        if not valid:
            return None
        return (max if want_max else min)(valid, key=lambda r: r[field])

    top_ach_branch = best(branch_rows, ach_field, True)
    top_ach_item = best(rows, ach_field, True)
    top_mom_branch = best(branch_rows, mom_field, True)
    top_mom_item = best(rows, mom_field, True)

    out = {
        "top_ach_branch": top_ach_branch, "top_ach_item": top_ach_item,
        "top_mom_branch": top_mom_branch, "top_mom_item": top_mom_item,
    }
    if include_worst:
        out["worst_mom_branch"] = best(branch_rows, mom_field, False)
        out["worst_mom_item"] = best(rows, mom_field, False)
    return out


# ── Report 1: LOKASI AGRESIF (PS) ───────────────────────────────────────────

def hitung_agresif_ps(cutoff: date, df_raw: pd.DataFrame, target_kec_df: pd.DataFrame) -> dict:
    bulan_now, _, _ = periods(cutoff)
    tlook = _target_kec_lookup(target_kec_df, bulan_now)

    def key_fn(e):
        return (e["city"].strip().upper(), e.get("kec", "").strip().upper() if e.get("kec") else "")

    entries = KEC_47 + AGRESIF_CITY_4  # AGRESIF_CITY_4 tanpa "kec" -> key (CITY,"")
    kec_rows, branch_rows, jateng_row = _build_ps_like_table(
        df_raw, entries, lambda k: tlook.get(k), cutoff, key_fn, EZNET_PROMO_NAMES)
    for r in kec_rows:
        r["fokus"] = "New Agresive Kec" if r.get("kec") else "Agresif city"

    # 4 "Agresif city" (BATANG/KOTA TEGAL/CILACAP/REMBANG, tanpa kecamatan)
    # TETAP tampil di tabel (kec_rows/rows), tapi SENGAJA dikecualikan dari
    # nominasi caption TOP ACH/TOP MoM — cuma kecamatan asli yang boleh
    # dinominasikan.
    kec_rows_nominasi = [r for r in kec_rows if r.get("kec")]
    caption = _top_bottom_caption(kec_rows_nominasi, branch_rows, None, None, include_worst=False)
    return {"cutoff": cutoff, "rows": kec_rows, "branch_rows": branch_rows,
            "jateng_row": jateng_row, "caption_data": caption,
            "n_kec": len(KEC_47), "n_agresif_city": len(AGRESIF_CITY_4)}


# ── Report 2: RE KECAMATAN AGRESIF ──────────────────────────────────────────

def _re_row(df, kab2, kec2, bulan_now, bulan_prev, day_max, target_low, target_mid):
    mtd1_low = _count(df, "bulan_re", "tgl_re", bulan_prev, day_max, kab2, kec2, "low")
    mtd_low = _count(df, "bulan_re", "tgl_re", bulan_now, day_max, kab2, kec2, "low")
    mtd1_mid = _count(df, "bulan_re", "tgl_re", bulan_prev, day_max, kab2, kec2, "MID HIGH")
    mtd_mid = _count(df, "bulan_re", "tgl_re", bulan_now, day_max, kab2, kec2, "MID HIGH")
    mtd1_total = _count(df, "bulan_re", "tgl_re", bulan_prev, day_max, kab2, kec2)
    mtd_total = _count(df, "bulan_re", "tgl_re", bulan_now, day_max, kab2, kec2)
    return {"target_low": target_low, "target_mid": target_mid,
            "mtd1_low": mtd1_low, "mtd_low": mtd_low,
            "mtd1_mid": mtd1_mid, "mtd_mid": mtd_mid,
            "mtd1_total": mtd1_total, "mtd_total": mtd_total}


_RE_RAW_KEYS = ["target_low", "target_mid", "mtd1_low", "mtd_low",
                "mtd1_mid", "mtd_mid", "mtd1_total", "mtd_total"]


def _derive_re_metrics(row, tot_low_mtd1, tot_low_mtd, tot_mid_mtd1, tot_mid_mtd):
    low_mom = _mom(row["mtd_low"], row["mtd1_low"])
    low_ach = _ach(row["mtd_low"], row["target_low"])
    low_contr_mtd1 = _contr(row["mtd1_low"], tot_low_mtd1)
    low_contr_mtd = _contr(row["mtd_low"], tot_low_mtd)

    mid_mom = _mom(row["mtd_mid"], row["mtd1_mid"])
    mid_ach = _ach(row["mtd_mid"], row["target_mid"])
    mid_contr_mtd1 = _contr(row["mtd1_mid"], tot_mid_mtd1)
    mid_contr_mtd = _contr(row["mtd_mid"], tot_mid_mtd)

    target_total = (row["target_low"] or 0) + (row["target_mid"] or 0)
    total_mom = _mom(row["mtd_total"], row["mtd1_total"])
    total_ach = _ach(row["mtd_total"], target_total if target_total else None)

    return {
        **row,
        "low_mom": low_mom, "low_ach": low_ach,
        "low_contr_mtd1": low_contr_mtd1, "low_contr_mtd": low_contr_mtd,
        "low_gap_contr": _gap_ppt(low_contr_mtd, low_contr_mtd1),
        "mid_mom": mid_mom, "mid_ach": mid_ach,
        "mid_contr_mtd1": mid_contr_mtd1, "mid_contr_mtd": mid_contr_mtd,
        "mid_gap_contr": _gap_ppt(mid_contr_mtd, mid_contr_mtd1),
        "target_total": target_total, "total_mom": total_mom, "total_ach": total_ach,
    }


def hitung_agresif_re(cutoff: date, df_raw: pd.DataFrame, target_kec_df: pd.DataFrame) -> dict:
    """RE report: 47 kec SAJA (TANPA 4 Agresif-city -> parity dgn perilaku existing,
    yg menyembunyikan 4 baris itu di RE krn tak ada target RE utk city-only)."""
    bulan_now, bulan_prev, day_max = periods(cutoff)
    tlook = _target_kec_lookup(target_kec_df, bulan_now)

    raw_rows = []
    for e in KEC_47:
        key = (e["city"].strip().upper(), e["kec"].strip().upper())
        tgt = tlook.get(key)
        target_low = tgt["re_low"] if tgt else None
        target_mid = tgt["re_mid"] if tgt else None
        raw = _re_row(df_raw, e["city"].strip().upper(), e["kec"].strip().upper(),
                      bulan_now, bulan_prev, day_max, target_low, target_mid)
        raw_rows.append({"branch": e["branch"], "city": e["city"], "kec": e["kec"], **raw})

    tot_low_mtd1 = sum(r["mtd1_low"] for r in raw_rows)
    tot_low_mtd = sum(r["mtd_low"] for r in raw_rows)
    tot_mid_mtd1 = sum(r["mtd1_mid"] for r in raw_rows)
    tot_mid_mtd = sum(r["mtd_mid"] for r in raw_rows)

    kec_rows = [_derive_re_metrics(r, tot_low_mtd1, tot_low_mtd, tot_mid_mtd1, tot_mid_mtd)
                for r in raw_rows]
    for r in kec_rows:
        r["fokus"] = "New Agresive Kec"

    branch_rows = []
    for b in BRANCH_ORDER_AGRESIF:
        members = [r for r in raw_rows if r["branch"] == b]
        if not members:
            continue
        summed = _sum_group(members, _RE_RAW_KEYS)
        branch_rows.append(_derive_re_metrics(
            {**summed, "branch": b, "city": None, "kec": None},
            tot_low_mtd1, tot_low_mtd, tot_mid_mtd1, tot_mid_mtd))

    summed_all = _sum_group(raw_rows, _RE_RAW_KEYS)
    jateng_row = _derive_re_metrics(
        {**summed_all, "branch": "JATENG-DIY", "city": None, "kec": None},
        tot_low_mtd1, tot_low_mtd, tot_mid_mtd1, tot_mid_mtd)

    caption = _top_bottom_caption(kec_rows, branch_rows, None, None, include_worst=True)
    return {"cutoff": cutoff, "rows": kec_rows, "branch_rows": branch_rows,
            "jateng_row": jateng_row, "caption_data": caption, "n_kec": len(KEC_47)}


# ── Report 3: ALL FMC CITY ───────────────────────────────────────────────────

def hitung_agresif_fmc(cutoff: date, df_raw: pd.DataFrame, target_fmc_df: pd.DataFrame) -> dict:
    """FMC report: city-level saja (kec2=None), PS-lens sama seperti report 1.
    2 seksi: NEW FMC (14 city) + OLD FMC (12 city), masing2 dgn urutan tampil
    sendiri, tapi branch-subtotal & JATENG-DIY dihitung dari GABUNGAN keduanya.

    BEDA dari report PS & RE: report ini SENGAJA TIDAK pakai hasil geocoding
    (kolom kab2). City di-match langsung dari kolom `kabupaten` mentah DB
    (Hadoop), cukup di-uppercase supaya sebanding dgn nama city di
    FMC_NEW_13/FMC_OLD_12. Report PS & RE tetap pakai kab2/kec2 hasil
    geocoding dari df_raw yang sama — tidak terpengaruh (df_raw asli tidak
    diubah, di sini cuma dibuat view kecil dgn kolom kab2 ditimpa)."""
    bulan_now, _, _ = periods(cutoff)
    tlook = _target_fmc_lookup(target_fmc_df, bulan_now)

    # View ramping (cuma kolom yang dibaca _count/_count_promo) supaya copy
    # tidak menggandakan seluruh 94 kolom raw — kab2 ditimpa dgn kabupaten
    # mentah DB, dinormalkan ke UPPER (kab2 hasil geocoding sudah UPPER, jadi
    # _build_ps_like_table yang meng-UPPER-kan nama entry tetap sebanding).
    _cols = ["order_id", "bulan_re", "tgl_re", "bulan_ps", "tgl_ps",
             "MIDLOW", "kec2", "product_commercial_name"]
    df_fmc = df_raw[[c for c in _cols if c in df_raw.columns]].copy()
    df_fmc["kab2"] = (df_raw["kabupaten"].astype(str).str.strip().str.upper()
                      .replace({"NAN": "", "NONE": ""}))

    def key_fn(e):
        return e["city"].strip().upper()

    entries = FMC_NEW_13 + FMC_OLD_12
    all_rows, branch_rows, jateng_row = _build_ps_like_table(
        df_fmc, entries, lambda k: tlook.get(k), cutoff, key_fn, ONE_DYNAMIC_PROMO_30GB_NAMES)

    n_new = len(FMC_NEW_13)
    new_rows, old_rows = all_rows[:n_new], all_rows[n_new:]
    for r in new_rows:
        r["fokus"] = "NEW FMC CITY"
    for r in old_rows:
        r["fokus"] = "OLD FMC CITY"

    caption = _top_bottom_caption(all_rows, branch_rows, None, None, include_worst=True)
    return {"cutoff": cutoff, "new_rows": new_rows, "old_rows": old_rows,
            "branch_rows": branch_rows, "jateng_row": jateng_row,
            "caption_data": caption, "n_new": n_new, "n_old": len(FMC_OLD_12)}
