"""
reports/murmer/command.py — Handler Telegram /murmer [DD-MM-YYYY] berbasis BaseReport.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

from telegram import InputFile, Update
from telegram.ext import CommandHandler, ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator, query
from .raw_export import build_raw_excel
from .renderer import render_murmer

logger = logging.getLogger(__name__)


def _build_caption(df, cutoff, region: str = "JATENG-DIY") -> str:
    row = df[df["REGION"] == region]
    if row.empty:
        return (
            f"<b>EZNET Wireless MURMER</b>\n{cutoff.strftime('%d-%b-%Y')}\n\n"
            f"⚠️ Region {region} tidak ada di daftar target."
        )
    row = row.iloc[0]

    df_sorted = df.sort_values("ACH_YTD", ascending=False).reset_index(drop=True)
    rank = df_sorted[df_sorted["REGION"] == region].index[0] + 1
    total_regions = len(df)

    return (
        f"<b>EZNET Wireless MURMER | {region}</b>\n"
        f"{cutoff.strftime('%d-%b-%Y')}\n\n"
        f"Ach {region} YTD: <b>{row['ACH_YTD']:.2f}%</b>\n\n"
        f"Peringkat <b>{rank}</b> dari <b>{total_regions}</b> Region yang tersedia Paket "
        f"EZNET Wireless Murmer. Mohon bantuannya untuk memaksimalkan potensi produk yang "
        f"terbuka khusus di City Banyumas.\n\n"
        f"Terima kasih."
    )


class ReportMurmer(BaseReport):
    """
    /murmer [DD-MM-YYYY] [raw] — Report EZNET Wireless Murmer.
    Sub-report:
      - tabel : Gambar report EZNET Wireless Murmer
      - raw   : File Excel raw data JATENG-DIY (otomatis dikirim pada hari Senin atau jika diminta)
    """

    command_name = "murmer"
    description = "Report EZNET Wireless Murmer"
    date_mode = "none"
    forward_to_group = False
    example_date = "20-09-2026"

    @sub_report("tabel", "Tabel Report EZNET Wireless Murmer")
    def build_tabel(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        cutoff = data["cutoff"]
        df_metrics = data["df_metrics"]
        img_buf = render_murmer(df_metrics, cutoff)
        caption = _build_caption(df_metrics, cutoff)
        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename=f"eznet_murmer_{cutoff.strftime('%Y%m%d')}.png",
            caption=caption,
            parse_mode="HTML",
        )

    @sub_report("raw", "Excel Data Raw EZNET Wireless Murmer JATENG-DIY", default=False)
    def build_raw(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        if "buf_raw" not in data:
            return None
        cutoff = data["cutoff"]
        return ReportOutput(
            kind="document",
            buf=data["buf_raw"],
            filename=data["nama_raw"],
            caption=f"📎 Data raw EZNET Wireless Murmer JATENG-DIY (cutoff {cutoff.strftime('%d-%m-%Y')})",
            parse_mode=None,
        )

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        from config import MURMER_PRODUCT_KEYWORD, MURMER_TARGETS, MURMER_YTD_START_MONTH

        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        paksa_raw = any(a.lower() == "raw" for a in raw_args)
        only_tabel = any(a.lower() == "tabel" for a in raw_args) and not paksa_raw
        args = [a for a in raw_args if a.lower() not in ("raw", "tabel")]

        if args:
            try:
                tgl = datetime.strptime(args[0], "%d-%m-%Y").date()
            except ValueError:
                await update.message.reply_text(
                    "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/murmer 20-09-2026`",
                    parse_mode="Markdown",
                )
                return
        else:
            tgl = None

        kirim_raw = (paksa_raw or date.today().weekday() == 0) and not only_tabel
        cutoff, month_start, _total_days = calculator.resolve_cutoff(tgl)

        await update.message.reply_text(
            f"⏳ Menyusun Report EZNET Wireless Murmer {cutoff.strftime('%d-%m-%Y')}..."
        )

        try:
            df_raw = await asyncio.to_thread(
                query.fetch_data, cutoff, MURMER_YTD_START_MONTH, MURMER_PRODUCT_KEYWORD
            )
            if df_raw.empty:
                await update.message.reply_text(
                    f"⚠️ Data EZNET Murmer kosong untuk cutoff {cutoff.strftime('%d-%m-%Y')}."
                )
                return

            df_metrics = calculator.calculate_metrics(
                df_raw, cutoff, month_start, MURMER_TARGETS
            )
            img_buf = render_murmer(df_metrics, cutoff)
            caption = _build_caption(df_metrics, cutoff)

            await update.message.reply_photo(
                photo=InputFile(img_buf, filename=f"eznet_murmer_{cutoff.strftime('%Y%m%d')}.png"),
                caption=caption,
                parse_mode="HTML",
            )

            if kirim_raw:
                buf_raw, nama_raw = await asyncio.to_thread(build_raw_excel, df_raw, cutoff)
                await update.message.reply_document(
                    document=InputFile(buf_raw, filename=nama_raw),
                    caption=f"📎 Data raw EZNET Wireless Murmer JATENG-DIY (cutoff {cutoff.strftime('%d-%m-%Y')})",
                )
        except Exception as e:
            logger.exception("Error /murmer")
            await update.message.reply_text(
                f"❌ Error:\n`{str(e)[:600]}`", parse_mode="Markdown"
            )


def register_handlers(app, timeout_wrapper=None):
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    try:
        from config import MURMER_PRODUCT_KEYWORD, MURMER_TARGETS, MURMER_YTD_START_MONTH  # noqa: F401
    except ImportError:
        logger.warning(
            "[murmer] MURMER_TARGETS/YTD_START_MONTH/PRODUCT_KEYWORD tidak ada di "
            "config.py — /murmer tidak didaftarkan"
        )
        return None

    report = ReportMurmer()
    cmd_murmer = report.handle
    app.add_handler(CommandHandler("murmer", _T(cmd_murmer)))
    return cmd_murmer
