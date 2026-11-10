"""
reports/murmer/calculator.py — Kalkulasi metrik Daily/MTD/YTD untuk /murmer.

Logika hitung PERSIS port dari skrip standalone murmer.py (calculate_metrics),
cuma cutoff sekarang bisa datang dari argumen command /murmer, bukan selalu
date.today() - 1 hari.
"""

from calendar import monthrange
from datetime import date, timedelta

import pandas as pd


def resolve_cutoff(tgl: date | None) -> tuple[date, date, int]:
    """
    (cutoff, month_start, total_hari_bulan_cutoff).
    tgl=None -> default H-1 (sama seperti skrip standalone aslinya).
    """
    cutoff = tgl if tgl is not None else date.today() - timedelta(days=1)
    month_start = cutoff.replace(day=1)
    total_days = monthrange(cutoff.year, cutoff.month)[1]
    return cutoff, month_start, total_days


def calculate_metrics(df: pd.DataFrame, cutoff: date, month_start: date, targets: dict) -> pd.DataFrame:
    """Hitung YTD, MTD, Daily (IO=io_ts, RE=re_ts, PS=ps_ts) per region di `targets`."""
    df = df.copy()
    df["io_ts"] = pd.to_datetime(df.get("io_ts"), errors="coerce")
    df["re_ts"] = pd.to_datetime(df.get("re_ts"), errors="coerce")
    df["ps_ts"] = pd.to_datetime(df.get("ps_ts"), errors="coerce")

    cutoff_ts = pd.Timestamp(cutoff) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ms_ts = pd.Timestamp(month_start)

    rows = []
    for region, target in targets.items():
        r = df[df["region"] == region] if "region" in df.columns else df.iloc[0:0]

        ytd_io = int((r["io_ts"] <= cutoff_ts).sum())
        ytd_re = int((r["re_ts"] <= cutoff_ts).sum())
        ytd_ps = int((r["ps_ts"] <= cutoff_ts).sum())

        mtd_io = int(((r["io_ts"] >= ms_ts) & (r["io_ts"] <= cutoff_ts)).sum())
        mtd_re = int(((r["re_ts"] >= ms_ts) & (r["re_ts"] <= cutoff_ts)).sum())
        mtd_ps = int(((r["ps_ts"] >= ms_ts) & (r["ps_ts"] <= cutoff_ts)).sum())

        d_io = int((r["io_ts"].dt.date == cutoff).sum())
        d_re = int((r["re_ts"].dt.date == cutoff).sum())
        d_ps = int((r["ps_ts"].dt.date == cutoff).sum())

        ach_ytd = (ytd_ps / target * 100) if target > 0 else 0

        rows.append({
            "REGION": region,
            "TARGET": target,
            "YTD_IO": ytd_io, "YTD_RE": ytd_re, "YTD_PS": ytd_ps,
            "MTD_IO": mtd_io, "MTD_RE": mtd_re, "MTD_PS": mtd_ps,
            "D_IO": d_io, "D_RE": d_re, "D_PS": d_ps,
            "ACH_YTD": ach_ytd,
        })

    return pd.DataFrame(rows)


def ach_color(val: float, ach_min: float, ach_max: float) -> str:
    """Gradasi warna ACH YTD: tertinggi = hijau, terendah = merah (via oranye)."""
    if ach_max == ach_min:
        ratio = 0.5
    else:
        ratio = (val - ach_min) / (ach_max - ach_min)

    if ratio < 0.5:
        t = ratio / 0.5
        r = int(239 + (255 - 239) * t)
        g = int(154 + (204 - 154) * t)
        b = int(154 + (128 - 154) * t)
    else:
        t = (ratio - 0.5) / 0.5
        r = int(255 - (255 - 165) * t)
        g = int(204 + (214 - 204) * t)
        b = int(128 + (167 - 128) * t)

    return f"#{r:02x}{g:02x}{b:02x}"
