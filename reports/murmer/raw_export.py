"""
reports/murmer/raw_export.py — Export data raw /murmer (hasil query.fetch_data) ke xlsx.
"""

from datetime import date
from io import BytesIO

import pandas as pd


def build_raw_excel(df: pd.DataFrame, cutoff: date, region: str = "JATENG-DIY") -> tuple[BytesIO, str]:
    """Return (buffer xlsx, nama file) untuk region tertentu."""
    df_region = df[df["region"] == region] if "region" in df.columns else df.iloc[0:0]

    buf = BytesIO()
    df_region.to_excel(buf, index=False, sheet_name="raw_data")
    buf.seek(0)

    filename = f"eznet_murmer_raw_{region.replace(' ', '_')}_{cutoff.strftime('%Y%m%d')}.xlsx"
    return buf, filename
