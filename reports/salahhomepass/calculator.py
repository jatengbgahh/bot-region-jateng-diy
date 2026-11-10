"""
calculator_salahhomepass.py — Monitoring RE : Fallout Salah Tagging/Salah Homepass
per WOK/BRANCH/REGION IndiHome Jateng-DIY.
Periode: MtD (tanggal 1 bulan berjalan s/d tgl_closing), MoM vs tanggal yang
sama bulan lalu. Source: indihome_ordering_detail_YYYYMM (db.query_re_fallout).

RE          = COUNT baris re_ts valid dalam periode, order_type='NEW SALES'
RE Fallout  = RE di atas dengan fallout_reason mengandung "SALAH TAGGING"
              atau "SALAH HOMEPASS" (substring, fallout_reason adalah string
              gabungan bebas format, bukan kategori bersih)
Dipecah per channel: AGENCY (channel_group='AGENCY') vs NON AGENCY (selain
itu) vs ALL CHANNEL (gabungan keduanya).

% Salah Tagging/Homepass = RE Fallout / RE pada channel yang sama * 100
MoM = growth RE Fallout (bukan RE) bulan ini vs bulan lalu, per channel.

Base count dihitung per WOK, BRANCH & REGION = SUM base count WOK-WOK
anggotanya (konsisten dengan calculator_homepass.py) — pct/MoM branch &
region dihitung ulang dari base count yang sudah dijumlah, bukan rata-rata
angka WOK.
"""

import calendar
import logging
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import db
from config import (
    WOK_TO_BRANCH_BARU, BRANCH_ORDER, WOK_ORDER_BARU, REGION_NAME,
    WOK_TO_BRANCH as WOK_TO_BRANCH_LAMA, WOK_ORDER as WOK_ORDER_LAMA,
)


def _acuan_wok(wok_lama: bool):
    """(WOK_TO_BRANCH, WOK_ORDER) — struktur WOK lama (16 WOK) atau baru (14 WOK)."""
    if wok_lama:
        return WOK_TO_BRANCH_LAMA, WOK_ORDER_LAMA
    return WOK_TO_BRANCH_BARU, WOK_ORDER_BARU

logger = logging.getLogger(__name__)

CHANNELS = ["AGENCY", "NON AGENCY"]


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["wok"]     = df["wok"].astype(str).str.strip().str.upper()
    df["branch"]  = df["branch"].astype(str).str.strip().str.upper()
    df["channel"] = df["channel"].astype(str).str.strip().str.upper()
    df["re_trx"]     = pd.to_numeric(df["re_trx"], errors="coerce").fillna(0).astype(int)
    df["re_fallout"] = pd.to_numeric(df["re_fallout"], errors="coerce").fillna(0).astype(int)
    return df


def _base_counts(df: pd.DataFrame, wok: str) -> dict:
    """re_trx & re_fallout per channel (AGENCY/NON AGENCY) untuk 1 WOK."""
    b = {f"{ch}_trx": 0 for ch in CHANNELS}
    b.update({f"{ch}_fallout": 0 for ch in CHANNELS})
    if df.empty:
        return b
    sub = df[df["wok"] == wok]
    for ch in CHANNELS:
        row = sub[sub["channel"] == ch]
        b[f"{ch}_trx"]     = int(row["re_trx"].sum())
        b[f"{ch}_fallout"] = int(row["re_fallout"].sum())
    return b


def _sum_counts(rows: list) -> dict:
    keys = [f"{ch}_trx" for ch in CHANNELS] + [f"{ch}_fallout" for ch in CHANNELS]
    return {k: sum(r.get(k, 0) for r in rows) for k in keys}


def _pct(part, total):
    return round(part / total * 100, 2) if total else 0.0


