"""
reports/clockin_sf_all/calculator.py — Report Clock-In SF All Category (/clockin_sf_all).

Mirip Report Clock-in SF Teritory, tapi untuk SELURUH SF terdaftar (semua kategori), bukan
hanya SF Teritory, dan tanpa target per SF: pembandingnya adalah assignment homepass di SELA.

Sumber:
  SF Register  = SF ACTIVE database_sf (snapshot tgl laporan; aturan sama dgn 5SO/7SO:
                 SF dummy dibuang, override snapshot SF Registered — reports/sf_momentum/sf_rules.py)
  Assign/Clock-in = file detail-homepass_*.xlsx hasil scraping SELA (sheet "Detail Homepass"),
                 hanya baris yang Kode-nya ada di SF Register, tanggal 1..tgl laporan.

Definisi (sama dengan HTML Report Clock-in SF Teritory):
  SF Assign DJP     SF yang punya >= 1 baris homepass (assign) di periode
  SF Clockin DJP    SF yang punya >= 1 baris Journey Status = CHECKOUT
  ODP Assign        kombinasi unik (Tanggal, Kode, ODP) semua baris
  ODP Clockin       kombinasi unik (Tanggal, Kode, ODP) baris CHECKOUT
  HP Assign         jumlah baris homepass;  HP Clockin = jumlah baris CHECKOUT
  ODP/SF/Day, HP/SF/Day = clock-in / jumlah hari-SF yang ada clock-in (pasangan unik Kode, Tanggal)
  % SF Assign / % SF Clockin dibagi SF Register; Ach ODP / Ach HP = clock-in / assign
"""
from __future__ import annotations

from datetime import date, datetime

import openpyxl
import pandas as pd

from reports.sf_momentum.calculator_5so import BRANCHES, WOK2BR, WOKS

BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
BULAN_PANJANG = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
                 "September", "Oktober", "November", "Desember"]
_WOK_TAMPIL = {"DAERAH ISTIMEWA YOGYAKARTA": "DI Yogyakarta"}
KOLOM = ("Kode", "Nama SF", "Tanggal", "ODP", "Journey Status")


def tampil_wok(w: str) -> str:
    return _WOK_TAMPIL.get(w, w.title())


