"""
Konstanta warna utk renderer_agresif.py — diekstrak LANGSUNG dari
conditionalFormatting + dxfs XML di `tika/TEMPLATE AGRESIVE TAHAP 1 JULI.xlsx`
(bukan tebakan dari screenshot). Rule sama dipakai berulang utk 3 blok kolom
(LOW/MID HIGH/TOTAL) di semua sheet report (PS/RE/FMC) — jadi cukup didefinisikan
sekali sbg konstanta semantik di sini.

Sumber rule per kolom (row 7 sqref, sheet REPORT AGRESIF):
  MOM   (N/Y/AJ)      : cellIs >0 -> hijau, <=0 -> merah   (dxf standar Excel Good/Bad)
  ACH   (O/Z/AK)      : dataBar warna #FF555A (merah-koral)
  CONTR MTD-1 (Q/AB)  : dataBar warna #638EC6 (biru)
  CONTR MTD   (R/AC)  : dataBar warna #63C384 (hijau)
  GAP CONTR (S)       : iconSet 3Symbols reverse, cfvo [percent 0, num>=0, num>=10]
                        -> <0 merah, 0-10 kuning, >=10 hijau
"""

# ── MOM (positif/negatif) — Excel standar "Good/Bad" ────────────────────────
MOM_POS_BG = "#C6EFCE"
MOM_POS_FG = "#006100"
MOM_NEG_BG = "#FFC7CE"
MOM_NEG_FG = "#9C0006"

# ── Data bar (ACH MTD, CONTR MTD-1, CONTR MTD) ──────────────────────────────
ACH_DATABAR = "#FF555A"          # merah-koral
CONTR_MTD1_DATABAR = "#638EC6"   # biru
CONTR_MTD_DATABAR = "#63C384"    # hijau

# ── GAP CONTR icon set (3 simbol: X merah / ! kuning / check hijau) ─────────
# [06-Aug-2026, user request] Icon GAP CONTR blok MID HIGH DIHAPUS (angka
# polos, lihat renderer_agresif._ps_like_blocks/_re_blocks: kind=None utk
# mid). Icon blok LOW TETAP ADA tapi polaritas DIBALIK dari hasil ekstraksi
# awal (dulu: gap kecil/negatif=merah, gap besar=hijau) — sekarang: gap
# makin RENDAH/negatif = HIJAU, gap makin BESAR = MERAH. gap_icon_color() di
# bawah sudah pakai polaritas baru ini, sekarang cuma dipakai blok LOW.
GAP_ICON_NEG = "#E74C3C"     # merah  -> gap TINGGI  (>= hi)
GAP_ICON_MID = "#F1C40F"     # kuning -> gap tengah  (lo <= gap < hi)
GAP_ICON_POS = "#27AE60"     # hijau  -> gap RENDAH  (< lo)
GAP_ICON_THRESHOLDS = (0, 10)

# ── Header/struktur statis (dari screenshot, warna solid tetap) ────────────
HDR_NAVY = "#1F3864"          # header FOKUS DISTRIC/BRANCH/CITY/KECAMATAN
HDR_RED_LOW = "#C00000"       # banner "NEW SALES LOW PACKAGE"
HDR_RED_MID = "#C00000"       # banner "NEW SALES MID HIGH PACKAGE"
ROW_ZEBRA_A = "#FFFFFF"
ROW_ZEBRA_B = "#F2F2F2"
JATENG_ROW_BG = "#E8D5F0"     # baris total JATENG-DIY (ungu muda)
BRANCH_ROW_BG = "#D9D9D9"     # baris subtotal branch (abu-abu)


def mom_color(v):
    """Return (bg, fg) utk sel MOM. v = fraksi (0.05 = 5%), None -> abu netral."""
    if v is None:
        return None, None
    return (MOM_POS_BG, MOM_POS_FG) if v > 0 else (MOM_NEG_BG, MOM_NEG_FG)


def gap_icon_color(v):
    """Return warna icon utk GAP CONTR (ppt) blok LOW. v None -> None (tak
    digambar). Polaritas: makin RENDAH (termasuk negatif) -> HIJAU, makin
    TINGGI -> MERAH (lihat komentar GAP_ICON_* di atas)."""
    if v is None:
        return None
    lo, hi = GAP_ICON_THRESHOLDS
    if v < lo:
        return GAP_ICON_POS
    if v < hi:
        return GAP_ICON_MID
    return GAP_ICON_NEG
