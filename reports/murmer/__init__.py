"""
Package reports.murmer — Report EZNET Wireless Murmer (/murmer).

Pintu depan: register_handlers(app, timeout_wrapper) dipanggil sekali di main() bot.py.
  query.py       query DB (raw indihome_ordering_detail, filter produk "murmer")
  calculator.py  hitung metrik Daily/MTD/YTD + gradasi warna ACH
  renderer.py    render tabel PNG
  raw_export.py  export raw data ke xlsx
  command.py     handler Telegram /murmer [DD-MM-YYYY]
"""

from .command import register_handlers

__all__ = ["register_handlers"]
