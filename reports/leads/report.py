"""
reports/leads/report.py — Implementasi BaseReport untuk /leads (Progress Caring Leads IO).
"""

from __future__ import annotations

import logging
from datetime import date
from io import BytesIO
from typing import Any

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from . import leads_browser

logger = logging.getLogger(__name__)


class ReportLeads(BaseReport):
    """
    /leads — Progress Caring Leads IO via Playwright login ke jatenggayeng.id.
    """

    command_name = "leads"
    description = "Progress Caring Leads IO (Summary Keseluruhan per WOK - Agency)"
    date_mode = "none"

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return "⏳ Login jatenggayeng.id & mengambil Caring Order..."

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await leads_browser.run_leads_report(date.today())
        return {"result": result}

    @sub_report("main", "Summary Keseluruhan per WOK - Agency (PNG Document)")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        return ReportOutput(
            kind="document",
            buf=BytesIO(result["png"]),
            filename=result["png_filename"],
            caption=result["caption"],
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
        except leads_browser.LeadsReportError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        except Exception as e:
            logger.exception("[LEADS] Gagal mengambil Caring Order")
            await update.message.reply_text(
                f"❌ Gagal mengambil Caring Order:\n`{e}`", parse_mode="Markdown"
            )
            return

        out = self.build_main(data, tgl)
        out.buf.seek(0)
        await update.message.reply_document(
            document=InputFile(out.buf, filename=out.filename),
            caption=out.caption,
        )
        if self.forward_to_group and update.effective_chat.id != self.group_id:
            out.buf.seek(0)
            await ctx.bot.send_document(
                chat_id=self.group_id,
                document=InputFile(out.buf, filename=out.filename),
                caption=out.caption,
            )
