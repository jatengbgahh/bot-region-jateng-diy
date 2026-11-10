"""
commands/clockin_sf_teritory.py — Handler Telegram /clockin_sf_teritory dan /homepass_raw berbasis BaseReport.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

from telegram import InputFile, Update
from utils.command_registry import TelegramCommand
from telegram.ext import CommandHandler, ContextTypes

from config import GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from reports.clockin_sf_teritory.generator import (
    ambil_url_sf_teritory,
    buat_report,
    label_mtd,
    simpan_url_sf_teritory,
)

logger = logging.getLogger(__name__)
BATAS_KIRIM_MB = 49
BATAS_CAPTION = 1024


def _tanggal(args):
    filtered = [
        a
        for a in (args or [])
        if not a.lower().startswith("file=") and a.lower() not in ("tabel", "excel", "main")
    ]
    if filtered:
        raw = filtered[0].replace("/", "-").replace(".", "-")
        return datetime.strptime(raw, "%d-%m-%Y").date()
    return date.today() - timedelta(days=1)


def _file_homepass(tgl: date, args=()):
    for a in args or ():
        if a.lower().startswith("file="):
            return a[5:]
    p = os.environ.get("CLOCKIN_HOMEPASS_FILE")
    if p:
        return p
    import djp_homepass
    return djp_homepass.cari_file(tgl)


async def _kirim(update, ctx, fn_nama: str, **kw):
    """Kirim ke chat peminta; kalau bukan grup koordinasi, salin ke GROUP_ID."""
    baca = lambda f: open(f, "rb").read() if isinstance(f, str) else f
    ke_grup = update.effective_chat.id != GROUP_ID
    for idx in range(2 if ke_grup else 1):
        data = {
            k: (InputFile(baca(v[0]), filename=v[1]) if isinstance(v, tuple) else v)
            for k, v in kw.items()
        }
        if idx == 0:
            await getattr(update.message, "reply_" + fn_nama)(**data)
        else:
            await getattr(ctx.bot, "send_" + fn_nama)(chat_id=GROUP_ID, **data)


class ReportClockinSFTeritory(BaseReport):
    """
    /clockin_sf_teritory [DD-MM-YYYY] [file=<path>] — Report Clock-in SF Teritory MTD.
    Sub-report:
      - tabel : Gambar PNG + teks update Clock-in SF Teritory MTD
      - excel : File Excel rekap Clock-in SF Teritory MTD
    """

    command_name = "clockin_sf_teritory"
    description = "Report Clock-in SF Teritory MTD (PNG + Teks + Excel)"
    date_mode = "optional"
    default_date_offset = 1
    example_date = "27-10-2026"

    @sub_report("tabel", "Gambar PNG + Teks Update Clock-in SF Teritory MTD")
    def build_tabel(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("excel", "File Excel Report Clock-in SF Teritory MTD")
    def build_excel(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            help_text = (
                self.format_help()
                + f"\n\n🔗 *URL SF Teritory Aktif:*\n`{ambil_url_sf_teritory()}`\n"
                + "Untuk mengganti URL tanpa restart bot:\n"
                + "`/clockin_sf_teritory url=https://...`"
            )
            await update.message.reply_text(help_text, parse_mode="Markdown")
            return

        for a in list(raw_args):
            if a.lower().startswith("url="):
                new_url = a[4:].strip()
                simpan_url_sf_teritory(new_url)
                raw_args.remove(a)
                if not raw_args:
                    await update.message.reply_text(
                        f"✅ URL SF Teritory berhasil diperbarui (tanpa restart bot):\n`{new_url}`",
                        parse_mode="Markdown",
                    )
                    return

        sub_map = self.get_sub_reports()
        selected_subs = [a.lower() for a in raw_args if a.lower() in sub_map]
        active_subs = set(selected_subs or ("tabel", "excel"))

        try:
            tgl = _tanggal(raw_args)
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\n"
                "Contoh: `/clockin_sf_teritory 27-10-2026`",
                parse_mode="Markdown",
            )
            return

        path = _file_homepass(tgl, raw_args)
        if not path or not os.path.exists(path):
            await update.message.reply_text(
                f"❌ File detail-homepass untuk {tgl:%d-%m-%Y} tidak ditemukan. Jalankan scraping SELA dulu "
                f"(python -m utils.sela_scraper --auto)."
            )
            return

        await update.message.reply_text(
            f"⏳ Menyusun Report Clock-in SF Teritory MTD {label_mtd(tgl)}..."
        )
        try:
            h = await asyncio.to_thread(buat_report, path, tgl)
            r = h["ringkasan"]
            if not r.get("sf"):
                raise RuntimeError("Teks report tidak terbaca: " + h["teks"][:200])
            logger.info(f"[clockin_sf_teritory] {h['periode']} | {r}")

            if "tabel" in active_subs:
                if len(h["teks"]) <= BATAS_CAPTION:
                    await _kirim(
                        update,
                        ctx,
                        "photo",
                        photo=(h["png"], os.path.basename(h["png"])),
                        caption=h["teks"],
                    )
                else:
                    await _kirim(
                        update,
                        ctx,
                        "photo",
                        photo=(h["png"], os.path.basename(h["png"])),
                    )
                    await update.message.reply_text(h["teks"])
                    if update.effective_chat.id != GROUP_ID:
                        await ctx.bot.send_message(chat_id=GROUP_ID, text=h["teks"])

            if "excel" in active_subs:
                await _kirim(
                    update,
                    ctx,
                    "document",
                    document=(h["xlsx"], os.path.basename(h["xlsx"])),
                )
        except Exception as e:
            logger.exception("Error /clockin_sf_teritory")
            await update.message.reply_text(f"❌ Error:\n{str(e)[:600]}")


class ReportHomepassRaw(BaseReport):
    """
    /homepass_raw [DD-MM-YYYY] — Kirim file detail-homepass mentah (hasil scraping SELA).
    """

    command_name = "homepass_raw"
    description = "Raw Data Clockin Homepass MTD (hasil scraping SELA)"
    date_mode = "optional"
    default_date_offset = 1
    example_date = "27-10-2026"

    @sub_report("main", "File Excel Raw Data Clockin Homepass MTD")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            help_text = (
                self.format_help()
                + f"\n\n🔗 *URL SF Teritory Aktif:*\n`{ambil_url_sf_teritory()}`\n"
                + "Untuk mengganti URL tanpa restart bot:\n"
                + "`/clockin_sf_teritory url=https://...`"
            )
            await update.message.reply_text(help_text, parse_mode="Markdown")
            return

        for a in list(raw_args):
            if a.lower().startswith("url="):
                new_url = a[4:].strip()
                simpan_url_sf_teritory(new_url)
                raw_args.remove(a)
                if not raw_args:
                    await update.message.reply_text(
                        f"✅ URL SF Teritory berhasil diperbarui (tanpa restart bot):\n`{new_url}`",
                        parse_mode="Markdown",
                    )
                    return

        try:
            tgl = _tanggal(raw_args)
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`", parse_mode="Markdown"
            )
            return

        path = _file_homepass(tgl, raw_args)
        if not path or not os.path.exists(path):
            await update.message.reply_text(
                f"❌ File detail-homepass untuk {tgl:%d-%m-%Y} tidak ditemukan."
            )
            return

        mb = os.path.getsize(path) / 1048576
        if mb > BATAS_KIRIM_MB:
            await update.message.reply_text(
                f"⚠️ {os.path.basename(path)} ({mb:.1f} MB) melebihi batas kirim Bot API "
                f"({BATAS_KIRIM_MB} MB) — tidak dikirim."
            )
            return

        caption = f"Raw Data Clockin Homepass MTD {label_mtd(tgl)}"
        try:
            await _kirim(
                update,
                ctx,
                "document",
                document=(path, os.path.basename(path)),
                caption=caption,
            )
        except Exception as e:
            logger.exception("Error /homepass_raw")
            await update.message.reply_text(f"❌ Error:\n{str(e)[:600]}")


def register_handlers(app, timeout_wrapper=None):
    """Daftarkan /clockin_sf_teritory dan /homepass_raw. Return (cmd_clockin_sf_teritory, cmd_homepass_raw)."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    cmd_clockin_sf_teritory = ReportClockinSFTeritory().handle
    cmd_homepass_raw = ReportHomepassRaw().handle
    TelegramCommand("clockin_sf_teritory", cmd_clockin_sf_teritory).register(app, timeout_wrapper=_T)
    TelegramCommand("homepass_raw", cmd_homepass_raw).register(app, timeout_wrapper=_T)
    return cmd_clockin_sf_teritory, cmd_homepass_raw
