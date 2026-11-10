"""
reports/homepass/command.py — Alur kirim Homepass Report berbasis BaseReport (dipakai bersama oleh
commands/homepass.py dan commands/homepass_wok_old.py).

Sub-report yang didukung:
  - main : Tabel utama Monitoring Homepass ID per WOK/Branch
  - sto  : 3 gambar breakdown per STO + teks Top/Bottom 3 STO per Branch
  - raw  : File ZIP raw data Homepass
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from io import BytesIO
from typing import Any

from telegram import InputFile, Update
from telegram.ext import ContextTypes

import db
from config import BRANCH_ORDER, GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from .calculator import export_raw_csv, hitung_homepass, hitung_homepass_sto, load_sumber
from .renderer import render_homepass, render_homepass_sto

logger = logging.getLogger(__name__)


JUMLAH_BULAN = 3


def buat_sql(tgl: date) -> str:
    """Bangun query SQL Console Rajawali untuk export homepass_sales 3 bulan."""
    from dateutil.relativedelta import relativedelta

    awal = tgl.replace(day=1)
    bagian = [
        f"SELECT '{m:%Y%m}' AS bln, sto_id, order_transaction, created_at, regional, wok, branch "
        f"FROM homepass_sales_{m:%Y%m} WHERE regional LIKE 'JATENG%'"
        for m in (awal - relativedelta(months=i) for i in range(JUMLAH_BULAN))
    ]
    return " UNION ALL ".join(bagian)


class ReportHomepass(BaseReport):
    """
    /homepass DD-MM-YYYY — Homepass Report per WOK/BRANCH IndiHome Jateng-DIY (MtD s/d tanggal).
    """

    command_name = "homepass"
    description = "Monitoring Homepass ID Jateng-DIY (Utama + Breakdown STO + Raw ZIP)"
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("hps", "iod_*")
    warn_future_date = True
    example_date = "15-07-2026"
    wok_lama: bool = False

    @classmethod
    def build_rajawali_sql(cls, tgl: date, **kwargs) -> str:
        return buat_sql(tgl)

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Memproses Homepass Report untuk {tgl.strftime('%d-%m-%Y')}..."

    @sub_report("main", "Tabel Utama Monitoring Homepass ID per WOK/Branch")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("sto", "Breakdown Homepass per STO (3 gambar + Top/Bottom 3 STO)")
    def build_sto(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("raw", "Raw Data ZIP (homepass_sales + ordering_detail)")
    def build_raw(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
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

        active_subs = set(selected_subs or ("main", "sto", "raw"))

        hari_ini = date.today()
        if tgl_closing > hari_ini:
            await update.message.reply_text(
                f"⚠️ Tanggal *{tgl_closing.strftime('%d-%m-%Y')}* belum terjadi "
                f"(hari ini {hari_ini.strftime('%d-%m-%Y')}).\nData mungkin belum lengkap.",
                parse_mode="Markdown",
            )

        await update.message.reply_text(self.format_progress(tgl_closing, selected_subs))

        try:
            cutoff_hp_dt = await asyncio.to_thread(
                db.query_last_update_homepass_sales, tgl_closing
            )
            if isinstance(cutoff_hp_dt, datetime):
                cutoff_hp_date = cutoff_hp_dt.date()
                cutoff_hp = cutoff_hp_dt.strftime("%d-%m-%Y %H:%M")
            elif isinstance(cutoff_hp_dt, date):
                cutoff_hp_date = cutoff_hp_dt
                cutoff_hp = cutoff_hp_dt.strftime("%d-%m-%Y")
            else:
                cutoff_hp_date = None
                cutoff_hp = None

            tgl_efektif = tgl_closing
            if cutoff_hp_date and cutoff_hp_date < tgl_closing:
                tgl_efektif = cutoff_hp_date
                await update.message.reply_text(
                    f"ℹ️ Data homepass_sales baru sampai *{tgl_efektif.strftime('%d-%m-%Y')}* "
                    f"({cutoff_hp}).\nordering_detail ikut dipotong di tanggal yang sama "
                    f"supaya perbandingannya adil — laporan dihitung MtD s/d "
                    f"*{tgl_efektif.strftime('%d-%m-%Y')}*.",
                    parse_mode="Markdown",
                )
            cutoff_info = {"ordering_detail": cutoff_hp, "homepass_sales": cutoff_hp}

            sumber = await asyncio.to_thread(load_sumber, tgl_efektif, wok_lama)

            if "main" in active_subs:
                result = await asyncio.to_thread(
                    hitung_homepass, tgl_efektif, sumber, wok_lama
                )
                img_buf = render_homepass(result, cutoff=cutoff_info)

                top_b = result["top_alerts"]["branch"]
                top_w = result["top_alerts"]["wok"]

                def _v(x):
                    return x if x else "-"

                caption = (
                    f"*Monitoring Homepass ID Jateng DIY{judul_lama}*\n"
                    f"{result['tgl_label']}\n\n"
                    f"BRANCH\n\n"
                    f"🥇 Top % IO Homepass - {_v(top_b['pct_io_top'])}\n"
                    f"🏳️ Bottom % IO Homepass - {_v(top_b['pct_io_bottom'])}\n\n"
                    f"🥇 Top Ach % SF with IO Homepass - {_v(top_b['pct_sf_top'])}\n"
                    f"🏳️ Bottom Ach % SF with IO Homepass - {_v(top_b['pct_sf_bottom'])}\n\n"
                    f"WOK\n\n"
                    f"🥇 Top % IO Homepass - {_v(top_w['pct_io_top'])}\n"
                    f"🏳️ Bottom % IO Homepass - {_v(top_w['pct_io_bottom'])}\n\n"
                    f"🥇 Top Ach % SF with IO Homepass - {_v(top_w['pct_sf_top'])}\n"
                    f"🏳️ Bottom Ach % SF with IO Homepass - {_v(top_w['pct_sf_bottom'])}\n\n"
                    f"Data ODP, Order dan PS Homepass ID bisa dilihat melalui link di bawah ini. Terimakasih."
                )

                img_buf.seek(0)
                await update.message.reply_photo(
                    photo=InputFile(img_buf, filename=f"homepass_report{sfx_file}.png"),
                    caption=caption,
                    parse_mode="Markdown",
                )
                if update.effective_chat.id != GROUP_ID:
                    img_buf.seek(0)
                    await ctx.bot.send_photo(
                        chat_id=GROUP_ID,
                        photo=InputFile(img_buf, filename=f"homepass_report{sfx_file}.png"),
                        caption=caption,
                        parse_mode="Markdown",
                    )

            if "sto" in active_subs:
                try:
                    result_sto = await asyncio.to_thread(
                        hitung_homepass_sto, tgl_efektif, sumber, wok_lama
                    )

                    branch_chunks = [BRANCH_ORDER[0:2], BRANCH_ORDER[2:4], BRANCH_ORDER[4:6]]
                    n_parts = len(branch_chunks)
                    for idx, chunk in enumerate(branch_chunks, 1):
                        img_buf_sto = render_homepass_sto(
                            result_sto,
                            cutoff=cutoff_info,
                            branch_filter=chunk,
                            part_label=f"({idx}/{n_parts})",
                        )
                        caption_sto = (
                            f"📊 *Homepass Report — Breakdown per STO ({idx}/{n_parts})*\n"
                            f"MtD {tgl_efektif.strftime('%d-%m-%Y')}  ({result_sto['bi_label']})\n"
                            f"Branch: {', '.join(chunk)}"
                        )
                        img_buf_sto.seek(0)
                        await update.message.reply_photo(
                            photo=InputFile(
                                img_buf_sto, filename=f"homepass_report{sfx_file}_sto_{idx}.png"
                            ),
                            caption=caption_sto,
                            parse_mode="Markdown",
                        )
                        if update.effective_chat.id != GROUP_ID:
                            img_buf_sto.seek(0)
                            await ctx.bot.send_photo(
                                chat_id=GROUP_ID,
                                photo=InputFile(
                                    img_buf_sto,
                                    filename=f"homepass_report{sfx_file}_sto_{idx}.png",
                                ),
                                caption=caption_sto,
                                parse_mode="Markdown",
                            )

                    def _fmt_sto(r):
                        pct = r.get("pct_io_home_id")
                        pct_str = f"{pct:.1f}%" if pct is not None else "-"
                        return f"{r['name']} ({r['wok']}) - {pct_str}"

                    lines = [
                        "*Top 3 & Bottom 3 STO %IO Homepass per Branch*",
                        result_sto["tgl_label"],
                        "",
                    ]
                    for branch, rank in result_sto["sto_rank_by_branch"].items():
                        lines.append(f"*{branch}*")
                        lines.append("🥇 Top 3 STO %IO Homepass")
                        top3 = rank["top3"]
                        lines += (
                            [f"{i}. {_fmt_sto(r)}" for i, r in enumerate(top3, 1)]
                            if top3
                            else ["-"]
                        )
                        lines.append("🏳️ Bottom 3 STO %IO Homepass")
                        bottom3 = rank["bottom3"]
                        lines += (
                            [f"{i}. {_fmt_sto(r)}" for i, r in enumerate(bottom3, 1)]
                            if bottom3
                            else ["-"]
                        )
                        lines.append("")
                    rank_text = "\n".join(lines).rstrip()

                    await update.message.reply_text(rank_text, parse_mode="Markdown")
                    if update.effective_chat.id != GROUP_ID:
                        await ctx.bot.send_message(
                            chat_id=GROUP_ID, text=rank_text, parse_mode="Markdown"
                        )
                except Exception as e:
                    logger.warning(f"Render Homepass breakdown per STO gagal: {e}")
                    await update.message.reply_text(
                        f"⚠️ Gagal render Homepass breakdown per STO:\n`{e}`",
                        parse_mode="Markdown",
                    )

            if "raw" in active_subs:
                try:
                    zip_bytes, zip_filename = await asyncio.to_thread(
                        export_raw_csv, tgl_efektif, sumber, wok_lama
                    )
                    await update.message.reply_document(
                        document=InputFile(BytesIO(zip_bytes), filename=zip_filename),
                        caption=(
                            f"📦 Raw data Homepass Report {tgl_efektif.strftime('%d-%m-%Y')}\n"
                            f"homepass_raw = homepass_sales JOIN ordering_detail\n"
                            f"iod_agency_raw = ordering_detail langsung (channel AGENCY)"
                        ),
                    )
                except Exception as e:
                    logger.warning(f"Export raw CSV Homepass gagal: {e}")
                    await update.message.reply_text(
                        f"⚠️ Gagal export raw data:\n`{e}`", parse_mode="Markdown"
                    )

            if update.effective_chat.id != GROUP_ID:
                await update.message.reply_text(
                    "✅ Homepass Report (1 utama + 3 breakdown per STO) sudah dikirim ke grup manajemen."
                )

        except Exception as e:
            logger.exception(f"Error /{nama_cmd}")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


class ReportHomepassWokOld(ReportHomepass):
    command_name = "homepass_wok_old"
    description = "Monitoring Homepass ID Jateng-DIY — WOK Lama (16 WOK)"
    wok_lama = True


async def jalankan_homepass(update, ctx, wok_lama: bool = False):
    cls = ReportHomepassWokOld if wok_lama else ReportHomepass
    await cls().handle(update, ctx)
