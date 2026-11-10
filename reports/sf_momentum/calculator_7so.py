"""
reports/sf_momentum/calculator_7so.py — Report /7so: SF Momentum basis RE per Region / Branch / WOK

Sama dengan /5so (calculator_5so.py: periode, sumber, mapping WOK), bedanya:
  - SF AKTIF / SF PRODUKTIF / PRODUKTIVITAS dihitung dari RE (re_ts), bukan PS:
      SF AKTIF = SF RE >= 1, SF PRODUKTIF = SF RE >= 10, PRODUKTIVITAS = RE AGENCY / SF AKTIF
  - 7 metrik: SF AKTIF DJP | ODP VISIT | DJP/SF/DAY | SF AKTIF | SF PRODUKTIF |
              PRODUKTIVITAS | SF REGISTERED
      DJP/SF/DAY = jumlah kunjungan DJP / SF AKTIF DJP / jumlah hari periode
  - STATUS: >=6 OUTPERFORM, 5 ON TRACK, 4 WATCH, <=3 CRITICAL

export_sf_tidak_aktif(): Excel "SF Belum RE 1-D <bln>" — SF tanpa RE di MTD (tgl 1..D
bulan ini), baik yang masih RE di M1 (1..D bulan lalu) maupun yang RE M1-nya juga 0.
Dikirim setelah gambar /7so. Sumber RE: indihome_ordering_detail (RE AGENCY, sama dgn
metrik SF AKTIF 7SO); daftar SF dgn RE M1 = 0 dari database_sf (status ACTIVE).
"""
from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import calculator_5so
from .calculator_5so import WOKS, WOK2BR, BRANCHES, _norm_wok
from config import REGION_NAME

METRICS = ["sf_djp", "odp", "djp_sf_day", "sf_aktif", "sf_prod", "prod", "sf_reg"]

_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
_WOK_TAMPIL = {"DAERAH ISTIMEWA YOGYAKARTA": "DI Yogyakarta"}
_LEBAR = {"A": 13, "B": 24, "C": 16, "D": 34, "E": 13, "F": 13}


def hitung_7so(tgl: date) -> dict:
    return calculator_5so.hitung_5so(tgl, basis="RE", metrics=METRICS,
                                     title="7SO Scorecard Jateng-DIY")


def _periode(a: date, b: date) -> str:
    """1-12 Sep"""
    return f"{a.day}-{b.day} {_BULAN[b.month - 1]}"


def _sf_master_lengkap(tgl: date) -> pd.DataFrame:
    """SF ACTIVE JATENG-DIY di database_sf (snapshot event_date terakhir <= tgl).
    Kolom: sf, w (WOK baru), nama_db. Fallback ke database_sf bulan sebelumnya bila
    tabel bulan tgl belum ada (calculator_5so.sf_snapshot)."""
    df = calculator_5so.sf_snapshot("kode, nama, wok", f"{tgl:%Y%m}", tgl, "7so sf master")
    if df.empty:
        return pd.DataFrame(columns=["sf", "w", "nama_db"])
    return pd.DataFrame({
        "sf"     : df["kode"].astype(str).str.strip().str.upper(),
        "w"      : df["wok"].map(_norm_wok),
        "nama_db": df["nama"].fillna("").astype(str).str.strip(),
    }).drop_duplicates("sf")


def export_sf_tidak_aktif(result: dict) -> tuple[BytesIO, str, pd.DataFrame]:
    """
    SF yang BELUM RE di MTD (1..D bulan ini), gabungan dari:
      - SF yang ada RE di M1 (1..D bulan lalu)  -> indihome_ordering_detail
      - SF ACTIVE database_sf yang RE M1 juga 0 -> database_sf
    Return (buffer xlsx, nama file, DataFrame baris SF). Kolom:
    Branch | WOK | SF Code | Nama SF | RE <M1> | RE <MTD>,
    urut Branch → WOK (urutan 7SO) → RE M1 terbanyak → SF Code.
    """
    tgl, awal = result["tgl"], result["awal"]
    lm_awal, lm_akhir = result["lm_awal"], result["lm_akhir"]
    m1, mtd = result["sf_m1"], result["sf_mtd"]

    lbl_m1, lbl_mtd = f"RE {_periode(lm_awal, lm_akhir)}", f"RE {_periode(awal, tgl)}"
    sudah_re = set(mtd["sf"])

    aktif_m1 = m1[(m1["n"] > 0) & ~m1["sf"].isin(sudah_re)]
    master = _sf_master_lengkap(tgl)
    master = master[~master["sf"].isin(sudah_re)]

    # SF M1 ambil WOK/nama dari ordering (fallback master); sisanya dari master dgn RE M1 = 0
    df = aktif_m1.merge(master, on="sf", how="left", suffixes=("", "_db"))
    df["w"] = df["w"].fillna(df["w_db"])
    df["nama"] = df["nama"].where(df["nama"].fillna("") != "", df["nama_db"])
    nol = master[~master["sf"].isin(set(aktif_m1["sf"]))].rename(columns={"nama_db": "nama"})
    nol = nol.assign(n=0)
    df = pd.concat([df[["sf", "n", "w", "nama"]], nol[["sf", "n", "w", "nama"]]], ignore_index=True)

    df["w"] = df["w"].fillna("")
    urut_wok = {w: i for i, w in enumerate(WOKS)}
    urut_br = {b: i for i, b in enumerate(BRANCHES)}
    df["br"] = df["w"].map(WOK2BR).fillna("")
    df = df.assign(_b=df["br"].map(urut_br).fillna(999), _w=df["w"].map(urut_wok).fillna(999))
    df = df.sort_values(["_b", "_w", "n", "sf"], ascending=[True, True, False, True])

    out = pd.DataFrame({
        "Branch" : df["br"].str.title().replace("", "-"),
        "WOK"    : df["w"].map(lambda w: _WOK_TAMPIL.get(w, w.title()) or "-"),
        "SF Code": df["sf"],
        "Nama SF": df["nama"].fillna(""),
        lbl_m1   : df["n"].astype(int),
        lbl_mtd  : 0,
    })

    judul = f"SF BELUM RE {_periode(awal, tgl).upper()} {tgl.year} — {REGION_NAME}"

    wb = Workbook()
    ws = wb.active
    ws.title = "SF Belum RE"
    ws["A1"] = judul
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([])
    ws.append(list(out.columns))
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1B2A41")
        c.alignment = Alignment(horizontal="center")
    for row in out.itertuples(index=False):
        ws.append(list(row))
    for col, w in _LEBAR.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:F{max(ws.max_row, 3)}"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    # SF Belum RE Mtd 14 Okt - Jateng-DIY.xlsx
    fname = f"SF Belum RE Mtd {tgl.day} {_BULAN[tgl.month - 1]} - Jateng-DIY.xlsx"
    return buf, fname, out
