"""
whatsapp/commands.py — Handler command Telegram /liveupdate_wa, /closingsql_wa, /agresif_wa.

Command-nya diketik di Telegram, tapi laporannya dikirim ke WhatsApp. Di sini hanya
urusan percakapan Telegram (validasi argumen, balasan status/error); pembuatan &
pengiriman laporan ada di senders.py.
"""

import logging
from datetime import datetime

from utils.command_registry import TelegramCommand
from telegram.ext import CommandHandler

import db
from .errors import clean_wa_error
from .senders import core_agresif_wa, core_closingsql_wa, core_liveupdate_wa

logger = logging.getLogger(__name__)


def register_commands(app, kirim_laporan_sql_func, timeout_wrapper,
                      default_chat_id: str, send_images: bool):
    """Daftarkan tiga command *_wa ke aplikasi Telegram."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_liveupdate_wa(update, ctx):
        """/liveupdate_wa [chat_id] — generate laporan DB sekarang dan kirim ke WhatsApp via WAHA."""
        args = ctx.args or []
        target_chat_id = args[0] if args else default_chat_id

        if not target_chat_id:
            await update.message.reply_text(
                "⚠️ Nomor atau ID WhatsApp tujuan belum ditentukan.\n"
                "Gunakan: `/liveupdate_wa 081234567890` atau isi `WAHA_TARGET_CHAT_ID` di `config.py`.",
                parse_mode="Markdown"
            )
            return

        await update.message.reply_text(
            f"⏳ Mengambil data database dan mengirim /liveupdate ke WhatsApp (`{target_chat_id}`) via WAHA..."
        )

        try:
            terkirim = await core_liveupdate_wa(kirim_laporan_sql_func, target_chat_id, send_images)
            await update.message.reply_text(
                f"✅ Laporan /liveupdate berhasil dikirim ke WhatsApp (`{target_chat_id}`)!\n"
                f"Total terkirim: {terkirim} pesan/media."
            )
        except Exception as e:
            logger.exception("Error /liveupdate_wa")
            await update.message.reply_text(f"❌ Error kirim ke WhatsApp:\n`{clean_wa_error(e)}`", parse_mode="Markdown")

    async def cmd_closing_sql_wa(update, ctx):
        """/closingsql_wa DD-MM-YYYY [chat_id] — generate closing DB dan kirim ke WhatsApp via WAHA."""
        raw_args = ctx.args or []
        if not raw_args:
            await update.message.reply_text(
                "⚠️ Sertakan tanggal.\nContoh: `/closingsql_wa 03-05-2026` atau `/closingsql_wa 03-05-2026 081234567890`",
                parse_mode="Markdown"
            )
            return

        try:
            tgl_closing = datetime.strptime(raw_args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah. Gunakan: `DD-MM-YYYY`\nContoh: `/closingsql_wa 03-05-2026`",
                parse_mode="Markdown"
            )
            return

        target_chat_id = raw_args[1] if len(raw_args) > 1 else default_chat_id
        if not target_chat_id:
            await update.message.reply_text(
                "⚠️ Nomor atau ID WhatsApp tujuan belum ditentukan.\n"
                f"Gunakan: `/closingsql_wa {raw_args[0]} 081234567890` atau isi `WAHA_TARGET_CHAT_ID` di `config.py`.",
                parse_mode="Markdown"
            )
            return

        # Validasi tanggal ada di DB (pesan detail khusus untuk command manual;
        # core_closingsql_wa mengulang validasi ini juga untuk job terjadwal)
        try:
            tanggal_tersedia = db.query_tanggal_tersedia(tgl_closing)
        except Exception as e:
            await update.message.reply_text(
                f"❌ Gagal cek database:\n`{e}`", parse_mode="Markdown"
            )
            return

        if tgl_closing not in tanggal_tersedia:
            tgl_str = ", ".join(t.strftime("%d-%m-%Y") for t in sorted(tanggal_tersedia)[-5:])
            cutoff_line = ""
            try:
                info = db.query_last_update()
                if info.get("last_update"):
                    cutoff_line = f"\n🕐 Cutoff data: {info['last_update'].strftime('%d-%m-%Y %H:%M:%S')}"
            except Exception as e:
                logger.warning(f"Gagal ambil info cutoff data: {e}")
            await update.message.reply_text(
                f"❌ Data tanggal {tgl_closing.strftime('%d-%m-%Y')} belum tersedia di database."
                f"{cutoff_line}\n"
                f"Tanggal tersedia (5 terakhir): {tgl_str}"
            )
            return

        await update.message.reply_text(
            f"⏳ Generating closing DB {tgl_closing.strftime('%d-%m-%Y')} dan mengirim ke WhatsApp (`{target_chat_id}`) via WAHA..."
        )

        try:
            terkirim = await core_closingsql_wa(kirim_laporan_sql_func, tgl_closing, target_chat_id, send_images)
            await update.message.reply_text(
                f"✅ Laporan /closingsql ({tgl_closing.strftime('%d-%m-%Y')}) berhasil dikirim ke WhatsApp (`{target_chat_id}`)!\n"
                f"Total terkirim: {terkirim} pesan/media."
            )
        except Exception as e:
            logger.exception("Error /closingsql_wa")
            await update.message.reply_text(f"❌ Error kirim ke WhatsApp:\n`{clean_wa_error(e)}`", parse_mode="Markdown")

    async def cmd_agresif_wa(update, ctx):
        """/agresif_wa DD-MM-YYYY [chat_id] — Report New Sales Lokasi Agresif via WAHA."""
        raw_args = ctx.args or []
        if not raw_args:
            await update.message.reply_text(
                "❌ Format: `/agresif_wa DD-MM-YYYY [chat_id]`\nContoh: `/agresif_wa 30-07-2026`",
                parse_mode="Markdown"
            )
            return

        try:
            tgl = datetime.strptime(raw_args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/agresif_wa 30-07-2026`",
                parse_mode="Markdown"
            )
            return

        target_chat_id = raw_args[1] if len(raw_args) > 1 else default_chat_id
        if not target_chat_id:
            await update.message.reply_text(
                "⚠️ Nomor atau ID WhatsApp tujuan belum ditentukan.\n"
                f"Gunakan: `/agresif_wa {raw_args[0]} 081234567890` atau isi `WAHA_TARGET_CHAT_ID` di `config.py`.",
                parse_mode="Markdown"
            )
            return

        await update.message.reply_text(
            f"⏳ Generating Report Kec Agresif {tgl.strftime('%d-%m-%Y')} dan mengirim ke WhatsApp (`{target_chat_id}`) via WAHA...\n"
            f"(tarik data DB 2 bulan + geocoding + kalkulasi, ±1-2 menit)"
        )

        try:
            terkirim = await core_agresif_wa(tgl, target_chat_id, send_images)
            await update.message.reply_text(
                f"✅ Report Kec Agresif ({tgl.strftime('%d-%m-%Y')}) berhasil dikirim ke WhatsApp (`{target_chat_id}`)!\n"
                f"Total terkirim: {terkirim} pesan/media/file."
            )
        except Exception as e:
            logger.exception("Error /agresif_wa")
            await update.message.reply_text(f"❌ Error kirim ke WhatsApp:\n`{clean_wa_error(e)}`", parse_mode="Markdown")

    TelegramCommand("liveupdate_wa", cmd_liveupdate_wa).register(app, timeout_wrapper=_T)
    TelegramCommand("closingsql_wa", cmd_closing_sql_wa).register(app, timeout_wrapper=_T)
    TelegramCommand("agresif_wa", cmd_agresif_wa).register(app, timeout_wrapper=_T)
