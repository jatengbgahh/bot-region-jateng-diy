"""
Package reports.wireless_channel — PS EZNet Wireless by Channel (/wirelesschannel).

Pintu depan: register_handlers(app, timeout_wrapper, get_cutoff_fn) dipanggil
sekali di main() bot.py — return handler-nya juga, supaya bisa didaftarkan ke
JADWAL_LAPORAN (laporan terjadwal, setelah /wireless).
  query.py       query DB (raw indihome_ordering_detail, produk WIRELESS, PS per channel)
  calculator.py  hitung MtD/MoM per WOK/BRANCH/REGION + pemisahan SF Household vs
                 SF Mobile lewat mapping/ (file .xlsx/.csv TERBARU di folder itu)
  renderer.py    render tabel PNG
  command.py     handler Telegram /wirelesschannel DD-MM-YYYY
  mapping/       file mapping sf_code -> Household/Mobile (timpa untuk update)
"""

from .command import register_handlers

__all__ = ["register_handlers"]
