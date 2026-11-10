"""
commands/jobs_manager.py — Handler perintah Telegram untuk manajemen job/jadwal dinamis SQLite.

Perintah:
  /jobs                — Tampilkan daftar slot jadwal, status aktif/nonaktif, jam, topic & laporan.
  /jobs_toggle <id>    — Aktifkan atau nonaktifkan slot jadwal secara instan (on/off).
  /jobs_edit <id> <jam>:<menit> [hari] — Ubah jam/menit jadwal tanpa restart bot.
  /jobs_run <id>       — Trigger ulang manual slot jadwal sekarang (tanpa menunggu jamnya).
  /jobs_logs [id]      — Tampilkan log eksekusi report terakhir (waktu, status, media terkirim, error).
  /jobs_reload         — Muat ulang scheduler bot dari database SQLite.
"""

import html
import logging
from datetime import datetime
from typing import Callable, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from utils import scheduler_db

logger = logging.getLogger(__name__)


def register_handlers(app: Application, timeout_wrapper: Optional[Callable] = None, reload_jobs_fn: Optional[Callable] = None, trigger_job_fn: Optional[Callable] = None):
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_jobs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/jobs — Daftar jadwal aktif & nonaktif."""
        jobs = scheduler_db.get_all_jobs()
        if not jobs:
            await update.message.reply_text("⚠️ Belum ada jadwal yang terdaftar di database.")
            return

        lines = ["📋 <b>Manajemen Jadwal Report (SQLite)</b>\n"]
        for j in jobs:
            status_emoji = "🟢" if j["is_active"] else "🔴 [OFF]"
            wa_badge = " 💬+WA" if j.get("wa") else ""
            hari_str = f" ({j['hari'].capitalize()})" if j.get("hari") else ""
            reps = ", ".join(f"/{r[0]}" for r in j["laporan"])
            lines.append(
                f"<b>#{j['id']}</b> {status_emoji} <b>{j['jam']:02d}:{j['menit']:02d}</b>{hari_str} "
                f"→ <i>{html.escape(j['topic'])}</i>{wa_badge}\n"
                f"   ↳ {html.escape(reps)}"
            )

        lines.append("\n💡 <b>Perintah Manajemen:</b>")
        lines.append("• <code>/jobs_toggle &lt;id&gt;</code> — Aktifkan / Nonaktifkan jadwal")
        lines.append("• <code>/jobs_edit &lt;id&gt; 14:30 [SENIN]</code> — Ganti jam/hari")
        lines.append("• <code>/jobs_run &lt;id&gt;</code> — Jalankan ulang slot sekarang")
        lines.append("• <code>/jobs_logs [id]</code> — Cek riwayat eksekusi")
        lines.append("• <code>/jobs_reload</code> — Sinkronisasi ulang jadwal aktif")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def cmd_jobs_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/jobs_toggle <id> — On/Off jadwal."""
        if not ctx.args:
            await update.message.reply_text("⚠️ Gunakan format: `/jobs_toggle <id>`\nContoh: `/jobs_toggle 1`", parse_mode="Markdown")
            return
        try:
            jid = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("❌ ID jadwal harus berupa angka.")
            return

        job = scheduler_db.get_job_by_id(jid)
        if not job:
            await update.message.reply_text(f"❌ Jadwal dengan ID #{jid} tidak ditemukan.")
            return

        new_status = not bool(job["is_active"])
        scheduler_db.toggle_job(jid, active=new_status)
        if reload_jobs_fn:
            reload_jobs_fn(ctx.application)

        status_text = "🟢 AKTIF" if new_status else "🔴 NONAKTIF (PAUSED)"
        await update.message.reply_text(
            f"✅ Jadwal <b>#{jid}</b> ({html.escape(job['label'])}) sekarang berstatus: <b>{status_text}</b>.\n"
            f"Scheduler bot telah diperbarui secara langsung.",
            parse_mode=ParseMode.HTML,
        )

    async def cmd_jobs_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/jobs_edit <id> <jam>:<menit> [hari]"""
        if len(ctx.args or []) < 2:
            await update.message.reply_text("⚠️ Gunakan format: `/jobs_edit <id> <jam:menit> [hari]`\nContoh: `/jobs_edit 1 07:30` atau `/jobs_edit 1 10:00 SENIN`", parse_mode="Markdown")
            return
        try:
            jid = int(ctx.args[0])
            waktu_parts = ctx.args[1].split(":")
            jam, menit = int(waktu_parts[0]), int(waktu_parts[1])
            hari = ctx.args[2].upper() if len(ctx.args) > 2 else None
        except Exception:
            await update.message.reply_text("❌ Format salah. Contoh: `/jobs_edit 1 07:30`", parse_mode="Markdown")
            return

        ok = scheduler_db.update_job_time(jid, jam, menit, hari)
        if not ok:
            await update.message.reply_text(f"❌ Gagal memperbarui jadwal ID #{jid}.")
            return

        if reload_jobs_fn:
            reload_jobs_fn(ctx.application)

        hari_str = f" tiap {hari.capitalize()}" if hari else " tiap hari"
        await update.message.reply_text(
            f"✅ Waktu jadwal <b>#{jid}</b> berhasil diubah menjadi <b>{jam:02d}:{menit:02d}</b> WIB{hari_str}.\n"
            f"Scheduler bot langsung diperbarui.",
            parse_mode=ParseMode.HTML,
        )

    async def cmd_jobs_reload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/jobs_reload — Sinkronisasi scheduler & daftar command menu dengan database."""
        from utils.command_registry import sync_commands_to_db, sync_telegram_menu_from_db

        # Sinkronisasi deklaratif bila ada class report baru
        new_synced = scheduler_db.sync_declared_report_schedules()
        cmd_stats = sync_commands_to_db()
        menu_count = await sync_telegram_menu_from_db(ctx.bot)
        if reload_jobs_fn:
            total = reload_jobs_fn(ctx.application)
            extra_msg = f" (ditemukan & didaftarkan {new_synced} report baru)" if new_synced > 0 else ""
            await update.message.reply_text(
                f"🔄 Berhasil memuat ulang {total} slot jadwal aktif{extra_msg} "
                f"serta memperbarui {menu_count} command di Menu Button Telegram "
                f"(+{cmd_stats['added']} / ~{cmd_stats['updated']} / -{cmd_stats['removed']})."
            )
        else:
            await update.message.reply_text("⚠️ Fungsi reload jadwal belum terpasang.")

    async def cmd_jobs_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/jobs_run <id> — Trigger ulang manual sebuah slot jadwal sekarang."""
        if not ctx.args:
            await update.message.reply_text("⚠️ Gunakan format: `/jobs_run <id>`\nContoh: `/jobs_run 1`", parse_mode="Markdown")
            return
        try:
            jid = int(ctx.args[0])
        except ValueError:
            await update.message.reply_text("❌ ID jadwal harus berupa angka.")
            return

        job = scheduler_db.get_job_by_id(jid)
        if not job:
            await update.message.reply_text(f"❌ Jadwal ID #{jid} tidak ditemukan.")
            return

        await update.message.reply_text(
            f"🚀 Menjalankan manual slot jadwal <b>#{jid}</b> ({html.escape(job['label'])})...",
            parse_mode=ParseMode.HTML,
        )
        if trigger_job_fn:
            ctx.application.create_task(trigger_job_fn(ctx, job, triggered_by="MANUAL"))
        else:
            await update.message.reply_text("⚠️ Runner manual belum dihubungkan.")

    async def cmd_jobs_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """/jobs_logs [id] — Cek riwayat eksekusi."""
        jid = int(ctx.args[0]) if ctx.args and ctx.args[0].isdigit() else None
        logs = scheduler_db.get_recent_logs(limit=10, job_id=jid)
        if not logs:
            await update.message.reply_text("ℹ️ Belum ada catatan riwayat eksekusi job.")
            return

        lines = [f"📊 <b>Riwayat Eksekusi Job {'#' + str(jid) if jid else 'Terbaru'}</b>\n"]
        for lg in logs:
            status_emoji = "✅" if lg["status"] == "SUCCESS" else ("❌" if lg["status"] == "FAILED" else "⏳")
            trig = "👤 Manual" if lg["triggered_by"] == "MANUAL" else "⏰ Auto"
            err = f"\n   ⚠️ <i>{html.escape(lg['error_message'][:120])}</i>" if lg.get("error_message") else ""
            lines.append(
                f"{status_emoji} <b>{lg['waktu_mulai']}</b> — <b>/{lg['report_name']}</b> ({lg['topic']})\n"
                f"   ↳ {trig} | Media: {lg['media_terkirim']}{err}"
            )

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    from utils.command_registry import TelegramCommand

    for cmd_obj in (
        TelegramCommand("jobs", cmd_jobs, "Manajemen jadwal report dinamis (SQLite)", category="SCHEDULER"),
        TelegramCommand("jobs_toggle", cmd_jobs_toggle, "Aktifkan / nonaktifkan slot jadwal report (on/off)", category="SCHEDULER"),
        TelegramCommand("jobs_edit", cmd_jobs_edit, "Ubah jam/hari jadwal report tanpa restart bot", category="SCHEDULER"),
        TelegramCommand("jobs_reload", cmd_jobs_reload, "Muat ulang jadwal & sinkronkan menu command dari DB", category="SCHEDULER"),
        TelegramCommand("jobs_run", cmd_jobs_run, "Jalankan manual slot jadwal report sekarang juga", category="SCHEDULER"),
        TelegramCommand("jobs_logs", cmd_jobs_logs, "Lihat riwayat eksekusi jadwal report terakhir", category="SCHEDULER"),
    ):
        cmd_obj.register(app, timeout_wrapper=_T)
