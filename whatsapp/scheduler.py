"""
whatsapp/scheduler.py — Jadwal otomatis pengiriman laporan ke WhatsApp.

Slot jadwal dibaca dari config.JADWAL_LAPORAN_WA (jam/menit WIB, laporan, offset hari).
Job berjalan lewat job_queue Telegram, tanpa Update/pesan masuk — hasil dan kegagalan
hanya dicatat ke log (bot_re_jateng.log), tidak ada balasan chat.
"""

import logging
from datetime import date, time as dtime, timedelta, timezone

from .senders import core_agresif_wa, core_closingsql_wa, core_liveupdate_wa

logger = logging.getLogger(__name__)

_WIB_TZ = timezone(timedelta(hours=7))  # WIB = UTC+7


async def _job_wa_terjadwal(context):
    """
    Callback job_queue untuk 1 slot JADWAL_LAPORAN_WA. Tidak ada Update Telegram
    di sini (dipicu scheduler, bukan pesan masuk) — jadi hasil/kegagalan cukup
    dicatat ke log (bot_re_jateng.log), tidak ada balasan chat seperti command
    manual /liveupdate_wa dkk.
    """
    data = context.job.data
    nama            = data["laporan"]
    offset          = data["offset_hari"]
    target_chat_id  = data["target_chat_id"]
    send_images     = data["send_images"]
    kirim_laporan_sql_func = data["kirim_laporan_sql_func"]

    tgl = date.today() - timedelta(days=offset) if offset else None
    label = f"WA/{nama}" + (f" (H-{offset}, {tgl.strftime('%d-%m-%Y')})" if tgl else "")

    try:
        if nama == "liveupdate":
            terkirim = await core_liveupdate_wa(kirim_laporan_sql_func, target_chat_id, send_images)
        elif nama == "closingsql":
            terkirim = await core_closingsql_wa(kirim_laporan_sql_func, tgl, target_chat_id, send_images)
        elif nama == "agresif":
            terkirim = await core_agresif_wa(tgl, target_chat_id, send_images)
        else:
            logger.error(f"[JADWAL-WA] Laporan '{nama}' tidak dikenal — slot dilewati")
            return
        logger.info(f"[JADWAL-WA] {label} terkirim ke WhatsApp ({target_chat_id}) — {terkirim} pesan/media")
    except Exception:
        logger.exception(f"[JADWAL-WA] {label} GAGAL dikirim ke WhatsApp ({target_chat_id})")


def daftar_jadwal_wa(app, kirim_laporan_sql_func, target_chat_id: str, send_images: bool):
    """
    [DEPRECATED] Jadwal otomatis WA kini disatukan ke siklus JADWAL_LAPORAN di bot.py
    dan flag BaseReport.send_wa. Fungsi ini dipertahankan sebagai no-op untuk kompatibilitas.
    """
    logger.info("[JADWAL-WA] Scheduler mandiri dinonaktifkan: jadwal WA kini bersatu dengan jadwal utama Telegram.")
    return
