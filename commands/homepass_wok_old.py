"""
commands/homepass_wok_old.py — Handler Telegram /homepass_wok_old DD-MM-YYYY.

Homepass Report per WOK/BRANCH IndiHome Jateng-DIY, struktur WOK lama.
Terjadwal (JADWAL_LAPORAN, nama "homepass") sementara memakai perintah ini.
Alur kirim & kalkulasi ada di reports/homepass/ (command.py, calculator.py, renderer.py).
"""

from telegram.ext import CommandHandler

from reports.homepass.command import jalankan_homepass


def register_handlers(app, timeout_wrapper=None):
    """Daftarkan command /homepass_wok_old. Return handler-nya supaya bot.py bisa memakainya di laporan terjadwal."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_homepass_wok_old(update, ctx):
        """/homepass_wok_old DD-MM-YYYY — Homepass Report, struktur WOK lama (16 WOK)."""
        await jalankan_homepass(update, ctx, wok_lama=True)

    app.add_handler(CommandHandler("homepass_wok_old", _T(cmd_homepass_wok_old)))
    return cmd_homepass_wok_old
