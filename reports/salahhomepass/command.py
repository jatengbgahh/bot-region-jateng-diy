"""
reports/salahhomepass/command.py — Alur kirim Monitoring RE : Fallout Salah Tagging/
Salah Homepass berbasis BaseReport (dipakai bersama oleh commands/salahtagging.py dan
commands/salahtagging_wok_old.py).

Sub-report yang didukung:
  - tabel : Tabel PNG Monitoring RE Fallout Salah Tagging/Homepass
  - raw   : File Excel Raw Data Fallout Salah Tagging/Homepass
  - sf    : File Excel Report SF Kontributor Salah Tagging/Homepass
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from io import BytesIO
from typing import Any

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from config import GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from .calculator import (
    export_raw_xlsx,
    export_sf_kontributor_xlsx,
    hitung_salah_homepass,
)
from .renderer import render_salah_homepass

logger = logging.getLogger(__name__)


class ReportSalahTagging(BaseReport):
    """
    /salahtagging DD-MM-YYYY — Monitoring RE : Fallout Salah Tagging/Salah Homepass per WOK/BRANCH.
    """

    command_name = "salahtagging"
    description = "Monitoring RE : Fallout Salah Tagging/Homepass (Tabel + Raw + SF Kontributor)"
    cutoff_table_key = "ordering detail"
    date_mode = "required"
    warn_future_date = True
    example_date = "14-07-2026"
    wok_lama: bool = False

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return (
            f"⏳ Memproses Monitoring RE Fallout Salah Tagging/Homepass "
            f"untuk {tgl.strftime('%d-%m-%Y')}..."
        )

    @sub_report("tabel", "Tabel Monitoring RE Fallout Salah Tagging/Homepass")
    def build_tabel(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("raw", "Excel Raw Data Fallout Salah Tagging/Homepass")
    def build_raw(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("sf", "Excel Report SF Kontributor Salah Tagging/Homepass")
    def build_sf(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        wok_lama = self.wok_lama
        nama_cmd = self.command_name
        judul_lama = " (WOK Lama)" if wok_lama else ""
        sfx_file = "_wok_old" if wok_lama else ""

        raw_args = list(ctx.args or [])
        tgl_closing, selected_subs, err = self.parse_args(raw_args)
        if err is not None:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

        active_subs = set(selected_subs or ("tabel", "raw", "sf"))

        hari_ini = date.today()
        if tgl_closing > hari_ini:
            await update.message.reply_text(
                f"⚠️ Tanggal *{tgl_closing.strftime('%d-%m-%Y')}* belum terjadi "
                f"(hari ini {hari_ini.strftime('%d-%m-%Y')}).\nData mungkin belum lengkap.",
                parse_mode="Markdown",
            )

        await update.message.reply_text(self.format_progress(tgl_closing, selected_subs))

        try:
            cutoff_str = await self.get_cutoff("ordering detail")
            result = await asyncio.to_thread(hitung_salah_homepass, tgl_closing, wok_lama)

            if "tabel" in active_subs:
                img_buf = render_salah_homepass(result, cutoff=cutoff_str)
                top_b = result["top_alerts"]["branch"]
                top_w = result["top_alerts"]["wok"]

                def alert_lines(top: dict) -> str:
                    lines = []
                    if top.get("re"):
                        lines.append(
                            f"⚠️ Top RE Fallout Salah Tagging/Homepass - {top['re'].title()}"
                        )
                    if top.get("pct"):
                        lines.append(
                            f"⚠️ Top % RE Fallout Salah Tagging/Homepass - {top['pct'].title()}"
                        )
                    if top.get("mom"):
                        lines.append(
                            f"⚠️ Top MoM RE Fallout Salah Tagging/Homepass - {top['mom'].title()}"
                        )
                    return "\n".join(lines)

                caption = (
                    f"*Monitoring RE : Fallout Salah Tagging/Homepass{judul_lama}*\n"
                    f"_period : {result['period_label']}_\n\n"
                    f"BRANCH\n{alert_lines(top_b)}\n\n"
                    f"WOK\n{alert_lines(top_w)}"
                )

                img_buf.seek(0)
                await update.message.reply_photo(
                    photo=InputFile(
                        img_buf, filename=f"salah_homepass_report{sfx_file}.png"
                    ),
                    caption=caption,
                    parse_mode="Markdown",
                )
                if update.effective_chat.id != GROUP_ID:
                    img_buf.seek(0)
                    await ctx.bot.send_photo(
                        chat_id=GROUP_ID,
                        photo=InputFile(
                            img_buf, filename=f"salah_homepass_report{sfx_file}.png"
                        ),
                        caption=caption,
                        parse_mode="Markdown",
                    )

            if "raw" in active_subs:
                try:
                    xlsx_bytes, xlsx_filename = await asyncio.to_thread(
                        export_raw_xlsx, tgl_closing, wok_lama
                    )
                    await update.message.reply_document(
                        document=InputFile(BytesIO(xlsx_bytes), filename=xlsx_filename),
                        caption=(
                            f"📦 Raw data Fallout Salah Tagging/Homepass {tgl_closing.strftime('%d-%m-%Y')}\n"
                            f"(baris fallout_reason mengandung \"SALAH TAGGING\" atau \"SALAH HOMEPASS\" saja)\n"
                            f"Sheet MTD = s/d {tgl_closing.strftime('%d-%m-%Y')}  |  "
                            f"Sheet MoM Lalu = periode sama bulan lalu (pembanding MoM)"
                        ),
                    )
                except Exception as e:
                    logger.warning(f"Export raw xlsx Salah Tagging/Homepass gagal: {e}")
                    await update.message.reply_text(
                        f"⚠️ Gagal export raw data:\n`{e}`", parse_mode="Markdown"
                    )

            if "sf" in active_subs:
                try:
                    sf_bytes, sf_filename = await asyncio.to_thread(
                        export_sf_kontributor_xlsx, tgl_closing, wok_lama
                    )
                    caption_sf = (
                        f"📑 *Report SF Kontributor Salah Tagging/Homepass*\n"
                        f"_period : {result['period_label']}_\n"
                        f"Sheet `Table Report SF` = rekap per SF (kontributor terbanyak di atas)\n"
                        f"Sheet `Detail Order` = raw order-nya"
                    )
                    await update.message.reply_document(
                        document=InputFile(BytesIO(sf_bytes), filename=sf_filename),
                        caption=caption_sf,
                        parse_mode="Markdown",
                    )
                    if update.effective_chat.id != GROUP_ID:
                        await ctx.bot.send_document(
                            chat_id=GROUP_ID,
                            document=InputFile(BytesIO(sf_bytes), filename=sf_filename),
                            caption=caption_sf,
                            parse_mode="Markdown",
                        )
                except Exception as e:
                    logger.warning(f"Export SF kontributor gagal: {e}")
                    await update.message.reply_text(
                        f"⚠️ Gagal export report SF kontributor:\n`{e}`",
                        parse_mode="Markdown",
                    )

            if update.effective_chat.id != GROUP_ID:
                await update.message.reply_text(
                    "✅ Monitoring RE Fallout Salah Tagging/Homepass sudah dikirim ke grup manajemen."
                )

        except Exception as e:
            logger.exception(f"Error /{nama_cmd}")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


class ReportSalahTaggingWokOld(ReportSalahTagging):
    command_name = "salahtagging_wok_old"
    description = "Monitoring RE : Fallout Salah Tagging/Homepass — WOK Lama (16 WOK)"
    wok_lama = True


async def jalankan_salahhomepass(update, ctx, wok_lama: bool = False, get_cutoff_fn=None):
    cls = ReportSalahTaggingWokOld if wok_lama else ReportSalahTagging
    await cls(get_cutoff_fn=get_cutoff_fn).handle(update, ctx)
