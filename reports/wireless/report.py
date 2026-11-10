"""
reports/wireless/report.py — Implementasi BaseReport untuk /wireless (Performance MtD EZNet Wireless).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable

from telegram import Update
from telegram.ext import ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_wireless, renderer_wireless

logger = logging.getLogger(__name__)


class ReportWireless(BaseReport):
    """
    /wireless DD-MM-YYYY — Performance MtD IO-RE-PS EZNet Wireless per WOK/BRANCH.
    """

    command_name = "wireless"
    description = "Performance MtD IO-RE-PS EZNet Wireless per WOK/BRANCH"
    date_mode = "required"
    warn_future_date = False
    example_date = "20-09-2026"

    def __init__(
        self,
        *,
        get_target_fn: Callable[[], Any] | None = None,
        get_cutoff_raw_fn: Callable[[], Any] | None = None,
        kirim_foto_retry_fn: Callable[..., Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_target_fn = get_target_fn
        self._get_cutoff_raw_fn = get_cutoff_raw_fn
        self._kirim_foto_retry_fn = kirim_foto_retry_fn

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
                "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/wireless 20-09-2026`",
            )
        return tgl, (selected_subs or None), None

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Menyusun Performance MtD EZNet Wireless {tgl.strftime('%d-%m-%Y')}..."

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        df_target = None
        if self._get_target_fn is not None:
            res_t = self._get_target_fn()
            df_target = await res_t if asyncio.iscoroutine(res_t) else res_t

        result = await asyncio.to_thread(calculator_wireless.hitung_wireless, df_target, tgl)
        cutoff_str = None
        if self._get_cutoff_raw_fn is not None:
            res_c = self._get_cutoff_raw_fn()
            cutoff_str = await res_c if asyncio.iscoroutine(res_c) else res_c

        return {"result": result, "cutoff": cutoff_str}

    @sub_report("main", "Tabel Performance MtD EZNet Wireless per WOK/BRANCH")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        img_buf = renderer_wireless.render_wireless(result, cutoff=data["cutoff"])
        caption = calculator_wireless.build_caption(result)
        fname = f"performance_wireless_{tgl.strftime('%Y%m%d')}.png"
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
            data = await self.fetch_data(tgl, update, ctx, selected_subs=selected_subs)
            out = self.build_main(data, tgl)
            if self._kirim_foto_retry_fn is not None:
                await self._kirim_foto_retry_fn(
                    ctx.bot,
                    update.effective_chat.id,
                    out.buf,
                    out.filename,
                    caption=out.caption,
                    label="wireless",
                )
                if self.forward_to_group and update.effective_chat.id != self.group_id:
                    await self._kirim_foto_retry_fn(
                        ctx.bot,
                        self.group_id,
                        out.buf,
                        out.filename,
                        caption=out.caption,
                        label="wireless_grup",
                    )
                    await update.message.reply_text("✅ Laporan sudah dikirim ke grup manajemen.")
            else:
                await self.send_outputs(update, ctx, [out])
                if self.forward_to_group and update.effective_chat.id != self.group_id:
                    await update.message.reply_text("✅ Laporan sudah dikirim ke grup manajemen.")
        except Exception as e:
            logger.exception("Error /wireless")
            await update.message.reply_text(f"❌ Error:\n`{str(e)[:600]}`", parse_mode="Markdown")
