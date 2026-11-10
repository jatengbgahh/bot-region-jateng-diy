"""
agresif_native.py — Orkestrasi report /agresif NATIVE (tanpa Excel/COM).

Menjembatani output agresif_data.build_raw() (94 kolom, kab2/kec2 sudah
digeocode, tapi MIDLOW & bulan_re/bulan_ps dikosongkan — dulu diisi formula
Excel oleh agresif_report.py) jadi format yang dibutuhkan calculator_agresif.py
(prepare_calc_df), lalu memformat hasil hitung_agresif_ps/re/fmc jadi:
  - DataFrame tabel lengkap (utk sheet Excel "raw" yang dikirim ke grup)
  - Teks caption Telegram (3 laporan)
  - File .xlsx multi-sheet (write_agresif_workbook)

Render PNG SENGAJA TIDAK di sini — dipanggil terpisah oleh bot.py lewat
renderer_agresif, SINKRON di event loop (lihat memory
concurrency-model-bot-re-jateng: render matplotlib tidak boleh masuk
asyncio.to_thread, supaya figure global tidak ketuker antar laporan yang
jalan bersamaan). Modul ini (build_raw + prepare_calc_df + hitung_agresif_*
+ format_*_table_df) dipanggil bot.py di DALAM asyncio.to_thread.
"""
import re

import pandas as pd


