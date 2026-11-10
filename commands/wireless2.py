"""
commands/wireless2.py — Handler Telegram /wireless2 dan /wirelesschannel2 DD-MM-YYYY berbasis BaseReport.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from reports.wireless2 import (
    build_caption as caption_wireless,
    hitung_wireless2,
    render_wireless2,
)
from reports.wirelesschannel2 import (
    build_caption as caption_channel,
    hitung_wireless_channel2,
    render_wireless_channel2,
)

try:
    from config import MURMER_PRODUCT_KEYWORD as EXCLUDE_KEYWORD
except ImportError:
    EXCLUDE_KEYWORD = "murmer"

logger = logging.getLogger(__name__)


class _Wireless2Base(BaseReport):
    date_mode = "required"
    warn_future_date = False
    example_date = "20-09-2026"

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
                f"❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/{self.command_name} {self.example_date}`",
            )
        return tgl, (selected_subs or None), None


class ReportWireless2(_Wireless2Base):
    command_name = "wireless2"
    description = f"Performance MtD IO-RE-PS EZNet Wireless (tanpa {EXCLUDE_KEYWORD.title()})"

    def __init__(
        self,
        *,
        get_target_fn: Callable[[], Any] | None = None,
        get_cutoff_fn: Callable[[], Any] | None = None,
        kirim_foto_fn: Callable[..., Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_target_fn = get_target_fn
        self._get_cutoff_raw_fn = get_cutoff_fn
        self._kirim_foto_fn = kirim_foto_fn

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return (
            f"⏳ Menyusun Performance MtD EZNet Wireless (tanpa {EXCLUDE_KEYWORD.title()}) "
            f"{tgl.strftime('%d-%m-%Y')}..."
        )

    @sub_report("main", "Tabel Performance MtD EZNet Wireless (tanpa Murmer)")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        img_buf = render_wireless2(result, cutoff=data["cutoff"])
        caption = caption_wireless(result)
        fname = f"performance_wireless2_{tgl.strftime('%Y%m%d')}.png"
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
            df_target = await self._get_target_fn() if self._get_target_fn else None
            result = await asyncio.to_thread(
                hitung_wireless2, df_target, tgl, EXCLUDE_KEYWORD
            )
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
                    label="wireless2",
                )
                if update.effective_chat.id != GROUP_ID:
                    await self._kirim_foto_fn(
                        ctx.bot,
                        GROUP_ID,
                        out.buf,
                        out.filename,
                        caption=out.caption,
                        label="wireless2_grup",
                    )
                    await update.message.reply_text("✅ Laporan sudah dikirim ke grup manajemen.")
            else:
                await self.send_outputs(update, ctx, [out])
        except Exception as e:
            logger.exception("Error /wireless2")
            await update.message.reply_text(f"❌ Error:\n`{str(e)[:600]}`", parse_mode="Markdown")


class ReportWirelessChannel2(_Wireless2Base):
    command_name = "wirelesschannel2"
    description = f"PS EZNet Wireless by Channel (tanpa {EXCLUDE_KEYWORD.title()})"

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

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return (
            f"⏳ Menyusun PS EZNet Wireless by Channel (tanpa {EXCLUDE_KEYWORD.title()}) "
            f"{tgl.strftime('%d-%m-%Y')}..."
        )

    @sub_report("main", "Tabel PS EZNet Wireless by Channel (tanpa Murmer)")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        img_buf = render_wireless_channel2(result, cutoff=data["cutoff"])
        caption = caption_channel(result)
        fname = f"ps_wireless_channel2_{tgl.strftime('%Y%m%d')}.png"
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
            result = await asyncio.to_thread(
                hitung_wireless_channel2, tgl, EXCLUDE_KEYWORD
            )
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
                    label="wireless_channel2",
                )
                if update.effective_chat.id != GROUP_ID:
                    await self._kirim_foto_fn(
                        ctx.bot,
                        GROUP_ID,
                        out.buf,
                        out.filename,
                        caption=out.caption,
                        label="wireless_channel2_grup",
                    )
                    await update.message.reply_text("✅ Laporan sudah dikirim ke grup manajemen.")
            else:
                await self.send_outputs(update, ctx, [out])
        except Exception as e:
            logger.exception("Error /wirelesschannel2")
            await update.message.reply_text(f"❌ Error:\n`{str(e)[:600]}`", parse_mode="Markdown")


def register_handlers(
    app,
    timeout_wrapper=None,
    get_target_fn=None,
    get_cutoff_fn=None,
    kirim_foto_fn=None,
):
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    rep_w2 = ReportWireless2(
        get_target_fn=get_target_fn,
        get_cutoff_fn=get_cutoff_fn,
        kirim_foto_fn=kirim_foto_fn,
    )
    rep_wc2 = ReportWirelessChannel2(
        get_cutoff_fn=get_cutoff_fn,
        kirim_foto_fn=kirim_foto_fn,
    )
    cmd_wireless2 = rep_w2.handle
    cmd_wirelesschannel2 = rep_wc2.handle
    app.add_handler(CommandHandler("wireless2", _T(cmd_wireless2)))
    app.add_handler(CommandHandler("wirelesschannel2", _T(cmd_wirelesschannel2)))
    return cmd_wireless2, cmd_wirelesschannel2
