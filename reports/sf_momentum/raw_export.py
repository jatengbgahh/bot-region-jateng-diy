"""
reports/sf_momentum/raw_export.py — Excel "5SO 7SO per SF + RAW DD-MM-YYYY.xlsx".

Dikirim sebagai sub-report `raw` dari /7so (setelah Excel SF Belum RE). Tujuannya: teman-teman
area butuh 5SO & 7SO versi raw lengkap dengan SF dan Team Leader-nya.

Sheet:
  REPORT 5SO / REPORT 7SO  scorecard Region/Branch/WOK (rumus ke sheet per SF & RAW), sama
                           dengan gambar /5so /7so termasuk Momentum Skor & Status
  GAMBAR 5SO / GAMBAR 7SO  gambar scorecard + caption (angka tetap per tanggal laporan)
  5SO / 7SO                per SF: Branch, WOK, SF Code, Nama SF, Team Leader, Status SF,
                           PS (5SO) / RE (7SO), Kunjungan DJP, ODP Visited — M1 & MTD (rumus ke RAW).
                           Tanpa flag, MoM, produktivitas dan momentum skor (permintaan user 08-11-2026)
  RAW_SF / RAW_PS / RAW_RE / RAW_DJP  data mentah M1 & MTD

Sumber & aturan sama persis dengan calculator_5so (WOK baru, SF dummy dibuang, override snapshot
SF Registered, ordering AGENCY NEW SALES non-wireless dedup order_id). Team Leader & Agency dari
mapping resources/team_leader (sf_rules.load_tl_map).
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from io import BytesIO

import pandas as pd
from dateutil.relativedelta import relativedelta
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

from config import REGION_NAME
from . import calculator_5so as c5, sf_rules
from .calculator_5so import BRANCHES, KAB2WOK, WOK2BR, WOKS, PROD_MIN_TRX, _norm_wok, _q

logger = logging.getLogger(__name__)

_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
_WOK_TAMPIL = {"DAERAH ISTIMEWA YOGYAKARTA": "DI Yogyakarta"}

F_HDR = PatternFill("solid", fgColor="1B2A41")
F_SUB = PatternFill("solid", fgColor="2F4A6D")
F_REG = PatternFill("solid", fgColor="E3E8EF")
F_BR = PatternFill("solid", fgColor="F3F5F8")
FT_HDR = Font(bold=True, color="FFFFFF")
B_THIN = Border(*(Side(style="thin", color="C9CED6"),) * 4)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def tampil_wok(w) -> str:
    return _WOK_TAMPIL.get(w, w.title()) if isinstance(w, str) and w else "-"


def tampil_br(b) -> str:
    return b.title() if isinstance(b, str) and b else "-"


# ── data ─────────────────────────────────────────────────────────────────────
def _master(ym: str, tgl: date) -> pd.DataFrame:
    df = c5.sf_snapshot("UPPER(TRIM(kode)) kode, nama, wok, event_date", ym, tgl, "sfo raw")
    if df.empty:
        return pd.DataFrame(columns=["kode", "nama", "wok", "event_date"])
    df["wok"] = df["wok"].map(_norm_wok)
    df["nama"] = df["nama"].fillna("").astype(str).str.strip()
    return df.drop_duplicates("kode")


def _ordering(a: date, b: date) -> pd.DataFrame:
    """Order AGENCY NEW SALES non-wireless dengan PS ATAU RE di a..b (satu query untuk PS & RE)."""
    t = f"indihome_ordering_detail_{a:%Y%m}"
    akhir = b + timedelta(days=1)
    kolom = "order_id, sf_code, sf_name, kabupaten, event_date, channel_group, product_commercial_name, ps_ts, re_ts"
    df = pd.DataFrame()
    for status in ("order_status", "NULL AS order_status"):   # export tanpa kolom order_status -> kosong
        try:
            df = _q(f"""SELECT {kolom}, {status} FROM {t}
                        WHERE region LIKE 'JATENG%%' AND order_type = 'NEW SALES'
                          AND UPPER(TRIM(channel_group)) = 'AGENCY'
                          AND (product_commercial_name NOT LIKE '%%WIRELESS%%' OR product_commercial_name IS NULL)
                          AND ((ps_ts >= %s AND ps_ts < %s) OR (re_ts >= %s AND re_ts < %s))""",
                    (a, akhir, a, akhir), f"sfo raw ordering {a:%Y%m}")
            break
        except Exception as e:
            logger.warning("sfo raw ordering %s (%s): %s", t, status, e)
    if df.empty:
        return pd.DataFrame(columns=kolom.split(", ") + ["order_status", "sf", "kab", "nama", "is_ps", "is_re"]
                            ).astype({"is_ps": bool, "is_re": bool})
    df = sf_rules.drop_dummy(df, "sf_code")
    df = df.sort_values("event_date").drop_duplicates("order_id", keep="last")
    df["sf"] = df["sf_code"].fillna("").astype(str).str.strip().str.upper()
    df["kab"] = df["kabupaten"].fillna("").astype(str).str.strip().str.upper()
    df["nama"] = df["sf_name"].fillna("").astype(str).str.strip()
    for c in ("order_status", "channel_group", "product_commercial_name"):
        df[c] = df[c].fillna("").astype(str)          # NaN tidak boleh masuk sel Excel
    a_ts, b_ts = pd.Timestamp(a), pd.Timestamp(akhir)
    for c in ("ps_ts", "re_ts"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["is_ps"] = (df["ps_ts"] >= a_ts) & (df["ps_ts"] < b_ts)
    df["is_re"] = (df["re_ts"] >= a_ts) & (df["re_ts"] < b_ts)
    return df


def _djp(a: date, b: date) -> pd.DataFrame:
    df = _q(f"""SELECT UPPER(TRIM(user_code)) sf, wok, odp_name, tugas_date
                FROM djp_daily_user_detailed_{a:%Y%m}
                WHERE regional LIKE 'JATENG%%' AND tugas_date BETWEEN %s AND %s""",
            (a, b), f"sfo raw djp {a:%Y%m}")
    if df.empty:
        return pd.DataFrame(columns=["sf", "wok", "odp_name", "tugas_date"])
    df = sf_rules.drop_dummy(df, "sf")
    df["tugas_date"] = pd.to_datetime(df["tugas_date"], errors="coerce")
    return df.sort_values(["tugas_date", "sf"], kind="stable")


def kumpulkan(tgl: date) -> dict:
    awal = tgl.replace(day=1)
    lm_awal = awal - relativedelta(months=1)
    lm_akhir = min(lm_awal + relativedelta(day=tgl.day), awal - timedelta(days=1))
    per = {"M1": (lm_awal, lm_akhir), "MTD": (awal, tgl)}
    master = {"M1": _master(f"{lm_awal:%Y%m}", lm_akhir), "MTD": _master(f"{awal:%Y%m}", tgl)}
    # WOK tiap SF: database_sf bulan berjalan dulu, lalu database_sf bulan periode itu (= calculator_5so)
    kode2wok = {k: w for k, w in zip(master["MTD"]["kode"], master["MTD"]["wok"]) if w}
    out = {"tgl": tgl, "awal": awal, "lm_awal": lm_awal, "lm_akhir": lm_akhir, "per": per,
           "master": master, "kode2wok": kode2wok, "ord": {}, "djp": {}}
    for p, (a, b) in per.items():
        own = dict(zip(master[p]["kode"], master[p]["wok"]))
        wok_of = lambda k, own=own: kode2wok.get(k) or own.get(k)
        o = _ordering(a, b)
        o["w"] = [wok_of(s) if s else None for s in o["sf"]]
        o["w"] = o["w"].fillna(o["kab"].map(KAB2WOK))
        dj = _djp(a, b)
        dj["w"] = [wok_of(s) or _norm_wok(w) for s, w in zip(dj["sf"], dj["wok"])]
        master[p]["w"] = master[p]["kode"].map(wok_of)
        out["ord"][p], out["djp"][p] = o, dj
    return out


# ── Excel helpers ────────────────────────────────────────────────────────────
def _hdr(ws, row, col, text, fill=F_HDR, span=1, rows=1):
    c = ws.cell(row=row, column=col, value=text)
    if span > 1 or rows > 1:
        ws.merge_cells(start_row=row, start_column=col, end_row=row + rows - 1, end_column=col + span - 1)
    for r in range(row, row + rows):
        for k in range(col, col + span):
            x = ws.cell(row=r, column=k)
            x.fill, x.font, x.alignment, x.border = fill, FT_HDR, CENTER, B_THIN
    return c


def _tulis_raw(ws, header, rows, widths):
    ws.append(header)
    for c in ws[1]:
        c.fill, c.font, c.alignment = F_HDR, FT_HDR, CENTER
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[L(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{L(len(header))}{max(ws.max_row, 2)}"
    return max(ws.max_row, 2)


def _flag_first(keys: pd.DataFrame) -> list:
    return (~keys.duplicated()).astype(int).tolist()


# ── builder ──────────────────────────────────────────────────────────────────
def build_excel(tgl: date, gambar: dict | None = None) -> tuple[BytesIO, str, dict]:
    """
    gambar = {"5SO": (png BytesIO | None, caption), "7SO": (...)} untuk sheet GAMBAR.
    Return (buffer xlsx, nama file, ringkasan {n_sf, ...}).
    """
    d = kumpulkan(tgl)
    tl = sf_rules.load_tl_map()
    awal, lm_awal, lm_akhir = d["awal"], d["lm_awal"], d["lm_akhir"]
    full = tgl == (awal + relativedelta(months=1) - timedelta(days=1))
    bl_m1, bl_mtd = _BULAN[lm_awal.month - 1], _BULAN[tgl.month - 1]
    lbl = {"M1": f"M1 ({'FM ' if full else ''}{bl_m1.upper()})", "MTD": "MTD"}
    rng = f"MTD {awal.day}-{tgl.day} {bl_mtd} {tgl.year} vs {lbl['M1']} {lm_awal.day}-{lm_akhir.day} {bl_m1}"

    wb = Workbook()
    wb.remove(wb.active)
    s_rep = {"5SO": wb.create_sheet("REPORT 5SO"), "7SO": wb.create_sheet("REPORT 7SO")}
    s_img = {"5SO": wb.create_sheet("GAMBAR 5SO"), "7SO": wb.create_sheet("GAMBAR 7SO")}
    s_sf = {"5SO": wb.create_sheet("5SO"), "7SO": wb.create_sheet("7SO")}
    ws_rsf, ws_ps, ws_re, ws_dj = (wb.create_sheet(n) for n in ("RAW_SF", "RAW_PS", "RAW_RE", "RAW_DJP"))

    # ---------------- RAW_SF
    rows = []
    for p in ("M1", "MTD"):
        m = d["master"][p]
        for k, nm, w, ev in zip(m["kode"], m["nama"], m["w"], m["event_date"]):
            t = tl.get(k, {})
            rows.append([p, pd.to_datetime(ev, errors="coerce").to_pydatetime() if ev else None, k, nm,
                         tampil_br(WOK2BR.get(w) if isinstance(w, str) else None), tampil_wok(w), t.get("tl_name", ""), t.get("agency", ""), "ACTIVE"])
    n_rsf = _tulis_raw(ws_rsf, ["Periode", "Snapshot", "SF Code", "Nama SF", "Branch", "WOK", "Team Leader",
                                "Agency", "Status"], rows, [10, 12, 15, 30, 14, 24, 28, 36, 10])
    for r in range(2, n_rsf + 1):
        ws_rsf.cell(row=r, column=2).number_format = "yyyy-mm-dd"

    # ---------------- RAW_PS / RAW_RE
    n_trx = {}
    for ws, basis, ts in ((ws_ps, "is_ps", "ps_ts"), (ws_re, "is_re", "re_ts")):
        rows = []
        for p in ("M1", "MTD"):
            o = d["ord"][p]
            o = o[o[basis]].sort_values(["sf", ts])
            for r in o.itertuples(index=False):
                v = getattr(r, ts)
                rows.append([p, r.sf, r.nama, r.order_id, None if pd.isna(v) else v.to_pydatetime(),
                             r.order_status or "", r.kab, tampil_wok(r.w), tampil_br(WOK2BR.get(r.w) if isinstance(r.w, str) else None),
                             r.channel_group or "", r.product_commercial_name or ""])
        n_trx[basis] = _tulis_raw(ws, ["Periode", "SF Code", "Nama SF", "Order ID", ts.replace("_ts", "").upper() + " TS",
                                       "Order Status", "Kabupaten", "WOK Baru", "Branch Baru", "Channel", "Produk"],
                                  rows, [10, 15, 28, 30, 19, 14, 18, 24, 14, 10, 34])
        for r in range(2, n_trx[basis] + 1):
            ws.cell(row=r, column=5).number_format = "yyyy-mm-dd hh:mm:ss"

    # ---------------- RAW_DJP
    nama_sf = {}
    for p in ("M1", "MTD"):
        nama_sf.update({k: n for k, n in zip(d["ord"][p]["sf"], d["ord"][p]["nama"]) if k and n})
    for p in ("M1", "MTD"):
        nama_sf.update({k: n for k, n in zip(d["master"][p]["kode"], d["master"][p]["nama"]) if n})
    sumber = {p: ("homepass SELA (CHECKOUT)" if c5._dari_export() and os.environ.get(f"SFO_DJP_SUMBER_{p}") == "SELA"
                  else "djp_daily_user_detailed") for p in ("M1", "MTD")}
    rows = []
    for p in ("M1", "MTD"):
        dj = d["djp"][p].copy()
        dj["br"] = dj["w"].map(lambda w: WOK2BR.get(w) if isinstance(w, str) else None)
        f_odp_sf = _flag_first(dj[["sf", "odp_name"]])
        f_hari = _flag_first(dj[["sf", "tugas_date"]])
        f_sf = _flag_first(dj[["sf"]])
        f_wok = _flag_first(dj[["w", "odp_name"]].fillna("-"))
        f_br = _flag_first(dj[["br", "odp_name"]].fillna("-"))
        f_reg = _flag_first(dj[["odp_name"]])
        odp_ok = dj["odp_name"].notna().tolist()
        src = sumber[p]
        for i, r in enumerate(dj.itertuples(index=False)):
            ok = odp_ok[i]                               # ODP kosong tidak dihitung ODP Visited (= nunique)
            rows.append([p, src, r.sf, nama_sf.get(r.sf, ""),
                         None if pd.isna(r.tugas_date) else r.tugas_date.to_pydatetime(),
                         r.odp_name if ok else "", 1,
                         f_odp_sf[i] * ok, f_hari[i], tampil_br(r.br), tampil_wok(r.w), f_sf[i],
                         f_wok[i] * ok, f_br[i] * ok, f_reg[i] * ok])
    n_dj = _tulis_raw(ws_dj, ["Periode", "Sumber", "SF Code", "Nama SF", "Tanggal", "ODP", "Kunjungan",
                              "ODP Unik (per SF)", "Hari Unik (per SF)", "Branch", "WOK", "SF Unik (Periode)",
                              "ODP Unik (WOK)", "ODP Unik (Branch)", "ODP Unik (Region)"],
                      rows, [10, 24, 15, 28, 12, 22, 10, 10, 10, 14, 24, 10, 10, 10, 10])
    for r in range(2, n_dj + 1):
        ws_dj.cell(row=r, column=5).number_format = "yyyy-mm-dd"

    # ---------------- daftar SF (per SF sheet)
    # WOK per SF, prioritas sama dengan calculator: database_sf bulan berjalan -> database_sf M1 ->
    # WOK baris ordering/DJP pertama (kabupaten / kolom wok DJP) untuk SF yang tidak ada di master.
    m1_wok = {k: w for k, w in zip(d["master"]["M1"]["kode"], d["master"]["M1"]["wok"]) if w}
    sf_w = {}
    for p in ("M1", "MTD"):
        for k in d["master"][p]["kode"]:
            sf_w[k] = None
        for src in (d["ord"][p][d["ord"][p]["sf"] != ""], d["djp"][p]):
            for k, w in zip(src["sf"], src["w"]):
                if not sf_w.get(k):
                    sf_w[k] = w
    for k in sf_w:
        sf_w[k] = d["kode2wok"].get(k) or m1_wok.get(k) or sf_w[k]
    mtd_set, m1_set = set(d["master"]["MTD"]["kode"]), set(d["master"]["M1"]["kode"])
    urut_b, urut_w = {b: i for i, b in enumerate(BRANCHES)}, {w: i for i, w in enumerate(WOKS)}
    n_ps_mtd = d["ord"]["MTD"][d["ord"]["MTD"]["is_ps"]].groupby("sf").size().to_dict()

    def status(k):
        if k in mtd_set:
            return "ACTIVE"
        return f"TIDAK ADA DI SNAPSHOT {bl_mtd.upper()}" if k in m1_set else "TIDAK ADA DI MASTER"

    daftar = sorted(sf_w, key=lambda k: (urut_b.get(WOK2BR.get(sf_w[k]), 99), urut_w.get(sf_w[k], 99),
                                         -n_ps_mtd.get(k, 0), k))

    # ---------------- sheet per SF (5SO = PS, 7SO = RE)
    R0 = 7
    last_sf = R0 + max(len(daftar), 1) - 1
    raw_ref = {"5SO": ("RAW_PS", n_trx["is_ps"], "PS"), "7SO": ("RAW_RE", n_trx["is_re"], "RE")}
    for key, ws in s_sf.items():
        raw, n_raw, basis = raw_ref[key]
        ws["A1"] = f"{key} per SF — {REGION_NAME.title()} — {rng}"
        ws["A1"].font = Font(bold=True, size=12)
        ws["A3"] = (f"{basis}, Kunjungan DJP dan ODP Visited per SF dihitung dari sheet {raw} dan RAW_DJP "
                    f"(COUNTIFS/SUMIFS). Team Leader dari mapping TL terbaru.")
        ws["A3"].font = Font(italic=True, color="6F7074")
        for i, h in enumerate(["Branch", "WOK", "SF Code", "Nama SF", "Team Leader", "Status SF"], 1):
            _hdr(ws, 5, i, h, rows=2)
        for gi, g in enumerate([basis, "KUNJUNGAN DJP", "ODP VISITED"]):
            _hdr(ws, 5, 7 + gi * 2, g, span=2)
            _hdr(ws, 6, 7 + gi * 2, lbl["M1"], fill=F_SUB)
            _hdr(ws, 6, 8 + gi * 2, lbl["MTD"], fill=F_SUB)
        for i, k in enumerate(daftar):
            r = R0 + i
            w = sf_w[k]
            vals = [tampil_br(WOK2BR.get(w) if isinstance(w, str) else None), tampil_wok(w), k, nama_sf.get(k, ""),
                    tl.get(k, {}).get("tl_name", ""), status(k)]
            for p_i, p in enumerate(("M1", "MTD")):
                vals_p = [
                    f'=COUNTIFS({raw}!$B$2:$B${n_raw},$C{r},{raw}!$A$2:$A${n_raw},"{p}")',
                    f'=COUNTIFS(RAW_DJP!$C$2:$C${n_dj},$C{r},RAW_DJP!$A$2:$A${n_dj},"{p}")',
                    f'=SUMIFS(RAW_DJP!$H$2:$H${n_dj},RAW_DJP!$C$2:$C${n_dj},$C{r},RAW_DJP!$A$2:$A${n_dj},"{p}")',
                ]
                for gi, f in enumerate(vals_p):
                    ws.cell(row=r, column=7 + gi * 2 + p_i, value=f)
            for c, v in enumerate(vals, 1):
                ws.cell(row=r, column=c, value=v)
        for col, w in zip("ABCDEFGHIJKL", [13, 24, 14, 30, 28, 26] + [13] * 6):
            ws.column_dimensions[col].width = w
        ws.row_dimensions[6].height = 30
        ws.freeze_panes = f"G{R0}"
        ws.auto_filter.ref = f"A6:L{last_sf}"

    # ---------------- REPORT 5SO / 7SO (scorecard, rumus)
    sf_rng = lambda ws_name, col: f"'{ws_name}'!${col}${R0}:${col}${last_sf}"

    def lvl_crit(sheet, level):
        """(kolom level di sheet, kriteria) — Region tanpa kriteria level."""
        col = {"per_sf": ("A", "B"), "RAW_SF": ("E", "F"), "RAW_TRX": ("I", "H"), "RAW_DJP": ("J", "K")}[sheet]
        return None if level == "Region" else (col[0] if level == "Branch" else col[1])

    rows_lvl = [("Region", REGION_NAME)]
    for b in BRANCHES:
        rows_lvl.append(("Branch", tampil_br(b)))
        rows_lvl += [("WOK", tampil_wok(w)) for w in WOKS if WOK2BR[w] == b]

    for key, ws in s_rep.items():
        raw, n_raw, basis = raw_ref[key]
        sfs = key                                            # nama sheet per SF
        metrics = (["sf_reg", "sf_aktif", "sf_prod", "prod", "sf_djp", "odp"] if key == "5SO"
                   else ["sf_djp", "odp", "djp_sf_day", "sf_aktif", "sf_prod", "prod", "sf_reg"])
        judul = {"sf_reg": "SF REGISTERED", "sf_aktif": f"SF AKTIF {basis}", "sf_prod": f"SF PRODUKTIF {basis}",
                 "prod": f"PRODUKTIVITAS {basis}", "sf_djp": "SF AKTIF DJP", "odp": "ODP VISITED",
                 "djp_sf_day": "DJP/SF/DAY"}
        n = len(metrics)
        ws["A1"] = f"{key} Scorecard {REGION_NAME.title()} — {rng}"
        ws["A1"].font = Font(bold=True, size=12)
        for r, (lb, a, b) in ((3, (lbl["M1"], lm_awal, lm_akhir)), (4, (lbl["MTD"], awal, tgl))):
            ws.cell(row=r, column=1, value=lb)
            ws.cell(row=r, column=2, value=a).number_format = "yyyy-mm-dd"
            ws.cell(row=r, column=3, value=b).number_format = "yyyy-mm-dd"
            ws.cell(row=r, column=4, value=f"=C{r}-B{r}+1")
            ws.cell(row=r, column=5, value="hari (dipakai DJP/SF/Day)")
        ws["A5"], ws["B5"] = "Jumlah metrik (n)", n
        ws["A6"], ws["B6"] = "Batas SF Produktif (trx ≥)", PROD_MIN_TRX
        H1, H2, S = 8, 9, 10
        _hdr(ws, H1, 1, "Level", rows=2)
        _hdr(ws, H1, 2, "Region / Branch / WOK", rows=2)
        col_m = {}
        for i, m in enumerate(metrics):
            c = 3 + i * 3
            col_m[m] = c
            _hdr(ws, H1, c, judul[m], span=3)
            for j, sub in enumerate([lbl["M1"], lbl["MTD"], "MoM %"]):
                _hdr(ws, H2, c + j, sub, fill=F_SUB)
        c_skor = 3 + n * 3
        _hdr(ws, H1, c_skor, "Momentum Skor", rows=2)
        _hdr(ws, H1, c_skor + 1, "Status", rows=2)
        c_b = c_skor + 2                                     # kolom bantu: total trx M1/MTD, kunjungan M1/MTD
        _hdr(ws, H1, c_b, "KOLOM BANTU", span=4)
        for j, sub in enumerate([f"Total {basis} {lbl['M1']}", f"Total {basis} MTD",
                                 f"Kunjungan DJP {lbl['M1']}", "Kunjungan DJP MTD"]):
            _hdr(ws, H2, c_b + j, sub, fill=F_SUB)

        for i, (level, nama) in enumerate(rows_lvl):
            r = S + i
            ws.cell(row=r, column=1, value=level)
            ws.cell(row=r, column=2, value=nama)

            def crit(sheet, rng_fn):
                col = lvl_crit(sheet, level)
                return "" if col is None else f",{rng_fn(col)},$B{r}"

            per_crit = (f",{sf_rng(sfs, 'A')},\"*\"" if level == "Region"
                        else f",{sf_rng(sfs, lvl_crit('per_sf', level))},$B{r}")
            rsf = lambda c: f"RAW_SF!${c}$2:${c}${n_rsf}"
            rtx = lambda c: f"{raw}!${c}$2:${c}${n_raw}"
            rdj = lambda c: f"RAW_DJP!${c}$2:${c}${n_dj}"
            odp_col = {"Region": "O", "Branch": "N", "WOK": "M"}[level]
            for p_i, p in enumerate(("M1", "MTD")):
                trx_col = "G" if p == "M1" else "H"
                dj_col = "I" if p == "M1" else "J"
                tot = L(c_b + p_i)
                vis = L(c_b + 2 + p_i)
                f = {
                    "sf_reg": f'=COUNTIFS({rsf("A")},"{p}"{crit("RAW_SF", rsf)})',
                    "sf_aktif": f'=COUNTIFS({sf_rng(sfs, trx_col)},">=1"{per_crit})',
                    "sf_prod": f'=COUNTIFS({sf_rng(sfs, trx_col)},">="&$B$6{per_crit})',
                    "prod": f'=IF({L(col_m["sf_aktif"] + p_i)}{r}=0,"",ROUND({tot}{r}/{L(col_m["sf_aktif"] + p_i)}{r},1))',
                    "sf_djp": f'=SUMIFS({rdj("L")},{rdj("A")},"{p}"{crit("RAW_DJP", rdj)})',
                    "odp": f'=SUMIFS({rdj(odp_col)},{rdj("A")},"{p}"{crit("RAW_DJP", rdj)})',
                }
                if "djp_sf_day" in col_m:
                    sd = f"{L(col_m['sf_djp'] + p_i)}{r}"
                    f["djp_sf_day"] = f'=IF({sd}=0,"",ROUND({vis}{r}/{sd}/$D${3 + p_i},1))'
                for m in metrics:
                    ws.cell(row=r, column=col_m[m] + p_i, value=f[m])
                ws.cell(row=r, column=c_b + p_i, value=f'=COUNTIFS({rtx("A")},"{p}"{crit("RAW_TRX", rtx)})')
                ws.cell(row=r, column=c_b + 2 + p_i, value=f'=COUNTIFS({rdj("A")},"{p}"{crit("RAW_DJP", rdj)})')
            moms = []
            for m in metrics:
                a, b, c = (f"{L(col_m[m] + j)}{r}" for j in range(3))
                ws[c] = f'=IF(OR({a}="",{b}="",{a}=0),"",ROUND(({b}-{a})/{a}*100,2))'
                moms.append(f"(N({c})>0)")
            sk = f"{L(c_skor)}{r}"
            ws[sk] = "=" + "+".join(moms)
            ws[f"{L(c_skor + 1)}{r}"] = (f'=IF({sk}>=$B$5-1,"OUTPERFORM",IF({sk}=$B$5-2,"ON TRACK",'
                                         f'IF({sk}=$B$5-3,"WATCH","CRITICAL")))')
            fill = F_REG if level == "Region" else F_BR if level == "Branch" else None
            for c in range(1, c_b + 4):
                x = ws.cell(row=r, column=c)
                x.border = B_THIN
                if fill:
                    x.fill, x.font = fill, Font(bold=True)
        last = S + len(rows_lvl) - 1
        ws.cell(row=last + 2, column=1, value=(
            "Momentum Skor = jumlah metrik dengan MoM > 0 (>= n-1 OUTPERFORM, n-2 ON TRACK, n-3 WATCH, sisanya "
            f"CRITICAL). SF Registered dari RAW_SF; ODP Visited & SF Aktif DJP dari RAW_DJP; SF Aktif/Produktif "
            f"dari sheet {sfs}; total {basis} dari {raw}. SF dummy tidak dihitung."
            + (f" {sf_rules.sf_override_note(f'{awal:%Y%m}')}." if sf_rules.sf_override_note(f"{awal:%Y%m}") else "")))
        ws.column_dimensions["A"].width = 18
        ws.column_dimensions["B"].width = 30
        for c in range(3, c_b + 4):
            ws.column_dimensions[L(c)].width = 13
        ws.row_dimensions[H2].height = 30
        ws.freeze_panes = f"C{S}"

    # ---------------- GAMBAR
    for key, ws in s_img.items():
        png, cap = (gambar or {}).get(key, (None, ""))
        baris = (cap or "").replace("*", "").splitlines()
        for i, t in enumerate(baris, 1):
            ws.cell(row=i, column=1, value=t)
        ws.cell(row=len(baris) + 2, column=1,
                value="Catatan: gambar = angka tetap dari data per tanggal laporan (bukan rumus); "
                      f"versi rumus ada di sheet REPORT {key}.").font = Font(italic=True, color="6F7074")
        ws.column_dimensions["A"].width = 120
        if png is not None:
            try:
                png.seek(0)
                img = XLImage(BytesIO(png.read()))
                k = min(1.0, 1500 / img.width)
                img.width, img.height = img.width * k, img.height * k
                ws.add_image(img, f"A{len(baris) + 4}")
            except Exception as e:
                logger.warning("sfo raw: gambar %s gagal disisipkan: %s", key, e)

    wb.calculation.fullCalcOnLoad = True              # rumus tanpa nilai cache -> hitung saat dibuka
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"5SO 7SO per SF + RAW {tgl:%d-%m-%Y}.xlsx"
    info = {"n_sf": len(daftar), "n_sf_mtd": len(mtd_set), "n_ps": n_trx["is_ps"] - 1, "n_re": n_trx["is_re"] - 1,
            "n_djp": n_dj - 1, "tl_kosong": sum(1 for k in daftar if not tl.get(k, {}).get("tl_name"))}
    return buf, fname, info
