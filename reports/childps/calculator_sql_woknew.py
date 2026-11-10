"""
calculator_sql_woknew.py — pemetaan kabupaten/kota -> WOK NEW -> BRANCH untuk report /childps.

File ini dibuat untuk bot ini karena modul dengan nama sama di bot lama (sumber patch Child per PS
Telkomsel One) tidak ada di sini. Sumbernya satu: MAP di reports/sf_momentum/calculator_5so.py (struktur WOK baru),
jadi kalau MAP berubah report ini ikut berubah — tidak ada daftar kedua yang perlu dirawat.
"""
from reports.sf_momentum.calculator_5so import KAB2WOK, WOK2BR, WOKS

WOK_NEW_ORDER = list(WOKS)               # urutan tampil WOK
WOK_NEW_TO_BRANCH = dict(WOK2BR)         # WOK -> BRANCH
__all__ = ["KAB2WOK", "WOK_NEW_ORDER", "WOK_NEW_TO_BRANCH"]
