"""
commands/nasional.py — Handler Telegram /nasional DD-MM-YYYY berbasis BaseReport.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable

from telegram import Update
from utils.command_registry import TelegramCommand
from telegram.ext import CommandHandler, ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from reports.nasional import hitung_national, render_national

logger = logging.getLogger(__name__)

REPORT_TITLE = "Daily Tracking IndiHome Performance — Region Level"


def _baris_rank(rows, key, label, signed=False):
    if not rows:
        return ["   - data tidak tersedia"]
    fmt = "+.1f" if signed else ".1f"
    return [f"   {i}. {r['name']} ({label} {r[key]:{fmt}}%)" for i, r in enumerate(rows, 1)]


def _rank(regions, key):
    valid = sorted(
        (r for r in regions if r.get(key) is not None),
        key=lambda r: r[key],
        reverse=True,
    )
    return valid[:3], list(reversed(valid[-3:]))


def _build_caption(result: dict) -> str:
    tgl = result["tgl_closing"]
    regions = [r for r in result.get("regions") or [] if r.get("name") != "UNMAPPED"]
    ach_top, ach_bot = _rank(regions, "re_ach")
    gr_top, gr_bot = _rank(regions, "re_mom")

    lines = [
        f"📊 {REPORT_TITLE}",
        f"MtD s/d {tgl.strftime('%d-%m-%Y')} vs tanggal yang sama bulan lalu",
    ]
    if not result["target_ada"]:
        lines.append(
            "⚠️ Target bulan ini belum ada di sheet TARGET_REGION (Target/Ach = 0/-)"
        )
    lines += [
        "",
        "🏆 Top 3 Ach RE",
        *_baris_rank(ach_top, "re_ach", "Ach"),
        "",
        "🔻 Bottom 3 Ach RE",
        *_baris_rank(ach_bot, "re_ach", "Ach"),
        "",
        "📈 Top 3 Growth RE (MoM)",
        *_baris_rank(gr_top, "re_mom", "MoM", signed=True),
        "",
        "📉 Bottom 3 Growth RE (MoM)",
        *_baris_rank(gr_bot, "re_mom", "MoM", signed=True),
    ]
    return "\n".join(lines)


def buat_sql(
    tgl: date,
    bagian: str | None = None,
    semua: bool = False,
    raw: bool = False,
) -> str:
    """
    Bangun SQL untuk SQL Console Rajawali (nasional + murmer, atau semua laporan pagi).
    Juga menyimpan file .sql dan .manifest.json di storage/sql_packets/.
    """
    import os
    import shutil
    import subprocess
    import sys
    from dateutil.relativedelta import relativedelta

    if raw:
        ref = tgl.replace(day=1)
        prev = ref - relativedelta(months=1)
        return " UNION ALL ".join(
            f"SELECT * FROM indihome_ordering_detail_{m:%Y%m} WHERE region LIKE 'JATENG%' AND order_type = 'NEW SALES'"
            for m in (prev, ref)
        )

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paket_dir = os.path.join(base, "storage", "sql_packets")
    os.makedirs(paket_dir, exist_ok=True)
    tgl_str = tgl.strftime("%d-%m-%Y")
    prefix = os.path.join(paket_dir, tgl.strftime("%Y%m%d") + (("_" + bagian) if bagian else ""))
    cmd = (
        [
            sys.executable,
            os.path.join(base, "utils", "csv_report_runner.py"),
            "--tanggal",
            tgl_str,
            "--out",
            os.path.join(paket_dir, "_tmp"),
            "--rekam",
            prefix,
        ]
        + ([] if semua else ["--only", "nasional,murmer"])
        + (["--bagian", bagian] if bagian else [])
    )
    r = subprocess.run(
        cmd,
        cwd=base,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not os.path.exists(prefix + ".sql"):
        raise RuntimeError("Gagal membuat SQL pagi:\n" + (r.stderr or "")[-1500:])
    if bagian:
        dasar = os.path.join(paket_dir, tgl.strftime("%Y%m%d"))
        shutil.move(prefix + ".manifest.json", dasar + ".manifest.json")
    with open(prefix + ".sql", encoding="utf-8") as f:
        return f.read()


class ReportNasional(BaseReport):
    """
    /nasional DD-MM-YYYY — Daily Tracking IndiHome Performance level Region nasional.
    """

    command_name = "nasional"
    description = REPORT_TITLE
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("nasional_murmer", "iod_*")
    warn_future_date = False
    forward_to_group = False
    example_date = "03-05-2026"

    @classmethod
    def build_rajawali_sql(
        cls,
        tgl: date,
        bagian: str | None = None,
        semua: bool = False,
        raw: bool = False,
        **kwargs,
    ) -> str:
        return buat_sql(tgl, bagian=bagian, semua=semua, raw=raw)

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
        self._get_cutoff_db_fn = get_cutoff_fn
        self._kirim_foto_fn = kirim_foto_fn

    def usage_text(self) -> str:
        return f"⚠️ Sertakan tanggal.\nContoh: `/{self.command_name} {self.example_date}`"

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Generating laporan nasional {tgl.strftime('%d-%m-%Y')}..."

    @sub_report("main", "Tabel Daily Tracking IndiHome Performance — Region Level")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        img = render_national(result, cutoff=data["cutoff_str"])
        return ReportOutput(
            kind="photo",
            buf=img,
            filename=f"national_performance_{tgl.strftime('%Y%m%d')}.png",
            caption=_build_caption(result),
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
                "❌ Format tanggal salah. Gunakan: `DD-MM-YYYY`", parse_mode="Markdown"
            )
            return

        target_df = await self._get_target_fn() if self._get_target_fn else None

        await update.message.reply_text(self.format_progress(tgl_closing, None))
        try:
            result = await asyncio.to_thread(hitung_national, target_df, tgl_closing)
            cutoff = await self._get_cutoff_db_fn() if self._get_cutoff_db_fn else None
            cutoff_str = f"Cutoff data: {cutoff}" if cutoff else None
            out = self.build_main(
                {"result": result, "cutoff_str": cutoff_str}, tgl_closing
            )
            if self._kirim_foto_fn:
                await self._kirim_foto_fn(
                    ctx.bot,
                    update.effective_chat.id,
                    out.buf,
                    out.filename,
                    caption=out.caption,
                    label="nasional",
                )
            else:
                await self.send_outputs(update, ctx, [out])
        except Exception as e:
            logger.exception("Error /nasional")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


def register_handlers(
    app,
    timeout_wrapper=None,
    get_target_fn=None,
    get_cutoff_fn=None,
    kirim_foto_fn=None,
):
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    report = ReportNasional(
        get_target_fn=get_target_fn,
        get_cutoff_fn=get_cutoff_fn,
        kirim_foto_fn=kirim_foto_fn,
    )
    cmd_nasional = report.handle
    TelegramCommand("nasional", cmd_nasional).register(app, timeout_wrapper=_T)
    return cmd_nasional
