"""
reports/djpprio/report.py — Implementasi BaseReport untuk /djpprio (DJP ODP Priority).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import date, datetime
from typing import Any, Callable

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from config import DJP_PRIORITY_MASTER_DIR, GROUP_ID
from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_djpprio, renderer_djpprio

logger = logging.getLogger(__name__)


class ReportDJPPrio(BaseReport):
    """
    /djpprio [DD-MM-YYYY] — Report "DJP ODP Priority" (%Visit ODP per WOK & Branch).
    Mendukung dua cara pemakaian:
      1. Upload file Approve-Tugas dengan caption `/djpprio [DD-MM-YYYY]`
      2. Reply ke pesan file Approve-Tugas dengan `/djpprio [DD-MM-YYYY]`
    """

    command_name = "djpprio"
    description = "DJP ODP Priority (%Visit ODP per WOK & Branch + Raw Data)"
    date_mode = "none"

    def __init__(
        self,
        *,
        parse_excel_csv_fn: Callable[[bytes, str], Any] | None = None,
        kirim_file_dedup_fn: Callable[..., Any] | None = None,
        write_raw_csv_gz_fn: Callable[[str, Any], Any] | None = None,
        unwrap_bot_fn: Callable[[Any], Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._parse_excel_csv_fn = parse_excel_csv_fn
        self._kirim_file_dedup_fn = kirim_file_dedup_fn
        self._write_raw_csv_gz_fn = write_raw_csv_gz_fn
        self._unwrap_bot_fn = unwrap_bot_fn

    @sub_report("tabel", "Tabel PNG DJP ODP Priority")
    def build_tabel(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("raw", "Raw Data CSV.GZ (Master + Flag Visit)")
    def build_raw(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        reply = update.message.reply_to_message
        doc = reply.document if reply else None
        if not doc:
            await update.message.reply_text(
                "❌ Kirim file *Approve-Tugas* (export tugas DJP bulan berjalan, "
                ".csv/.xlsx) dengan caption `/djpprio`, ATAU reply ke file itu "
                "dengan `/djpprio`.\nOpsional tanggal cutoff: `/djpprio 02-08-2026` "
                "(default: tanggal terakhir di file).",
                parse_mode="Markdown",
            )
            return
        await self.process_document(update, ctx, doc, update.message.text or "")

    async def process_document(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        doc: Any,
        command_text: str,
    ) -> None:
        fname = (doc.file_name or "").lower()
        if not (fname.endswith(".xlsx") or fname.endswith(".xls") or fname.endswith(".csv")):
            await update.message.reply_text(
                "⚠️ Format tidak didukung. Kirim file *.xlsx* atau *.csv*",
                parse_mode="Markdown",
            )
            return

        MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
        if doc.file_size and doc.file_size > MAX_DOWNLOAD_BYTES:
            await update.message.reply_text(
                f"❌ File *{doc.file_size / 1048576:.1f} MB* — melebihi batas download Bot API "
                f"Telegram (maks 20 MB, batas platform bukan batas bot).\n\n"
                f"Coba kirim approve-tugas *1 bulan saja* (bukan gabungan beberapa bulan) "
                f"supaya ukurannya di bawah 20 MB — bot tetap otomatis pilih bulan/tanggal "
                f"yang benar dari isinya.",
                parse_mode="Markdown",
            )
            return

        cutoff_override = None
        selected_subs: list[str] = []
        sub_map = self.get_sub_reports()
        parts = command_text.strip().split()
        for token in parts[1:]:
            low = token.lower()
            if low in sub_map:
                if low not in selected_subs:
                    selected_subs.append(low)
                continue
            try:
                cutoff_override = datetime.strptime(token, "%d-%m-%Y").date()
            except ValueError:
                await update.message.reply_text(
                    "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/djpprio 02-08-2026`",
                    parse_mode="Markdown",
                )
                return

        active_subs = set(selected_subs or ("tabel", "raw"))

        await update.message.reply_text(
            "⏳ Generating DJP ODP Priority... (parsing approve-tugas + kalkulasi)"
        )

        try:
            try:
                tg_file = await doc.get_file()
            except Exception as e:
                if "too big" in str(e).lower():
                    await update.message.reply_text(
                        "❌ File terlalu besar utk didownload Bot API Telegram (maks 20 MB, "
                        "batas platform). Coba kirim approve-tugas 1 bulan saja.",
                        parse_mode="Markdown",
                    )
                    return
                raise
            file_bytes = bytes(await tg_file.download_as_bytearray())

            def _compute():
                master_path = calculator_djpprio.find_latest_master_file(DJP_PRIORITY_MASTER_DIR)
                if not master_path:
                    raise RuntimeError(
                        f"File master 'DJP ODP Priority - <Bulan> <Tahun>.xlsx' "
                        f"tidak ditemukan di {DJP_PRIORITY_MASTER_DIR}."
                    )
                master, master_df = calculator_djpprio.load_master_full(master_path)
                df_tugas = self._parse_excel_csv_fn(file_bytes, doc.file_name or "approve_tugas.csv")

                cutoff = cutoff_override
                if cutoff is None:
                    _, meta0 = calculator_djpprio.build_visited_set(df_tugas, date.today())
                    if meta0["max_key"]:
                        y, rest = divmod(meta0["max_key"], 10000)
                        m, d = divmod(rest, 100)
                        cutoff = date(y, m, d)
                    else:
                        cutoff = date.today()

                visited, meta = calculator_djpprio.build_visited_set(df_tugas, cutoff)
                result = calculator_djpprio.build_result(master, visited)
                raw_export_df = calculator_djpprio.build_raw_export_df(master_df, visited)
                return master_path, cutoff, meta, result, raw_export_df

            master_path, cutoff, meta, result, raw_export_df = await asyncio.to_thread(_compute)
        except Exception as e:
            logger.exception("[/djpprio] gagal parse/hitung")
            await update.message.reply_text(
                f"❌ Gagal generate DJP ODP Priority:\n`{str(e)[:600]}`",
                parse_mode="Markdown",
            )
            return

        title = f"DJP ODP Priority - {cutoff.strftime('%B %Y')}"
        date_label = cutoff.strftime("%d-%b-%Y")
        out_suffix = cutoff.strftime("%d%m%Y")

        requester_chat = update.effective_chat.id
        requester_thread = getattr(update.message, "message_thread_id", None)
        targets = [(requester_chat, requester_thread)]
        if GROUP_ID != requester_chat:
            targets.append((GROUP_ID, None))

        if "tabel" in active_subs:
            png_buf = renderer_djpprio.render_djpprio(result, title, date_label)
            caption_txt = renderer_djpprio.build_caption(result, title, date_label)
            fname_png = f"DJP_ODP_Priority_{out_suffix}.png"

            file_id = None
            for chat, thread in targets:
                if file_id is None:
                    png_buf.seek(0)
                    msg = await ctx.bot.send_document(
                        chat_id=chat,
                        message_thread_id=thread,
                        document=InputFile(png_buf, filename=fname_png),
                        caption=caption_txt,
                        write_timeout=180,
                        read_timeout=120,
                    )
                    file_id = msg.document.file_id
                else:
                    await ctx.bot.send_document(
                        chat_id=chat,
                        message_thread_id=thread,
                        document=file_id,
                        caption=caption_txt,
                    )

        if "raw" in active_subs and self._write_raw_csv_gz_fn and self._kirim_file_dedup_fn:
            raw_out_dir = tempfile.mkdtemp(prefix="djpprio_")
            try:
                raw_gz_path = os.path.join(raw_out_dir, f"RAW_DJP_ODP_PRIORITY_{out_suffix}.csv.gz")
                await asyncio.to_thread(self._write_raw_csv_gz_fn, raw_gz_path, raw_export_df)
                real_bot = self._unwrap_bot_fn(ctx.bot) if self._unwrap_bot_fn else ctx.bot
                await self._kirim_file_dedup_fn(
                    ctx,
                    targets,
                    raw_gz_path,
                    f"RAW_DJP_ODP_PRIORITY_{out_suffix}.csv.gz",
                    f"🗂️ Raw Data (master + Flag Visit) — {title}",
                    "RAW_DJP_ODP_PRIORITY_LATEST.csv.gz",
                    bot=real_bot,
                )
            finally:
                shutil.rmtree(raw_out_dir, ignore_errors=True)

        note = (
            f"master: {os.path.basename(master_path)} ({len(result['detail'])} WOK) · "
            f"{meta['used']:,} ODP visit tercatat"
        )
        if meta["skipped_month"]:
            note += f" · {meta['skipped_month']:,} baris bulan lain diabaikan"
        if meta["skipped_date"]:
            note += f" · {meta['skipped_date']:,} baris di luar cutoff/tanpa tanggal diabaikan"
        await update.message.reply_text(f"✅ DJP ODP Priority berhasil ✓ · {note}")
