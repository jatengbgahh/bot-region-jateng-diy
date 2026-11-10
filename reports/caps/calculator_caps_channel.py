"""
calculator_caps_channel.py — Kalkulasi CAPS (DO) per Channel Deaktivasi

Report ke-3 dari perintah /caps.

Logic:
  - Sumber: retensi_dd_YYYYMM (nama tabel LITERAL mengikuti bulan closing,
    mis. /caps 22-07-2026 -> retensi_dd_202607, bulan berikutnya
    retensi_dd_202608, dst; M-1 pakai tabel bulan sebelumnya).
  - Hanya order dgn retention_category = 'DO' dan region_sales mengandung
    'JATENG' (filter di db.query_retensi_do()).
  - Cutoff MtD pakai deactivation_date: [tgl-1-bulan-closing, tgl_closing].
  - Channel diturunkan dari unit_type:
        GRAPARI     -> unit_type mengandung 'grapari' ATAU 'plasa'
        CALL CENTER -> unit_type mengandung 'call center'
        E-CARE      -> unit_type mengandung 'e care'
        OTHERS      -> selain 3 di atas (termasuk unit_type kosong)
  - MtD  = COUNT(DISTINCT bb_id) per channel
  - Cont.= MtD channel / MtD total baris tsb * 100
  - MoM  = (MtD - MtD M-1) / MtD M-1 * 100  (churn naik = positif = jelek),
    MtD M-1 = rentang tanggal yang sama di bulan sebelumnya.
  - Territory: WOK -> Branch -> Region JATENG-DIY, mengikuti calculator_caps.py.
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

CHANNEL_ORDER = ["GRAPARI", "CALL CENTER", "E-CARE", "OTHERS"]
CHANNEL_LABEL = {
    "GRAPARI"    : "GRAPARI",
    "CALL CENTER": "CALL CENTER",
    "E-CARE"     : "E-CARE",
    "OTHERS"     : "OTHERS",
}


def _norm_unit(v) -> str:
    """
    Normalisasi unit_type untuk pencocokan substring: lowercase, pemisah
    '-'/'_' jadi spasi, spasi ganda dirapatkan. Supaya 'E-CARE', 'E_CARE',
    dan 'E CARE' sama-sama kena aturan 'e care'.
    """
    s = str(v or "").strip().lower().replace("-", " ").replace("_", " ")
    return " ".join(s.split())


def map_channel(unit_type) -> str:
    u = _norm_unit(unit_type)
    if "grapari" in u or "plasa" in u:
        return "GRAPARI"
    if "call center" in u:
        return "CALL CENTER"
    if "e care" in u:
        return "E-CARE"
    return "OTHERS"


def _prep(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["wok"]               = df["wok"].fillna("").astype(str).str.strip().str.upper()
    df["branch"]            = df["branch"].fillna("").astype(str).str.strip().str.upper()
    df["bb_id"]             = df["bb_id"].astype(str).str.strip()
    df["deactivation_date"] = pd.to_datetime(df["deactivation_date"], errors="coerce")
    df["channel"]           = df["unit_type"].map(map_channel)
    return df


def _agg_wok(df: pd.DataFrame, tgl_awal: date, tgl_akhir: date) -> dict:
    """Aggregate per WOK dalam rentang MtD. Return {wok: {"total": n, channel: n, ...}}"""
    if df.empty:
        return {}

    mask = (df["deactivation_date"] >= pd.Timestamp(tgl_awal)) & \
           (df["deactivation_date"] <= pd.Timestamp(tgl_akhir))
    dfm = df[mask]

    result = {}
    for wok, grp in dfm.groupby("wok"):
        d = {"total": grp["bb_id"].nunique()}
        for ch in CHANNEL_ORDER:
            d[ch] = grp[grp["channel"] == ch]["bb_id"].nunique()
        result[wok] = d
    return result


def _mom(m, m1):
    if m1:
        return round((m - m1) / m1 * 100, 2)
    return None


def _make_metrics(agg_ini: dict, agg_lalu: dict, woks_list: list) -> tuple[dict, int, int, float]:
    def _sum(agg, key):
        return sum(agg.get(w, {}).get(key, 0) for w in woks_list)

    total_i = _sum(agg_ini,  "total")
    total_l = _sum(agg_lalu, "total")

    chans = {}
    for ch in CHANNEL_ORDER:
        jml_i = _sum(agg_ini,  ch)
        jml_l = _sum(agg_lalu, ch)
        chans[ch] = {
            "m1"   : jml_l,
            "mtd"  : jml_i,
            "cont" : round(jml_i / total_i * 100, 2) if total_i else None,
            "mom"  : _mom(jml_i, jml_l),
        }
    return chans, total_i, total_l, _mom(total_i, total_l)


def cutoff_efektif(df: pd.DataFrame, tgl_closing: date) -> date:
    """
    Tanggal MtD yang benar-benar terwakili datanya.

    retensi_dd kadang tertinggal 1 hari dari churn_dd (sumber /caps by LoS):
    mis. churn_dd_202607 sudah punya deactivation_date 22-07 sementara
    retensi_dd_202607 baru s/d 21-07. Kalau tetap dihitung s/d tanggal yang
    diminta, MtD-nya kelihatan lebih kecil dari report pertama padahal
    sebenarnya cuma beda ketersediaan data (per tanggal angkanya identik).

    Jadi cutoff dipotong ke tanggal terakhir yang ada, lalu tanggal itu yang
    ditampilkan di judul/caption — angkanya jujur dan pembandingnya jelas.
    """
    if df.empty:
        return tgl_closing
    dmax = df["deactivation_date"].max()
    if pd.isna(dmax):
        return tgl_closing
    return min(dmax.date(), tgl_closing)


def hitung_caps_channel(tgl_closing: date) -> dict:
    bp_ini  = tgl_closing.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)

    tabel_ini  = f"retensi_dd_{bp_ini.strftime('%Y%m')}"
    tabel_lalu = f"retensi_dd_{bp_lalu.strftime('%Y%m')}"

    df_ini  = _prep(db.query_retensi_do(tabel_ini))
    df_lalu = _prep(db.query_retensi_do(tabel_lalu))

    tgl_efektif = cutoff_efektif(df_ini, tgl_closing)

    # MtD bulan lalu mengikuti tanggal EFEKTIF (bukan yang diminta) supaya
    # jumlah hari yang dibandingkan sama persis — apple to apple.
    hari_max     = calendar.monthrange(bp_lalu.year, bp_lalu.month)[1]
    tgl_mtd_lalu = date(bp_lalu.year, bp_lalu.month, min(tgl_efektif.day, hari_max))

    agg_ini  = _agg_wok(df_ini,  bp_ini,  tgl_efektif)
    agg_lalu = _agg_wok(df_lalu, bp_lalu, tgl_mtd_lalu)

    semua_wok = set(list(agg_ini.keys()) + list(agg_lalu.keys())) | set(w.upper() for w in WOK_ORDER)
    semua_wok.discard("")

    # ── WOK rows ──────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        canon  = next((w for w in WOK_ORDER if w.upper() == wok), wok)
        branch = WOK_TO_BRANCH.get(canon, "LAINNYA")
        chans, tot_i, tot_l, tot_mom = _make_metrics(agg_ini, agg_lalu, [wok])
        wok_rows.append({
            "level"   : "WOK",
            "name"    : canon,
            "branch"  : branch,
            "channels": chans,
            "m1"      : tot_l,
            "mtd"     : tot_i,
            "mom"     : tot_mom,
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"].upper()) if r["name"].upper() in wok_up else 999)

    # ── BRANCH rows ───────────────────────────────────────────────────────
    branch_rows = []
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    for branch in branch_names:
        bwoks = [r["name"].upper() for r in wok_rows if r["branch"] == branch]
        if not bwoks:
            continue
        chans, tot_i, tot_l, tot_mom = _make_metrics(agg_ini, agg_lalu, bwoks)
        branch_rows.append({
            "level"   : "BRANCH",
            "name"    : branch,
            "channels": chans,
            "m1"      : tot_l,
            "mtd"     : tot_i,
            "mom"     : tot_mom,
        })

    # ── REGION row ────────────────────────────────────────────────────────
    chans, tot_i, tot_l, tot_mom = _make_metrics(agg_ini, agg_lalu, list(semua_wok))
    region_row = {
        "level"   : "REGION",
        "name"    : REGION_NAME,
        "channels": chans,
        "m1"      : tot_l,
        "mtd"     : tot_i,
        "mom"     : tot_mom,
    }

    return {
        "tgl_closing"  : tgl_efektif,          # tanggal yang benar-benar dihitung
        "tgl_diminta"  : tgl_closing,          # tanggal di perintah /caps
        "tgl_mundur"   : tgl_efektif < tgl_closing,
        "bi_label"     : bp_ini.strftime("%b %Y").upper(),
        "bl_label"     : bp_lalu.strftime("%b %Y").upper(),
        "region"       : region_row,
        "branches"     : branch_rows,
        "woks"         : wok_rows,
        "channel_order": CHANNEL_ORDER,
        "channel_label": CHANNEL_LABEL,
    }
