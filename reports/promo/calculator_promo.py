"""
calculator_promo.py — Kalkulasi PS harian paket PROMO 'One Dynamic'
(New Sales), dipecah per BRANCH, WOK, dan CITY (kabupaten). Dipakai /promo.

PS  = order dengan ps_ts valid (bukan NULL / '0000-00-00'),
      order_type = 'NEW SALES',
      product_commercial_name LIKE '%One Dynamic Promo%' (KHUSUS promo).

Kolom tanggal yang dihasilkan hanya 1 s/d tgl_closing.day (bukan 1 bulan penuh),
supaya tabel tidak terlalu panjang — sama seperti calculator_dod.
"""

from datetime import date

import pandas as pd

import db
from config import WOK_TO_BRANCH_BARU as WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER_BARU as WOK_ORDER, REGION_NAME

BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

PROMO_LABEL = "One Dynamic Promo"


def _daily_from_counts(counts_list: list, n_days: int) -> dict:
    """counts_list: list of {date: count} dict yang dijumlahkan per tanggal → {day:int}."""
    out = {}
    for d in range(1, n_days + 1):
        out[d] = sum(int(c.get(d, 0)) for c in counts_list)
    return out


def hitung_promo(tgl_closing: date) -> dict:
    """
    Hitung PS harian paket One Dynamic per WOK, per BRANCH (agregat WOK),
    grand total JATENG-DIY, dan breakdown per CITY (kabupaten) yang
    dikelompokkan di bawah branch-nya masing-masing.

    Return dict siap pakai untuk renderer_promo.render_promo().
    """
    awal_bulan = tgl_closing.replace(day=1)
    n_days     = tgl_closing.day

    rows = db.query_ps_daily_promo(awal_bulan, tgl_closing)
    df   = pd.DataFrame(rows)
    if not df.empty:
        df["wok"]       = df["wok"].astype(str).str.strip().str.upper()
        df["branch"]    = df["branch"].astype(str).str.strip().str.upper()
        df["kabupaten"] = df["kabupaten"].astype(str).str.strip().str.upper().str.title()
        df["day"]       = pd.to_datetime(df["ps_date"]).dt.day
        df["ps_count"]  = pd.to_numeric(df["ps_count"], errors="coerce").fillna(0).astype(int)

    def counts_by(col: str, key) -> dict:
        """{day: count} untuk baris di mana df[col] == key."""
        if df.empty:
            return {}
        sub = df[df[col] == key]
        return sub.groupby("day")["ps_count"].sum().to_dict()

    # ── Baris WOK ────────────────────────────────────────────────────────────
    wok_rows = []
    for wok in WOK_ORDER:
        branch = WOK_TO_BRANCH.get(wok, "LAINNYA")
        counts = counts_by("wok", wok)
        wok_rows.append({
            "name"       : wok,
            "branch"     : branch,
            "_counts"    : counts,
            "count_daily": _daily_from_counts([counts], n_days),
        })

    # ── Baris ringkasan BRANCH (agregat WOK anggotanya) ─────────────────────
    branch_rows = []
    for branch in BRANCH_ORDER:
        members = [w["_counts"] for w in wok_rows if w["branch"] == branch]
        branch_rows.append({
            "name"       : branch,
            "count_daily": _daily_from_counts(members, n_days),
        })

    # ── Grand total JATENG-DIY ────────────────────────────────────────────────
    total = {
        "name"       : REGION_NAME,
        "count_daily": _daily_from_counts([w["_counts"] for w in wok_rows], n_days),
    }

    # ── Breakdown per CITY (kabupaten), dikelompokkan di bawah branch ────────
    # Tiap kabupaten ditempatkan di branch dominan-nya (branch dengan PS
    # terbanyak untuk kabupaten itu). Di dalam grup diurut total desc.
    city_rows = []
    if not df.empty:
        city_total = df.groupby("kabupaten")["ps_count"].sum()
        # branch dominan per kabupaten
        dom = (df.groupby(["kabupaten", "branch"])["ps_count"].sum()
                 .reset_index()
                 .sort_values("ps_count", ascending=False)
                 .drop_duplicates("kabupaten")
                 .set_index("kabupaten")["branch"].to_dict())

        branch_pos = {b: i for i, b in enumerate(BRANCH_ORDER)}
        cities = sorted(
            city_total.index,
            key=lambda c: (branch_pos.get(dom.get(c, ""), 99), -int(city_total[c])),
        )
        for city in cities:
            counts = counts_by("kabupaten", city)
            city_rows.append({
                "name"       : city,
                "branch"     : dom.get(city, "LAINNYA"),
                "count_daily": _daily_from_counts([counts], n_days),
            })

    return {
        "tgl_closing": tgl_closing,
        "bulan_label": f"{BULAN_ID[tgl_closing.month]} {tgl_closing.year}",
        "n_days"     : n_days,
        "promo_label": PROMO_LABEL,
        "woks"       : wok_rows,
        "branches"   : branch_rows,
        "total"      : total,
        "cities"     : city_rows,
    }
