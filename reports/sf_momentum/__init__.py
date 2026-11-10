"""
Package reports.sf_momentum — Report /5so dan /7so (SF Momentum Scorecard + Excel SF Belum RE).

Struktur modul:
  calculator_5so.py  kalkulasi inti SF Momentum per Region/Branch/WOK (basis PS) + mapping WOK baru
  calculator_7so.py  kalkulasi 7SO (basis RE) + export Excel SF Belum RE MTD
  renderer.py        render gambar tabel 5SO / 7SO Scorecard (lebar kolom menyesuaikan isi)
  raw_export.py      Excel "5SO 7SO per SF + RAW" (sub-report `raw` dari /7so, dengan Team Leader)
  sf_rules.py        aturan bersama: SF dummy, override snapshot SF Registered, mapping Team Leader
  report.py          class Report5SO & Report7SO (turunan BaseReport) + register_handlers()
"""

from . import calculator_5so, calculator_7so
from .renderer import render_5so
from .report import Report5SO, Report7SO, register_handlers

__all__ = [
    "calculator_5so",
    "calculator_7so",
    "render_5so",
    "Report5SO",
    "Report7SO",
    "register_handlers",
]
