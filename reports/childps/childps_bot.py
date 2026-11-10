"""
childps_bot.py — Handler Telegram report Child per PS Telkomsel One by WOK (/childps).

Cara pakai di Telegram:
  • Kirim file hasil SQL (.csv atau .zip berisi .csv) dengan caption:
        /childps                → cutoff otomatis = event_date terakhir di file
        /childps DD-MM-YYYY     → cutoff tanggal tertentu
    Data file disimpan di memori, jadi sesudahnya cukup ketik /childps [DD-MM-YYYY].
  • Ketik /childps [DD-MM-YYYY] tanpa file:
        - pakai file terakhir yang diupload (kalau ada), atau
        - query agregat langsung ke MySQL (childps_sql.py; tabel tselone_to_msisdn_YYYYMM)
          (default tanggal = kemarin / closing H-1).
  • Terjadwal 08:00 topic GTM (config.JADWAL_LAPORAN). Mode /modequery rajawali: data dari export agregat
    SQL Console Rajawali (utils/rajawali_auto.py --only childps).

Hitungan: calculator_childps.py, gambar: renderer_childps.py.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta

from telegram import InputFile, Update
from telegram.ext import ContextTypes

import calculator_childps
import config_childps
import renderer_childps
from config import GROUP_ID

logger = logging.getLogger(__name__)

_childps_df = None          # data upload terakhir
_childps_export = None      # export agregat Rajawali (diisi pasang_export, hanya proses runner)
_childps_upload_time = None
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024   # batas download file bot Telegram


def is_childps_upload(message) -> bool:
    return (message.caption or "").strip().lower().startswith("/childps")


def _parse_tgl(teks: str):
    """'/childps 03-11-2026' → date(2026, 11, 3); tanpa tanggal → None."""
    parts = (teks or "").split()
    if len(parts) < 2:
        return None
    return datetime.strptime(parts[1], "%d-%m-%Y").date()


async def _kirim(update: Update, ctx: ContextTypes.DEFAULT_TYPE, df, tgl, sumber: str):
    res = await asyncio.to_thread(calculator_childps.hitung_childps, df, tgl)
    img = await asyncio.to_thread(renderer_childps.render_childps, res)
    caption = calculator_childps.buat_caption(res)
    fname = f"childps_tselone_{res['tgl'].strftime('%Y%m%d')}.png"

    img.seek(0)
    await update.message.reply_photo(photo=InputFile(img, filename=fname), caption=caption)
    if config_childps.CHILDPS_KIRIM_KE_GRUP and update.effective_chat.id != GROUP_ID:
        img.seek(0)
        await ctx.bot.send_photo(chat_id=GROUP_ID, photo=InputFile(img, filename=fname),
                                 caption=caption)
        await update.message.reply_text("✅ Report Child per PS sudah dikirim ke grup.")
    if res["tanpa_wok"]:
        await update.message.reply_text(
            f"ℹ️ {res['tanpa_wok']:,} PS tidak masuk WOK mana pun "
            f"(city & cluster kosong / di luar mapping) — tidak dihitung. Sumber: {sumber}")


async def handle_childps_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE, doc):
    """File (.csv/.zip) dengan caption /childps [DD-MM-YYYY]."""
    global _childps_df, _childps_upload_time
    msg = update.message
    fname = doc.file_name or ""
    if not fname.lower().endswith((".csv", ".zip")):
        await msg.reply_text("⚠️ File untuk /childps harus .csv atau .zip berisi .csv")
        return
    if doc.file_size and doc.file_size > MAX_DOWNLOAD_BYTES:
        await msg.reply_text(
            f"❌ File {fname} ({doc.file_size / 1048576:.1f} MB) melebihi batas 20 MB bot Telegram. "
            "Kirim versi .zip supaya lebih kecil.")
        return
    try:
        tgl = _parse_tgl(msg.caption)
    except ValueError:
        await msg.reply_text("❌ Format tanggal salah. Contoh caption: /childps 03-11-2026")
        return

    await msg.reply_text("⏳ Membaca file & menghitung Child per PS...")
    try:
        tg_file = await doc.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
        df = await asyncio.to_thread(calculator_childps.baca_file, file_bytes, fname)
        await _kirim(update, ctx, df, tgl, f"file {fname}")
        _childps_df, _childps_upload_time = df, datetime.now()
    except Exception as e:
        logger.exception("Error handle_childps_upload")
        await msg.reply_text(f"❌ Gagal membuat report Child per PS:\n{e}")


def pasang_export(path: str):
    """Dipakai report_pagi_csv.py (jalur Rajawali): muat export agregat childps_sql.py ke memori, lalu
    cmd_childps terjadwal memakainya (bukan query DB)."""
    global _childps_export
    with open(path, "rb") as f:
        _childps_export = calculator_childps.baca_file(f.read(), os.path.basename(path))
    return len(_childps_export)


def _tgl_dari_args(ctx):
    for a in (ctx.args or []):
        return datetime.strptime(a, "%d-%m-%Y").date()
    return None


async def cmd_childps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/childps [DD-MM-YYYY]. Dipakai juga oleh jadwal (ctx = SimpleNamespace tanpa .application).
    Urutan sumber data:
      1. export Rajawali yang dimuat report_pagi_csv.py (pasang_export)
      2. file upload terakhir — HANYA command manual (jalur terjadwal tidak boleh memakai file basi)
      3. query agregat langsung ke MySQL (childps_sql.py; tabel tselone_to_msisdn_YYYYMM)"""
    from .report import ReportChildPS
    await ReportChildPS().handle(update, ctx)
