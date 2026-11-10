"""
Package commands — handler command bot Telegram yang dipisah dari bot.py.

Tiap modul di sini punya register_handlers(app, ...) yang dipanggil dari main()
di bot.py. Logika hitung & gambar report tetap di folder reports/.
  kategori_paket.py  /kategoripaket DD-MM-YYYY — Sales by Kategori Paket
  jadwal.py          /jadwal — daftar jadwal laporan otomatis yang aktif
  reports_schedule.py /reports_schedule — jadwal report otomatis dalam bentuk gambar 3 tabel
  market_share.py    /ms [DD-MM-YYYY] — Market Share per City + MOM Growth Jateng-DIY (auto 10:00 topic MARKET_SHARE)
  wireless2.py       /wireless2, /wirelesschannel2 — wireless tanpa produk Murmer (yang dijadwalkan)
  c3mrsvp.py         /c3mrSVP DD-MM-YYYY — C3MR Fokus SVP (LOS <=24 Bulan), auto 13:15 topic COLLECTION setelah c3mr10s
  homepass.py        /homepass DD-MM-YYYY — Homepass Report (WOK baru)
  homepass_wok_old.py /homepass_wok_old DD-MM-YYYY — Homepass Report (WOK lama; dipakai auto-report sementara)
  salahtagging.py    /salahtagging DD-MM-YYYY — Fallout Salah Tagging/Homepass (WOK baru)
  salahtagging_wok_old.py /salahtagging_wok_old DD-MM-YYYY — idem (WOK lama; dipakai auto-report sementara)
  nasional.py        /nasional DD-MM-YYYY — Daily Tracking IndiHome Performance Region Level + Top/Bottom 3 Ach & Growth RE
"""

from . import kategori_paket, jadwal, wireless2, reports_schedule, market_share, c3mrsvp, nasional, homepass, homepass_wok_old, salahtagging, salahtagging_wok_old

__all__ = ["kategori_paket", "jadwal", "wireless2", "reports_schedule", "market_share", "c3mrsvp", "nasional", "homepass", "homepass_wok_old", "salahtagging", "salahtagging_wok_old"]
