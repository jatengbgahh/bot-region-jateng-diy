"""
calculator_addon.py — Kalkulasi Laporan Addon (FTTR / IP Camera / Mesh Wifi) per WOK/BRANCH
IndiHome Jateng-DIY.

Periode: 2 bulan penuh sebelumnya + MTD bulan berjalan (mis. Mei, Jun, MTD Jul), rolling
otomatis mengikuti tgl_closing yang diminta (bukan hardcode Mei/Jun/Jul).

Source: indihome_ordering_detail_YYYYMM (db.query_addon) — ps_ts valid,
order_type = 'MODIFICATION - ADDON'.

Klasifikasi produk (lihat db.query_addon):
  FTTR       : product_commercial_name mengandung kata 'FTTR'
  IP_CAM     : product_commercial_name = 'Indoor Camera'
  MESH_WIFI  : product_commercial_name = 'Ultra Mesh Wifi'

Metrik per WOK/BRANCH/REGION, per produk:
  m2/m1  : jumlah PS bulan penuh (2 bulan & 1 bulan sebelum tgl_closing)
  m0     : jumlah PS 1 s/d tgl_closing bulan berjalan (MTD)
  ytd    : m2 + m1 + m0
  mom    : growth m0 terhadap m1 (None kalau m1 = 0) — konsisten dengan pola
           _growth/_pct_growth di calculator lain (calculator_homepass, calculator_sql, dst)
  target : dari 3 sheet target terpisah, satu per produk (BULAN=YYYY-MM, WOK, TARGET_PS):
             FTTR      -> sheet TARGET_MONTHLY_FTTR
             IP_CAM    -> sheet TARGET_MONTHLY_IN CAMERA
             MESH_WIFI -> sheet TARGET_MONTHLY_MESH_WIFI
  contr  : m0 WOK / total m0 seluruh WOK yang PUNYA target, produk yang sama (%) —
           bulan terakhir saja (MTD bulan berjalan), bukan YTD
  ach    : m0 (bulan terakhir / MTD bulan berjalan) / target * 100
  has_target : False kalau WOK ini tidak punya target > 0 utk produk ini (baris tidak ada,
               atau TARGET_PS = 0/kosong — artinya produk belum digulirkan di WOK tsb) —
               dipakai renderer untuk menampilkan blok abu-abu sesuai desain report existing.
"""

import calendar
import logging
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

logger = logging.getLogger(__name__)

PRODUCT_ORDER  = ["FTTR", "IP_CAM", "MESH_WIFI"]
PRODUCT_LABELS = {"FTTR": "FTTR", "IP_CAM": "IP Camera", "MESH_WIFI": "Mesh Wifi"}

# Nama sheet Excel target per produk (satu sheet per produk, kolom BULAN/WOK/TARGET_PS)
PRODUCT_TARGET_SHEET = {
    "FTTR"     : "TARGET_MONTHLY_FTTR",
    "IP_CAM"   : "TARGET_MONTHLY_IN CAMERA",
    "MESH_WIFI": "TARGET_MONTHLY_MESH_WIFI",
}

BULAN_ID = ["JAN", "FEB", "MAR", "APR", "MEI", "JUN", "JUL",
            "AGU", "SEP", "OKT", "NOV", "DES"]

# Target sementara dipakai kalau belum ada satupun sheet target Addon ter-upload
# (lihat hitung_addon) — supaya report tetap menampilkan angka riil, bukan
# blok abu-abu total, selagi menunggu file target yang sebenarnya.
DEFAULT_TARGET = 10.0


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["wok"]     = df["wok"].astype(str).str.strip().str.upper()
    df["branch"]  = df["branch"].astype(str).str.strip().str.upper()
    df["product"] = df["product"].astype(str).str.strip().str.upper()
    df["ps_ts"]   = pd.to_datetime(df["ps_ts"], errors="coerce")
    return df


def _growth(cur, prev):
    if prev and prev > 0:
        return round((cur - prev) / prev * 100, 2)
    return None


def _count(df: pd.DataFrame, wok: str, product: str, awal: date, akhir: date) -> int:
    if df.empty:
        return 0
    akhir_excl = pd.Timestamp(akhir) + pd.Timedelta(days=1)
    awal_ts    = pd.Timestamp(awal)
    mask = (
        (df["wok"] == wok) & (df["product"] == product) &
        df["ps_ts"].notna() & (df["ps_ts"] >= awal_ts) & (df["ps_ts"] < akhir_excl)
    )
    return int(mask.sum())


