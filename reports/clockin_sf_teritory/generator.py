"""
reports/clockin_sf_teritory/generator.py — generator Report Clock-in SF Teritory (100% Python).

Alur:
1. Mengambil data SF Teritory dari link SharePoint (tersimpan di storage/state/rajawali_auto.json / .env)
   menggunakan profil Chrome yang sama dengan scraping SELA (storage/sela/data/browser_profile).
2. Membaca sheet AREA 3, mengambil kolom REGION, BRANCH, WOK/CLUSTER, ID SF,
   dan memfilter baris REGION = 'JATENG'.
3. Menghitung metrik Clock-in SF Teritory dari detail-homepass_*.xlsx langsung di Python.
4. Merender HTML + SVG secara dinamis di memori, memotret elemen #paper menjadi PNG via Chrome headless,
   membuat file Excel 5 sheet dengan openpyxl, serta menyusun teks update WhatsApp/Telegram.
"""
from __future__ import annotations

import glob
import html
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta

import openpyxl
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_SF = os.path.join(BASE_DIR, "storage", "cache", "sf_teritory_jateng_cache.xlsx")
CHROME_DEFAULT = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

URL_SF_TERITORY_DEFAULT = ""

STATE_FILE = os.path.join(BASE_DIR, "storage", "state", "rajawali_auto.json")
DEFAULT_SCRAPING_DIR = os.path.join(BASE_DIR, "storage", "sela")
LEGACY_SCRAPING_DIR = r"D:\Kerjaan\hasil gabungan data"

TARGETS_REGION = {
    "Kebumen": 11,
    "Semarang": 18,
    "Batang": 18,
    "Tegal Brebes": 15,
    "Cilacap Banyumas": 9,
    "Banjarnegara": 6,
    "Magelang Temanggung": 15,
    "Boyolali": 12,
    "Demak": 11,
    "Jepara Kudus": 11,
    "Surakarta": 14,
    "Pati": 8,
    "Sragen": 11,
    "DI Yogyakarta": 40,
}

TARGET_ODP_PER_SF = 60
TARGET_HP_PER_SF = 600

CSS_PAPER = """
*{box-sizing:border-box}
body{margin:0;background:#fff;font-family:'Poppins',Arial,sans-serif;font-size:15px}
.paper{--r:#ed1846;--rd:#ba093e;--n:#001446;--ink:#414042;--g:#6f7074;--l:#cfcdce;--cr:#ffecc5;--sb:#f2f1f1;--tn:#fef1eb;--bl:#e8edf7;
 width:1200px;background:#fff;color:var(--ink);font-family:'Poppins',Arial,sans-serif;padding:36px 40px 30px;display:flex;flex-direction:column;gap:22px;border:1px solid #dedbdc}
.paper *{color-scheme:light}
.ph{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;border-bottom:3px solid var(--r);padding-bottom:14px}
.ph h3{margin:0;font-size:28px;line-height:1.2;color:var(--n);font-weight:700}
.ph p{margin:4px 0 0;font-size:14px;color:var(--g)}
.pill{background:var(--r);color:#fff;font-weight:700;font-size:14px;padding:6px 16px;border-radius:999px;white-space:nowrap}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.k{border-radius:16px;padding:14px 18px;display:flex;flex-direction:column;gap:2px}
.k .l{font-size:14px;font-weight:700;line-height:1.25}
.k .v{font-size:34px;font-weight:700;line-height:1.15;color:var(--n)}
.k .s{font-size:13px;line-height:1.35;color:var(--ink)}
.k.a{background:var(--tn)}.k.a .l{color:var(--rd)}
.k.b{background:var(--bl)}.k.b .l{color:var(--n)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:22px}
.paper .two>*{min-width:0}
.sec h4{margin:0 0 8px;font-size:16px;color:var(--n);font-weight:700}
.sec .hint{font-size:12px;color:var(--g);margin:0 0 8px}
.sec svg{max-width:100%;height:auto;display:block}
.nb{background:var(--tn);border-radius:14px;padding:12px 16px;display:flex;flex-direction:column;gap:7px}
.nb .cols{columns:2;column-gap:28px}.nb .cols .w{break-inside:avoid;margin-bottom:5px}.nb .na{border-top:1px solid #e9c9bb;padding-top:7px}
.nb h4{color:var(--rd);margin:0;font-size:15px}
.nb .w{font-size:13px;line-height:1.4;color:var(--ink)}
.nb .w b{color:var(--n)}
table.t{border-collapse:collapse;width:100%;font-size:12.5px;color:var(--ink)}
table.t th,table.t td{padding-left:6px!important;padding-right:6px!important}
table.t th{background:var(--n);color:#fff;text-align:right;padding:7px 8px;font-weight:600;white-space:nowrap}
table.t th:nth-child(-n+2){text-align:left}
table.t td{padding:6px 8px;text-align:right;border-bottom:1px solid #e5e3e4;white-space:nowrap}
table.t td:nth-child(-n+2){text-align:left}
table.t tr:nth-child(even) td{background:var(--sb)}
table.t tr.tot td{background:var(--cr);font-weight:700;border-bottom:0}
.lo{color:var(--rd);font-weight:700}
.pf{font-size:12px;color:var(--g);line-height:1.5;border-top:1px solid var(--l);padding-top:10px}
svg text{font-family:'Poppins',Arial,sans-serif}
"""


def label_mtd(tgl: date) -> str:
    """'27 Okt 2026' (format yang sama dgn teks di HTML)."""
    return f"{tgl.day} {BULAN[tgl.month - 1]} {tgl.year}"


