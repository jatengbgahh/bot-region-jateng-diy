"""
reports/wirelesschannel2/calculator.py - PS EZNet Wireless by Channel TANPA produk tertentu
(mis. Murmer) - /wirelesschannel2.

Cara hitung SAMA dengan reports.wireless_channel.calculator (/wirelesschannel):
kolom channel, mapping SF Household/Mobile (file di reports/wireless_channel/mapping/),
MtD + MoM. Bedanya sumber datanya query.query_wireless_ps_channel yang meng-exclude
exclude_keyword. Helper & konstanta dipakai ulang dari wireless_channel.
"""

import logging
from datetime import date

from config import BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME
from calculator_wireless import _rentang_mtd, _branch_for
from reports.wireless_channel.calculator import (
    CHANNELS, CHANNEL_LABEL, REPORT_TITLE, load_sf_mapping, _growth, _agg,
)

from . import query

logger = logging.getLogger(__name__)


def hitung_wireless_channel2(tgl: date, exclude_keyword: str) -> dict:
    awal_ini, awal_lalu, akhir_lalu = _rentang_mtd(tgl)
    mapping  = load_sf_mapping()
    unmapped = set()

    a_ini  = _agg(query.query_wireless_ps_channel(awal_ini, tgl, exclude_keyword), mapping, unmapped)
    a_lalu = _agg(query.query_wireless_ps_channel(awal_lalu, akhir_lalu, exclude_keyword), mapping, set())

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
        "exclude_keyword": exclude_keyword,
    }


def _fm(v):
    return "-" if v is None else f"{'+' if v > 0 else ''}{v:.1f}%"


def build_caption(result: dict) -> str:
    """Caption: per channel MtD PS | MoM % | Cont % (kontribusi thd total PS MtD)."""
    r = result["region"]
    tot = r["all"]
    baris = [
        f"📊 {REPORT_TITLE} (tanpa {result['exclude_keyword'].title()})",
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
