"""
commands/homepass.py — Handler Telegram /homepass DD-MM-YYYY.

Homepass Report per WOK/BRANCH IndiHome Jateng-DIY (MtD s/d tanggal), WOK baru.
Alur kirim & kalkulasi ada di reports/homepass/ (command.py, calculator.py, renderer.py).
"""

from telegram.ext import CommandHandler

from reports.homepass.command import jalankan_homepass


def register_handlers(app, timeout_wrapper=None):
    """Daftarkan command /homepass. Return handler-nya supaya bot.py bisa memakainya di laporan terjadwal."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_homepass(update, ctx):
        """/homepass DD-MM-YYYY — Homepass Report, struktur WOK baru (14 WOK)."""
        await jalankan_homepass(update, ctx, wok_lama=False)

    app.add_handler(CommandHandler("homepass", _T(cmd_homepass)))
    return cmd_homepass
