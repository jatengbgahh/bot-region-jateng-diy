"""
Package reports.kategori_paket — Sales by Kategori Paket IndiHome Jateng-DIY.

Sebelumnya dikirim otomatis oleh /closingsql; sekarang dipisah dan dikirim lewat
command sendiri /kategoripaket (handler di commands/kategori_paket.py).
  calculator.py  hitung MtD/MoM/Cont/MoM Cont per kategori (Tsel One, EZnet, IH Reguler)
  renderer.py    render tabel PNG
"""

from .calculator import hitung_kategori_paket
from .renderer import render_kategori_paket

__all__ = ["hitung_kategori_paket", "render_kategori_paket"]
