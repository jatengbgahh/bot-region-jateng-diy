"""
commands/salahtagging_wok_old.py — Handler Telegram /salahtagging_wok_old DD-MM-YYYY.

Monitoring RE : Fallout Salah Tagging/Salah Homepass, struktur WOK lama.
Terjadwal (JADWAL_LAPORAN, nama "salahtagging") sementara memakai perintah ini.
Alur kirim & kalkulasi ada di reports/salahhomepass/ (command.py, calculator.py, renderer.py).
"""

from utils.command_registry import TelegramCommand
from telegram.ext import CommandHandler

from reports.salahhomepass.command import jalankan_salahhomepass


def register_handlers(app, timeout_wrapper=None, get_cutoff_fn=None):
    """Daftarkan command /salahtagging_wok_old. Return handler-nya supaya bot.py bisa memakainya di laporan terjadwal."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_salahtagging_wok_old(update, ctx):
        """/salahtagging_wok_old DD-MM-YYYY — Monitoring RE Fallout Salah Tagging/Homepass, struktur WOK lama (16 WOK)."""
        await jalankan_salahhomepass(update, ctx, wok_lama=True, get_cutoff_fn=get_cutoff_fn)

    TelegramCommand("salahtagging_wok_old", cmd_salahtagging_wok_old).register(app, timeout_wrapper=_T)
    return cmd_salahtagging_wok_old