def _target_lookup(target_dfs: dict, bulan_label: str) -> dict:
    """
    target_dfs: {"FTTR": df, "IP_CAM": df, "MESH_WIFI": df} — masing-masing dari sheet
    TARGET_MONTHLY_<PRODUK> (kolom BULAN, WOK, TARGET_PS).
    Return {(wok, product): target}. Baris dengan TARGET_PS kosong ATAU <= 0 TIDAK
    dimasukkan (dianggap "belum ada target" -> has_target=False -> blok abu-abu di renderer),
    sesuai pola data: WOK yang belum digulirkan produk tsb diisi TARGET_PS = 0.
    """
    out = {}
    if not target_dfs:
        return out
    for prod, df in target_dfs.items():
        if df is None or df.empty or "WOK" not in df.columns or "TARGET_PS" not in df.columns:
            continue
        sub = df[df.get("BULAN") == bulan_label] if "BULAN" in df.columns else df
        for _, row in sub.iterrows():
            wok = str(row.get("WOK", "")).strip().upper()
            val = row.get("TARGET_PS")
            if not wok or pd.isna(val):
                continue
            val = float(val)
            if val > 0:
                out[(wok, prod)] = val
    return out


def _finalize(m: dict, m0_base: float) -> dict:
    m = dict(m)
    # %Contr = bulan terakhir (m0, MTD bulan berjalan) dibanding total m0 semua WOK
    # ber-target — bukan YTD, konsisten dengan ACH to Target.
    m["contr"] = round(m["m0"] / m0_base * 100, 2) if m0_base else None
    m["ach"] = (
        round(m["m0"] / m["target"] * 100, 2)
        if m.get("target") not in (None, 0) else None
    )
    return m