def _growth(cur, prev):
    """
    MoM dalam persen — SELALU persen, tidak pernah "-" atau angka absolut.

    Kalau bulan lalu 0/kosong, pembagian normal mustahil (bagi nol), jadi
    basisnya dianggap 1: 0 -> 1 = +100%, 0 -> 3 = +300%. Cara ini tetap
    memperlihatkan besaran lonjakannya (0->3 lebih parah dari 0->1), beda
    dengan kalau semuanya dipukul rata +100%.
    Kalau dua-duanya 0 -> 0.0% (tidak ada perubahan).
    """
    if prev:
        return round((cur - prev) / prev * 100, 1)
    if cur:
        return round(cur * 100.0, 1)
    return 0.0


def _derived(now: dict, prev: dict) -> dict:
    re_now  = sum(now[f"{ch}_trx"] for ch in CHANNELS)
    re_prev = sum(prev[f"{ch}_trx"] for ch in CHANNELS)
    fallout_now  = sum(now[f"{ch}_fallout"] for ch in CHANNELS)
    fallout_prev = sum(prev[f"{ch}_fallout"] for ch in CHANNELS)

    row = {
        "re_mtd": re_now,
        "re_mom": _growth(re_now, re_prev),
        "all_mtd": fallout_now,
        "all_pct": _pct(fallout_now, re_now),
        "all_mom": _growth(fallout_now, fallout_prev),
    }
    for ch, key in (("AGENCY", "agency"), ("NON AGENCY", "nonagency")):
        row[f"{key}_mtd"] = now[f"{ch}_fallout"]
        row[f"{key}_pct"] = _pct(now[f"{ch}_fallout"], now[f"{ch}_trx"])
        row[f"{key}_mom"] = _growth(now[f"{ch}_fallout"], prev[f"{ch}_fallout"])
    return row


def _top(rows: list, key: str):
    """Nama row dengan nilai `key` terbesar (skip None)."""
    kandidat = [r for r in rows if r.get(key) is not None]
    if not kandidat:
        return None
    return max(kandidat, key=lambda r: r[key])["name"]




