"""
commands/salahtagging.py — Handler Telegram /salahtagging DD-MM-YYYY.

Monitoring RE : Fallout Salah Tagging/Salah Homepass per WOK/BRANCH, WOK baru.
Alur kirim & kalkulasi ada di reports/salahhomepass/ (command.py, calculator.py, renderer.py).
"""

from utils.command_registry import TelegramCommand
from telegram.ext import CommandHandler

from reports.salahhomepass.command import jalankan_salahhomepass


def register_handlers(app, timeout_wrapper=None, get_cutoff_fn=None):
    """Daftarkan command /salahtagging. Return handler-nya supaya bot.py bisa memakainya di laporan terjadwal."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_salahtagging(update, ctx):
        """/salahtagging DD-MM-YYYY — Monitoring RE Fallout Salah Tagging/Homepass, WOK baru."""
        await jalankan_salahhomepass(update, ctx, wok_lama=False, get_cutoff_fn=get_cutoff_fn)

    TelegramCommand("salahtagging", cmd_salahtagging).register(app, timeout_wrapper=_T)
    return cmd_salahtagging
