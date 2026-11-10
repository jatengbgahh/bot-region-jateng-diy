"""
reports/wireless_channel/command.py — Handler Telegram /wirelesschannel DD-MM-YYYY berbasis BaseReport.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable

from telegram import Update
from utils.command_registry import TelegramCommand
from telegram.ext import CommandHandler, ContextTypes

from config import GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from .calculator import build_caption, hitung_wireless_channel
from .renderer import render_wireless_channel

logger = logging.getLogger(__name__)

REPORT_TITLE = "PS EZNet Wireless Jateng-DIY by Channel"


class ReportWirelessChannel(BaseReport):
    """
    /wirelesschannel DD-MM-YYYY — PS EZNet Wireless by Channel (MtD + MoM).
    """

    command_name = "wirelesschannel"
    description = REPORT_TITLE
    date_mode = "required"
    warn_future_date = False
    example_date = "20-09-2026"

    def __init__(
        self,
        *,
        get_cutoff_fn: Callable[[], Any] | None = None,
        kirim_foto_fn: Callable[..., Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_cutoff_raw_fn = get_cutoff_fn
        self._kirim_foto_fn = kirim_foto_fn

    def parse_args(
        self, raw_args: list[str]
    ) -> tuple[date | None, list[str] | None, str | None]:
        sub_map = self.get_sub_reports()
        selected_subs: list[str] = []
        date_token: str | None = None

        for token in raw_args or []:
            low = token.strip().lower()
            if not low:
                continue
            if low in ("help", "list", "?"):
                return None, None, self.format_help()
            if low in sub_map:
                if low not in selected_subs:
                    selected_subs.append(low)
                continue
            if date_token is None:
                date_token = token.strip()
            else:
                return None, None, self.usage_text()

        if date_token is None:
            return None, None, self.usage_text()

        raw = date_token.replace("/", "-").replace(".", "-")
        try:
            tgl = datetime.strptime(raw, "%d-%m-%Y").date()
        except ValueError:
            return (
                None,
                None,
                "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/wirelesschannel 20-09-2026`",
            )
        return tgl, (selected_subs or None), None

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Menyusun {REPORT_TITLE} {tgl.strftime('%d-%m-%Y')}..."

    @sub_report("main", "Tabel PS EZNet Wireless by Channel")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        img_buf = render_wireless_channel(result, cutoff=data["cutoff"])
        caption = build_caption(result)
        fname = f"ps_wireless_channel_{tgl.strftime('%Y%m%d')}.png"
        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename=fname,
            caption=caption,
            parse_mode=None,
        )

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        tgl, selected_subs, err = self.parse_args(raw_args)
        if err is not None:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

        await update.message.reply_text(self.format_progress(tgl, selected_subs))
        try:
            result = await asyncio.to_thread(hitung_wireless_channel, tgl)
            cutoff_str = (
                await self._get_cutoff_raw_fn() if self._get_cutoff_raw_fn else None
            )
            out = self.build_main({"result": result, "cutoff": cutoff_str}, tgl)
            if self._kirim_foto_fn:
                await self._kirim_foto_fn(
                    ctx.bot,
                    update.effective_chat.id,
                    out.buf,
                    out.filename,
                    caption=out.caption,
                    label="wireless_channel",
                )
                if update.effective_chat.id != GROUP_ID:
                    await self._kirim_foto_fn(
                        ctx.bot,
                        GROUP_ID,
                        out.buf,
                        out.filename,
                        caption=out.caption,
                        label="wireless_channel_grup",
                    )
                    await update.message.reply_text("✅ Laporan sudah dikirim ke grup manajemen.")
            else:
                await self.send_outputs(update, ctx, [out])
        except Exception as e:
            logger.exception("Error /wirelesschannel")
            await update.message.reply_text(f"❌ Error:\n`{str(e)[:600]}`", parse_mode="Markdown")


def register_handlers(app, timeout_wrapper=None, get_cutoff_fn=None, kirim_foto_fn=None):
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    report = ReportWirelessChannel(get_cutoff_fn=get_cutoff_fn, kirim_foto_fn=kirim_foto_fn)
    cmd_wireless_channel = report.handle
    TelegramCommand("wirelesschannel", cmd_wireless_channel).register(app, timeout_wrapper=_T)
    return cmd_wireless_channel
