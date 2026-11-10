"""
commands/clockin_sf_all.py — Handler Telegram /clockin_sf_all: Report Clock-In SF All Category.

  /clockin_sf_all [DD-MM-YYYY] [tabel|excel] [file=<path detail-homepass>]
    tabel : gambar PNG + caption update clock-in seluruh SF
    excel : Excel ringkasan WOK, detail per SF, SF belum clock-in, harian
  Kosong = H-1. Sumber: file detail-homepass hasil scraping SELA + SF Register (database_sf).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from telegram import Update
from utils.command_registry import TelegramCommand
from telegram.ext import CommandHandler, ContextTypes

from commands.clockin_sf_teritory import BATAS_CAPTION, _file_homepass, _kirim, _tanggal
from config import GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from reports.clockin_sf_all import calculator as calc, renderer

logger = logging.getLogger(__name__)


def buat_report(path_homepass: str, tgl: date) -> dict:
    """Hitung + render. Return {r, png (BytesIO), xlsx (BytesIO), xlsx_name, teks}."""
    from reports.sf_momentum.calculator_7so import _sf_master_lengkap

    master = _sf_master_lengkap(tgl)
    if master.empty:
        raise RuntimeError(f"SF Register (database_sf) untuk {tgl:%d-%m-%Y} kosong / tidak tersedia.")
    hp = calc.baca_homepass(path_homepass)
    r = calc.hitung(hp, master, tgl)
    if not r["total"]["asg"]:
        raise RuntimeError(f"Tidak ada assignment homepass SF terdaftar di periode {calc.label_periode(r)} "
                           f"pada file {path_homepass}.")
    xlsx, nama = renderer.build_excel(r)
    return {"r": r, "png": renderer.render_png(r), "xlsx": xlsx, "xlsx_name": nama, "teks": calc.caption(r)}


class ReportClockinSFAll(BaseReport):
    """/clockin_sf_all [DD-MM-YYYY] — Report Clock-In SF All Category MTD (PNG + caption + Excel)."""

    command_name = "clockin_sf_all"
    description = "Report Clock-In SF All Category MTD (PNG + Teks + Excel)"
    date_mode = "optional"
    default_date_offset = 1
    example_date = "07-11-2026"

    @sub_report("tabel", "Gambar PNG + Teks Update Clock-In SF All Category MTD")
    def build_tabel(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("excel", "File Excel Report Clock-In SF All Category MTD")
    def build_excel(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return
        sub_map = self.get_sub_reports()
        active = set(a.lower() for a in raw_args if a.lower() in sub_map) or {"tabel", "excel"}
        try:
            tgl = _tanggal(raw_args)
        except ValueError:
            await update.message.reply_text("❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\n"
                                            "Contoh: `/clockin_sf_all 07-11-2026`", parse_mode="Markdown")
            return
        path = _file_homepass(tgl, raw_args)
        import os
        if not path or not os.path.exists(path):
            await update.message.reply_text(
                f"❌ File detail-homepass untuk {tgl:%d-%m-%Y} tidak ditemukan. Jalankan scraping SELA dulu "
                f"(python -m sources.detail_sf_indihome --auto).")
            return
        await update.message.reply_text(f"⏳ Menyusun Report Clock-In SF All Category MTD {tgl:%d-%m-%Y}...")
        try:
            h = await asyncio.to_thread(buat_report, path, tgl)
            logger.info(f"[clockin_sf_all] {calc.label_periode(h['r'])} | {h['r']['total']}")
            png_name = f"Report_Clockin_SF_All_Category_{tgl:%Y%m%d}.png"
            if "tabel" in active:
                png = h["png"].getvalue()
                if len(h["teks"]) <= BATAS_CAPTION:
                    await _kirim(update, ctx, "photo", photo=(png, png_name), caption=h["teks"])
                else:
                    await _kirim(update, ctx, "photo", photo=(png, png_name))
                    await update.message.reply_text(h["teks"])
                    if update.effective_chat.id != GROUP_ID:
                        await ctx.bot.send_message(chat_id=GROUP_ID, text=h["teks"])
            if "excel" in active:
                await _kirim(update, ctx, "document", document=(h["xlsx"].getvalue(), h["xlsx_name"]))
        except Exception as e:
            logger.exception("Error /clockin_sf_all")
            await update.message.reply_text(f"❌ Error:\n{str(e)[:600]}")


def register_handlers(app, timeout_wrapper=None):
    """Daftarkan /clockin_sf_all. Return cmd_clockin_sf_all (dipakai scheduler & csv_report_runner)."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    cmd = ReportClockinSFAll().handle
    TelegramCommand("clockin_sf_all", cmd).register(app, timeout_wrapper=_T)
    return cmd
