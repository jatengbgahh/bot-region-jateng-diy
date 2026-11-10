"""
commands/kategori_paket.py — Handler Telegram /kategoripaket DD-MM-YYYY berbasis BaseReport.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import db
from config import GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from reports.kategori_paket import hitung_kategori_paket, render_kategori_paket

logger = logging.getLogger(__name__)


class ReportKategoriPaket(BaseReport):
    """
    /kategoripaket DD-MM-YYYY — Sales by Kategori Paket IndiHome Jateng-DIY (sumber DB).
    """

    command_name = "kategoripaket"
    description = "Sales by Kategori Paket IndiHome Jateng-DIY"
    date_mode = "required"
    warn_future_date = False
    example_date = "03-05-2026"

    def __init__(self, *, kirim_foto_fn: Callable[..., Any] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._kirim_foto_fn = kirim_foto_fn

    def usage_text(self) -> str:
        return f"⚠️ Sertakan tanggal.\nContoh: `/{self.command_name} {self.example_date}`"

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Menyusun Sales by Kategori Paket {tgl.strftime('%d-%m-%Y')}..."

    @sub_report("main", "Tabel Sales by Kategori Paket IndiHome Jateng-DIY")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result_kp = data["result"]
        img_kp = data["img"]
        caption = (
            f"📊 Sales by Kategori Paket IndiHome Jateng-DIY\n"
            f"MtD {tgl.strftime('%d-%m-%Y')}  |  "
            f"MoM vs {result_kp['bl_label']}"
        )
        return ReportOutput(
            kind="photo",
            buf=img_kp,
            filename="kategori_paket_report.png",
            caption=caption,
            parse_mode=None,
        )

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        if not raw_args:
            await update.message.reply_text(self.usage_text(), parse_mode="Markdown")
            return

        try:
            tgl_closing = datetime.strptime(raw_args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah. Gunakan: `DD-MM-YYYY`",
                parse_mode="Markdown",
            )
            return

        try:
            tanggal_tersedia = await asyncio.to_thread(
                db.query_tanggal_tersedia, tgl_closing
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Gagal cek database:\n`{e}`", parse_mode="Markdown"
            )
            return

        if tgl_closing not in tanggal_tersedia:
            tgl_str = ", ".join(
                t.strftime("%d-%m-%Y") for t in sorted(tanggal_tersedia)[-5:]
            )
            await update.message.reply_text(
                f"❌ Data tanggal {tgl_closing.strftime('%d-%m-%Y')} belum tersedia di database.\n"
                f"Tanggal tersedia (5 terakhir): {tgl_str}"
            )
            return

        await update.message.reply_text(self.format_progress(tgl_closing, None))

        try:
            try:
                info = await asyncio.to_thread(db.query_last_update)
                last_update = info.get("last_update")
                last_date = info.get("last_date")
                if last_update:
                    cutoff_str = last_update.strftime("%d-%m-%Y %H:%M")
                    if last_date and last_date < tgl_closing:
                        cutoff_str = (
                            f"⚠️ data {tgl_closing.strftime('%d-%m-%Y')} belum tersedia, "
                            f"pakai data terakhir {cutoff_str}"
                        )
                else:
                    cutoff_str = None
            except Exception as e:
                logger.warning(f"Gagal ambil info cutoff data: {e}")
                cutoff_str = None

            result_kp = await asyncio.to_thread(hitung_kategori_paket, tgl_closing)
            img_kp = await asyncio.to_thread(render_kategori_paket, result_kp, cutoff_str)
            out = self.build_main({"result": result_kp, "img": img_kp}, tgl_closing)

            if self._kirim_foto_fn:
                await self._kirim_foto_fn(
                    ctx.bot,
                    update.effective_chat.id,
                    out.buf,
                    out.filename,
                    caption=out.caption,
                    label="kategori_paket",
                )
                if update.effective_chat.id != GROUP_ID:
                    await self._kirim_foto_fn(
                        ctx.bot,
                        GROUP_ID,
                        out.buf,
                        out.filename,
                        caption=out.caption,
                        label="kategori_paket_grup",
                    )
            else:
                await self.send_outputs(update, ctx, [out])
        except Exception as e:
            logger.exception("Error /kategoripaket")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


def register_handlers(app, timeout_wrapper=None, kirim_foto_fn=None):
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    report = ReportKategoriPaket(kirim_foto_fn=kirim_foto_fn)
    app.add_handler(CommandHandler("kategoripaket", _T(report.handle)))