def hitung_salah_homepass(tgl_closing: date, wok_lama: bool = False) -> dict:
    """
    Query & hitung Monitoring RE Fallout Salah Tagging/Homepass MtD s/d
    tgl_closing, MoM vs tanggal sama bulan lalu.
    Return dict siap pakai untuk renderer_salahhomepass.render_salah_homepass().
    """
    WOK_TO_BRANCH, WOK_ORDER = _acuan_wok(wok_lama)
    awal_ini   = tgl_closing.replace(day=1)
    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_mtd_lalu = min(tgl_closing.day, hari_max_lalu)
    akhir_lalu    = date(bulan_lalu.year, bulan_lalu.month, hari_mtd_lalu)

    rows_now  = db.query_re_fallout(awal_ini, tgl_closing, wok_lama=wok_lama)
    rows_prev = db.query_re_fallout(awal_lalu, akhir_lalu, wok_lama=wok_lama)

    # Pengaman: kalau bulan ini ada data tapi bulan lalu kosong melompong, itu
    # hampir pasti masalah pengambilan data (bukan benar-benar nol sebulan
    # penuh). Kalau diteruskan, semua pembagi jadi 0 dan MoM meledak jadi angka
    # ngawur (mis. +905900%) yang kelihatan seperti angka beneran.
    if rows_now and not rows_prev:
        raise RuntimeError(
            f"Data pembanding MoM ({awal_lalu} s/d {akhir_lalu}) kosong, "
            f"padahal bulan ini ada {len(rows_now)} baris. "
            f"Laporan dibatalkan supaya MoM-nya tidak salah."
        )

    df_now  = _prep(pd.DataFrame(rows_now)  if rows_now  else pd.DataFrame())
    df_prev = _prep(pd.DataFrame(rows_prev) if rows_prev else pd.DataFrame())

    semua_wok_raw = (
        set(df_now["wok"].unique()  if not df_now.empty  else []) |
        set(df_prev["wok"].unique() if not df_prev.empty else [])
    )
    wok_dikenal = {w.upper() for w in WOK_ORDER}
    wok_asing   = semua_wok_raw - wok_dikenal
    if wok_asing:
        logger.warning(f"[salahhomepass] WOK tidak dikenal, dilewati: {sorted(wok_asing)}")
    semua_wok = sorted(semua_wok_raw & wok_dikenal)

    def branch_of(wok: str) -> str:
        return WOK_TO_BRANCH.get(wok, "LAINNYA")

    wok_rows  = []
    wok_now, wok_prev = {}, {}
    for wok in semua_wok:
        base_now  = _base_counts(df_now,  wok)
        base_prev = _base_counts(df_prev, wok)
        wok_now[wok]  = base_now
        wok_prev[wok] = base_prev
        wok_rows.append({
            "level": "WOK", "name": wok, "branch": branch_of(wok),
            **_derived(base_now, base_prev),
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    branch_rows = []
    for branch in branch_names:
        member_woks = [r["name"] for r in wok_rows if r["branch"] == branch]
        if not member_woks:
            continue
        base_now  = _sum_counts([wok_now[w]  for w in member_woks])
        base_prev = _sum_counts([wok_prev[w] for w in member_woks])
        branch_rows.append({
            "level": "BRANCH", "name": branch,
            **_derived(base_now, base_prev),
        })

    reg_now  = _sum_counts(list(wok_now.values()))
    reg_prev = _sum_counts(list(wok_prev.values()))
    reg_row = {
        "level": "REGION", "name": REGION_NAME,
        **_derived(reg_now, reg_prev),
    }

    top_alerts = {
        "branch": {
            "re":  _top(branch_rows, "all_mtd"),
            "pct": _top(branch_rows, "all_pct"),
            "mom": _top(branch_rows, "all_mom"),
        },
        "wok": {
            "re":  _top(wok_rows, "all_mtd"),
            "pct": _top(wok_rows, "all_pct"),
            "mom": _top(wok_rows, "all_mom"),
        },
    }

    return {
        "tgl_closing": tgl_closing,
        "awal_ini": awal_ini,
        "period_label": f"{awal_ini.day}-{tgl_closing.day} {tgl_closing.strftime('%B %Y')}",
        "region": reg_row,
        "branches": branch_rows,
        "woks": wok_rows,
        "top_alerts": top_alerts,
    }


def export_raw_xlsx(tgl_closing: date, wok_lama: bool = False) -> tuple:
    """
    Export data mentah (row-level, belum diagregasi, HANYA baris fallout
    "SALAH TAGGING"/"SALAH HOMEPASS") dari indihome_ordering_detail untuk
    Monitoring RE Fallout Salah Tagging/Homepass — bulan berjalan (MtD s/d
    tgl_closing) + bulan lalu (periode sama, untuk pembanding MoM), supaya
    bisa dicek manual (kolom & filter sama seperti "Monitor Salah Tagging.sql"
    di folder Willy). Digabung jadi 1 file .xlsx (sheet "MTD" & "MoM Lalu")
    biar langsung bisa dilihat tanpa perlu extract zip.
    Return (xlsx_bytes, xlsx_filename).
    """
    import io

    awal_ini   = tgl_closing.replace(day=1)
    bulan_lalu = tgl_closing - relativedelta(months=1)
    awal_lalu  = bulan_lalu.replace(day=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_mtd_lalu = min(tgl_closing.day, hari_max_lalu)
    akhir_lalu    = date(bulan_lalu.year, bulan_lalu.month, hari_mtd_lalu)

    rows_now  = db.query_re_fallout_raw(awal_ini, tgl_closing, wok_lama=wok_lama)
    rows_prev = db.query_re_fallout_raw(awal_lalu, akhir_lalu, wok_lama=wok_lama)

    if not rows_now and not rows_prev:
        raise ValueError("Tidak ada data untuk diekspor")

    def _to_df(rows: list) -> pd.DataFrame:
        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(str)
        return df

    tgl_str = tgl_closing.strftime("%Y%m%d")
    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        _to_df(rows_now).to_excel(writer, sheet_name="MTD", index=False)
        _to_df(rows_prev).to_excel(writer, sheet_name="MoM Lalu", index=False)
    xlsx_buf.seek(0)

    xlsx_name = f"salah_tagging_raw_{tgl_str}.xlsx"
    logger.info(
        f"Export raw salah_tagging selesai: {len(rows_now)} baris MtD, "
        f"{len(rows_prev)} baris bulan lalu -> {xlsx_name}"
    )
    return xlsx_buf.read(), xlsx_name


# ── Report ke-2: Kontributor SF Salah Tagging / Salah Homepass ───────────────
# Format mengikuti "Willy/Report SF Kontributor Salah Homepass 1-14 Juli 2026.xlsx":
#   sheet "Table Report SF" -> rekap per SF (Branch, WOK, SF Code, SF Name, jumlah)
#   sheet "Detail Order"    -> raw order-nya (Order ID, RE Timestamp, Branch, WOK,
#                              Channel Group, SF Code, SF Name, Fallout Reason)
SHEET_REPORT = "Table Report SF"
SHEET_DETAIL = "Detail Order"

DETAIL_HEADERS = [
    "Order ID", "RE Timestamp", "Branch", "WOK",
    "Channel Group", "SF Code", "SF Name", "Fallout Reason",
]
DETAIL_WIDTHS = [31, 21, 16, 26, 17, 17, 31, 70]

REPORT_HEADERS = ["Branch", "WOK", "SF Code", "SF Name", "Order Salah Homepass"]
REPORT_WIDTHS  = [18, 28, 18, 34, 23]


def export_sf_kontributor_xlsx(tgl_closing: date, wok_lama: bool = False) -> tuple:
    """
    Report ke-2 /salahtagging — Kontributor SF Salah Tagging / Salah Homepass,
    dikirim sebagai 1 file Excel dengan 2 sheet (format & judul mengikuti file
    contoh di folder Willy):

      - "Table Report SF" : rekap jumlah order salah tagging/homepass per SF
                            (Branch, WOK, SF Code, SF Name, Order Salah Homepass),
                            diurutkan dari kontributor terbanyak.
      - "Detail Order"    : raw order-nya (sumber angka di Table Report SF).

    Periode: MtD tanggal 1 s/d tgl_closing. Return (xlsx_bytes, xlsx_filename).
    """
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    awal_ini = tgl_closing.replace(day=1)
    rows = db.query_re_fallout_raw(awal_ini, tgl_closing, wok_lama=wok_lama)
    if not rows:
        raise ValueError("Tidak ada data kontributor SF untuk diekspor")

    df = pd.DataFrame(rows)
    for kol in ("sf_code", "sf_name", "branch", "wok", "channel_group", "fallout_reason", "order_id"):
        if kol not in df.columns:
            df[kol] = ""
    df["sf_code"] = df["sf_code"].fillna("").astype(str).str.strip()
    df["sf_name"] = df["sf_name"].fillna("").astype(str).str.strip()

    # Order tanpa sf_code dibuang — report ini soal KONTRIBUTOR SF, order yang
    # tidak ter-tag SF tidak bisa ditagihkan ke siapa pun. Dibuang dari rekap
    # DAN dari sheet Detail Order (raw), sesuai permintaan.
    # NB: akibatnya total di file ini bisa lebih kecil dari angka fallout di
    # gambar /salahtagging (gambar tetap menghitung semua order).
    n_semua = len(df)
    df = df[df["sf_code"] != ""].copy()
    n_tanpa_sf = n_semua - len(df)
    if df.empty:
        raise ValueError(
            f"Semua {n_semua} order fallout tidak punya sf_code — tidak ada kontributor SF untuk dilaporkan"
        )

    # ── Rekap per SF ────────────────────────────────────────────────────────
    # Dikelompokkan per (branch, wok, sf_code) — BUKAN per sf_code saja lalu
    # branch/wok diambil "first". Kalau pakai "first", SF yang ordernya tersebar
    # di beberapa WOK akan ditumpuk jadi 1 baris dan dilabeli WOK mana pun yang
    # kebetulan urutan pertama (pernah kejadian: 26 order tanpa SF dari 13 WOK
    # semuanya terlabel TEGAL BREBES). Dengan cara ini, SF lintas WOK muncul
    # sebagai baris terpisah per WOK — labelnya selalu jujur.
    df["_sf_name"] = df["sf_name"].replace("", "-")

    rekap = (
        df.groupby(["branch", "wok", "sf_code"], dropna=False)
          .agg(sf_name=("_sf_name", "first"), jumlah=("sf_code", "size"))
          .reset_index()
    )
    rekap = rekap.sort_values(["jumlah", "sf_name"], ascending=[False, True])

    # ── Tulis workbook ──────────────────────────────────────────────────────
    bulan_label = f"1-{tgl_closing.day} {tgl_closing.strftime('%B %Y')}"

    F_JUDUL  = Font(bold=True, size=12)
    F_PERIOD = Font(italic=True, size=10, color="7F7F7F")
    F_HEAD   = Font(bold=True, color="FFFFFF")
    FILL_HEAD = PatternFill("solid", fgColor="1B2A4A")
    THIN = Side(style="thin", color="BFBFBF")
    BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

    wb = Workbook()

    ws = wb.active
    ws.title = SHEET_REPORT
    ws["A1"] = "Kontributor SF : Salah Tagging / Salah Homepass"
    ws["A1"].font = F_JUDUL
    ws["E1"] = f"period : {bulan_label}"
    ws["E1"].font = F_PERIOD
    for i, (judul, lebar) in enumerate(zip(REPORT_HEADERS, REPORT_WIDTHS), start=1):
        sel = ws.cell(row=3, column=i, value=judul)
        sel.font, sel.fill, sel.alignment, sel.border = F_HEAD, FILL_HEAD, CENTER, BORDER
        ws.column_dimensions[sel.column_letter].width = lebar
    for baris, (_, r) in enumerate(rekap.iterrows(), start=4):
        for i, nilai in enumerate(
            [r["branch"], r["wok"], r["sf_code"], r["sf_name"], int(r["jumlah"])], start=1
        ):
            sel = ws.cell(row=baris, column=i, value=nilai)
            sel.border = BORDER
            if i == 5:
                sel.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:E{max(3, 3 + len(rekap))}"

    wsd = wb.create_sheet(SHEET_DETAIL)
    for i, (judul, lebar) in enumerate(zip(DETAIL_HEADERS, DETAIL_WIDTHS), start=1):
        sel = wsd.cell(row=1, column=i, value=judul)
        sel.font, sel.fill, sel.alignment, sel.border = F_HEAD, FILL_HEAD, CENTER, BORDER
        wsd.column_dimensions[sel.column_letter].width = lebar
    for baris, (_, r) in enumerate(df.iterrows(), start=2):
        re_ts = r.get("re_ts")
        wsd.cell(row=baris, column=1, value=str(r.get("order_id") or ""))
        sel_ts = wsd.cell(row=baris, column=2, value=re_ts if re_ts is not None else "")
        if re_ts is not None and not isinstance(re_ts, str):
            sel_ts.number_format = "yyyy-mm-dd hh:mm:ss"
        wsd.cell(row=baris, column=3, value=str(r.get("branch") or ""))
        wsd.cell(row=baris, column=4, value=str(r.get("wok") or ""))
        wsd.cell(row=baris, column=5, value=str(r.get("channel_group") or ""))
        wsd.cell(row=baris, column=6, value=str(r.get("sf_code") or ""))
        wsd.cell(row=baris, column=7, value=str(r.get("sf_name") or ""))
        wsd.cell(row=baris, column=8, value=str(r.get("fallout_reason") or ""))
    wsd.freeze_panes = "A2"
    wsd.auto_filter.ref = f"A1:H{max(1, len(df) + 1)}"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    nama = f"Report SF Kontributor Salah Homepass {bulan_label}.xlsx"
    logger.info(
        f"Export SF kontributor selesai: {len(rekap)} SF, {len(df)} order "
        f"({n_tanpa_sf} order tanpa sf_code dibuang) -> {nama}"
    )
    return buf.read(), nama