# ==============================================================================
# JEMBATAN: agresif_data.build_raw() -> format yang dibutuhkan calculator_agresif
# ==============================================================================
def prepare_calc_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Lengkapi kolom yang dibutuhkan calculator_agresif.py (dulu diisi formula
    Excel oleh agresif_report.py, sekarang dihitung native Python):
      bulan_re/tgl_re, bulan_ps/tgl_ps : "YYYY-MM" (str) + hari (int)
      MIDLOW : "low" (speed_product < 50000) / "MID HIGH" (>= 50000) /
               "" (produk wireless) — threshold & rumus PERSIS master
               "TEMPLATE REPORT FMC AGRESIF" kolom MIDLOW:
               IF(SEARCH("wireless",product),"",IF(speed_product<50000,"low","MID HIGH"))
    kab2/kec2 SUDAH ada dari agresif_data.build_raw() (tidak disentuh di sini).
    Return DataFrame baru (df sumber tidak diubah in-place).
    """
    out = df.copy()

    def to_year_month(col):
        return pd.to_datetime(out[col], errors="coerce").dt.strftime("%Y-%m")

    def to_day(col):
        return pd.to_datetime(out[col], errors="coerce").dt.day

    out["bulan_re"] = to_year_month("re_ts")
    out["tgl_re"] = to_day("re_ts")
    out["bulan_ps"] = to_year_month("ps_ts")
    out["tgl_ps"] = to_day("ps_ts")

    def _midlow(pname, spd):
        if "WIRELESS" in str(pname or "").upper():
            return ""
        try:
            spd_num = float(re.sub(r"[^\d.]", "", str(spd)))
            return "low" if spd_num < 50000 else "MID HIGH"
        except Exception:
            # fallback kalau speed_product tak keparse angka — 50M ke atas
            # = MID HIGH (samain dgn ambang 50000 di jalur numerik).
            return "low" if any(s in str(spd).upper() for s in ("10M", "20M", "30M", "40M")) else "MID HIGH"

    out["MIDLOW"] = [_midlow(p, s) for p, s in zip(out["product_commercial_name"], out["speed_product"])]
    return out


# ==============================================================================
# FORMATTER TABEL DETIL (utk sheet Excel "raw" — 38/23/38 kolom lengkap)
# ==============================================================================
def _pct(v):
    return "-" if v is None or pd.isna(v) else f"{v * 100:.1f}%"


def _ppt(v):
    return "-" if v is None or pd.isna(v) else f"{v:+.2f}"


def _fokus_override(r, fokus):
    """Baris subtotal branch/JATENG-DIY menimpa label 'fokus' bawaan dari
    calculator_agresif (yg sudah benar utk baris kec/city — lihat
    hitung_agresif_ps/re/fmc). Baris lain (kec/city) pakai fokus apa adanya."""
    if not r.get("city") and r.get("branch") and r.get("branch") != "JATENG-DIY":
        return "Branch Total"
    if r.get("branch") == "JATENG-DIY":
        return "JATENG-DIY"
    return fokus


def format_ps_table_df(r_ps: dict) -> pd.DataFrame:
    rows_data = []
    all_rows = r_ps["rows"] + r_ps.get("branch_rows", []) + [r_ps["jateng_row"]]
    for r in all_rows:
        fokus = _fokus_override(r, r.get("fokus"))
        rows_data.append({
            "FOKUS DISTRIK": fokus,
            "BRANCH": r.get("branch", ""),
            "CITY": r.get("city", "") or "",
            "KECAMATAN": r.get("kec", "") or "",
            "JML RE MTD (20Mbps)": r.get("re_mtd_helper", 0),
            "JML PS MTD (20Mbps)": r.get("ps_mtd_helper", 0),
            "TARGET PS (LOW)": r.get("target_low"),
            "RE MTD (LOW)": r.get("re_mtd_low", 0),
            "PS MTD-1 (LOW)": r.get("ps_mtd1_low", 0),
            "PS MTD (LOW)": r.get("ps_mtd_low", 0),
            "RE to PS (LOW)": _pct(r.get("low_re_to_ps")),
            "MOM PS (LOW)": _pct(r.get("low_mom")),
            "ACH MTD (LOW)": _pct(r.get("low_ach")),
            "CONTR MTD-1 (LOW)": _pct(r.get("low_contr_mtd1")),
            "CONTR MTD (LOW)": _pct(r.get("low_contr_mtd")),
            "GAP CONTR ppt (LOW)": _ppt(r.get("low_gap_contr")),
            "TARGET PS (MID HIGH)": r.get("target_mid"),
            "RE MTD (MID HIGH)": r.get("re_mtd_mid", 0),
            "PS MTD-1 (MID HIGH)": r.get("ps_mtd1_mid", 0),
            "PS MTD (MID HIGH)": r.get("ps_mtd_mid", 0),
            "RE to PS (MID HIGH)": _pct(r.get("mid_re_to_ps")),
            "MOM PS (MID HIGH)": _pct(r.get("mid_mom")),
            "ACH MTD (MID HIGH)": _pct(r.get("mid_ach")),
            "CONTR MTD-1 (MID HIGH)": _pct(r.get("mid_contr_mtd1")),
            "CONTR MTD (MID HIGH)": _pct(r.get("mid_contr_mtd")),
            "GAP CONTR ppt (MID HIGH)": _ppt(r.get("mid_gap_contr")),
            "TARGET PS (TOTAL)": r.get("target_total"),
            "RE MTD (TOTAL)": r.get("re_mtd_total", 0),
            "PS MTD-1 (TOTAL)": r.get("ps_mtd1_total", 0),
            "PS MTD (TOTAL)": r.get("ps_mtd_total", 0),
            "RE to PS (TOTAL)": _pct(r.get("total_re_to_ps")),
            "MOM PS (TOTAL)": _pct(r.get("total_mom")),
            "ACH MTD (TOTAL)": _pct(r.get("total_ach")),
        })
    return pd.DataFrame(rows_data)


def format_re_table_df(r_re: dict) -> pd.DataFrame:
    rows_data = []
    all_rows = r_re["rows"] + r_re.get("branch_rows", []) + [r_re["jateng_row"]]
    for r in all_rows:
        fokus = _fokus_override(r, r.get("fokus"))
        rows_data.append({
            "FOKUS DISTRIK": fokus,
            "BRANCH": r.get("branch", ""),
            "CITY": r.get("city", "") or "",
            "KECAMATAN": r.get("kec", "") or "",
            "TARGET (LOW)": r.get("target_low"),
            "MTD-1 (LOW)": r.get("mtd1_low", 0),
            "MTD (LOW)": r.get("mtd_low", 0),
            "MOM (LOW)": _pct(r.get("low_mom")),
            "ACH MTD (LOW)": _pct(r.get("low_ach")),
            "CONTR MTD-1 (LOW)": _pct(r.get("low_contr_mtd1")),
            "CONTR MTD (LOW)": _pct(r.get("low_contr_mtd")),
            "GAP CONTR ppt (LOW)": _ppt(r.get("low_gap_contr")),
            "TARGET (MID HIGH)": r.get("target_mid"),
            "MTD-1 (MID HIGH)": r.get("mtd1_mid", 0),
            "MTD (MID HIGH)": r.get("mtd_mid", 0),
            "MOM (MID HIGH)": _pct(r.get("mid_mom")),
            "ACH MTD (MID HIGH)": _pct(r.get("mid_ach")),
            "CONTR MTD-1 (MID HIGH)": _pct(r.get("mid_contr_mtd1")),
            "CONTR MTD (MID HIGH)": _pct(r.get("mid_contr_mtd")),
            "GAP CONTR ppt (MID HIGH)": _ppt(r.get("mid_gap_contr")),
            "TARGET (RE TOTAL)": r.get("target_total"),
            "MTD-1 (RE TOTAL)": r.get("mtd1_total", 0),
            "MTD (RE TOTAL)": r.get("mtd_total", 0),
            "MOM (RE TOTAL)": _pct(r.get("total_mom")),
            "ACH MTD (RE TOTAL)": _pct(r.get("total_ach")),
        })
    return pd.DataFrame(rows_data)


def format_fmc_table_df(r_fmc: dict) -> pd.DataFrame:
    rows_data = []
    all_rows = (r_fmc.get("new_rows", []) + r_fmc.get("old_rows", [])
                + r_fmc.get("branch_rows", []) + [r_fmc["jateng_row"]])
    for r in all_rows:
        fokus = _fokus_override(r, r.get("fokus"))
        rows_data.append({
            "FOKUS DISTRIK": fokus,
            "BRANCH": r.get("branch", ""),
            "CITY": r.get("city", "") or "",
            "JML RE MTD (20Mbps)": r.get("re_mtd_helper", 0),
            "JML PS MTD (20Mbps)": r.get("ps_mtd_helper", 0),
            "TARGET PS (LOW)": r.get("target_low"),
            "RE MTD (LOW)": r.get("re_mtd_low", 0),
            "PS MTD-1 (LOW)": r.get("ps_mtd1_low", 0),
            "PS MTD (LOW)": r.get("ps_mtd_low", 0),
            "RE to PS (LOW)": _pct(r.get("low_re_to_ps")),
            "MOM PS (LOW)": _pct(r.get("low_mom")),
            "ACH MTD (LOW)": _pct(r.get("low_ach")),
            "CONTR MTD-1 (LOW)": _pct(r.get("low_contr_mtd1")),
            "CONTR MTD (LOW)": _pct(r.get("low_contr_mtd")),
            "GAP CONTR ppt (LOW)": _ppt(r.get("low_gap_contr")),
            "TARGET PS (MID HIGH)": r.get("target_mid"),
            "RE MTD (MID HIGH)": r.get("re_mtd_mid", 0),
            "PS MTD-1 (MID HIGH)": r.get("ps_mtd1_mid", 0),
            "PS MTD (MID HIGH)": r.get("ps_mtd_mid", 0),
            "RE to PS (MID HIGH)": _pct(r.get("mid_re_to_ps")),
            "MOM PS (MID HIGH)": _pct(r.get("mid_mom")),
            "ACH MTD (MID HIGH)": _pct(r.get("mid_ach")),
            "CONTR MTD-1 (MID HIGH)": _pct(r.get("mid_contr_mtd1")),
            "CONTR MTD (MID HIGH)": _pct(r.get("mid_contr_mtd")),
            "GAP CONTR ppt (MID HIGH)": _ppt(r.get("mid_gap_contr")),
            "TARGET PS (TOTAL)": r.get("target_total"),
            "RE MTD (TOTAL)": r.get("re_mtd_total", 0),
            "PS MTD-1 (TOTAL)": r.get("ps_mtd1_total", 0),
            "PS MTD (TOTAL)": r.get("ps_mtd_total", 0),
            "RE to PS (TOTAL)": _pct(r.get("total_re_to_ps")),
            "MOM PS (TOTAL)": _pct(r.get("total_mom")),
            "ACH MTD (TOTAL)": _pct(r.get("total_ach")),
        })
    return pd.DataFrame(rows_data)


# ==============================================================================
# CAPTION TELEGRAM (3 laporan) — dibangun dari caption_data yg sudah dihitung
# calculator_agresif.py (top/worst ACH & MoM per branch/kec/city), bukan
# dihitung ulang di sini.
# ==============================================================================
def _b(row):
    return row["branch"] if row else "-"


def _v(row, field):
    return _pct(row[field]) if row else "-"


def _name(row, key):
    val = row.get(key) if row else None
    return str(val).title() if val else "-"


def build_captions(cutoff_date, r_ps: dict, r_re: dict, r_fmc: dict) -> tuple:
    """Return (caption1, caption2, caption3) — teks siap kirim per gambar."""
    date_label = cutoff_date.strftime("%d-%b-%Y").upper()

    jt = r_ps["jateng_row"]
    cd = r_ps["caption_data"]
    cap1 = "\n".join([
        "REPORT NEW SALES LOKASI AGRESIF", date_label, "",
        f"Growth Total PS {_pct(jt.get('total_mom'))}",
        f"- MoM PS Low Package {_pct(jt.get('low_mom'))}",
        f"- MoM PS Mid High Package {_pct(jt.get('mid_mom'))}", "",
        "TOP ACH PS:",
        f"- BRANCH {_b(cd['top_ach_branch'])} = {_v(cd['top_ach_branch'], 'total_ach')}",
        f"- Kecamatan {_name(cd['top_ach_item'], 'kec')} = {_v(cd['top_ach_item'], 'total_ach')}", "",
        "TOP MoM PS:",
        f"- BRANCH {_b(cd['top_mom_branch'])} = {_v(cd['top_mom_branch'], 'total_mom')}",
        f"- Kecamatan {_name(cd['top_mom_item'], 'kec')} = {_v(cd['top_mom_item'], 'total_mom')}",
    ])

    jt = r_re["jateng_row"]
    cd = r_re["caption_data"]
    cap2 = "\n".join([
        "REPORT RE NEW KECAMATAN AGRESIF", date_label, "",
        f"Growth Total RE {_pct(jt.get('total_mom'))}",
        f"- MoM RE Low Package {_pct(jt.get('low_mom'))}",
        f"- MoM RE Mid High Package {_pct(jt.get('mid_mom'))}", "",
        "TOP ACH RE:",
        f"- BRANCH {_b(cd['top_ach_branch'])} = {_v(cd['top_ach_branch'], 'total_ach')}",
        f"- Kecamatan {_name(cd['top_ach_item'], 'kec')} = {_v(cd['top_ach_item'], 'total_ach')}", "",
        "TOP MoM RE:",
        f"- BRANCH {_b(cd['top_mom_branch'])} = {_v(cd['top_mom_branch'], 'total_mom')}",
        f"- Kecamatan {_name(cd['top_mom_item'], 'kec')} = {_v(cd['top_mom_item'], 'total_mom')}", "",
        "Worst MoM RE:",
        f"- BRANCH {_b(cd['worst_mom_branch'])} = {_v(cd['worst_mom_branch'], 'total_mom')}",
        f"- Kecamatan {_name(cd['worst_mom_item'], 'kec')} = {_v(cd['worst_mom_item'], 'total_mom')}",
    ])

    jt = r_fmc["jateng_row"]
    cd = r_fmc["caption_data"]
    cap3 = "\n".join([
        "REPORT NEW SALES ALL FMC CITY", date_label, "",
        f"Growth Total PS {_pct(jt.get('total_mom'))}",
        f"- MoM PS Low Package {_pct(jt.get('low_mom'))}",
        f"- MoM PS Mid High Package {_pct(jt.get('mid_mom'))}", "",
        "TOP ACH PS:",
        f"- BRANCH {_b(cd['top_ach_branch'])} = {_v(cd['top_ach_branch'], 'total_ach')}",
        f"- City {_name(cd['top_ach_item'], 'city')} = {_v(cd['top_ach_item'], 'total_ach')}", "",
        "TOP MoM PS:",
        f"- BRANCH {_b(cd['top_mom_branch'])} = {_v(cd['top_mom_branch'], 'total_mom')}",
        f"- City {_name(cd['top_mom_item'], 'city')} = {_v(cd['top_mom_item'], 'total_mom')}", "",
        "Worst MoM PS:",
        f"- BRANCH {_b(cd['worst_mom_branch'])} = {_v(cd['worst_mom_branch'], 'total_mom')}",
        f"- City {_name(cd['worst_mom_item'], 'city')} = {_v(cd['worst_mom_item'], 'total_mom')}",
    ])

    return cap1, cap2, cap3


# ==============================================================================
# EXPORT .xlsx MULTI-SHEET (streaming write_only — cepat & hemat memori utk
# sheet RAW yg bisa berisi puluhan-ratusan ribu baris)
# ==============================================================================
_ILLEGAL_CHARACTERS_RE = re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]')


def write_agresif_workbook(filepath: str, sheets_dict: dict) -> None:
    import openpyxl

    wb = openpyxl.Workbook(write_only=True)
    for sheet_name, df in sheets_dict.items():
        ws = wb.create_sheet(title=sheet_name)
        ws.append([_ILLEGAL_CHARACTERS_RE.sub('', str(c)) if isinstance(c, str) else c
                   for c in df.columns])
        for row in df.itertuples(index=False, name=None):
            clean_row = []
            for v in row:
                if isinstance(v, str):
                    clean_row.append(_ILLEGAL_CHARACTERS_RE.sub('', v))
                elif v is None or pd.isna(v):
                    clean_row.append(None)
                else:
                    clean_row.append(v)
            ws.append(clean_row)
    wb.save(filepath)


def write_raw_csv_gz(filepath: str, df: pd.DataFrame) -> None:
    """
    RAW DATA (94 kolom, bisa >100rb baris) diekspor sbg CSV di-gzip, BUKAN
    sheet .xlsx — XLSX bungkus tiap sel dalam XML verbose (bahkan setelah
    di-DEFLATE tetap boros utk data tabular repetitif spt ini), sedangkan
    CSV+gzip bisa 3-5x lebih kecil utk data serupa. Ini yang bikin file "raw"
    /agresif dulu ~49-50MB (mepet/lewat limit kirim Bot API) — dgn CSV+gzip
    harusnya jauh di bawah 50MB, jadi bisa OTOMATIS terkirim lagi.
    """
    df.to_csv(filepath, index=False, sep=';', encoding='utf-8-sig', compression='gzip')
