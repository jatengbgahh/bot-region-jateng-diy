"""
reports/wireless_channel/calculator.py — PS EZNet Wireless by Channel (/wirelesschannel).

Sumber: tabel raw indihome_ordering_detail_YYYYMM, hanya produk yang
product_commercial_name-nya mengandung WIRELESS (query.query_wireless_ps_channel).
Metrik: PS saja, MtD bulan ini + MoM vs MtD bulan lalu (tanggal yang sama).

Kolom channel: SF HOUSEHOLD | SF MOBILE | GRAPARI | DIGITAL | COMMUNITY.
SF HOUSEHOLD & SF MOBILE sama-sama channel AGENCY; dibedakan lewat sf_code
memakai file mapping di folder reports/wireless_channel/mapping/ (kolom "Kode SF", "Category SF" =
Household/Mobile). File dibaca ULANG tiap laporan jalan, file .xlsx/.xls/.csv
TERBARU (mtime) di folder itu yang dipakai -> untuk update mapping cukup
timpa/ganti file-nya, tidak perlu ubah kode. sf_code AGENCY yang tidak ada di
mapping dihitung sebagai SF HOUSEHOLD (dan dilaporkan di caption).
"""

import glob
import logging
import os
from datetime import date

import pandas as pd

from . import query
from calculator_wireless import _rentang_mtd, _branch_for
from config import BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

logger = logging.getLogger(__name__)

MAPPING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mapping")

CHANNELS = ["SF_HH", "SF_MOBILE", "GRAPARI", "DIGITAL", "COMMUNITY"]

REPORT_TITLE = "PS EZNet Wireless Jateng-DIY by Channel"
CHANNEL_LABEL = {"SF_HH": "SF Household", "SF_MOBILE": "SF Mobile", "GRAPARI": "Grapari",
                 "DIGITAL": "Digital", "COMMUNITY": "Community"}


def load_sf_mapping() -> dict:
    """{SF_CODE_UPPER: 'HOUSEHOLD'|'MOBILE'} dari file mapping terbaru di mapping_sf/."""
    files = [f for ext in ("xlsx", "xls", "csv")
             for f in glob.glob(os.path.join(MAPPING_DIR, f"*.{ext}"))
             if not os.path.basename(f).startswith("~$")]
    if not files:
        logger.warning(f"[wireless_channel] Tidak ada file mapping SF di {MAPPING_DIR}")
        return {}
    path = max(files, key=os.path.getmtime)
    df = pd.read_csv(path, dtype=str) if path.lower().endswith(".csv") else pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip().str.upper()
    kc = next((c for c in df.columns if c in ("KODE SF", "SF_CODE", "SF CODE")), None)
    kk = next((c for c in df.columns if c in ("CATEGORY SF", "KATEGORI SF", "CATEGORY")), None)
    if not kc or not kk:
        raise ValueError(
            f"Mapping SF {os.path.basename(path)}: kolom 'Kode SF' & 'Category SF' tidak ditemukan")
    df = df.dropna(subset=[kc, kk])
    mp = {}
    for kode, cat in zip(df[kc], df[kk]):
        cat = str(cat).strip().upper()
        mp[str(kode).strip().upper()] = "MOBILE" if cat.startswith("MOB") else "HOUSEHOLD"
    logger.info(f"[wireless_channel] Mapping SF {os.path.basename(path)}: {len(mp)} kode")
    return mp


def _growth(cur, prev):
    if prev and prev > 0:
        return round((cur - prev) / prev * 100, 1)
    return None


def _agg(rows: list, mapping: dict, unmapped: set) -> dict:
    """{wok: {'all', 'SF_HH', 'SF_MOBILE', 'GRAPARI', 'DIGITAL', 'COMMUNITY'}} (jumlah PS)."""
    out = {}
    for r in rows:
        wok = (r["wok"] or "").strip().upper() or "TANPA WOK"
        n = int(r["ps_trx"])
        ch = r["channel"]
        if ch == "AGENCY":
            kode = (r.get("sf_code") or "").strip().upper()
            cat = mapping.get(kode)
            if cat is None:
                unmapped.add(kode or "(kosong)")
                cat = "HOUSEHOLD"
            ch = "SF_MOBILE" if cat == "MOBILE" else "SF_HH"
        d = out.setdefault(wok, dict.fromkeys(["all"] + CHANNELS, 0))
        d[ch] += n
        d["all"] += n
    return out


def hitung_wireless_channel(tgl: date) -> dict:
    awal_ini, awal_lalu, akhir_lalu = _rentang_mtd(tgl)
    mapping  = load_sf_mapping()
    unmapped = set()

    a_ini  = _agg(query.query_wireless_ps_channel(awal_ini, tgl), mapping, unmapped)
    a_lalu = _agg(query.query_wireless_ps_channel(awal_lalu, akhir_lalu), mapping, set())

    semua_wok = {w.upper() for w in WOK_ORDER} | set(a_ini) | set(a_lalu)
    keys = ["all"] + CHANNELS
    zero = dict.fromkeys(keys, 0)

    def build(name, ini, lalu, branch=""):
        row = {"name": name, "branch": branch}
        for k in keys:
            row[k] = ini[k]
            row[f"{k}_mom"] = _growth(ini[k], lalu[k])
        return row

    wok_rows = [build(w, a_ini.get(w, zero), a_lalu.get(w, zero), _branch_for(w)) for w in semua_wok]
    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    def total(names):
        ini  = {k: sum(a_ini.get(w, zero)[k] for w in names) for k in keys}
        lalu = {k: sum(a_lalu.get(w, zero)[k] for w in names) for k in keys}
        return ini, lalu

    branch_rows = []
    for br in BRANCH_ORDER:
        names = [r["name"] for r in wok_rows if r["branch"] == br]
        if names:
            ini, lalu = total(names)
            branch_rows.append(build(br, ini, lalu, br))

    ini, lalu = total(semua_wok)
    region_row = build(REGION_NAME, ini, lalu)

    return {
        "tgl_closing": tgl,
        "label_ini"  : f"01 s/d {tgl.strftime('%d-%m-%Y')}",
        "label_lalu" : f"01 s/d {akhir_lalu.strftime('%d-%m-%Y')}",
        "bl_label"   : akhir_lalu.strftime("%b %Y").upper(),
        "region": region_row, "branches": branch_rows, "woks": wok_rows,
        "unmapped": sorted(unmapped),
    }


def _fm(v):
    return "-" if v is None else f"{'+' if v > 0 else ''}{v:.1f}%"


def build_caption(result: dict) -> str:
    """Caption: per channel MtD PS | MoM % | Cont % (kontribusi thd total PS MtD)."""
    r = result["region"]
    tot = r["all"]
    baris = [
        f"📊 {REPORT_TITLE}",
        f"MtD {result['tgl_closing'].strftime('%d-%m-%Y')}  |  MoM vs {result['bl_label']}",
        "",
    ]
    for key, label in CHANNEL_LABEL.items():
        cont = f"{r[key] / tot * 100:.1f}%" if tot else "-"
        baris.append(f"{label}: MtD {r[key]:,} PS | MoM {_fm(r[f'{key}_mom'])} | Cont {cont}")
    baris += ["", f"Total: MtD {tot:,} PS | MoM {_fm(r['all_mom'])}"]
    if result["unmapped"]:
        baris += ["", f"⚠️ {len(result['unmapped'])} sf_code agency belum ada di mapping "
                      f"(dihitung SF Household): {', '.join(result['unmapped'][:10])}"
                      + (" ..." if len(result["unmapped"]) > 10 else "")]
    return "\n".join(baris)
