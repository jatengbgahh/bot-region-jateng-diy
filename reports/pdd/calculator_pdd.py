"""
calculator_pdd.py — Kalkulasi PDD per WOK/BRANCH/REGION IndiHome Jateng-DIY
Source: indihome_ordering_detail_YYYYMM (region=JATENG-DIY, order_type=NEW SALES)
PDD order = pdd_enabled = 1
Periode: MtD (tanggal 1 bulan berjalan s/d tgl_closing)

Metrik:
- SF Active            = unique sf_code dengan PS (semua order, tidak difilter pdd_enabled)
- SF Active PDD        = unique sf_code dengan PS & pdd_enabled=1
- %SF Active           = SF Active PDD / SF Active
- New Sales PDD by SF  = jumlah PS pdd_enabled=1, channel AGENCY
- Avg Sales PDD by SF  = New Sales PDD by SF / SF Active PDD
- TRX by Channel       = jumlah PS pdd_enabled=1 per channel (Agency/GraPARI/SOBI/Web&Apps)
- Contr PDD by Channel = TRX channel / total TRX ke-4 channel di atas

Catatan agregasi (konsisten dengan calculator_sf.py / calculator_djp.py):
unique sf_code dihitung per WOK, lalu BRANCH & REGION = SUM dari angka per-WOK
(bukan hitung ulang nunique() di data gabungan) — supaya total BRANCH selalu
sama dengan jumlah WOK di dalamnya, dan total REGION selalu sama dengan jumlah
semua BRANCH. Konsekuensinya: kalau satu SF aktif di lebih dari satu WOK dalam
sebulan, dia akan terhitung lebih dari sekali di level BRANCH/REGION — sama
seperti perilaku SF Aktif PS di /sf dan SF DJP di /djp.
"""

import pandas as pd
from datetime import date, timedelta
import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

CHANNELS      = ["AGENCY", "GRAPARI", "SOBI", "WEB_APPS"]
CHANNEL_LABEL = {"AGENCY": "Agency", "GRAPARI": "GraPARI", "SOBI": "SOBI", "WEB_APPS": "Web & Apps"}


def _base_counts(df: pd.DataFrame) -> dict:
    """Hitung base count (bukan rasio) dari satu WOK — basis buat dijumlahkan ke BRANCH/REGION."""
    b = {"sf_active": 0, "sf_active_pdd": 0, "new_sales_pdd_by_sf": 0}
    for ch in CHANNELS:
        b[f"trx_{ch}"] = 0

    if df.empty:
        return b

    df_pdd = df[df["pdd_enabled"] == 1]

    b["sf_active"]            = int(df["sf_code"].nunique())
    b["sf_active_pdd"]        = int(df_pdd["sf_code"].nunique())
    b["new_sales_pdd_by_sf"]  = int((df_pdd["channel"] == "AGENCY").sum())
    for ch in CHANNELS:
        b[f"trx_{ch}"] = int((df_pdd["channel"] == ch).sum())

    return b


def _derived(b: dict) -> dict:
    """Hitung rasio/persentase dari base count (WOK sendiri, atau hasil SUM WOK-WOK)."""
    m = dict(b)
    m["pct_sf_active"] = (
        b["sf_active_pdd"] / b["sf_active"] * 100 if b["sf_active"] > 0 else None
    )
    m["avg_sales_pdd_by_sf"] = (
        b["new_sales_pdd_by_sf"] / b["sf_active_pdd"] if b["sf_active_pdd"] > 0 else None
    )
    trx_total = sum(b[f"trx_{ch}"] for ch in CHANNELS)
    for ch in CHANNELS:
        m[f"contr_{ch}"] = (b[f"trx_{ch}"] / trx_total * 100) if trx_total > 0 else None
    return m


def _sum_counts(rows: list[dict]) -> dict:
    """Jumlahkan base count dari beberapa WOK (dict hasil _base_counts)."""
    keys = ["sf_active", "sf_active_pdd", "new_sales_pdd_by_sf"] + [f"trx_{ch}" for ch in CHANNELS]
    return {k: sum(r.get(k, 0) for r in rows) for k in keys}


def hitung_pdd(tgl_closing: date) -> dict:
    """
    Query & hitung metrik PDD MtD s/d tgl_closing.
    Return dict siap pakai untuk renderer_pdd.render_pdd().
    """
    awal_ini = tgl_closing.replace(day=1)
    # +1 hari: ps_ts DATETIME, BETWEEN perlu batas atas esok hari agar tanggal tgl_closing ikut
    rows = db.query_pdd(awal_ini, tgl_closing + timedelta(days=1))
    df   = pd.DataFrame(rows) if rows else pd.DataFrame()

    if not df.empty:
        df["wok"]         = df["wok"].astype(str).str.strip().str.upper()
        df["branch"]      = df["branch"].astype(str).str.strip().str.upper()
        df["pdd_enabled"] = pd.to_numeric(df["pdd_enabled"], errors="coerce").fillna(0).astype(int)

    def branch_of(wok: str) -> str:
        return WOK_TO_BRANCH.get(
            next((k for k in WOK_TO_BRANCH if k.upper() == wok), wok),
            "LAINNYA"
        )

    semua_wok = sorted(df["wok"].unique()) if not df.empty else []

    # ── WOK rows (base count asli dari nunique per-WOK) ─────────────────────
    wok_rows = []
    wok_base = {}
    for wok in semua_wok:
        sub  = df[df["wok"] == wok]
        base = _base_counts(sub)
        wok_base[wok] = base
        wok_rows.append({
            "level": "WOK", "name": wok, "branch": branch_of(wok),
            **_derived(base),
        })

    wok_up = [w.upper() for w in WOK_ORDER]
    wok_rows.sort(key=lambda r: wok_up.index(r["name"]) if r["name"] in wok_up else 999)

    # ── BRANCH rows (SUM base count WOK-WOK anggotanya) ─────────────────────
    branch_names = BRANCH_ORDER + sorted(
        {r["branch"] for r in wok_rows if r["branch"] not in BRANCH_ORDER}
    )
    branch_rows = []
    for branch in branch_names:
        member_woks = [r["name"] for r in wok_rows if r["branch"] == branch]
        if not member_woks:
            continue
        base = _sum_counts([wok_base[w] for w in member_woks])
        branch_rows.append({
            "level": "BRANCH", "name": branch,
            **_derived(base),
        })

    # ── REGION row (SUM base count semua WOK) ────────────────────────────────
    reg_base = _sum_counts(list(wok_base.values()))
    reg_row  = {"level": "REGION", "name": REGION_NAME, **_derived(reg_base)}

    return {
        "tgl_closing": tgl_closing,
        "bi_label"   : tgl_closing.strftime("%b %Y").upper(),
        "region"     : reg_row,
        "branches"   : branch_rows,
        "woks"       : wok_rows,
    }
