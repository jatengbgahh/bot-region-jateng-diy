"""
reports/performance/report.py — Implementasi BaseReport untuk /performance (SF Performance Tracking + SAPA).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_performance, performance_browser

HELP_TEXT_PERFORMANCE = (
    "📊 *SF Performance Tracking* (Section 0-6) + *Report SAPA*\n\n"
    "Pilih file sekaligus di Telegram (multi-select/album) — bisa *6 sekaligus*, atau sebagian saja:\n"
    "Report utama:\n"
    "• Sumber Data 1 — PS apple-to-apple (.csv)\n"
    "• Sumber Data 2 — approve-tugas (.csv)\n"
    "• Data SF Master (.xlsx) — opsional, kalau tidak ada SF REG pakai estimasi dari approve-tugas\n"
    "Report SAPA (opsional):\n"
    "• SAPA 1 — Assignment (.csv)\n"
    "• SAPA 2 — Survey (.csv)\n"
    "• SAPA 3 — Prospect Homepass (.csv)\n\n"
    "Beri SATU caption `/performance` (opsional tanggal cutoff, contoh "
    "`/performance 11-08-2026` — default: tanggal terakhir di file), lalu kirim sekaligus.\n"
    "Bot mendeteksi jenis file dari isinya otomatis — tidak perlu nama file/urutan tertentu. "
    "Cukup kirim report utama saja atau SAPA saja juga bisa, keduanya jalan independen."
)


class ReportPerformance(BaseReport):
    """
    /performance — Handler panduan ketika user mengetik `/performance` tanpa lampiran file.
    (Proses upload album tetap ditangani oleh _handle_performance_upload & performance_browser).
    """

    command_name = "performance"
    description = "SF Performance Tracking (Section 0-6) + Report SAPA via Headless Browser"
    date_mode = "none"

    @sub_report("main", "SF Performance Tracking (Section 0-6)")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("sapa", "Report SAPA")
    def build_sapa(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(HELP_TEXT_PERFORMANCE, parse_mode="Markdown")
