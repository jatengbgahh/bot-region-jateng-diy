"""
calculator_mb_daily.py — Daily grid MB: unique SF per WOK per tanggal dalam 1 bulan
Sama dengan calculator_djp_daily.py tapi menggunakan mb_df (BRIEFING).
"""
import pandas as pd
from datetime import date
import calendar
from config import WOK_TO_BRANCH, BRANCH_ORDER, WOK_ORDER, REGION_NAME


def hitung_mb_daily(tgl: date, mb_df: pd.DataFrame, sf_aktif_df=None) -> dict:
    from dateutil.relativedelta import relativedelta as _rdelta
    import calculator_djp_daily as _djp_daily  # reuse logic, beda df saja
    # Delegasi ke calculator_djp_daily dengan df MB
    result = _djp_daily.hitung_djp_daily(tgl, mb_df, sf_aktif_df)
    # Ganti label
    result["category"] = "MB"
    return result
