"""
reports/djp_mb_sf/report.py — Implementasi BaseReport untuk keluarga report DJP, MB, dan SF:
  - /djp    (ReportDJP)
  - /sf     (ReportSF)
  - /djpcsv (ReportDJPCSV: sub-report summary & daily)
  - /mbcsv  (ReportMBCSV: sub-report summary & daily)
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Callable

from telegram import Update
from telegram.ext import ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from . import (
    calculator_djp,
    calculator_djp_daily,
    calculator_mb,
    calculator_mb_daily,
    calculator_sf,
    renderer_djp,
    renderer_djp_daily,
    renderer_mb,
    renderer_sf,
)


def top_bottom_djp(woks: list[dict], field: str = "mtd_pct_sf") -> tuple[str, str]:
    """Return (top_label, bottom_label) berdasarkan field di list WOK rows."""
    valid = [w for w in woks if w.get(field) is not None]
    if not valid:
        return "-", "-"
    top = max(valid, key=lambda r: r[field])
    bottom = min(valid, key=lambda r: r[field])
    top_lbl = f"{top['name']} ({top[field]:.1f}%)"
    bottom_lbl = f"{bottom['name']} ({bottom[field]:.1f}%)"
    return top_lbl, bottom_lbl


def build_djp_caption(tgl: date, result: dict, sumber: str | None = None) -> str:
    reg = result["region"]
    sumber_str = f"  _(Sumber: {sumber})_" if sumber else ""
    caption = (
        f"📊 *Evaluasi Aktivitas DJP SF IndiHome Jateng-DIY*\n"
        f"Update {tgl.strftime('%d-%m-%Y')}{sumber_str}\n\n"
        f"*Region JATENG-DIY*\n"
        f"Visit DJP Today : *{reg['today_visit']:,}*\n"
        f"SF DJP Today    : *{reg['today_sf_djp']:,}*\n"
        f"Visit DJP MtD   : *{reg['mtd_visit']:,}*\n"
        f"SF DJP MtD      : *{reg['mtd_sf_djp']:,}*\n"
    )
    if reg.get("mtd_pct_sf") is not None:
        caption += f"%SF Active DJP  : *{reg['mtd_pct_sf']:.1f}%*\n"
    if reg.get("mtd_djp_per_sf") is not None:
        caption += f"DJP/SF/Day      : *{reg['mtd_djp_per_sf']:.1f}*\n"

    top_lbl, bottom_lbl = top_bottom_djp(result["woks"], "mtd_pct_sf")
    caption += (
        f"\n🥇 Top %SF Aktif DJP - WOK {top_lbl}\n"
        f"🏳️ Bottom %SF Aktif DJP - WOK {bottom_lbl}"
    )
    return caption


def build_sf_caption(tgl: date, result: dict) -> str:
    reg = result["region"]
    caption = (
        f"📊 *SF Productivity Performance IndiHome Jateng-DIY*\n"
        f"Update {tgl.strftime('%d-%m-%Y')}\n\n"
        f"*Region JATENG-DIY*\n"
        f"SF REG          : *{reg['sf_reg']:,}*\n"
        f"SF Aktif PS MtD : *{reg['sf_aktif_m']:,}*\n"
        f"Total PS MtD    : *{reg['total_ps_m']:,}*\n"
    )
    if reg.get("sf_aktif_pctm") is not None:
        caption += f"%M SF Aktif PS  : *{reg['sf_aktif_pctm']:.1f}%*\n"
    if reg.get("prod_m") is not None:
        caption += f"SF Productivity : *{reg['prod_m']:.1f}*\n"

    top_lbl, bottom_lbl = top_bottom_djp(result["woks"], "sf_aktif_pctm")
    caption += (
        f"\n🥇 Top %M SF Aktif PS - WOK {top_lbl}\n"
        f"🏳️ Bottom %M SF Aktif PS - WOK {bottom_lbl}"
    )
    return caption


class ReportDJP(BaseReport):
    command_name = "djp"
    description = "Evaluasi Aktivitas DJP SF IndiHome Jateng-DIY (DB)"
    cutoff_table_key = "djp"
    date_mode = "required"
    warn_future_date = False
    example_date = "09-06-2026"

    def __init__(self, *, get_sf_aktif_fn: Callable[[], Any] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._get_sf_aktif_fn = get_sf_aktif_fn

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Memproses laporan DJP untuk {tgl.strftime('%d-%m-%Y')}..."

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        cutoff_str = await self.get_cutoff()
        sf_df = self._get_sf_aktif_fn() if self._get_sf_aktif_fn else None
        result = await asyncio.to_thread(calculator_djp.hitung_djp, tgl, sf_aktif_df=sf_df)
        return {"result": result, "cutoff": cutoff_str}

    @sub_report("main", "Evaluasi Aktivitas DJP SF per WOK")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        img_buf = renderer_djp.render_djp(result, cutoff=data["cutoff"])
        caption = build_djp_caption(tgl, result)
        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="djp_report.png",
            caption=caption,
            parse_mode="Markdown",
        )

    async def send_outputs(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        outputs: list[ReportOutput],
    ) -> None:
        await super().send_outputs(update, ctx, outputs)
        if self.forward_to_group and update.effective_chat.id != self.group_id and outputs:
            await update.message.reply_text("✅ Laporan DJP sudah dikirim ke grup.")


class ReportSF(BaseReport):
    command_name = "sf"
    description = "SF Performance channel AGENCY IndiHome Jateng-DIY"
    cutoff_table_key = "ordering detail"
    date_mode = "required"
    warn_future_date = False
    example_date = "09-06-2026"

    def __init__(self, *, get_sf_aktif_fn: Callable[[], Any] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._get_sf_aktif_fn = get_sf_aktif_fn

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Memproses laporan SF untuk {tgl.strftime('%d-%m-%Y')}..."

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        cutoff_str = await self.get_cutoff()
        sf_df = self._get_sf_aktif_fn() if self._get_sf_aktif_fn else None
        result = await asyncio.to_thread(calculator_sf.hitung_sf, tgl, sf_aktif_df=sf_df)
        return {"result": result, "cutoff": cutoff_str}

    @sub_report("main", "SF Productivity Performance IndiHome Jateng-DIY")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        img_buf = renderer_sf.render_sf(result, cutoff=data["cutoff"])
        caption = build_sf_caption(tgl, result)
        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="sf_report.png",
            caption=caption,
            parse_mode="Markdown",
        )

    async def send_outputs(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        outputs: list[ReportOutput],
    ) -> None:
        await super().send_outputs(update, ctx, outputs)
        if self.forward_to_group and update.effective_chat.id != self.group_id and outputs:
            await update.message.reply_text("✅ Laporan SF sudah dikirim ke grup.")


class ReportDJPCSV(BaseReport):
    command_name = "djpcsv"
    description = "Laporan DJP dari CSV manual (Summary + Daily Grid)"
    date_mode = "required"
    warn_future_date = False
    example_date = "09-06-2026"

    def __init__(
        self,
        *,
        get_djp_csv_fn: Callable[[], Any],
        get_sf_aktif_fn: Callable[[], Any],
        get_upload_cutoff_fn: Callable[[], str | None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_djp_csv_fn = get_djp_csv_fn
        self._get_sf_aktif_fn = get_sf_aktif_fn
        self._get_upload_cutoff_fn = get_upload_cutoff_fn

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Memproses laporan DJP CSV untuk {tgl.strftime('%d-%m-%Y')}..."

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        df_csv = self._get_djp_csv_fn()
        if df_csv is None:
            await update.message.reply_text(
                "❌ Belum ada CSV DJP tersimpan.\n"
                "Upload dulu file CSV DJP (nama file harus mengandung kata *djp*).",
                parse_mode="Markdown",
            )
            return
        await super().handle(update, ctx)

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        df_csv = self._get_djp_csv_fn()
        sf_df = self._get_sf_aktif_fn()
        cutoff_str = self._get_upload_cutoff_fn()
        keys = set(selected_subs or ("summary", "daily"))
        data: dict[str, Any] = {"cutoff": cutoff_str}
        if "summary" in keys:
            data["summary"] = await asyncio.to_thread(
                calculator_djp.hitung_djp_csv, tgl, df_csv, sf_df
            )
        if "daily" in keys:
            data["daily"] = await asyncio.to_thread(
                calculator_djp_daily.hitung_djp_daily, tgl, df_csv, sf_df
            )
        return data

    @sub_report("summary", "Evaluasi Aktivitas DJP SF (Summary)")
    def build_summary(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["summary"]
        img_buf = renderer_djp.render_djp(result, cutoff=data["cutoff"])
        caption = build_djp_caption(tgl, result, sumber="CSV Manual")
        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="djp_report.png",
            caption=caption,
            parse_mode="Markdown",
        )

    @sub_report("daily", "Daily Grid SF DJP")
    def build_daily(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result_d = data["daily"]
        img_buf_d = renderer_djp_daily.render_daily_grid(
            result_d, category="DJP", cutoff=data["cutoff"]
        )
        cap_d = (
            f"📅 *SF DJP — {tgl.strftime('%B %Y')}*\n"
            f"Data s/d {tgl.strftime('%d-%m-%Y')}  _(Sumber: CSV Manual)_"
        )
        return ReportOutput(
            kind="photo",
            buf=img_buf_d,
            filename="djp_daily.png",
            caption=cap_d,
            parse_mode="Markdown",
        )

    async def send_outputs(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        outputs: list[ReportOutput],
    ) -> None:
        await super().send_outputs(update, ctx, outputs)
        if self.forward_to_group and update.effective_chat.id != self.group_id and outputs:
            await update.message.reply_text("✅ Laporan DJP (2 report) sudah dikirim ke grup.")


class ReportMBCSV(BaseReport):
    command_name = "mbcsv"
    description = "Laporan Morning Briefing dari CSV manual (Summary + Daily Grid)"
    date_mode = "required"
    warn_future_date = False
    example_date = "09-06-2026"

    def __init__(
        self,
        *,
        get_mb_csv_fn: Callable[[], Any],
        get_sf_aktif_fn: Callable[[], Any],
        get_upload_cutoff_fn: Callable[[], str | None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_mb_csv_fn = get_mb_csv_fn
        self._get_sf_aktif_fn = get_sf_aktif_fn
        self._get_upload_cutoff_fn = get_upload_cutoff_fn

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Memproses laporan MB untuk {tgl.strftime('%d-%m-%Y')}..."

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        df_csv = self._get_mb_csv_fn()
        if df_csv is None:
            await update.message.reply_text(
                "❌ Belum ada data MB tersimpan.\n"
                "Upload dulu file CSV (nama file harus mengandung kata *djp*).",
                parse_mode="Markdown",
            )
            return
        await super().handle(update, ctx)

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        df_csv = self._get_mb_csv_fn()
        sf_df = self._get_sf_aktif_fn()
        cutoff_str = self._get_upload_cutoff_fn()
        keys = set(selected_subs or ("summary", "daily"))
        data: dict[str, Any] = {"cutoff": cutoff_str}
        if "summary" in keys:
            data["summary"] = await asyncio.to_thread(
                calculator_mb.hitung_mb_csv, tgl, df_csv, sf_df
            )
        if "daily" in keys:
            data["daily"] = await asyncio.to_thread(
                calculator_mb_daily.hitung_mb_daily, tgl, df_csv, sf_df
            )
        return data

    @sub_report("summary", "Evaluasi Morning Briefing SF (Summary)")
    def build_summary(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result_mb = data["summary"]
        img_mb = renderer_mb.render_mb(result_mb, cutoff=data["cutoff"])
        reg = result_mb["region"]
        top_w, bot_w = top_bottom_djp(result_mb["woks"], "mtd_pct_sf_mb")
        cap_mb = (
            f"📋 *Evaluasi Morning Briefing SF IndiHome Jateng-DIY*\n"
            f"Update {tgl.strftime('%d-%m-%Y')}  _(Sumber: CSV Manual)_\n\n"
            f"*Region JATENG-DIY*\n"
            f"SF MB Today  : *{reg['today_sf_mb']:,}*\n"
            f"SF MB MtD    : *{reg['mtd_sf_mb']:,}*\n"
            f"SF REG       : *{reg['sf_reg']:,}*\n"
        )
        if reg.get("mtd_pct_sf_mb") is not None:
            cap_mb += f"%SF MB       : *{reg['mtd_pct_sf_mb']:.1f}%*\n"
        cap_mb += (
            f"\n🥇 Top %SF MB - WOK {top_w}\n"
            f"🏳️ Bottom %SF MB - WOK {bot_w}"
        )
        return ReportOutput(
            kind="photo",
            buf=img_mb,
            filename="mb_report.png",
            caption=cap_mb,
            parse_mode="Markdown",
        )

    @sub_report("daily", "Daily Grid SF Morning Briefing")
    def build_daily(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result_d = data["daily"]
        img_buf_d = renderer_djp_daily.render_daily_grid(
            result_d, category="MB", cutoff=data["cutoff"]
        )
        cap_d = (
            f"📅 *SF Morning Briefing — {tgl.strftime('%B %Y')}*\n"
            f"Data s/d {tgl.strftime('%d-%m-%Y')}  _(Sumber: CSV Manual)_"
        )
        return ReportOutput(
            kind="photo",
            buf=img_buf_d,
            filename="mb_daily.png",
            caption=cap_d,
            parse_mode="Markdown",
        )

    async def send_outputs(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        outputs: list[ReportOutput],
    ) -> None:
        await super().send_outputs(update, ctx, outputs)
        if self.forward_to_group and update.effective_chat.id != self.group_id and outputs:
            await update.message.reply_text("✅ Laporan MB (2 report) sudah dikirim ke grup.")
