"""
reports/agresif/report.py — Implementasi BaseReport untuk /agresif (LITE) dan ReportAgresifFull.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import date
from typing import Any, Callable

import pandas as pd
from telegram import InputFile, Update
from telegram.ext import ContextTypes

from config import AGRESIF_KIRIM_KE_TOPIC, GROUP_ID, REPORT_GROUP_ID, TOPIC_IDS
from reports.base import BaseReport, ReportOutput, sub_report
from . import (
    agresif_data,
    agresif_lite,
    agresif_native,
    calculator_agresif,
    renderer_agresif,
    renderer_agresif_lite,
)

logger = logging.getLogger(__name__)


class ReportAgresif(BaseReport):
    """
    /agresif DD-MM-YYYY — Report Kec Agresif versi LITE (sejak 09-Sep-2026).
    Menghasilkan 2 sub-report PNG document:
      - lokasi : REPORT NEW SALES LOKASI AGRESIF (47 Kecamatan + 4 Agresif City)
      - fmc    : REPORT NEW SALES ALL FMC CITY (14 New FMC + 12 Old FMC)
    """

    command_name = "agresif"
    description = "Report Kec Agresif LITE (Lokasi Agresif + All FMC City)"
    date_mode = "required"
    warn_future_date = False
    example_date = "08-09-2026"
    send_wa = True

    def __init__(
        self,
        *,
        get_targets_fn: Callable[[], tuple[Any, Any]] | None = None,
        is_terjadwal_fn: Callable[[Any], bool] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_targets_fn = get_targets_fn
        self._is_terjadwal_fn = is_terjadwal_fn

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return (
            f"⏳ Generating Report Kec Agresif LITE {tgl.strftime('%d-%m-%Y')}... "
            f"(tarik data DB 2 bulan + geocoding + kalkulasi, ±1-2 menit)"
        )

    @sub_report("lokasi", "Report New Sales Lokasi Agresif (47 Kecamatan + 4 City)")
    def build_lokasi(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        png_buf = renderer_agresif_lite.render_lite_lokasi(
            data["r_lok"], cutoff=data["cutoff_str"]
        )
        out_suffix = tgl.strftime("%d%m%Y")
        return ReportOutput(
            kind="document",
            buf=png_buf,
            filename=f"NEW_SALES_LOKASI_AGRESIF_{out_suffix}.png",
            caption=data["caption1"],
            parse_mode=None,
        )

    @sub_report("fmc", "Report New Sales All FMC City (14 New + 12 Old)")
    def build_fmc(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        png_buf = renderer_agresif_lite.render_lite_fmc(
            data["r_fmc"], cutoff=data["cutoff_str"]
        )
        out_suffix = tgl.strftime("%d%m%Y")
        return ReportOutput(
            kind="document",
            buf=png_buf,
            filename=f"NEW_SALES_ALL_FMC_CITY_{out_suffix}.png",
            caption=data["caption2"],
            parse_mode=None,
        )

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        tgl, selected_subs, err = self.parse_args(raw_args)
        if err is not None:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

        await update.message.reply_text(self.format_progress(tgl, selected_subs))

        out_dir = tempfile.mkdtemp(prefix="agresiflite_")
        try:
            if self._get_targets_fn is not None:
                res_t = self._get_targets_fn()
                if asyncio.iscoroutine(res_t):
                    df_kec, df_fmc = await res_t
                else:
                    df_kec, df_fmc = res_t
            else:
                df_kec, df_fmc = None, None

            def _compute():
                df_raw = agresif_data.build_raw(tgl)
                if df_raw.empty:
                    raise RuntimeError(
                        "Data RAW kosong untuk cutoff ini — cek koneksi DB/VPN "
                        "atau apakah tabel indihome_ordering_detail bulan terkait ada isinya."
                    )
                df_calc = agresif_native.prepare_calc_df(df_raw)
                last_update_max = pd.to_datetime(df_raw["last_update"], errors="coerce").max()
                cutoff_str = (
                    last_update_max.strftime("%d-%m-%Y %H:%M")
                    if pd.notna(last_update_max)
                    else None
                )

                r_lok = agresif_lite.hitung_lite_lokasi(tgl, df_calc, df_kec)
                r_fmc = agresif_lite.hitung_lite_fmc(tgl, df_calc, df_fmc)

                r_ps_full = calculator_agresif.hitung_agresif_ps(tgl, df_calc, df_kec)
                r_fmc_full = calculator_agresif.hitung_agresif_fmc(tgl, df_calc, df_fmc)
                cap_lok, cap_fmc = agresif_lite.build_lite_captions(
                    tgl, r_ps_full, r_fmc_full
                )
                return cutoff_str, r_lok, r_fmc, cap_lok, cap_fmc

            cutoff_str, r_lok, r_fmc, caption1, caption2 = await asyncio.to_thread(_compute)
            data = {
                "cutoff_str": cutoff_str,
                "r_lok": r_lok,
                "r_fmc": r_fmc,
                "caption1": caption1,
                "caption2": caption2,
            }

            outputs = self.build_outputs(data, tgl, selected_subs=selected_subs)

            is_terjadwal = (
                self._is_terjadwal_fn(ctx.bot) if self._is_terjadwal_fn else False
            )
            requester_chat = update.effective_chat.id
            requester_thread = getattr(update.message, "message_thread_id", None)

            if AGRESIF_KIRIM_KE_TOPIC and is_terjadwal:
                img_targets = [(REPORT_GROUP_ID, TOPIC_IDS["SALES"])]
                if (
                    requester_chat != GROUP_ID
                    and (requester_chat, requester_thread) not in img_targets
                ):
                    img_targets.append((requester_chat, requester_thread))
            else:
                img_targets = [(requester_chat, requester_thread)]
            reply_id = None if is_terjadwal else update.message.message_id

            for idx, out in enumerate(outputs, start=1):
                png_path = os.path.join(out_dir, f"{idx:02d}_{out.filename}")
                with open(png_path, "wb") as f:
                    f.write(out.buf.getbuffer())

                file_id = None
                for chat, thread in img_targets:
                    if file_id is None:
                        with open(png_path, "rb") as fh:
                            msg = await ctx.bot.send_document(
                                chat_id=chat,
                                message_thread_id=thread,
                                document=InputFile(fh, filename=out.filename),
                                caption=out.caption,
                                reply_to_message_id=reply_id,
                                write_timeout=180,
                                read_timeout=120,
                            )
                        file_id = msg.document.file_id
                    else:
                        await ctx.bot.send_document(
                            chat_id=chat,
                            message_thread_id=thread,
                            document=file_id,
                            caption=out.caption,
                            reply_to_message_id=reply_id,
                        )
        except Exception as e:
            logger.exception("[/agresif] gagal generate/kirim (LITE)")
            await update.message.reply_text(
                f"❌ Gagal generate Report Kec Agresif LITE:\n`{str(e)[:600]}`",
                parse_mode="Markdown",
            )
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)


class ReportAgresifFull(BaseReport):
    """
    Report New Sales Lokasi Agresif versi FULL (3 PNG + Excel 3 sheet + RAW csv.gz).
    Dipertahankan utuh untuk kompatibilitas cmd_agresif_full.
    """

    command_name = "agresif"
    description = "Report New Sales Lokasi Agresif FULL (PS + RE + FMC + Excel + Raw)"
    date_mode = "required"
    warn_future_date = False
    example_date = "30-07-2026"

    def __init__(
        self,
        *,
        get_targets_fn: Callable[[], tuple[Any, Any]] | None = None,
        is_terjadwal_fn: Callable[[Any], bool] | None = None,
        unwrap_bot_fn: Callable[[Any], Any] | None = None,
        kirim_file_dedup_fn: Callable[..., Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_targets_fn = get_targets_fn
        self._is_terjadwal_fn = is_terjadwal_fn
        self._unwrap_bot_fn = unwrap_bot_fn
        self._kirim_file_dedup_fn = kirim_file_dedup_fn

    @sub_report("ps", "Report New Sales Lokasi Agresif (PS)")
    def build_ps(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("re", "Report RE New Kecamatan Agresif")
    def build_re(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("fmc", "Report New Sales All FMC City")
    def build_fmc(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        tgl, selected_subs, err = self.parse_args(raw_args)
        if err is not None:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

        await update.message.reply_text(
            f"⏳ Generating Report Kec Agresif {tgl.strftime('%d-%m-%Y')}... "
            f"(tarik data DB 2 bulan + geocoding + kalkulasi, ±1-2 menit)"
        )

        out_dir = tempfile.mkdtemp(prefix="agresif_")
        try:
            if self._get_targets_fn is not None:
                res_t = self._get_targets_fn()
                if asyncio.iscoroutine(res_t):
                    df_kec, df_fmc = await res_t
                else:
                    df_kec, df_fmc = res_t
            else:
                df_kec, df_fmc = None, None

            def _compute():
                df_raw = agresif_data.build_raw(tgl)
                if df_raw.empty:
                    raise RuntimeError(
                        "Data RAW kosong untuk cutoff ini — cek koneksi DB/VPN "
                        "atau apakah tabel indihome_ordering_detail bulan terkait ada isinya."
                    )
                df_calc = agresif_native.prepare_calc_df(df_raw)
                last_update_max = pd.to_datetime(df_raw["last_update"], errors="coerce").max()
                cutoff_str = (
                    last_update_max.strftime("%d-%m-%Y %H:%M")
                    if pd.notna(last_update_max)
                    else None
                )

                r_ps = calculator_agresif.hitung_agresif_ps(tgl, df_calc, df_kec)
                r_re = calculator_agresif.hitung_agresif_re(tgl, df_calc, df_kec)
                r_fmc = calculator_agresif.hitung_agresif_fmc(tgl, df_calc, df_fmc)

                df_ps_report = agresif_native.format_ps_table_df(r_ps)
                df_re_report = agresif_native.format_re_table_df(r_re)
                df_fmc_report = agresif_native.format_fmc_table_df(r_fmc)
                return (
                    df_raw,
                    cutoff_str,
                    r_ps,
                    r_re,
                    r_fmc,
                    df_ps_report,
                    df_re_report,
                    df_fmc_report,
                )

            (
                df_raw,
                cutoff_str,
                r_ps,
                r_re,
                r_fmc,
                df_ps_report,
                df_re_report,
                df_fmc_report,
            ) = await asyncio.to_thread(_compute)

            png1_buf = renderer_agresif.render_agresif_ps(r_ps, cutoff=cutoff_str)
            png2_buf = renderer_agresif.render_agresif_re(r_re, cutoff=cutoff_str)
            png3_buf = renderer_agresif.render_agresif_fmc(r_fmc, cutoff=cutoff_str)

            caption1, caption2, caption3 = agresif_native.build_captions(
                tgl, r_ps, r_re, r_fmc
            )

            out_suffix = tgl.strftime("%d%m%Y")
            png1_path = os.path.join(out_dir, f"01_NEW_SALES_LOKASI_AGRESIF_{out_suffix}.png")
            png2_path = os.path.join(out_dir, f"02_RE_NEW_KECAMATAN_AGRESIF_{out_suffix}.png")
            png3_path = os.path.join(out_dir, f"03_NEW_SALES_ALL_FMC_CITY_{out_suffix}.png")
            for path, buf in (
                (png1_path, png1_buf),
                (png2_path, png2_buf),
                (png3_path, png3_buf),
            ):
                with open(path, "wb") as f:
                    f.write(buf.getbuffer())

            xlsx_path = os.path.join(out_dir, f"Report_Kec_Agresif_{out_suffix}.xlsx")
            raw_gz_path = os.path.join(out_dir, f"RAW_AGRESIF_{out_suffix}.csv.gz")
            await asyncio.to_thread(
                agresif_native.write_agresif_workbook,
                xlsx_path,
                {
                    "NEW SALES LOKASI AGRESIF": df_ps_report,
                    "RE NEW KECAMATAN AGRESIF": df_re_report,
                    "NEW SALES ALL FMC CITY": df_fmc_report,
                },
            )
            await asyncio.to_thread(agresif_native.write_raw_csv_gz, raw_gz_path, df_raw)

            is_terjadwal = (
                self._is_terjadwal_fn(ctx.bot) if self._is_terjadwal_fn else False
            )
            if AGRESIF_KIRIM_KE_TOPIC and is_terjadwal:
                img_chat, img_thread = REPORT_GROUP_ID, TOPIC_IDS["SALES"]
            else:
                img_chat, img_thread = GROUP_ID, None

            requester_chat = update.effective_chat.id
            requester_thread = getattr(update.message, "message_thread_id", None)

            def _tambah(daftar, chat, thread):
                if (chat, thread) not in daftar:
                    daftar.append((chat, thread))

            img_targets: list[tuple[int, int | None]] = []
            _tambah(img_targets, img_chat, img_thread)
            if requester_chat != GROUP_ID:
                _tambah(img_targets, requester_chat, requester_thread)

            raw_targets: list[tuple[int, int | None]] = []
            _tambah(raw_targets, GROUP_ID, None)
            if requester_chat != GROUP_ID:
                _tambah(raw_targets, requester_chat, requester_thread)

            laporan = [
                (png1_path, caption1, f"NEW_SALES_LOKASI_AGRESIF_{out_suffix}.png"),
                (png2_path, caption2, f"RE_NEW_KECAMATAN_AGRESIF_{out_suffix}.png"),
                (png3_path, caption3, f"NEW_SALES_ALL_FMC_CITY_{out_suffix}.png"),
            ]
            for png_path, cap, fname in laporan:
                file_id = None
                for chat, thread in img_targets:
                    if file_id is None:
                        with open(png_path, "rb") as fh:
                            msg = await ctx.bot.send_document(
                                chat_id=chat,
                                message_thread_id=thread,
                                document=InputFile(fh, filename=fname),
                                caption=cap,
                                write_timeout=180,
                                read_timeout=120,
                            )
                        file_id = msg.document.file_id
                    else:
                        await ctx.bot.send_document(
                            chat_id=chat,
                            message_thread_id=thread,
                            document=file_id,
                            caption=cap,
                        )

            real_bot = self._unwrap_bot_fn(ctx.bot) if self._unwrap_bot_fn else ctx.bot
            if self._kirim_file_dedup_fn:
                await self._kirim_file_dedup_fn(
                    ctx,
                    raw_targets,
                    xlsx_path,
                    f"Report_Kec_Agresif_{out_suffix}.xlsx",
                    f"🗂️ Report (3 tabel) — Report Kec Agresif {tgl.strftime('%d-%m-%Y')}",
                    "Report_Kec_Agresif_LATEST.xlsx",
                    bot=real_bot,
                )
                await self._kirim_file_dedup_fn(
                    ctx,
                    raw_targets,
                    raw_gz_path,
                    f"RAW_AGRESIF_{out_suffix}.csv.gz",
                    f"🗂️ Raw (94 kolom, ter-gzip) — Report Kec Agresif {tgl.strftime('%d-%m-%Y')}",
                    "RAW_AGRESIF_LATEST.csv.gz",
                    bot=real_bot,
                )
        except Exception as e:
            logger.exception("[/agresif] gagal generate/kirim")
            await update.message.reply_text(
                f"❌ Gagal generate Report Kec Agresif:\n`{str(e)[:600]}`",
                parse_mode="Markdown",
            )
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
