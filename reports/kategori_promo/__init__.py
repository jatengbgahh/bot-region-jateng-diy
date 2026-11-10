"""
Package reports.kategori_promo — Sales by Kategori Promo Paket IndiHome Jateng-DIY.

Dikirim otomatis oleh /closingsql (sumber DB) tepat setelah report
"Sales by Kategori Paket"; tidak punya command sendiri.
  calculator.py  hitung MtD/MoM/Cont/MoM Cont per kategori (Tsel One, Tsel One Promo,
                 EZnet, EZnet Promo, IH Reguler); reuse query db.query_ps_by_wok_product
  renderer.py    render tabel PNG
  command.py     build_caption (caption foto); pengiriman Telegram ada di bot.py
"""

from .calculator import hitung_kategori_promo
from .renderer import render_kategori_promo
from .command import build_caption, REPORT_TITLE

__all__ = ["hitung_kategori_promo", "render_kategori_promo", "build_caption", "REPORT_TITLE"]
