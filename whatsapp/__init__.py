"""
Package whatsapp — kirim laporan bot ke WhatsApp (via WAHA).

Pintu depan: register_handlers(app, kirim_laporan_sql_func, timeout_wrapper)
dipanggil sekali di main() bot.py. Isinya:
  client.py     HTTP client ke WAHA (satu-satunya yang tahu mesin pengirim WA)
  adapter.py    WahaBotAdapter: objek yang menyerupai bot Telegram
  senders.py    logika hasilkan laporan + kirim (liveupdate / closingsql / agresif)
  commands.py   handler command Telegram /liveupdate_wa, /closingsql_wa, /agresif_wa
  scheduler.py  jadwal otomatis (config.JADWAL_LAPORAN_WA)
  errors.py     perapi pesan error untuk Telegram
"""

import logging

from .adapter import WahaBotAdapter
from .client import WahaClient, get_waha_client
from .commands import register_commands
from .scheduler import daftar_jadwal_wa

logger = logging.getLogger(__name__)

__all__ = ["WahaClient", "WahaBotAdapter", "get_waha_client", "register_handlers"]


def register_handlers(app, kirim_laporan_sql_func, timeout_wrapper=None):
    """
    Daftarkan command manual /liveupdate_wa, /closingsql_wa, /agresif_wa.
    Jadwal otomatis WA kini disatukan ke jadwal utama Telegram (BaseReport.send_wa).
    """
    try:
        from config import WAHA_TARGET_CHAT_ID, WAHA_SEND_IMAGES
    except ImportError:
        WAHA_TARGET_CHAT_ID = ""
        WAHA_SEND_IMAGES = True

    register_commands(app, kirim_laporan_sql_func, timeout_wrapper,
                      WAHA_TARGET_CHAT_ID, WAHA_SEND_IMAGES)