def baca_homepass(path: str) -> pd.DataFrame:
    """Baca kolom yang dipakai saja dari detail-homepass (read-only, jauh lebih cepat dari read_excel)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Detail Homepass"] if "Detail Homepass" in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        hdr = [str(c or "").strip() for c in next(it)]
        hilang = [k for k in ("Kode", "Tanggal", "ODP", "Journey Status") if k not in hdr]
        if hilang:
            raise ValueError(f"Kolom {', '.join(hilang)} tidak ada di {path}")
        idx = [hdr.index(k) if k in hdr else None for k in KOLOM]
        rows = [tuple(r[i] if i is not None and i < len(r) else None for i in idx) for r in it]
    finally:
        wb.close()
    df = pd.DataFrame(rows, columns=["kode", "nama", "tgl", "odp", "status"])
    df["kode"] = df["kode"].fillna("").astype(str).str.strip().str.upper()
    df["tgl"] = pd.to_datetime(df["tgl"], errors="coerce").dt.date
    df["odp"] = df["odp"].fillna("").astype(str).str.strip()
    df["ck"] = df["status"].fillna("").astype(str).str.strip().str.upper() == "CHECKOUT"
    return df[(df["kode"] != "") & df["tgl"].notna()]


def _agg(sf: pd.DataFrame, hp: pd.DataFrame) -> dict:
    ck = hp[hp["ck"]]
    reg = len(sf)
    asg = hp["kode"].nunique()
    cl = ck["kode"].nunique()
    odp_a = len(hp.drop_duplicates(["tgl", "kode", "odp"]))
    odp_c = len(ck.drop_duplicates(["tgl", "kode", "odp"]))
    hp_a, hp_c = len(hp), len(ck)
    hari = len(ck.drop_duplicates(["kode", "tgl"]))
    pct = lambda a, b: a / b * 100 if b else None
    return {"reg": reg, "asg": asg, "p_asg": pct(asg, reg), "cl": cl, "p_cl": pct(cl, reg),
            "odp_a": odp_a, "odp_c": odp_c, "ach_odp": pct(odp_c, odp_a), "odp_day": odp_c / hari if hari else None,
            "hp_a": hp_a, "hp_c": hp_c, "ach_hp": pct(hp_c, hp_a), "hp_day": hp_c / hari if hari else None,
            "belum_ck": asg - cl, "belum_asg": reg - asg}


def hitung(hp: pd.DataFrame, master: pd.DataFrame, tgl: date) -> dict:
    """
    hp     : hasil baca_homepass()
    master : SF Register, kolom sf, w (WOK baru), nama_db (calculator_7so._sf_master_lengkap)
    """
    awal = tgl.replace(day=1)
    sf = master[master["w"].isin(WOKS)].drop_duplicates("sf").copy()
    hp = hp[(hp["tgl"] >= awal) & (hp["tgl"] <= tgl) & hp["kode"].isin(set(sf["sf"]))].copy()
    w_of = dict(zip(sf["sf"], sf["w"]))
    hp["w"] = hp["kode"].map(w_of)
    t_max = hp["tgl"].max() if not hp.empty else None

    woks = []
    for w in WOKS:
        r = _agg(sf[sf["w"] == w], hp[hp["w"] == w])
        r.update(wok=tampil_wok(w), br=WOK2BR[w].title())
        woks.append(r)
    total = _agg(sf, hp)

    # harian (semua tanggal periode, termasuk hari tanpa clock-in)
    ck = hp[hp["ck"]]
    harian = []
    for d in pd.date_range(awal, tgl).date:
        x = ck[ck["tgl"] == d]
        harian.append({"d": d, "odp": len(x.drop_duplicates(["kode", "odp"])), "hp": len(x)})

    # detail per SF (Excel)
    asg_n = hp.groupby("kode").size()
    ck_n = ck.groupby("kode").size()
    odp_n = ck.drop_duplicates(["tgl", "kode", "odp"]).groupby("kode").size()
    odpa_n = hp.drop_duplicates(["tgl", "kode", "odp"]).groupby("kode").size()
    hari_n = ck.drop_duplicates(["kode", "tgl"]).groupby("kode").size()
    nama_hp = hp.dropna(subset=["nama"]).drop_duplicates("kode").set_index("kode")["nama"]
    urut_w = {w: i for i, w in enumerate(WOKS)}
    det = []
    for k, w, nm in zip(sf["sf"], sf["w"], sf["nama_db"]):
        a, c = int(asg_n.get(k, 0)), int(ck_n.get(k, 0))
        det.append({"br": WOK2BR[w].title(), "wok": tampil_wok(w), "_u": urut_w[w], "kode": k,
                    "nama": nm or str(nama_hp.get(k, "") or ""), "hari": int(hari_n.get(k, 0)),
                    "odp_a": int(odpa_n.get(k, 0)), "odp_c": int(odp_n.get(k, 0)), "hp_a": a, "hp_c": c,
                    "status": "Sudah clock-in" if c else ("Belum clock-in" if a else "Belum di-assign")})
    det.sort(key=lambda r: (r["_u"], -r["hp_c"], -r["hp_a"], r["kode"]))

    belum_ck_br = {b.title(): sum(r["belum_ck"] for r in woks if r["br"] == b.title()) for b in BRANCHES}
    return {"tgl": tgl, "awal": awal, "t_max": t_max, "woks": woks, "total": total, "harian": harian,
            "detail": det, "belum_ck_br": belum_ck_br, "n_baris": int(hp.shape[0])}


# ── teks ─────────────────────────────────────────────────────────────────────
def fnum(v, dec=0) -> str:
    """Format angka gaya Indonesia: 1.234 / 2,9."""
    if v is None:
        return "-"
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fpct(v) -> str:
    return "-" if v is None else fnum(v, 1) + "%"


def label_periode(r: dict) -> str:
    a, t = r["awal"], r["tgl"]
    return f"{a.day}–{t.day} {BULAN[t.month - 1]} {t.year}"


def _rank(woks, key, n=3, desc=True, fmt=fpct):
    xs = [w for w in woks if w[key] is not None]
    xs.sort(key=lambda w: w[key], reverse=desc)
    return ", ".join(f"{w['wok']} {fmt(w[key])}" for w in xs[:n])


def caption(r: dict, sekarang: datetime | None = None) -> str:
    """Caption WhatsApp/Telegram (teks biasa, tanpa Markdown)."""
    jam = (sekarang or datetime.now()).hour
    salam = "pagi" if jam < 11 else "siang" if jam < 15 else "sore" if jam < 18 else "malam"
    t, W = r["total"], r["woks"]
    tgl = r["tgl"]
    full = len(r["harian"]) == pd.Period(tgl, "M").days_in_month
    per = f"{BULAN_PANJANG[tgl.month - 1]} {tgl.year}" if full else f"MTD {tgl.day} {BULAN[tgl.month - 1]} {tgl.year}"
    penuh = [w["wok"] for w in W if w["p_asg"] is not None and w["p_asg"] >= 100]
    kurang = [w for w in W if w["p_asg"] is None or w["p_asg"] < 100]
    f1 = lambda v: fnum(v, 1)
    baris = [
        f"Selamat {salam} rekan-rekan, berikut update Clock-In DJP seluruh SF (All Category) "
        f"Jateng-DIY {per}:",
        "",
        f"📌 SF Assign DJP: {fnum(t['asg'])} dari {fnum(t['reg'])} SF ({fpct(t['p_asg'])})",
    ]
    if penuh:
        baris.append(f"✅ Sudah 100%: {', '.join(penuh)}")
    if kurang:
        baris.append(f"⚠️ Terendah: {_rank(kurang, 'p_asg', desc=False)}")
    baris += [
        "",
        f"📌 SF Clock-in DJP: {fnum(t['cl'])} SF ({fpct(t['p_cl'])} dari SF Register)",
        f"✅ Top 3: {_rank(W, 'p_cl')}",
        f"⚠️ Bottom 3: {_rank(W, 'p_cl', desc=False)}",
        "",
        f"📌 Clock-in ODP: {fnum(t['odp_c'])} ({fpct(t['ach_odp'])} dari assign) · {f1(t['odp_day'])} ODP/SF/Day",
        f"✅ Top 3 Ach: {_rank(W, 'ach_odp')}",
        f"✅ Top 3 ODP/SF/Day: {_rank(W, 'odp_day', fmt=f1)}",
        f"⚠️ Bottom 3 Ach: {_rank(W, 'ach_odp', desc=False)}",
        f"⚠️ Bottom 3 ODP/SF/Day: {_rank(W, 'odp_day', desc=False, fmt=f1)}",
        "",
        f"📌 Clock-in Homepass: {fnum(t['hp_c'])} ({fpct(t['ach_hp'])} dari assign) · {f1(t['hp_day'])} HP/SF/Day",
        f"✅ Top 3 Ach: {_rank(W, 'ach_hp')}",
        f"✅ Top 3 HP/SF/Day: {_rank(W, 'hp_day', fmt=f1)}",
        f"⚠️ Bottom 3 Ach: {_rank(W, 'ach_hp', desc=False)}",
        f"⚠️ Bottom 3 HP/SF/Day: {_rank(W, 'hp_day', desc=False, fmt=f1)}",
        "",
        f"👥 {fnum(t['belum_ck'])} SF sudah di-assign tapi belum clock-in, "
        f"{fnum(t['belum_asg'])} SF belum di-assign (detail di Excel).",
    ]
    return "\n".join(baris)