def hitung_addon(tgl_closing: date, target_dfs: dict = None) -> dict:
    bulan_now = tgl_closing.replace(day=1)
    bulan_m1  = bulan_now - relativedelta(months=1)
    bulan_m2  = bulan_now - relativedelta(months=2)

    def _akhir_bulan(b: date) -> date:
        return date(b.year, b.month, calendar.monthrange(b.year, b.month)[1])

    periode_m2 = (bulan_m2, _akhir_bulan(bulan_m2))
    periode_m1 = (bulan_m1, _akhir_bulan(bulan_m1))
    periode_m0 = (bulan_now, tgl_closing)

    label_m2 = BULAN_ID[bulan_m2.month - 1]
    label_m1 = BULAN_ID[bulan_m1.month - 1]
    label_m0 = f"MTD {BULAN_ID[bulan_now.month - 1]}"

    rows = db.query_addon(periode_m2[0], tgl_closing)
    df   = _prep(pd.DataFrame(rows) if rows else pd.DataFrame())

    wok_dikenal = {w.upper() for w in WOK_ORDER}
    if not df.empty:
        wok_asing = set(df["wok"].unique()) - wok_dikenal
        if wok_asing:
            logger.warning(f"[addon] WOK tidak dikenal, dilewati: {sorted(wok_asing)}")
    semua_wok = sorted(wok_dikenal)

    target_map = _target_lookup(target_dfs, bulan_now.strftime("%Y-%m"))
    target_is_default = not target_map
    if target_is_default:
        # Belum ada sheet target (TARGET_MONTHLY_FTTR / _IN CAMERA / _MESH_WIFI) ter-upload
        # sama sekali — pakai target sementara = DEFAULT_TARGET utk semua WOK/produk supaya
        # report tidak abu-abu total selagi menunggu file target asli.
        # Begitu sheet target ter-upload, fallback ini otomatis tidak berlaku lagi.
        logger.info(f"[addon] Sheet target Addon kosong utk bulan {bulan_now.strftime('%Y-%m')}, "
                    f"pakai target sementara = {DEFAULT_TARGET} utk semua WOK/produk.")
        target_map = {
            (wok, prod): DEFAULT_TARGET
            for wok in semua_wok for prod in PRODUCT_ORDER
        }

    def branch_of(wok: str) -> str:
        return WOK_TO_BRANCH.get(wok, WOK_TO_BRANCH.get(wok.title(), "LAINNYA"))

    # ── WOK-level per-produk metric mentah ──────────────────────────────────
    wok_metrics = {}
    for wok in semua_wok:
        wok_metrics[wok] = {}
        for prod in PRODUCT_ORDER:
            m2 = _count(df, wok, prod, *periode_m2)
            m1 = _count(df, wok, prod, *periode_m1)
            m0 = _count(df, wok, prod, *periode_m0)
            wok_metrics[wok][prod] = {
                "m2": m2, "m1": m1, "m0": m0, "ytd": m2 + m1 + m0,
                "mom": _growth(m0, m1),
                "target": target_map.get((wok, prod)),
                "has_target": (wok, prod) in target_map,
            }

    # ── Total m0 (bulan terakhir) per produk — basis %Contr, hanya WOK ber-target ──
    m0_total = {
        prod: sum(wok_metrics[w][prod]["m0"] for w in semua_wok if wok_metrics[w][prod]["has_target"])
        for prod in PRODUCT_ORDER
    }

    # ── WOK rows ─────────────────────────────────────────────────────────
    wok_rows = []
    for wok in semua_wok:
        row = {"level": "WOK", "name": wok, "branch": branch_of(wok), "products": {}}
        for prod in PRODUCT_ORDER:
            row["products"][prod] = _finalize(wok_metrics[wok][prod], m0_total[prod])
        wok_rows.append(row)

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows ──────────────────────────────────────────────────────
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    branch_rows = []
    for branch in branch_names:
        member = [r["name"] for r in wok_rows if r["branch"] == branch]
        if not member:
            continue
        row = {"level": "BRANCH", "name": branch, "products": {}}
        for prod in PRODUCT_ORDER:
            # Hanya WOK yang punya target utk produk ini yang disertakan dalam agregat —
            # konsisten dengan basis %Contr (m0_total) & desain report (WOK tanpa target
            # ditampilkan abu-abu / tidak ikut dihitung).
            contributing = [w for w in member if wok_metrics[w][prod]["has_target"]]
            m2 = sum(wok_metrics[w][prod]["m2"] for w in contributing)
            m1 = sum(wok_metrics[w][prod]["m1"] for w in contributing)
            m0 = sum(wok_metrics[w][prod]["m0"] for w in contributing)
            has_target = len(contributing) > 0
            target = sum(
                wok_metrics[w][prod]["target"] for w in contributing
            ) if has_target else None
            raw = {
                "m2": m2, "m1": m1, "m0": m0, "ytd": m2 + m1 + m0,
                "mom": _growth(m0, m1),
                "target": target, "has_target": has_target,
            }
            row["products"][prod] = _finalize(raw, m0_total[prod])
        branch_rows.append(row)

    # ── REGION row ───────────────────────────────────────────────────────
    region_row = {"level": "REGION", "name": REGION_NAME, "products": {}}
    for prod in PRODUCT_ORDER:
        contributing = [w for w in semua_wok if wok_metrics[w][prod]["has_target"]]
        m2 = sum(wok_metrics[w][prod]["m2"] for w in contributing)
        m1 = sum(wok_metrics[w][prod]["m1"] for w in contributing)
        m0 = sum(wok_metrics[w][prod]["m0"] for w in contributing)
        has_target = len(contributing) > 0
        target = sum(
            wok_metrics[w][prod]["target"] for w in contributing
        ) if has_target else None
        raw = {
            "m2": m2, "m1": m1, "m0": m0, "ytd": m2 + m1 + m0,
            "mom": _growth(m0, m1),
            "target": target, "has_target": has_target,
        }
        region_row["products"][prod] = _finalize(raw, m0_total[prod])

    return {
        "tgl_closing": tgl_closing,
        "label_m2": label_m2, "label_m1": label_m1, "label_m0": label_m0,
        "bi_label": f"{label_m2}-{label_m1}-{label_m0} {tgl_closing.year}",
        "product_order" : PRODUCT_ORDER,
        "product_labels": PRODUCT_LABELS,
        "target_is_default": target_is_default,
        "default_target": DEFAULT_TARGET,
        "region"  : region_row,
        "branches": branch_rows,
        "woks"    : wok_rows,
    }