def _folder_scraping() -> str:
    """Folder scraping SELA dari storage/state/rajawali_auto.json, default storage/sela."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8-sig") as f:
                custom = json.load(f).get("folder_scraping")
                if custom:
                    return custom
    except Exception:
        pass
    if os.path.exists(os.path.join(DEFAULT_SCRAPING_DIR, "data", "browser_profile")):
        return DEFAULT_SCRAPING_DIR
    if os.path.exists(os.path.join(LEGACY_SCRAPING_DIR, "data", "browser_profile")):
        return LEGACY_SCRAPING_DIR
    return DEFAULT_SCRAPING_DIR


def ambil_url_sf_teritory() -> str:
    """
    Ambil link SF Teritory secara dinamis (tanpa perlu restart bot):
    1. storage/state/rajawali_auto.json (kunci 'url_sf_teritory')
    2. File .env (SF_TERITORY_URL) dibaca langsung dari disk menggunakan dotenv_values()
    3. URL default SharePoint
    """
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8-sig") as f:
                val = json.load(f).get("url_sf_teritory", "").strip()
                if val:
                    return val
    except Exception:
        pass
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        try:
            from dotenv import dotenv_values
            val = (dotenv_values(env_file, interpolate=False, encoding="utf-8-sig").get("SF_TERITORY_URL") or "").strip()
            if val:
                return val
        except Exception:
            pass
    return URL_SF_TERITORY_DEFAULT


def simpan_url_sf_teritory(url: str):
    """Update link SF Teritory ke storage/state/rajawali_auto.json dan .env tanpa perlu restart bot."""
    url = url.strip()
    if not url:
        return
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    d = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8-sig") as f:
                d = json.load(f)
        except Exception:
            d = {}
    d["url_sf_teritory"] = url
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    try:
        from dotenv import set_key
        env_file = os.path.join(BASE_DIR, ".env")
        if os.path.exists(env_file):
            set_key(env_file, "SF_TERITORY_URL", url, quote_mode="never")
    except Exception:
        pass


def proses_sf_teritory(path_raw_xlsx: str, path_out_xlsx: str) -> int:
    """
    Membaca file Excel SF Teritory:
    - Mencari sheet AREA 3 / AREA3
    - Mengambil kolom REGION, BRANCH, CLUSTER/WOK, ID SF (serta NAMA jika ada)
    - Memfilter baris REGION == 'JATENG'
    - Menulis file Excel baru dengan kolom REGION, BRANCH, WOK, ID SF
    Return jumlah SF Teritory Jateng yang diproses.
    """
    wb = openpyxl.load_workbook(path_raw_xlsx, read_only=True, data_only=True)
    try:
        target_sheet = None
        for name in wb.sheetnames:
            norm = name.replace(" ", "").upper()
            if norm == "AREA3":
                target_sheet = name
                break
        if not target_sheet:
            target_sheet = wb.sheetnames[0]

        ws = wb[target_sheet]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not rows:
        raise ValueError(f"Sheet {target_sheet} di {path_raw_xlsx} kosong.")

    header = [str(c or "").strip().upper() for c in rows[0]]
    idx_reg = next((i for i, h in enumerate(header) if "REGION" in h), None)
    idx_br = next((i for i, h in enumerate(header) if "BRANCH" in h), None)
    idx_wok = next((i for i, h in enumerate(header) if "WOK" in h or "CLUSTER" in h), None)
    idx_id = next((i for i, h in enumerate(header) if "ID SF" in h or "ID_SF" in h or "KODE" in h), None)
    idx_nm = next((i for i, h in enumerate(header) if "NAMA" in h or "NAME" in h), None)

    if None in (idx_reg, idx_br, idx_wok, idx_id):
        idx_reg, idx_br, idx_wok, idx_id = 0, 1, 2, 3

    out_wb = openpyxl.Workbook()
    out_ws = out_wb.active
    out_ws.title = "AREA 3"
    out_ws.append(["REGION", "BRANCH", "WOK", "ID SF", "NAMA SF"])

    seen = set()
    count = 0
    for r in rows[1:]:
        if not r or len(r) <= max(idx_reg, idx_br, idx_wok, idx_id):
            continue
        reg = str(r[idx_reg] or "").strip().upper()
        if reg != "JATENG" and not reg.startswith("JATENG"):
            continue
        idsf = str(r[idx_id] or "").strip()
        if not idsf or idsf.upper() == "NAN" or idsf in seen:
            continue
        seen.add(idsf)
        br = str(r[idx_br] or "").strip()
        wok = str(r[idx_wok] or "").strip()
        nm = str(r[idx_nm] or "").strip() if (idx_nm is not None and len(r) > idx_nm and r[idx_nm]) else ""
        out_ws.append([reg, br, wok, idsf, nm])
        count += 1

    os.makedirs(os.path.dirname(os.path.abspath(path_out_xlsx)), exist_ok=True)
    out_wb.save(path_out_xlsx)
    return count


def unduh_sf_teritory(url: str, folder_out: str, timeout_detik: int = 45) -> str:
    """
    Unduh data SF Teritory dari link SharePoint menggunakan profil Chrome scraping SELA.
    Return path file Excel hasil filter Jateng.
    """
    from playwright.sync_api import sync_playwright

    profile_dir = os.path.join(_folder_scraping(), "data", "browser_profile")
    raw_download = os.path.join(folder_out, "raw_sf_teritory.xlsx")
    filtered_out = os.path.join(folder_out, "sf_teritory_jateng.xlsx")

    success = False
    if url and os.path.exists(profile_dir):
        dl_url = url + ("&" if "?" in url else "?") + "download=1"
        try:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    channel="chrome" if os.path.exists(CHROME_DEFAULT) else None,
                    headless=True,
                    accept_downloads=True,
                )
                try:
                    sess = os.path.join(profile_dir, "session_cookies.json")
                    if os.path.exists(sess):
                        try:
                            with open(sess, encoding="utf-8") as f:
                                ctx.add_cookies(json.load(f))
                        except Exception:
                            pass
                    page = ctx.new_page()
                    page.set_default_timeout(timeout_detik * 1000)
                    with page.expect_download(timeout=timeout_detik * 1000) as dl_info:
                        try:
                            page.goto(dl_url, wait_until="commit")
                        except Exception:
                            pass
                    dl = dl_info.value
                    dl.save_as(raw_download)
                    success = True
                finally:
                    ctx.close()
        except Exception as e:
            logger.warning(f"Gagal unduh SF Teritory via browser profile: {e}")

    # Fallback jika unduh gagal (misal profil sedang terkunci oleh proses lain)
    if not success or not os.path.exists(raw_download) or os.path.getsize(raw_download) == 0:
        cands = []
        for d in [
            os.path.join(os.path.expanduser("~"), "Downloads"),
            os.path.join(_folder_scraping(), "data", "results"),
            os.path.join(DEFAULT_SCRAPING_DIR, "data", "results"),
            os.path.join(LEGACY_SCRAPING_DIR, "data", "results"),
        ]:
            cands.extend(glob.glob(os.path.join(d, "**", "*SF Teritory*.xlsx"), recursive=True))
        if cands:
            terbaru = max(cands, key=os.path.getmtime)
            logger.info(f"Menggunakan file SF Teritory lokal terbaru: {terbaru}")
            raw_download = terbaru
        elif os.path.exists(CACHE_SF):
            logger.info(f"Menggunakan cache SF Teritory: {CACHE_SF}")
            return CACHE_SF
        else:
            raise RuntimeError("Tidak dapat mengunduh SF Teritory dari SharePoint dan tidak ada file lokal.")

    n = proses_sf_teritory(raw_download, filtered_out)
    logger.info(f"Data SF Teritory berhasil diekstrak: {n} SF Jateng-DIY -> {filtered_out}")
    try:
        os.makedirs(os.path.dirname(CACHE_SF), exist_ok=True)
        shutil.copy2(filtered_out, CACHE_SF)
    except Exception:
        pass
    return filtered_out


# ==========================================
# HELPER FORMAT & KALKULASI PYTHON
# ==========================================
def _tcase(s: str) -> str:
    return re.sub(r"\b[a-z]", lambda m: m.group(0).upper(), str(s or "").strip().lower())


def _n0(x: float | int) -> str:
    return f"{int(round(x)):,}".replace(",", ".")


def _pc(a: float | int, b: float | int) -> int:
    return int(round(a / b * 100)) if b > 0 else 0


def _pcs(a: float | int, b: float | int) -> str:
    return f"{_pc(a, b)}%" if b > 0 else "–"


def _dl(ymd_str: str) -> str:
    y, m, d = (int(p) for p in ymd_str.split("-"))
    return f"{d} {BULAN[m - 1]} {y}"


def _dshort(ymd_str: str) -> str:
    _, m, d = (int(p) for p in ymd_str.split("-"))
    return f"{d} {BULAN[m - 1]}"


def _rg_short(a: str, b: str) -> str:
    if a == b:
        return _dl(a)
    ay, am, ad = (int(p) for p in a.split("-"))
    by, bm, bd = (int(p) for p in b.split("-"))
    if ay == by and am == bm:
        return f"{ad}–{bd} {BULAN[bm - 1]} {by}"
    return f"{_dl(a)} – {_dl(b)}"


def _rb(v: float | int) -> str:
    if v >= 1000:
        val = round(v / 100) / 10
        s = f"{val:g}".replace(".", ",")
        return f"{s}rb"
    return str(int(round(v)))


def _parse_ymd(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def _load_sela_cached_names() -> dict[str, str]:
    """Muat kamus kode SF -> Nama SF dari cache mingguan SELA (_weekly_users.json) jika tersedia."""
    names: dict[str, str] = {}
    roots = [
        os.path.join(_folder_scraping(), "data", "cache_detail_sf"),
        os.path.join(DEFAULT_SCRAPING_DIR, "data", "cache_detail_sf"),
        os.path.join(LEGACY_SCRAPING_DIR, "data", "cache_detail_sf"),
    ]
    seen_dirs = set()
    files = []
    for r in roots:
        nr = os.path.normcase(os.path.abspath(r))
        if nr in seen_dirs or not os.path.isdir(r):
            continue
        seen_dirs.add(nr)
        files.extend(glob.glob(os.path.join(r, "*", "_weekly_users.json")))
    for p in sorted(files):
        try:
            with open(p, encoding="utf-8") as f:
                users = json.load(f).get("users") or []
            for u in users:
                code = str(u.get("code") or "").strip()
                nm = str(u.get("name") or "").strip()
                if code and nm:
                    names[code] = nm
        except Exception:
            pass
    return names


def _baca_data(xlsx_homepass: str, xlsx_sf: str, tgl: date | None = None) -> dict:
    """Baca file detail-homepass & daftar SF Teritory, lalu hitung seluruh agregasi report."""
    # 1. Baca detail-homepass_*.xlsx
    wb_hp = openpyxl.load_workbook(xlsx_homepass, read_only=True, data_only=True)
    try:
        ws_hp = wb_hp["Detail Homepass"] if "Detail Homepass" in wb_hp.sheetnames else wb_hp.worksheets[0]
        it_hp = ws_hp.iter_rows(values_only=True)
        hdr_hp = [str(c or "").strip() for c in next(it_hp, ())]
        req_cols = ("Kode", "Tanggal", "ODP", "Journey Status")
        if not hdr_hp or any(k not in hdr_hp for k in req_cols):
            raise RuntimeError(
                "Format tidak sesuai. Kolom Kode, Tanggal, ODP, dan Journey Status harus ada (sheet Detail Homepass)."
            )
        idx_k = hdr_hp.index("Kode")
        idx_t = hdr_hp.index("Tanggal")
        idx_o = hdr_hp.index("ODP")
        idx_j = hdr_hp.index("Journey Status")
        idx_n = hdr_hp.index("Nama SF") if "Nama SF" in hdr_hp else None

        mn, mx = "9999", "0000"
        days: dict[str, dict[str, list[int]]] = {}
        seen_odp: set[tuple[str, str, str]] = set()
        asg: dict[str, int] = {}
        nmx: dict[str, str] = {}
        bad = 0
        total_rows = 0

        for r in it_hp:
            total_rows += 1
            if not r:
                continue
            d = _parse_ymd(r[idx_t] if idx_t < len(r) else None)
            if not d:
                bad += 1
                continue
            if d < mn:
                mn = d
            if d > mx:
                mx = d
            raw_k = r[idx_k] if idx_k < len(r) else None
            k0 = str(raw_k if raw_k is not None else "").strip()
            if not k0:
                continue
            asg[k0] = asg.get(k0, 0) + 1
            if idx_n is not None and idx_n < len(r) and r[idx_n] and k0 not in nmx:
                nmx[k0] = str(r[idx_n]).strip()
            st = str(r[idx_j] if idx_j < len(r) and r[idx_j] is not None else "").strip()
            if st != "CHECKOUT":
                continue
            o_day = days.setdefault(d, {})
            e = o_day.setdefault(k0, [0, 0])
            e[1] += 1
            odp_val = str(r[idx_o] if idx_o < len(r) and r[idx_o] is not None else "")
            key = (d, k0, odp_val)
            if key not in seen_odp:
                seen_odp.add(key)
                e[0] += 1
    finally:
        wb_hp.close()

    if mx == "0000":
        raise RuntimeError("Kolom Tanggal tidak terbaca di file homepass.")

    # 2. Baca sf_teritory_jateng.xlsx + lengkapi nama SF
    sela_names = _load_sela_cached_names()
    tg_map = {k.upper(): k for k in TARGETS_REGION}
    tg_map["DAERAH ISTIMEWA YOGYAKARTA"] = "DI Yogyakarta"
    tg_map.setdefault("YOGYAKARTA", "DI Yogyakarta")

    wb_sf = openpyxl.load_workbook(xlsx_sf, read_only=True, data_only=True)
    try:
        sheet_sf = next(
            (n for n in wb_sf.sheetnames if n.replace(" ", "").upper() == "AREA3"),
            wb_sf.sheetnames[0],
        )
        rows_sf = list(wb_sf[sheet_sf].iter_rows(values_only=True))
    finally:
        wb_sf.close()

    if not rows_sf:
        raise RuntimeError("File daftar SF Teritory kosong.")

    hdr_sf = [str(c or "").strip().upper() for c in rows_sf[0]]
    col_reg = next((i for i, h in enumerate(hdr_sf) if h == "REGION" or "REGION" in h), 0)
    col_br = next((i for i, h in enumerate(hdr_sf) if h == "BRANCH" or "BRANCH" in h), 1)
    col_wok = next((i for i, h in enumerate(hdr_sf) if h in ("WOK", "CLUSTER") or "WOK" in h or "CLUSTER" in h), 2)
    col_id = next((i for i, h in enumerate(hdr_sf) if h == "ID SF" or "ID SF" in h or "ID_SF" in h), 3)
    col_nm = next((i for i, h in enumerate(hdr_sf) if "NAMA" in h or "NAME" in h), None)

    master = []
    seen_sf = set()
    for r in rows_sf[1:]:
        if not r or len(r) <= max(col_reg, col_br, col_wok, col_id):
            continue
        rg = str(r[col_reg] or "").strip().upper()
        if not rg.startswith("JATENG"):
            continue
        id_sf = str(r[col_id] or "").strip()
        if not id_sf or id_sf.upper() == "NAN" or id_sf in seen_sf:
            continue
        seen_sf.add(id_sf)
        cl_raw = str(r[col_wok] or "").strip().upper()
        wok = tg_map.get(cl_raw) or _tcase(cl_raw)
        br = _tcase(str(r[col_br] or "").strip())
        nm_excel = str(r[col_nm] or "").strip() if (col_nm is not None and len(r) > col_nm and r[col_nm]) else ""
        raw_name = nmx.get(id_sf) or nm_excel or sela_names.get(id_sf)
        nm = _tcase(raw_name) if raw_name else f"SF {id_sf}"
        master.append((id_sf, nm, br, wok))

    if not master:
        raise RuntimeError("Tidak ada baris REGION JATENG yang punya ID SF di file SF Teritory.")

    # 3. Tentukan rentang tanggal RG (from .. to)
    rg_from, rg_to = mn, mx
    if tgl is not None:
        iso = tgl.strftime("%Y-%m-%d")
        if iso >= mn and iso < mx:
            rg_to = iso

    d_start = date.fromisoformat(rg_from)
    d_end = date.fromisoformat(rg_to)
    ds = [(d_start + timedelta(days=i)).isoformat() for i in range((d_end - d_start).days + 1)]

    # 4. Hitung agregasi SF, WOK, Branch, dan Harian
    sf_map: dict[str, dict] = {}
    for k, nm, br, wok in master:
        sf_map[k] = {
            "k": k,
            "nm": nm,
            "br": br,
            "wok": wok,
            "odp": 0,
            "hp": 0,
            "hari": 0,
            "asg": asg.get(k, 0),
        }

    daily_map = {d: {"odp": 0, "hp": 0, "sf": 0} for d in ds}
    for d, o_day in days.items():
        if d < rg_from or d > rg_to:
            continue
        dm = daily_map.setdefault(d, {"odp": 0, "hp": 0, "sf": 0})
        for k, (odp_c, hp_c) in o_day.items():
            s = sf_map.get(k)
            if not s:
                continue
            s["odp"] += odp_c
            s["hp"] += hp_c
            s["hari"] += 1
            dm["odp"] += odp_c
            dm["hp"] += hp_c
            dm["sf"] += 1

    woks_dict: dict[str, dict] = {}
    for k, s in sf_map.items():
        key = f"{s['br']}|{s['wok']}"
        w = woks_dict.get(key)
        if w is None:
            w = {
                "br": s["br"],
                "wok": s["wok"],
                "tg": TARGETS_REGION.get(s["wok"], 0),
                "n": 0,
                "odp": 0,
                "hp": 0,
                "cl": 0,
                "belum": [],
                "noasg": [],
            }
            woks_dict[key] = w
        w["n"] += 1
        w["odp"] += s["odp"]
        w["hp"] += s["hp"]
        if s["odp"] > 0 or s["hp"] > 0:
            w["cl"] += 1
        elif s["asg"] == 0:
            w["noasg"].append(s)
        else:
            w["belum"].append(s)

    wl = sorted(woks_dict.values(), key=lambda w: (w["br"], w["wok"]))
    for w in wl:
        w["tOdp"] = w["n"] * TARGET_ODP_PER_SF
        w["tHp"] = w["n"] * TARGET_HP_PER_SF

    tot = {
        "tg": sum(w["tg"] for w in wl),
        "n": sum(w["n"] for w in wl),
        "odp": sum(w["odp"] for w in wl),
        "hp": sum(w["hp"] for w in wl),
        "cl": sum(w["cl"] for w in wl),
        "tOdp": sum(w["tOdp"] for w in wl),
        "tHp": sum(w["tHp"] for w in wl),
        "belum": [s for w in wl for s in w["belum"]],
        "noasg": [s for w in wl for s in w["noasg"]],
    }

    daily_list = [
        {"d": d, "odp": daily_map[d]["odp"], "hp": daily_map[d]["hp"], "sf": daily_map[d]["sf"]}
        for d in ds
    ]

    msg = (
        f"Data {os.path.basename(xlsx_homepass)} terbaca: {total_rows:,} baris, "
        f"periode {_dshort(mn)} sampai {_dl(mx)}.".replace(",", ".")
    )

    return {
        "sf": sf_map,
        "woks": wl,
        "T": tot,
        "daily": daily_list,
        "days": days,
        "rg_from": rg_from,
        "rg_to": rg_to,
        "model_from": mn,
        "model_to": mx,
        "label": os.path.basename(xlsx_homepass),
        "msg": msg,
    }


# ==========================================
# RENDERER HTML, SVG, PNG, EXCEL & TEKS WA
# ==========================================
def _chart_day(arr: list[dict], key: str, col: str, title: str, fmt) -> str:
    W, H, B, T = 578, 215, 26, 46
    n = len(arr)
    bw = (W - 10) / max(1, n)
    mx = max([1] + [x[key] for x in arr])
    rot = n > 14
    act = [x for x in arr if x[key] > 0]
    avg = sum(x[key] for x in act) / max(1, len(act))
    s = []
    for i, x in enumerate(arr):
        val = x[key]
        h = val / mx * (H - B - T)
        xx = 5 + i * bw
        y = H - B - h
        last = i == n - 1
        cx = xx + bw / 2
        op = "" if last else ' fill-opacity="0.78"'
        s.append(f'<rect x="{xx + bw * 0.14}" y="{y}" width="{bw * 0.72}" height="{max(h, 0.5)}" fill="{col}"{op}/>')
        if val > 0:
            fw = 700 if last else 400
            if rot:
                s.append(
                    f'<text transform="translate({cx + 3.5} {y - 5}) rotate(-90)" '
                    f'font-size="10" fill="#414042" font-weight="{fw}">{fmt(val)}</text>'
                )
            else:
                s.append(
                    f'<text x="{cx}" y="{y - 4}" font-size="10" fill="#414042" '
                    f'text-anchor="middle" font-weight="{fw}">{fmt(val)}</text>'
                )
        day_num = int(x["d"][8:])
        s.append(f'<text x="{cx}" y="{H - 10}" font-size="9.5" fill="#6f7074" text-anchor="middle">{day_num}</text>')
    ya = H - B - avg / mx * (H - B - T)
    s.append(
        f'<line x1="5" y1="{H - B}" x2="{W - 5}" y2="{H - B}" stroke="#6f7074"/>'
        f'<line x1="5" y1="{ya}" x2="{W - 5}" y2="{ya}" stroke="{col}" stroke-dasharray="5 4" stroke-width="1.2"/>'
    )
    return (
        f'<div class="sec"><h4>{title}</h4>'
        f'<p class="hint">Rata-rata {_n0(avg)} per hari yang ada clock-in (garis putus-putus). '
        f'Angka di bawah batang = tanggal.</p>'
        f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" aria-label="{title}">{"".join(s)}</svg></div>'
    )


def _group_sf_names(data: dict) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    sf_map = data["sf"]
    dup_n: dict[str, int] = {}
    for s in sf_map.values():
        dup_n[s["nm"]] = dup_n.get(s["nm"], 0) + 1

    def lab(s: dict, with_hp: bool) -> str:
        base = f"{s['nm']} [{s['k']}]" if dup_n.get(s["nm"], 0) > 1 else s["nm"]
        extra = f" ({_n0(s['asg'])} HP)" if (with_hp and s["asg"]) else ""
        return base + extra

    def grp(lst: list[dict], with_hp: bool) -> dict[str, list[str]]:
        g: dict[str, list[str]] = {}
        for s in lst:
            g.setdefault(s["wok"], []).append(lab(s, with_hp))
        return g

    T = data["T"]
    return grp(T["belum"], True), grp(T["belum"], False), grp(T["noasg"], False)


def build_html_teritory(data: dict) -> tuple[str, str]:
    """Return (html_str, periode_pill_text)."""
    e = html.escape
    T = data["T"]
    rg_from, rg_to = data["rg_from"], data["rg_to"]
    per = _rg_short(rg_from, rg_to)
    mtd_txt = (
        f"MTD {_dl(rg_to)}"
        if (rg_from[:7] == rg_to[:7] and rg_from[8:] == "01")
        else f"periode {per}"
    )
    t_odp, t_hp = T["tOdp"], T["tHp"]
    p_odp, p_hp = _pc(T["odp"], t_odp), _pc(T["hp"], t_hp)
    n_bel = len(T["belum"]) + len(T["noasg"])

    act_d = [x for x in data["daily"] if x["odp"] > 0 or x["hp"] > 0]
    la = act_d[-1] if act_d else None
    pa = act_d[-2] if len(act_d) >= 2 else None

    def dtx(f: str) -> str:
        if not la:
            return ""
        s = f"Hari terakhir {_dshort(la['d'])}: {_n0(la[f])}"
        if pa:
            df = la[f] - pa[f]
            arrow = "▲ " if df >= 0 else "▼ "
            s += f" ({arrow}{_n0(abs(df))} vs {_dshort(pa['d'])})"
        return s

    bw, _, nw = _group_sf_names(data)

    out = [
        "<!doctype html><html lang='id'><head><meta charset='utf-8'>",
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap'>",
        f"<style>{CSS_PAPER}</style></head><body><div class='paper' id='paper'>",
        f"<div class='ph'><div><h3>Report Clock-in SF Teritory</h3>"
        f"<p>Region Jateng-DIY · {e(mtd_txt)} · Sumber: detail homepass SELA (status CHECKOUT)</p></div>"
        f"<div class='pill'>Periode {e(per)}</div></div>",
        "<div class='kpis'>"
        f"<div class='k a'><span class='l'>SF Teritory</span><span class='v'>{_n0(T['n'])} "
        f"<span style='font-size:18px'>dari {_n0(T['tg'])}</span></span>"
        f"<span class='s'>Ach {_pc(T['n'], T['tg'])}% terhadap target SF Teritory Region</span></div>"
        f"<div class='k b'><span class='l'>SF sudah clock-in</span><span class='v'>{_n0(T['cl'])} "
        f"<span style='font-size:18px'>dari {_n0(T['n'])} SF</span></span>"
        f"<span class='s'>{n_bel} belum clock-in</span></div>"
        f"<div class='k a'><span class='l'>Clock-in ODP</span><span class='v'>{_n0(T['odp'])} "
        f"<span style='font-size:18px'>({p_odp}%)</span></span>"
        f"<span class='s'>Target {_n0(t_odp)} ({TARGET_ODP_PER_SF} ODP per SF)</span>"
        f"<span class='s'>{e(dtx('odp'))}</span></div>"
        f"<div class='k b'><span class='l'>Clock-in Homepass</span><span class='v'>{_n0(T['hp'])} "
        f"<span style='font-size:18px'>({p_hp}%)</span></span>"
        f"<span class='s'>Target {_n0(t_hp)} ({TARGET_HP_PER_SF} HP per SF)</span>"
        f"<span class='s'>{e(dtx('hp'))}</span></div></div>",
        "<div class='two'>"
        + _chart_day(data["daily"], "odp", "#ed1846", "Clock-in ODP per hari", lambda v: str(int(round(v))))
        + _chart_day(data["daily"], "hp", "#001446", "Clock-in Homepass per hari", _rb)
        + "</div>",
    ]

    def cls_lo(cond: bool) -> str:
        return ' class="lo"' if cond else ""

    def low_sf(a: int, b: int) -> bool:
        return b > 0 and _pc(a, b) < 75

    def low_ci(a: int, b: int) -> bool:
        return b > 0 and _pc(a, b) < 25

    def cells(o: dict, bl: int) -> str:
        return (
            f"<td>{o['tg']}</td>"
            f"<td>{o['n']}</td>"
            f"<td{cls_lo(low_sf(o['n'], o['tg']))}>{_pcs(o['n'], o['tg'])}</td>"
            f"<td{cls_lo(bl > 0)}>{o['cl']}</td>"
            f"<td{cls_lo(bl > 0)}>{_pcs(o['cl'], o['n'])}</td>"
            f"<td>{_n0(o['tOdp'])}</td>"
            f"<td>{_n0(o['odp'])}</td>"
            f"<td{cls_lo(low_ci(o['odp'], o['tOdp']))}>{_pcs(o['odp'], o['tOdp'])}</td>"
            f"<td>{_n0(o['tHp'])}</td>"
            f"<td>{_n0(o['hp'])}</td>"
            f"<td{cls_lo(low_ci(o['hp'], o['tHp']))}>{_pcs(o['hp'], o['tHp'])}</td>"
        )

    out.append(
        "<div class='sec'><h4>Detail per WOK</h4><table class='t'><tr><th>Branch</th><th>WOK</th>"
        "<th>Target SF</th><th>SF Real</th><th>Ach SF</th><th>SF Clockin</th><th>%SF Clockin</th>"
        "<th>Target ODP</th><th>Clock-in ODP</th><th>Ach ODP</th>"
        "<th>Target HP</th><th>Clock-in HP</th><th>Ach HP</th></tr>"
    )
    for w in data["woks"]:
        out.append(
            f"<tr><td>{e(w['br'])}</td><td>{e(w['wok'])}</td>"
            f"{cells(w, len(w['belum']) + len(w['noasg']))}</tr>"
        )
    out.append(
        f"<tr class='tot'><td>Jateng-DIY</td><td></td>{cells(T, n_bel)}</tr></table></div>"
    )

    nb = [f"<div class='nb'><h4>SF belum clock-in ({len(T['belum'])})</h4>"]
    if not T["belum"]:
        nb.append("<div class='w'>Semua SF yang sudah di-assign sudah clock-in.</div>")
    else:
        nb.append("<div class='cols'>")
        for k in sorted(bw):
            nb.append(f"<div class='w'><b>{e(k)}</b> ({len(bw[k])}): {e(', '.join(bw[k]))}</div>")
        nb.append("</div>")

    if T["noasg"]:
        noasg_str = ": " + " · ".join(
            f"{e(k)} ({len(nw[k])}): {e(', '.join(nw[k]))}" for k in sorted(nw)
        )
    else:
        noasg_str = ": semua SF sudah punya assignment homepass di SELA."
    nb.append(f"<div class='w na'><b>SF belum di-assign ({len(T['noasg'])})</b>{noasg_str}</div></div>")
    out.append("".join(nb))

    note_asg = (
        " Angka dalam kurung pada daftar SF belum clock-in = homepass yang sudah di-assign ke SF tersebut."
        if T["belum"]
        else ""
    )
    out.append(
        f"<div class='pf'>Keterangan: Target SF Teritory = target Region. Target ODP dan homepass = "
        f"SF Teritory real × target per SF ({TARGET_ODP_PER_SF} ODP dan {TARGET_HP_PER_SF} HP). "
        f"SF belum clock-in = SF yang sudah di-assign tapi tidak ada homepass berstatus CHECKOUT selama periode."
        f"{note_asg}</div></div></body></html>"
    )
    return "".join(out), f"Periode {per}"


def build_caption_teritory(data: dict) -> str:
    T = data["T"]
    rg_from, rg_to = data["rg_from"], data["rg_to"]
    per = _rg_short(rg_from, rg_to)
    mtd_txt = (
        f"MTD {_dl(rg_to)}"
        if (rg_from[:7] == rg_to[:7] and rg_from[8:] == "01")
        else f"periode {per}"
    )
    t_odp, t_hp = T["tOdp"], T["tHp"]
    p_odp, p_hp = _pc(T["odp"], t_odp), _pc(T["hp"], t_hp)
    n_bel = len(T["belum"]) + len(T["noasg"])
    _, bwn, nw = _group_sf_names(data)

    wa_x = ""
    if T["belum"]:
        wa_x += "\n\nSF Teritory yang belum clock-in:\n" + "\n".join(
            f"- {k}: {', '.join(bwn[k])}" for k in sorted(bwn)
        )
    if T["noasg"]:
        wa_x += "\n\nSF Teritory yang belum di-assign homepass:\n" + "\n".join(
            f"- {k}: {', '.join(nw[k])}" for k in sorted(nw)
        )

    return (
        f"Dear kakak-kakak Agency terbaik, berikut kami share update clock-in SF Teritory {mtd_txt} via SELA.\n\n"
        f"Update Region Jateng-DIY\n"
        f"- {T['n']} SF Teritory dari target {T['tg']} ({_pc(T['n'], T['tg'])}%)\n"
        f"- Clock-in ODP {_n0(T['odp'])} dari target {_n0(t_odp)} ({p_odp}%)\n"
        f"- Clock-in homepass {_n0(T['hp'])} dari target {_n0(t_hp)} ({p_hp}%)\n"
        f"- {T['cl']} SF Teritory sudah clock-in, masih ada {n_bel} SF yang belum clock-in sama sekali"
        f"{wa_x}"
    )


def render_png_teritory(html_str: str, out_png: str, timeout_ms: int = 60000) -> str:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="clockin_teritory_html_") as d:
        p_html = os.path.join(d, "report.html")
        with open(p_html, "w", encoding="utf-8") as f:
            f.write(html_str)
        with sync_playwright() as p:
            kw = {"channel": "chrome"} if os.path.exists(CHROME_DEFAULT) else {}
            b = p.chromium.launch(headless=True, **kw)
            try:
                page = b.new_page(viewport={"width": 1280, "height": 1000}, device_scale_factor=2)
                page.set_default_timeout(timeout_ms)
                try:
                    page.goto("file:///" + p_html.replace("\\", "/"), wait_until="networkidle", timeout=20000)
                except Exception:
                    pass
                page.evaluate("document.fonts && document.fonts.ready")
                png_bytes = page.locator("#paper").screenshot(type="png")
            finally:
                b.close()
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    with open(out_png, "wb") as f:
        f.write(png_bytes)
    return out_png


def write_excel_teritory(data: dict, out_xlsx: str) -> str:
    T = data["T"]
    rg_from, rg_to = data["rg_from"], data["rg_to"]
    wb = Workbook()

    def _add_sheet(ws, aoa: list[list], widths: list[int], pct_cols: tuple[int, ...] = (), start_pct_row: int = 1):
        for r in aoa:
            ws.append(r)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for r_idx in range(start_pct_row, len(aoa) + 1):
            for c_idx in pct_cols:
                cell = ws.cell(row=r_idx, column=c_idx)
                if isinstance(cell.value, (int, float)):
                    cell.number_format = "0%"

    def _pr(a: int | float, b: int | float):
        return a / b if b > 0 else ""

    # Sheet 1: Ringkasan WOK
    ws1 = wb.active
    ws1.title = "Ringkasan WOK"
    info = [
        ["Report Clock-in SF Teritory — Jateng-DIY"],
        [f"Periode {_dl(rg_from)} sampai {_dl(rg_to)} · sumber {data['label']} · clock-in = status CHECKOUT"],
        ["Target SF Teritory: Region"],
        ["Target clock-in ODP per SF", TARGET_ODP_PER_SF],
        ["Target clock-in Homepass per SF", TARGET_HP_PER_SF],
        [],
    ]
    hd1 = [
        "Branch", "WOK", "Target SF", "SF Real", "Ach SF", "SF Clockin", "%SF Clockin",
        "Target ODP", "Clock-in ODP", "Ach ODP", "Target HP", "Clock-in HP", "Ach HP",
    ]
    rows1 = [
        [
            w["br"], w["wok"], w["tg"], w["n"], _pr(w["n"], w["tg"]),
            w["cl"], _pr(w["cl"], w["n"]), w["tOdp"], w["odp"], _pr(w["odp"], w["tOdp"]),
            w["tHp"], w["hp"], _pr(w["hp"], w["tHp"]),
        ]
        for w in data["woks"]
    ]
    rows1.append([
        "TOTAL JATENG-DIY", "", T["tg"], T["n"], _pr(T["n"], T["tg"]),
        T["cl"], _pr(T["cl"], T["n"]), T["tOdp"], T["odp"], _pr(T["odp"], T["tOdp"]),
        T["tHp"], T["hp"], _pr(T["hp"], T["tHp"]),
    ])
    widths1 = [14, 22] + [14] * 11
    _add_sheet(ws1, info + [hd1] + rows1, widths1, pct_cols=(5, 7, 10, 13), start_pct_row=len(info) + 2)

    # Sheet 2: Detail SF Teritory
    ws2 = wb.create_sheet("Detail SF Teritory")
    d_rows = [[
        "Branch", "WOK", "Nama SF Teritory", "Kode SF", "Hari clock-in",
        "Clock-in ODP", "Ach ODP", "Clock-in Homepass", "Ach Homepass", "Status",
    ]]
    sorted_sfs = sorted(
        data["sf"].values(),
        key=lambda s: (s["br"], s["wok"], -s["odp"]),
    )
    for s in sorted_sfs:
        status = (
            "Sudah clock-in"
            if (s["odp"] > 0 or s["hp"] > 0)
            else ("Belum di-assign" if s["asg"] == 0 else "Belum clock-in")
        )
        d_rows.append([
            s["br"], s["wok"], s["nm"], s["k"], s["hari"],
            s["odp"], s["odp"] / TARGET_ODP_PER_SF,
            s["hp"], s["hp"] / TARGET_HP_PER_SF,
            status,
        ])
    _add_sheet(ws2, d_rows, [14, 22, 32, 14, 12, 13, 10, 17, 13, 16], pct_cols=(7, 9), start_pct_row=2)

    # Sheet 3: SF Belum Clock-in
    ws3 = wb.create_sheet("SF Belum Clock-in")
    b_rows = [["Branch", "WOK", "Nama SF Teritory", "Kode SF", "Homepass ter-assign", "Status"]]
    for s in T["belum"]:
        b_rows.append([s["br"], s["wok"], s["nm"], s["k"], s["asg"], "Belum clock-in"])
    for s in T["noasg"]:
        b_rows.append([s["br"], s["wok"], s["nm"], s["k"], 0, "Belum di-assign"])
    _add_sheet(ws3, b_rows, [14, 22, 32, 14, 20, 22])

    # Sheet 4: Harian SF Teritory
    ws4 = wb.create_sheet("Harian SF Teritory")
    h_rows = [["Tanggal", "Branch", "WOK", "Nama SF Teritory", "Kode SF", "Clock-in ODP", "Clock-in Homepass"]]
    for dt in sorted(data["days"]):
        if dt < rg_from or dt > rg_to:
            continue
        o_day = data["days"][dt]
        for k, (odp_c, hp_c) in o_day.items():
            s = data["sf"].get(k)
            if s:
                h_rows.append([dt, s["br"], s["wok"], s["nm"], k, odp_c, hp_c])
    _add_sheet(ws4, h_rows, [12, 14, 22, 32, 14, 13, 17])

    # Sheet 5: Harian Region
    ws5 = wb.create_sheet("Harian Region")
    g_rows = [["Tanggal", "SF clock-in", "Clock-in ODP", "Clock-in Homepass"]]
    for x in data["daily"]:
        g_rows.append([x["d"], x["sf"], x["odp"], x["hp"]])
    _add_sheet(ws5, g_rows, [12, 12, 14, 18])

    os.makedirs(os.path.dirname(os.path.abspath(out_xlsx)), exist_ok=True)
    wb.save(out_xlsx)
    return out_xlsx


def buat_report(
    xlsx_homepass: str,
    tgl: date = None,
    folder_out: str = None,
    timeout_detik: int = 240,
    url_sf: str = None,
) -> dict:
    """
    xlsx_homepass : detail-homepass_*.xlsx (sheet 'Detail Homepass': Kode, Tanggal, ODP, Journey Status)
    tgl           : batas akhir periode (None = semua tanggal di file). MTD = awal data s/d tgl.
    url_sf        : link SharePoint SF Teritory (opsional, default ambil_url_sf_teritory())
    Return dict: png (path), xlsx (path), teks (caption WhatsApp/Telegram), periode, ringkasan {angka-angka KPI}.
    """
    folder_out = folder_out or tempfile.mkdtemp(prefix="clockin_")
    os.makedirs(folder_out, exist_ok=True)

    # 1. Unduh dan filter data SF Teritory dari SharePoint (atau cache lokal)
    link = url_sf or ambil_url_sf_teritory()
    xlsx_sf = unduh_sf_teritory(link, folder_out, timeout_detik=45)

    # 2. Kalkulasi langsung di Python
    data = _baca_data(xlsx_homepass, xlsx_sf, tgl=tgl)
    html_str, periode = build_html_teritory(data)
    teks = build_caption_teritory(data)

    c = lambda s: s.replace("-", "")
    stamp = (
        c(data["rg_to"])
        if data["rg_from"] == data["model_from"]
        else f"{c(data['rg_from'])}-{c(data['rg_to'])}"
    )
    out_png = os.path.join(folder_out, f"Report_Clockin_SF_Teritory_{stamp}.png")
    out_xlsx = os.path.join(folder_out, f"Report_Clockin_SF_Teritory_{stamp}.xlsx")

    # 3. Render PNG & tulis Excel
    render_png_teritory(html_str, out_png, timeout_ms=timeout_detik * 1000)
    write_excel_teritory(data, out_xlsx)

    return {
        "png": out_png,
        "xlsx": out_xlsx,
        "teks": teks,
        "periode": periode,
        "ringkasan": _ringkas(teks),
        "pesan_halaman": data["msg"],
        "sf_file": xlsx_sf,
    }


def _ringkas(teks: str) -> dict:
    """Angka KPI dari teks (untuk log & uji)."""
    def n(s):
        return int(s.replace(".", ""))

    r = {}
    m = re.search(r"- (\d+) SF Teritory dari target (\d+) \((\d+)%\)", teks)
    if m:
        r.update(sf=int(m[1]), target_sf=int(m[2]), ach_sf=int(m[3]))
    m = re.search(r"Clock-in ODP ([\d.]+) dari target ([\d.]+) \((\d+)%\)", teks)
    if m:
        r.update(odp=n(m[1]), target_odp=n(m[2]), ach_odp=int(m[3]))
    m = re.search(r"Clock-in homepass ([\d.]+) dari target ([\d.]+) \((\d+)%\)", teks)
    if m:
        r.update(hp=n(m[1]), target_hp=n(m[2]), ach_hp=int(m[3]))
    m = re.search(r"- (\d+) SF Teritory sudah clock-in, masih ada (\d+) SF", teks)
    if m:
        r.update(sudah=int(m[1]), belum=int(m[2]))
    return r


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Uji generator Clock-in SF Teritory")
    ap.add_argument("xlsx", help="File detail-homepass_*.xlsx")
    ap.add_argument("--tanggal", help="DD-MM-YYYY (batas akhir MTD)")
    ap.add_argument("--url-sf", help="Link SharePoint file SF Teritory")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    t = datetime.strptime(a.tanggal, "%d-%m-%Y").date() if a.tanggal else None
    h = buat_report(a.xlsx, t, a.out, url_sf=a.url_sf)
    print(h["periode"], "|", h["ringkasan"])
    print("PNG:", h["png"])
    print("XLSX:", h["xlsx"])
    print("Teks update:\n" + h["teks"])
