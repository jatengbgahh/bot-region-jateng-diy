"""
utils/command_registry.py — Class Command OOP, Auto-Sync SQLite (termasuk kolom `help_text`),
Menu Ringkas Dinamis (`/menu`), Bantuan Detail (`/menu help <cmd>` & `/<cmd> help`),
dan Auto-Update Menu Button Telegram.

Arsitektur:
  1. `TelegramCommand`: Class representasi command Telegram. Setiap command didaftarkan
     sebagai objek dari class ini (memiliki atribut `command`, `handler`, `description`,
     `help_text`, `category`, `use_timeout`, `show_in_menu`, `sort_order`).
  2. `CommandRegistry`: Menyimpan seluruh objek `TelegramCommand` yang aktif di kode saat ini,
     sekaligus memindai `app.handlers` agar `CommandHandler` dari sub-modul mana pun
     otomatis tercatat sebagai objek `TelegramCommand`.
  3. Sinkronisasi Database SQLite (`bot_commands` di `storage/state/scheduler.db`):
     - Menyimpan kolom `command`, `description` (info singkat), `help_text` (penjelasan detail),
       `category`, `handler_name`, `use_timeout`, `show_in_menu`, dan `sort_order`.
     - Jika ada penambahan command di kode -> otomatis di-INSERT ke tabel `bot_commands`.
     - Jika ada perubahan deskripsi/help_text di kode -> otomatis di-UPDATE di tabel `bot_commands`.
     - Jika ada pengurangan/penghapusan command di kode -> otomatis dihapus dari tabel `bot_commands`.
  4. Auto-Update Telegram Command Menu Button (`set_my_commands` & `set_chat_menu_button`):
     - Mengambil daftar command langsung dari tabel SQLite `bot_commands`.
     - Mendaftarkan daftar tersebut secara otomatis dan terprogram ke Menu Button Telegram
       setiap kali bot dinyalakan atau direstart (`post_init`).
"""

from __future__ import annotations

import html
import inspect
import logging
import re
from datetime import datetime
from typing import Any, Callable, Optional

from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from utils import scheduler_db

logger = logging.getLogger(__name__)

# Validasi format command Telegram: 1-32 karakter, huruf kecil, angka, dan underscore
_VALID_CMD_RE = re.compile(r"^[a-z0-9_]{1,32}$")

# Urutan prioritas kategori di Menu Button Telegram & /menu
CATEGORY_ORDER: dict[str, int] = {
    "LIVE_DB": 10,
    "REPORT": 20,
    "SCHEDULER": 30,
    "WHATSAPP": 40,
    "LEGACY": 50,
    "UTILITY": 60,
}

CATEGORY_LABELS: dict[str, str] = {
    "LIVE_DB": "🔴 LIVE DB & CLOSING HARIAN",
    "REPORT": "📊 REPORT PENJUALAN, SF, C3MR & CAPS",
    "SCHEDULER": "⏰ JADWAL & MANAJEMEN JOB",
    "WHATSAPP": "💬 WHATSAPP (WAHA)",
    "LEGACY": "📦 UPLOAD KPRO / HADOOP (ALUR LAMA)",
    "UTILITY": "⚙️ UTILITAS & SISTEM",
}

# Kamus deskripsi singkat default (maks 256 karakter, untuk Menu Button Telegram & daftar ringkas /menu)
DEFAULT_COMMAND_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    # 1. LIVE DB & CLOSING HARIAN
    "liveupdate": ("Monitoring RE & RE-PS hari ini secara live dari DB", "LIVE_DB"),
    "closingsql": ("Laporan closing harian IO-RE-PS, WOK, City & Channel", "LIVE_DB"),
    "dailyre": ("Monitoring Daily RE terhadap target weekday/weekend", "LIVE_DB"),
    "nasional": ("Daily Tracking IndiHome tingkat Nasional (12 Region)", "LIVE_DB"),
    "dod": ("PS Harian & %DoD PS per Branch dan WOK", "LIVE_DB"),
    "liveupdateutoip": ("Backup /liveupdate dari sumber FMC API", "LIVE_DB"),
    "liveupdatebk": ("Backup /liveupdate dari raw ordering_detail", "LIVE_DB"),
    "closingutoip": ("Backup /closingsql dari sumber FMC API", "LIVE_DB"),
    "closingbk": ("Backup /closingsql dari raw ordering_detail", "LIVE_DB"),
    # 2. REPORT PENJUALAN, SF, C3MR, CAPS, PRANPC, HOMEPASS
    "promo": ("PS harian paket promo One Dynamic per Branch/WOK/City", "REPORT"),
    "kategoripaket": ("Sales PS berdasarkan kategori paket (Tsel One/EZnet/Reguler)", "REPORT"),
    "addon": ("Laporan penjualan Addon (FTTR, IP Camera, Mesh Wifi)", "REPORT"),
    "sf": ("Produktivitas SF channel Agency (SF Aktif & PS)", "REPORT"),
    "5so": ("5SO Scorecard & Momentum per Region/Branch/WOK", "REPORT"),
    "7so": ("7SO Scorecard basis RE + Excel SF Belum RE & Raw", "REPORT"),
    "pdd": ("Report Pembayaran di Depan (PDD) per Branch/WOK", "REPORT"),
    "djp": ("Evaluasi aktivitas kunjungan DJP SF dari DB", "REPORT"),
    "djpcsv": ("Laporan evaluasi DJP SF dari CSV manual", "REPORT"),
    "mbcsv": ("Laporan kehadiran Morning Briefing SF dari CSV", "REPORT"),
    "djpprio": ("Report DJP ODP Priority (%Visit ODP per WOK/Branch)", "REPORT"),
    "performance": ("SF Performance Tracking (MB, DJP, PS, Daily & SAPA)", "REPORT"),
    "clockin_sf_teritory": ("Report Clock-in SF Teritory MTD (PNG + Teks + Excel)", "REPORT"),
    "clockin_sf_all": ("Report Clock-in SF All Category MTD per WOK", "REPORT"),
    "homepass_raw": ("Unduh file Excel mentah Detail Homepass hasil SELA", "REPORT"),
    "homepass": ("Homepass Report IO/RE/PS Home ID per WOK & STO", "REPORT"),
    "homepass_wok_old": ("Homepass Report dengan struktur 16 WOK lama", "REPORT"),
    "salahtagging": ("Monitoring RE Fallout Salah Tagging / Salah Homepass", "REPORT"),
    "salahtagging_wok_old": ("Monitoring Salah Tagging dengan struktur 16 WOK lama", "REPORT"),
    "wireless": ("Performance MtD IO-RE-PS EZNet Wireless per WOK", "REPORT"),
    "wireless2": ("Performance EZNet Wireless per WOK (tanpa Murmer)", "REPORT"),
    "wirelesschannel": ("PS EZNet Wireless by Channel (Household/Mobile/dll)", "REPORT"),
    "wirelesschannel2": ("PS EZNet Wireless by Channel (tanpa Murmer)", "REPORT"),
    "murmer": ("Report EZNet Wireless Murmer (Daily/MTD/YTD per Region)", "REPORT"),
    "c3mr": ("C3MR Clearing Rate Early Tenure & All LoS per WOK/City", "REPORT"),
    "c3mr10s": ("C3MR Clearing Rate per 12 Customer Segment", "REPORT"),
    "c3mrnew": ("C3MR pelanggan baru per umur tagihan (BILL-1 s/d BILL-6)", "REPORT"),
    "c3mrnewch": ("C3MR LoS 0-6 Bulan per Channel Group", "REPORT"),
    "c3mrsvp": ("C3MR Fokus SVP (Pelanggan LoS <= 24 Bulan) per WOK/City", "REPORT"),
    "payment": ("Ekspor CSV data mentah pembayaran C3MR per tanggal", "REPORT"),
    "klaim": ("Rekap data pelanggan klaim per program & status bayar", "REPORT"),
    "caps": ("Laporan Churn/CAPS (by LoS, Segmen, Channel & Reason)", "REPORT"),
    "pranpcall": ("Recovery Rate (SSL) PraNPC All WO per WOK (DB Indiana)", "REPORT"),
    "pranpcagent": ("Report PraNPC per Channel Agent per WOK", "REPORT"),
    "moretensi": ("Retensi PraNPC All LoS per WOK (MO Retensi, DO, CT0)", "REPORT"),
    "pranpcsp": ("PraNPC Agency & Super Partner per WOK (%RR, %Caring, %Visit)", "REPORT"),
    "pranpcprio": ("PraNPC by Prioritas (Branch x P1/P2/P3/Tactical)", "REPORT"),
    "agresif": ("Report New Sales Kecamatan Agresif & All FMC City", "REPORT"),
    "leads": ("Progress Caring Leads IO per WOK (jatenggayeng.id)", "REPORT"),
    "childps": ("Report Child per PS Telkomsel One by WOK", "REPORT"),
    "ms": ("Market Share FBB per City Jateng-DIY + MoM Growth", "REPORT"),
    "msbranch": ("Market Share FBB per Branch Jateng-DIY", "REPORT"),
    # 3. MANAJEMEN JADWAL & COMMAND (SQLITE)
    "jadwal": ("Tampilkan daftar jadwal laporan otomatis yang aktif", "SCHEDULER"),
    "reports_schedule": ("Tabel gambar jadwal report otomatis (Telegram & WA)", "SCHEDULER"),
    "jobs": ("Manajemen jadwal report dinamis (SQLite)", "SCHEDULER"),
    "jobs_add": ("Tambah slot jadwal report baru tanpa restart bot", "SCHEDULER"),
    "jobs_del": ("Hapus slot jadwal report berdasarkan ID", "SCHEDULER"),
    "jobs_toggle": ("Aktifkan / nonaktifkan slot jadwal report (on/off)", "SCHEDULER"),
    "jobs_edit": ("Ubah jam/hari jadwal report tanpa restart bot", "SCHEDULER"),
    "jobs_run": ("Jalankan manual slot jadwal report sekarang juga", "SCHEDULER"),
    "jobs_logs": ("Lihat riwayat eksekusi jadwal report terakhir", "SCHEDULER"),
    "jobs_reload": ("Muat ulang jadwal & sinkronkan menu command dari DB", "SCHEDULER"),
    # 4. WHATSAPP MANUAL TRIGGER
    "liveupdate_wa": ("Kirim laporan /liveupdate ke WhatsApp via WAHA", "WHATSAPP"),
    "closingsql_wa": ("Kirim laporan /closingsql ke WhatsApp via WAHA", "WHATSAPP"),
    "agresif_wa": ("Kirim laporan /agresif ke WhatsApp via WAHA", "WHATSAPP"),
    # 5. ALUR LAMA (KPRO / HADOOP UPLOAD)
    "closing": ("Laporan closing dari file upload KPRO [DD-MM-YYYY]", "LEGACY"),
    "closinghadoop": ("Laporan closing dari file upload Hadoop CSV", "LEGACY"),
    "dailyreps": ("Ulang laporan daily RE & PS dari upload terakhir", "LEGACY"),
    "closingdaily": ("Laporan closing daily RE & PS dari upload terakhir", "LEGACY"),
    # 6. UTILITAS & MENU
    "start": ("Panduan lengkap penggunaan bot", "UTILITY"),
    "menu": ("Daftar ringkas semua command (ketik /menu help <cmd> utk detail)", "UTILITY"),
    "status": ("Cek status bot, target tersimpan, & koneksi DB", "UTILITY"),
    "dbstatus": ("Cek status koneksi & tabel database bulan berjalan", "UTILITY"),
    "dbinfo": ("Cek waktu update terakhir data di database", "UTILITY"),
    "modequery": ("Lihat atau ubah mode query (langsung / rajawali / auto)", "UTILITY"),
    "rajawali": ("Jalankan report paksa lewat otomasi Rajawali Dashboard", "UTILITY"),
    "target": ("Lihat ringkasan target RE/PS per WOK yang tersimpan", "UTILITY"),
    "gp": ("Cek status & sambungkan VPN GlobalProtect di server", "UTILITY"),
}

# Kamus HELP LENGKAP (disimpan di kolom `help_text` pada tabel SQLite `bot_commands`)
DEFAULT_COMMAND_HELP: dict[str, str] = {
    "liveupdate": (
        "Format: `/liveupdate`\n"
        "Sumber: `dashboard_hourly_sales` (MySQL Rajawali, struktur 14 WOK baru).\n"
        "Output: 2 gambar (Monitoring RE Hourly & Monitoring RE-PS) + caption Top 5 & Bottom 5 WOK Ach RE.\n"
        "⏰ Jadwal otomatis: 13:00, 15:00, 17:00, 19:00, 21:00 WIB (topic SALES + WhatsApp)."
    ),
    "liveupdateutoip": (
        "Format: `/liveupdateutoip`\n"
        "Backup `/liveupdate` menggunakan sumber API dashboard FMC (membutuhkan `FMC_COOKIE` dan `FMC_XTOKEN` aktif)."
    ),
    "liveupdatebk": (
        "Format: `/liveupdatebk`\n"
        "Backup `/liveupdate` yang dihitung ulang langsung dari tabel mentah `indihome_ordering_detail`."
    ),
    "closingsql": (
        "Format: `/closingsql DD-MM-YYYY`\n"
        "Contoh: `/closingsql 27-10-2026`\n"
        "Sumber: `indihome_ordering_detail` (MySQL Rajawali).\n"
        "Output: Paket 5 gambar closing harian:\n"
        "  1. Monitoring RE Closing\n"
        "  2. Daily IO-RE-PS (DoD, WoW, MoM + pembanding D-1 & D-7)\n"
        "  3. Performance MtD by WOK (IO, RE, PS, ACH, DRR, Revenue, ARPU)\n"
        "  4. Performance MtD by City (40 Kabupaten/Kota)\n"
        "  5. IO-RE-PS by Channel (AGENCY, GRAPARI, DIGITAL, COMMUNITY)\n"
        "⏰ Jadwal otomatis: 07:00 WIB setiap hari untuk H-1 (topic SALES + WhatsApp)."
    ),
    "closingutoip": (
        "Format: `/closingutoip DD-MM-YYYY`\n"
        "Backup `/closingsql` menggunakan sumber API dashboard FMC."
    ),
    "closingbk": (
        "Format: `/closingbk DD-MM-YYYY`\n"
        "Backup `/closingsql` yang dihitung ulang dari tabel mentah `indihome_ordering_detail`."
    ),
    "dailyre": (
        "Format: `/dailyre DD-MM-YYYY` (atau `DD/MM/YYYY`)\n"
        "Monitoring Daily RE terhadap target harian yang dibedakan hari kerja (weekday) dan akhir pekan (weekend), "
        "lengkap dengan koreksi target untuk esok hari (`TGT RE D+1 = base(d+1) - GAP`)."
    ),
    "nasional": (
        "Format: `/nasional [DD-MM-YYYY]` (kosong = H-1)\n"
        "Daily Tracking IndiHome tingkat Nasional: 12 Region, Area 1-4, dan Total Nasional "
        "(IO, RE, PS, Revenue, ARPU, MoM, Ach terhadap `TARGET_REGION`).\n"
        "⏰ Jadwal otomatis: 07:00 WIB setiap hari untuk H-1 (topic SALES)."
    ),
    "dod": (
        "Format: `/dod DD-MM-YYYY [count|pct]`\n"
        "PS Harian & %DoD (Day over Day) PS per Branch dan WOK untuk bulan berjalan "
        "(2 gambar: grafik batang + tabel jumlah PS per tanggal dengan pembagian Tsel One/EZNET/IH Reguler, serta tabel %DoD).\n"
        "⏰ Jadwal otomatis: 07:00 WIB setiap hari untuk H-1 (topic SALES)."
    ),
    "promo": (
        "Format: `/promo [DD-MM-YYYY]` (kosong = H-1)\n"
        "PS harian khusus paket promo One Dynamic Promo per Branch, WOK, dan City dalam 1 gambar gabungan."
    ),
    "kategoripaket": (
        "Format: `/kategoripaket DD-MM-YYYY`\n"
        "Sales (PS) berdasarkan kategori paket IndiHome Jateng-DIY: Tsel One, EZnet, dan IH Reguler "
        "(MtD, MoM, Cont %, MoM Cont pp)."
    ),
    "addon": (
        "Format: `/addon DD-MM-YYYY`\n"
        "Laporan penjualan produk Addon (`MODIFICATION - ADDON`): FTTR, IP Camera (Indoor Camera), dan Mesh Wifi "
        "per Branch/WOK (2 bulan penuh + MTD, YTD, %Contr, ACH to Target).\n"
        "⏰ Jadwal otomatis: Senin 10:00 WIB untuk H-1 (topic SALES)."
    ),
    "sf": (
        "Format: `/sf DD-MM-YYYY`\n"
        "Produktivitas Sales Force (SF) channel AGENCY per WOK/Branch: SF Registered (`SF_AKTIF`), "
        "SF Aktif PS, Total PS, %SF Aktif, dan SF Productivity (TODAY, MtD, M-1, MoM)."
    ),
    "5so": (
        "Format: `/5so [DD-MM-YYYY]` (kosong = H-1)\n"
        "5SO Scorecard basis PS: SF Registered, SF Aktif, SF Produktif, Produktivitas, SF Aktif DJP, "
        "ODP Visited per Region/Branch/WOK + Momentum Skor & Status."
    ),
    "7so": (
        "Format: `/7so [DD-MM-YYYY] [scorecard|belum_re|raw]` (kosong = H-1)\n"
        "7SO Scorecard basis RE: SF Aktif DJP, ODP Visit, DJP/SF/Day, SF Aktif, SF Produktif, Produktivitas, "
        "SF Registered per Region/Branch/WOK + Momentum Skor & Status, disusul Excel *SF Belum RE MTD* dan "
        "Excel *5SO 7SO per SF + RAW* (dengan Team Leader)."
    ),
    "pdd": (
        "Format: `/pdd DD-MM-YYYY`\n"
        "Report Pembayaran di Depan (PDD) per Branch/WOK: SF Active, SF Active PDD, %SF Active, "
        "New Sales PDD by SF, Avg Sales PDD by SF, TRX & Kontribusi per Channel.\n"
        "⏰ Jadwal otomatis: Senin 10:00 WIB untuk H-1 (topic SALES)."
    ),
    "djp": (
        "Format: `/djp DD-MM-YYYY`\n"
        "Evaluasi aktivitas kunjungan door-to-door (DJP) SF dari tabel `djp_daily_user_detailed_YYYYMM` "
        "(Visit DJP, Unique ODP, SF DJP, %SF Active DJP, DJP per SF)."
    ),
    "djpcsv": (
        "Format: `/djpcsv DD-MM-YYYY`\n"
        "Laporan evaluasi DJP SF dari file CSV yang diupload manual ke bot."
    ),
    "mbcsv": (
        "Format: `/mbcsv DD-MM-YYYY`\n"
        "Laporan kehadiran Morning Briefing (MB) SF dari file CSV manual (`SCHEDULE CATEGORY = BRIEFING`)."
    ),
    "djpprio": (
        "Format: Upload file *Approve-Tugas* DJP dengan caption `/djpprio [DD-MM-YYYY]` (atau reply file dengan `/djpprio`).\n"
        "Menghasilkan Report DJP ODP Priority: %Visit ODP prioritas (P1A s/d P3B) per WOK & Branch "
        "berdasarkan master `resources/djp_priority/DJP ODP Priority - <Bulan> <Tahun>.xlsx` terbaru."
    ),
    "performance": (
        "Format: Kirim 1 s/d 6 file sekaligus (PS apple-to-apple + approve-tugas + opsional Data SF Master, "
        "dan/atau 3 file SAPA: Assignment + Survey + Prospect Homepass) dengan caption `/performance [DD-MM-YYYY]`.\n"
        "Menghasilkan SF Performance Tracking Process, Result & Daily Monitoring (7 gambar + caption) "
        "dan/atau Report SAPA (1 gambar + caption)."
    ),
    "clockin_sf_teritory": (
        "Format: `/clockin_sf_teritory [DD-MM-YYYY] [tabel|excel]` (kosong = H-1)\n"
        "Menyusun *Report Clock-in SF Teritory* MTD (gambar PNG + teks ringkasan + Excel 5 sheet) "
        "dengan memadukan daftar SF Teritory dari Excel SharePoint (`SF_TERITORY_URL`) dan file `detail-homepass` hasil scraping SELA.\n"
        "Ganti link SharePoint tanpa restart bot: `/clockin_sf_teritory url=https://...`"
    ),
    "clockin_sf_all": (
        "Format: `/clockin_sf_all [DD-MM-YYYY] [tabel|excel]` (kosong = H-1)\n"
        "Menyusun *Report Clock-In SF All Category* MTD: SF Assign DJP, SF Clockin DJP, Clock-in ODP & Homepass "
        "seluruh SF terdaftar per WOK (gambar PNG + teks + Excel 5 sheet)."
    ),
    "homepass_raw": (
        "Format: `/homepass_raw [DD-MM-YYYY]` (kosong = H-1)\n"
        "Mengirimkan file Excel mentah `detail-homepass_*.xlsx` hasil scraping SELA dengan caption `Raw Data Clockin Homepass MTD <tgl>`."
    ),
    "homepass": (
        "Format: `/homepass DD-MM-YYYY`\n"
        "Homepass Report per WOK/Branch (14 WOK baru): IO/RE/PS Home ID, RE Salah Homepass, SF Active with Home ID, "
        "serta 3 gambar rincian per STO untuk masing-masing 2 branch.\n"
        "⏰ Jadwal otomatis: Senin 10:00 WIB untuk H-1 (topic GTM)."
    ),
    "homepass_wok_old": (
        "Format: `/homepass_wok_old DD-MM-YYYY`\n"
        "Sama seperti `/homepass`, namun menggunakan struktur 16 WOK lama."
    ),
    "salahtagging": (
        "Format: `/salahtagging DD-MM-YYYY`\n"
        "Monitoring RE Fallout 'Salah Tagging / Salah Homepass' per WOK/Branch (14 WOK baru), "
        "dipecah per AGENCY, NON AGENCY, dan ALL CHANNEL beserta lampiran file raw.\n"
        "⏰ Jadwal otomatis: Senin 10:00 WIB untuk H-1 (topic GTM)."
    ),
    "salahtagging_wok_old": (
        "Format: `/salahtagging_wok_old DD-MM-YYYY`\n"
        "Sama seperti `/salahtagging`, namun menggunakan struktur 16 WOK lama."
    ),
    "wireless": (
        "Format: `/wireless DD-MM-YYYY`\n"
        "Performance MtD IO-RE-PS *EZNet Wireless* (termasuk Murmer) per WOK/Branch terhadap target `TARGET_WIRELESS`."
    ),
    "wireless2": (
        "Format: `/wireless2 DD-MM-YYYY`\n"
        "Performance MtD IO-RE-PS *EZNet Wireless* per WOK/Branch **tanpa produk Murmer**.\n"
        "⏰ Jadwal otomatis: 07:30 WIB setiap hari untuk H-1 (topic SALES)."
    ),
    "wirelesschannel": (
        "Format: `/wirelesschannel DD-MM-YYYY`\n"
        "PS EZNet Wireless Jateng-DIY by Channel (SF Household, SF Mobile, GraPARI, Digital, Community; MtD + MoM)."
    ),
    "wirelesschannel2": (
        "Format: `/wirelesschannel2 DD-MM-YYYY`\n"
        "PS EZNet Wireless Jateng-DIY by Channel **tanpa produk Murmer**.\n"
        "⏰ Jadwal otomatis: 07:30 WIB setiap hari untuk H-1 (topic SALES)."
    ),
    "murmer": (
        "Format: `/murmer [DD-MM-YYYY] [raw]` (kosong = H-1)\n"
        "Report khusus EZNet Wireless *Murmer*: Daily, MTD, dan YTD per Region (Jateng-DIY, Jatim, Jabar, Eastern Jabotabek) "
        "+ %Ach YTD vs target dan ranking di caption. Hari Senin otomatis disusul file Excel raw Jateng-DIY "
        "(tambahkan argumen `raw` untuk meminta file Excel di hari lain).\n"
        "⏰ Jadwal otomatis: 07:30 WIB setiap hari untuk H-1 (topic SALES)."
    ),
    "c3mr": (
        "Format: `/c3mr DD-MM-YYYY [wok|city|los]`\n"
        "Laporan C3MR (Clearing Rate) tagihan bulan berjalan per WOK/Branch (Early Tenure 0-6 bulan vs All LoS), "
        "per City, dan per kelompok LoS (3 gambar).\n"
        "⏰ Jadwal otomatis: 13:15 WIB setiap hari untuk H-1 (topic COLLECTION)."
    ),
    "c3mr10s": (
        "Format: `/c3mr10s DD-MM-YYYY`\n"
        "Laporan C3MR Clearing Rate per 12 Customer Segment (CVM) per WOK.\n"
        "⏰ Jadwal otomatis: 13:15 WIB setiap hari untuk H-1 (topic COLLECTION)."
    ),
    "c3mrnew": (
        "Format: `/c3mrnew DD-MM-YYYY [tabel|csv]`\n"
        "Laporan C3MR pelanggan baru per umur tagihan (BILL-1 s/d BILL-6) per WOK/Branch + lampiran CSV pelanggan unpaid.\n"
        "⏰ Jadwal otomatis: 13:15 WIB setiap hari untuk H-1 (topic COLLECTION)."
    ),
    "c3mrnewch": (
        "Format: `/c3mrnewch DD-MM-YYYY`\n"
        "Laporan C3MR LoS 0-6 Bulan (Total + BILL-1 s/d BILL-6) yang dikelompokkan per *Channel Group* "
        "(Agency, GraPARI, B2B2C&Others, Sobi Affiliate, Web&App).\n"
        "⏰ Jadwal otomatis: 13:15 WIB setiap hari untuk H-1 (topic COLLECTION)."
    ),
    "c3mrsvp": (
        "Format: `/c3mrsvp DD-MM-YYYY [wok|city]`\n"
        "Laporan C3MR Fokus SVP (khusus pelanggan LoS <= 24 Bulan) per WOK/Branch dan per City, "
        "lengkap dengan caption Top 3 & Bottom 3 WOK.\n"
        "⏰ Jadwal otomatis: 13:15 WIB setiap hari untuk H-1 (topic COLLECTION)."
    ),
    "payment": (
        "Format: `/payment DD-MM-YYYY`\n"
        "Mengekspor data mentah pembayaran C3MR pada satu tanggal dalam bentuk file CSV "
        "(`bb_id, account_num, payment_date, clearing_amount, payment_amount`)."
    ),
    "klaim": (
        "Format: `/klaim`\n"
        "Rekap data pelanggan klaim per Nama Program dari file `resources/klaim/Rekap Data Pelanggan Klaim.xlsx` "
        "dengan status Paid Flag yang diperbarui live dari tabel `bwmp_c3mr_dd` (3 gambar + file Excel raw unpaid).\n"
        "⏰ Jadwal otomatis: 14:00 WIB setiap hari (topic GTM)."
    ),
    "caps": (
        "Format: `/caps DD-MM-YYYY [los|segmen|channel|reason]`\n"
        "Laporan Churn / CAPS dalam 4 gambar:\n"
        "  1. `los` — Churn by LoS terhadap target `TARGET_CAPS`\n"
        "  2. `segmen` — Churn by 12 Customer Segment\n"
        "  3. `channel` — Retensi DO by Channel (GraPARI, Call Center, E-Care, Others)\n"
        "  4. `reason` — Top 5 alasan berhenti per Branch & Region\n"
        "⏰ Jadwal otomatis: 13:00 WIB setiap hari untuk H-2 (topic CAPS)."
    ),
    "pranpcall": (
        "Format: `/pranpcall [DD-MM-YYYY]` (kosong = data terakhir)\n"
        "Recovery Rate (SSL) PraNPC All WO per WOK dari database Indiana (`DB2_*`)."
    ),
    "pranpcagent": (
        "Format: `/pranpcagent [DD-MM-YYYY]` (kosong = data terakhir)\n"
        "Report PraNPC per Channel Agent (Agency/SP, CTB, Freelance, OBC) per WOK (DB Indiana)."
    ),
    "moretensi": (
        "Format: `/moretensi [DD-MM-YYYY]` (kosong = data terakhir)\n"
        "Retensi PraNPC All LoS per WOK: MO Retensi CTB/Non CTB/Prepaid, Ach, DO, dan New CT0 (DB Indiana)."
    ),
    "pranpcsp": (
        "Format: `/pranpcsp [DD-MM-YYYY]` (kosong = data terakhir)\n"
        "PraNPC Agency & Super Partner per WOK: %RR SSL/Rp, %Caring, %Visit, %Contacted, dan MoM Paid (DB Indiana)."
    ),
    "pranpcprio": (
        "Format: `/pranpcprio [DD-MM-YYYY]` (kosong = data terakhir)\n"
        "PraNPC by Prioritas (Branch x P1/P2/P3/TACTICAL): %RR, %Caring, %Visit, %Contacted (DB Indiana)."
    ),
    "agresif": (
        "Format: `/agresif DD-MM-YYYY`\n"
        "Report Kecamatan Agresif *LITE* (2 gambar): *NEW SALES LOKASI AGRESIF* (47 kecamatan + 4 kota agresif) "
        "dan *NEW SALES ALL FMC CITY* (13 kota baru + 12 kota lama), lengkap dengan geocoding koordinat, "
        "caption Top ACH / Top MoM / Worst MoM PS, serta file raw.\n"
        "⏰ Jadwal otomatis: 07:30 WIB setiap hari untuk H-1 (topic SALES + WhatsApp)."
    ),
    "leads": (
        "Format: `/leads`\n"
        "Progress Caring Leads IO: login otomatis ke dashboard `jatenggayeng.id` (menu Caring Order) "
        "menggunakan headless browser, mengunduh tabel Summary per WOK-Agency + caption Total Potensi Order "
        "belum di-caring & 3 WOK terendah.\n"
        "⏰ Jadwal otomatis: 08:00 WIB setiap hari (topic GTM)."
    ),
    "childps": (
        "Format: `/childps [DD-MM-YYYY]` (atau kirim file SQL `.csv`/`.zip` dengan caption `/childps`).\n"
        "Report Child per PS Telkomsel One by WOK."
    ),
    "ms": (
        "Format: `/ms [DD-MM-YYYY]` (kosong = event date terbaru)\n"
        "Market Share FBB per City Jateng-DIY + MoM Growth (2 gambar: TSEL Group, WoW/MoM/YoY, Status).\n"
        "⏰ Jadwal otomatis: 10:00 WIB setiap hari bila ada update event date baru."
    ),
    "msbranch": (
        "Format: `/msbranch [DD-MM-YYYY]` (kosong = event date terbaru)\n"
        "Market Share FBB per Branch Jateng-DIY dari tabel `fixed_ms_branch`."
    ),
    "jadwal": (
        "Format: `/jadwal`\n"
        "Menampilkan daftar jadwal laporan otomatis yang sedang aktif di memori scheduler bot (jam, hari, topic, dan isi report)."
    ),
    "reports_schedule": (
        "Format: `/reports_schedule`\n"
        "Menampilkan jadwal report otomatis yang aktif dalam bentuk gambar tabel (Telegram harian, WhatsApp, dan mingguan)."
    ),
    "jobs": (
        "Format: `/jobs`\n"
        "Menampilkan daftar semua slot jadwal di database SQLite beserta ID, status aktif/nonaktif (`🟢`/`🔴`), "
        "jam tayang, topic tujuan, tanda `+WA`, dan perintah manajemennya."
    ),
    "jobs_add": (
        "Format: `/jobs_add <jam:menit> <topic> <report1,report2> [hari] [wa]`\n"
        "Contoh harian: `/jobs_add 08:30 SALES closingsql,dod`\n"
        "Contoh + WhatsApp: `/jobs_add 16:00 SALES liveupdate:0 wa`\n"
        "Contoh mingguan: `/jobs_add 10:00 GTM homepass,salahtagging SENIN`\n"
        "Menambahkan slot jadwal report baru ke database SQLite dan langsung mendaftarkannya ke scheduler bot tanpa perlu restart."
    ),
    "jobs_del": (
        "Format: `/jobs_del <id>`\n"
        "Contoh: `/jobs_del 9`\n"
        "Menghapus slot jadwal dengan ID terkait dari database SQLite dan langsung memperbarui scheduler bot tanpa restart."
    ),
    "jobs_toggle": (
        "Format: `/jobs_toggle <id>`\n"
        "Contoh: `/jobs_toggle 2`\n"
        "Mengaktifkan atau menonaktifkan (*pause/resume*) slot jadwal dengan ID terkait secara langsung tanpa restart bot."
    ),
    "jobs_edit": (
        "Format: `/jobs_edit <id> <jam:menit> [hari]`\n"
        "Contoh harian: `/jobs_edit 1 07:15`\n"
        "Contoh mingguan: `/jobs_edit 4 10:30 SENIN`\n"
        "Mengubah jam/menit dan hari tayang slot jadwal di SQLite dan langsung memperbarui scheduler bot tanpa restart."
    ),
    "jobs_run": (
        "Format: `/jobs_run <id>`\n"
        "Contoh: `/jobs_run 1`\n"
        "Menjalankan (*trigger* manual) seluruh report pada slot jadwal ID terkait saat ini juga tanpa menunggu jam tayangnya."
    ),
    "jobs_logs": (
        "Format: `/jobs_logs [id]`\n"
        "Contoh: `/jobs_logs` atau `/jobs_logs 1`\n"
        "Menampilkan 10 riwayat eksekusi jadwal terakhir dari database SQLite (waktu mulai, status, jumlah media terkirim, dan pesan error)."
    ),
    "jobs_reload": (
        "Format: `/jobs_reload`\n"
        "Memuat ulang seluruh jadwal aktif dari database SQLite ke scheduler bot serta menyinkronkan ulang daftar command ke Menu Button Telegram."
    ),
    "liveupdate_wa": (
        "Format: `/liveupdate_wa [chat_id]`\n"
        "Menjalankan laporan `/liveupdate` dan mengirimkannya ke grup/nomor WhatsApp melalui layanan WAHA."
    ),
    "closingsql_wa": (
        "Format: `/closingsql_wa DD-MM-YYYY [chat_id]`\n"
        "Menjalankan laporan `/closingsql` untuk tanggal terkait dan mengirimkannya ke WhatsApp melalui WAHA."
    ),
    "agresif_wa": (
        "Format: `/agresif_wa DD-MM-YYYY [chat_id]`\n"
        "Menjalankan laporan `/agresif` untuk tanggal terkait dan mengirimkannya ke WhatsApp melalui WAHA."
    ),
    "closing": (
        "Format: `/closing DD-MM-YYYY`\n"
        "Laporan closing harian dari file KPRO yang diupload manual ke bot (alur lama)."
    ),
    "closinghadoop": (
        "Format: `/closinghadoop DD-MM-YYYY`\n"
        "Laporan closing harian dari file CSV Hadoop (`ordering_detail*.csv`) yang diupload manual."
    ),
    "dailyreps": (
        "Format: `/dailyreps`\n"
        "Mengulang pembuatan laporan daily RE & PS dari file upload terakhir."
    ),
    "closingdaily": (
        "Format: `/closingdaily DD-MM-YYYY`\n"
        "Laporan closing daily RE & PS dari file upload terakhir."
    ),
    "start": (
        "Format: `/start`\n"
        "Menampilkan panduan awal penggunaan Bot Monitoring RE Jateng-DIY."
    ),
    "menu": (
        "Format:\n"
        "• `/menu` — Tampilkan daftar ringkas semua command beserta info singkatnya.\n"
        "• `/menu help <nama_command>` — Tampilkan penjelasan detail, format argumen, sub-report, & jadwal dari command tersebut.\n"
        "• `/menu <kategori>` — Filter daftar command per kategori (`livedb`, `report`, `jadwal`, `wa`, `utilitas`).\n"
        "Contoh: `/menu help closingsql` atau `/menu help 7so`."
    ),
    "status": (
        "Format: `/status`\n"
        "Mengecek status kesehatan bot: apakah target sudah tersimpan (jumlah baris), data upload terakhir, koneksi DB, dan waktu server."
    ),
    "dbstatus": (
        "Format: `/dbstatus`\n"
        "Mengecek status koneksi database MySQL dan ketersediaan tabel-tabel utama pada bulan berjalan."
    ),
    "dbinfo": (
        "Format: `/dbinfo`\n"
        "Mengecek waktu update (snapshot) terakhir dan jumlah baris pada tabel `dashboard_hourly_sales` bulan berjalan."
    ),
    "modequery": (
        "Format: `/modequery [langsung|rajawali|auto]`\n"
        "Melihat atau mengubah mode pengambilan data report:\n"
        "• `langsung` — Query langsung ke MySQL lewat VPN GlobalProtect\n"
        "• `rajawali` — Ambil lewat otomasi SQL Console Rajawali Dashboard\n"
        "• `auto` — Langsung bila MySQL terjangkau, otomatis lewat Rajawali bila VPN putus."
    ),
    "rajawali": (
        "Format: `/rajawali [DD-MM-YYYY] [closingsql,dod,nasional,...]`\n"
        "Memaksa eksekusi report melalui otomasi SQL Console Rajawali Dashboard apa pun setelan `/modequery` saat ini."
    ),
    "target": (
        "Format: `/target` (atau kirim file Excel bernama memuat kata `target` ke chat pribadi bot).\n"
        "Melihat ringkasan target RE/PS per WOK yang saat ini tersimpan di bot (`storage/state/saved_target.pkl`)."
    ),
    "gp": (
        "Format: `/gp`\n"
        "Memeriksa status koneksi VPN GlobalProtect di server Windows dan mencoba menekan tombol Connect secara otomatis bila terputus."
    ),
}


def _clean_description(desc: str, fallback_cmd: str) -> str:
    """Bersihkan deskripsi singkat agar valid untuk BotCommand Telegram (1-256 karakter, satu baris)."""
    text = (desc or "").strip()
    if not text:
        text = f"Jalankan perintah /{fallback_cmd}"
    text = re.sub(r"^/[a-zA-Z0-9_]+(?:\s+\[[^\]]+\]|\s+<[^>]+>)*\s*[\-—:]+\s*", "", text).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    one_line = lines[0] if lines else f"Jalankan perintah /{fallback_cmd}"
    one_line = one_line.replace("*", "").replace("`", "")
    if len(one_line) > 256:
        one_line = one_line[:253] + "..."
    return one_line


def _extract_handler_info(command: str, handler: Callable) -> tuple[str, str, str, str]:
    """
    Kembalikan `(description, help_text, category, handler_name)` dari handler function/method
    serta kamus `DEFAULT_COMMAND_DESCRIPTIONS` & `DEFAULT_COMMAND_HELP`.
    """
    cmd_norm = command.lower().strip().lstrip("/")
    default_desc, default_cat = DEFAULT_COMMAND_DESCRIPTIONS.get(cmd_norm, ("", "REPORT"))
    default_help = DEFAULT_COMMAND_HELP.get(cmd_norm, "").strip()

    # Nama simbol handler untuk pencatatan di database
    self_obj = getattr(handler, "__self__", None)
    if self_obj is not None:
        handler_name = (
            f"{self_obj.__class__.__module__}.{self_obj.__class__.__name__}."
            f"{getattr(handler, '__name__', 'handle')}"
        )
    else:
        mod = getattr(handler, "__module__", "") or ""
        qual = getattr(handler, "__qualname__", getattr(handler, "__name__", str(handler)))
        handler_name = f"{mod}.{qual}" if mod else qual

    # 1. Deskripsi singkat (untuk Menu Button & /menu ringkas)
    if default_desc:
        short_desc = _clean_description(default_desc, cmd_norm)
    elif self_obj is not None and (getattr(self_obj, "description", None) or getattr(self_obj, "title", None)):
        short_desc = _clean_description(
            str(getattr(self_obj, "description", None) or getattr(self_obj, "title", None)),
            cmd_norm,
        )
    else:
        doc = inspect.getdoc(handler) or ""
        short_desc = _clean_description(doc, cmd_norm) if doc else f"Jalankan perintah /{cmd_norm}"

    # 2. Help text detail (untuk kolom `help_text` di SQLite, dipakai oleh `/menu help <cmd>` dan `/<cmd> help`)
    help_parts: list[str] = []
    if default_help:
        help_parts.append(default_help)

    # Jika berasal dari BaseReport dan punya daftar sub-report, sertakan daftar sub-reportnya
    if self_obj is not None and hasattr(self_obj, "_build_help_text"):
        try:
            base_help = str(self_obj._build_help_text()).strip()
            if base_help:
                if not help_parts:
                    help_parts.append(base_help)
                elif "*Daftar Sub-Report:*" in base_help:
                    sub_section = base_help[base_help.index("*Daftar Sub-Report:*") :]
                    help_parts.append(sub_section)
        except Exception:
            pass

    if not help_parts:
        doc = (inspect.getdoc(handler) or "").strip()
        if doc:
            help_parts.append(doc)
        else:
            help_parts.append(f"Format: `/{cmd_norm}`\n{short_desc}")

    full_help = "\n\n".join(help_parts)
    return short_desc, full_help, default_cat, handler_name


class TelegramCommand:
    """
    Class representasi sebuah Command Telegram.
    Setiap command di bot didaftarkan sebagai objek dari class ini.
    """

    def __init__(
        self,
        command: str,
        handler: Callable,
        description: str = "",
        *,
        help_text: str = "",
        category: Optional[str] = None,
        use_timeout: bool = True,
        show_in_menu: bool = True,
        sort_order: Optional[int] = None,
        group: int = 0,
    ):
        self.command: str = command.strip().lstrip("/").lower()
        self.handler: Callable = handler
        self.use_timeout: bool = bool(use_timeout)
        self.show_in_menu: bool = bool(show_in_menu)
        self.group: int = int(group)

        auto_desc, auto_help, auto_cat, handler_name = _extract_handler_info(self.command, handler)
        self.description: str = _clean_description(description, self.command) if description else auto_desc
        self.help_text: str = help_text.strip() if help_text and help_text.strip() else auto_help
        self.category: str = (category or auto_cat or "REPORT").upper()
        self.handler_name: str = handler_name

        if sort_order is not None:
            self.sort_order: int = int(sort_order)
        else:
            cat_base = CATEGORY_ORDER.get(self.category, 40) * 100
            keys_list = list(DEFAULT_COMMAND_DESCRIPTIONS.keys())
            idx = keys_list.index(self.command) if self.command in keys_list else 99
            self.sort_order = cat_base + idx

    def is_valid_bot_command(self) -> bool:
        """Apakah nama command memenuhi syarat BotCommand Telegram API (^[a-z0-9_]{1,32}$)."""
        return bool(_VALID_CMD_RE.match(self.command))

    def to_bot_command(self) -> BotCommand:
        """Konversi menjadi objek `telegram.BotCommand`."""
        return BotCommand(command=self.command, description=self.description)

    def _wrap_with_help_handler(self, fn: Callable) -> Callable:
        """
        Bungkus handler agar setiap command otomatis merespons argumen `help` atau `?`
        (contoh: `/closingsql help`, `/liveupdate ?`, `/jobs help`) dengan mengambil
        penjelasan detail dari kolom `help_text` di tabel SQLite `bot_commands`.
        """
        cmd_name = self.command
        # /menu punya logika argumen `help <cmd>` sendiri; clockin_sf_teritory & homepass_raw
        # menampilkan URL SharePoint aktif secara dinamis di handler-nya.
        if cmd_name in ("menu", "clockin_sf_teritory", "homepass_raw"):
            return fn

        async def _with_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            raw_args = list(getattr(ctx, "args", None) or [])
            if raw_args and str(raw_args[0]).strip().lower() in ("help", "?", "--help", "-h"):
                msg = update.effective_message
                if msg:
                    teks_help = build_command_help_text(cmd_name)
                    await msg.reply_text(teks_help, parse_mode=ParseMode.HTML)
                return
            return await fn(update, ctx)

        return _with_help

    def register(self, app: Application, timeout_wrapper: Optional[Callable] = None) -> Callable:
        """
        Daftarkan objek command ini ke `CommandRegistry` dan pasang `CommandHandler`-nya ke `app`.
        Kembalikan fungsi handler aslinya (untuk kompatibilitas pemanggil).
        """
        CommandRegistry.register_command_object(self)
        wrapped_fn = self._wrap_with_help_handler(self.handler)
        effective_handler = (
            timeout_wrapper(wrapped_fn)
            if (self.use_timeout and timeout_wrapper is not None)
            else wrapped_fn
        )
        cmd_handler = CommandHandler(self.command, effective_handler)
        app.add_handler(cmd_handler, group=self.group)
        return self.handler

    def __repr__(self) -> str:
        return (
            f"TelegramCommand(command={self.command!r}, category={self.category!r}, "
            f"description={self.description!r})"
        )


class CommandRegistry:
    """
    Registry terpusat yang menampung seluruh objek `TelegramCommand` yang aktif,
    menyinkronkannya ke database SQLite, dan mendaftarkannya ke Menu Button Telegram.
    """

    _commands: dict[str, TelegramCommand] = {}
    _app_ref: Optional[Application] = None

    @classmethod
    def clear(cls) -> None:
        cls._commands.clear()

    @classmethod
    def register_command_object(cls, cmd_obj: TelegramCommand) -> TelegramCommand:
        """Simpan objek `TelegramCommand` ke dalam registry memori."""
        cls._commands[cmd_obj.command] = cmd_obj
        return cmd_obj

    @classmethod
    def register(
        cls,
        app: Application,
        command: str,
        handler: Callable,
        description: str = "",
        *,
        help_text: str = "",
        category: Optional[str] = None,
        use_timeout: bool = True,
        show_in_menu: bool = True,
        sort_order: Optional[int] = None,
        timeout_wrapper: Optional[Callable] = None,
        group: int = 0,
    ) -> TelegramCommand:
        """Helper singkat untuk membuat `TelegramCommand` sekaligus mendaftarkannya ke `app`."""
        cmd_obj = TelegramCommand(
            command=command,
            handler=handler,
            description=description,
            help_text=help_text,
            category=category,
            use_timeout=use_timeout,
            show_in_menu=show_in_menu,
            sort_order=sort_order,
            group=group,
        )
        cmd_obj.register(app, timeout_wrapper=timeout_wrapper)
        return cmd_obj

    @classmethod
    def get_all_registered_objects(cls) -> list[TelegramCommand]:
        """Kembalikan seluruh objek `TelegramCommand` yang terdaftar, diurutkan menurut `sort_order`."""
        return sorted(cls._commands.values(), key=lambda c: (c.sort_order, c.command))

    @classmethod
    def install_app_hook(cls, app: Application) -> None:
        """Simpan referensi `app` agar handler yang terdaftar langsung di `app.handlers` ikut dipindai."""
        cls._app_ref = app

    @classmethod
    def collect_from_app(cls, app: Optional[Application] = None) -> None:
        """
        Pindai `app.handlers` untuk memastikan bila ada sub-modul yang memanggil
        `app.add_handler(CommandHandler(...))` secara langsung, command tersebut
        tetap otomatis tercatat sebagai objek `TelegramCommand`.
        """
        target_app = app or cls._app_ref
        if target_app is None or not hasattr(target_app, "handlers"):
            return
        for group, handler_list in target_app.handlers.items():
            for handler in handler_list:
                if isinstance(handler, CommandHandler):
                    for raw_cmd in getattr(handler, "commands", ()):
                        cmd_norm = str(raw_cmd).strip().lstrip("/").lower()
                        if cmd_norm and cmd_norm not in cls._commands:
                            cb = getattr(handler, "callback", None)
                            cmd_obj = TelegramCommand(
                                command=cmd_norm,
                                handler=cb or (lambda *a, **k: None),
                                group=group,
                            )
                            cls.register_command_object(cmd_obj)


# ==============================================================================
#  SQLITE DATABASE STORAGE (`bot_commands` di `storage/state/scheduler.db`)
# ==============================================================================

def init_commands_table() -> None:
    """Pastikan tabel `bot_commands` beserta kolom `help_text` sudah ada di database SQLite."""
    with scheduler_db._get_connection() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                help_text TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'REPORT',
                handler_name TEXT,
                use_timeout INTEGER NOT NULL DEFAULT 1,
                show_in_menu INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 100,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        # Migrasi otomatis jika tabel bot_commands dibuat sebelum kolom `help_text` ditambahkan
        cur = con.cursor()
        cur.execute("PRAGMA table_info(bot_commands)")
        existing_cols = {row["name"] for row in cur.fetchall()}
        if "help_text" not in existing_cols:
            con.execute("ALTER TABLE bot_commands ADD COLUMN help_text TEXT NOT NULL DEFAULT ''")
            logger.info("[CMD-DB] Kolom 'help_text' berhasil ditambahkan ke tabel bot_commands.")

        con.execute("CREATE INDEX IF NOT EXISTS idx_bot_commands_order ON bot_commands(sort_order, command);")


def sync_commands_to_db(commands: Optional[list[TelegramCommand]] = None) -> dict[str, int]:
    """
    Sinkronkan seluruh objek `TelegramCommand` yang terdaftar saat startup ke tabel `bot_commands`.
    - Command baru di kode -> INSERT otomatis ke database (termasuk `help_text`).
    - Command yang berubah deskripsi/help_text/kategori/urutan/handler -> UPDATE otomatis di database.
    - Command yang sudah dihapus dari kode/handler -> DELETE otomatis dari database
      agar tidak lagi muncul di Menu Button Telegram maupun `/menu`.
    """
    init_commands_table()
    CommandRegistry.collect_from_app()
    if commands is None:
        commands = CommandRegistry.get_all_registered_objects()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_map: dict[str, TelegramCommand] = {c.command: c for c in commands if c.is_valid_bot_command()}

    added = 0
    updated = 0
    removed = 0

    with scheduler_db._get_connection() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT command, description, help_text, category, handler_name, use_timeout, show_in_menu, sort_order FROM bot_commands"
        )
        existing_rows = {row["command"]: dict(row) for row in cur.fetchall()}

        # 1. Hapus command dari DB jika handler-nya sudah dihapus dari kode
        for old_cmd in list(existing_rows.keys()):
            if old_cmd not in active_map:
                cur.execute("DELETE FROM bot_commands WHERE command = ?", (old_cmd,))
                removed += 1
                logger.info(f"[CMD-DB] Command '/{old_cmd}' dihapus dari DB karena handler tidak lagi terdaftar.")

        # 2. Insert command baru atau Update command yang berubah
        for cmd_name, cmd_obj in active_map.items():
            use_to_int = 1 if cmd_obj.use_timeout else 0
            show_int = 1 if cmd_obj.show_in_menu else 0

            if cmd_name not in existing_rows:
                cur.execute(
                    """
                    INSERT INTO bot_commands (
                        command, description, help_text, category, handler_name,
                        use_timeout, show_in_menu, sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cmd_obj.command,
                        cmd_obj.description,
                        cmd_obj.help_text,
                        cmd_obj.category,
                        cmd_obj.handler_name,
                        use_to_int,
                        show_int,
                        cmd_obj.sort_order,
                        now_str,
                        now_str,
                    ),
                )
                added += 1
                logger.info(f"[CMD-DB] Command baru '/{cmd_obj.command}' ditambahkan ke DB: {cmd_obj.description}")
            else:
                ex = existing_rows[cmd_name]
                if (
                    ex["description"] != cmd_obj.description
                    or (ex.get("help_text") or "") != cmd_obj.help_text
                    or ex["category"] != cmd_obj.category
                    or ex["handler_name"] != cmd_obj.handler_name
                    or int(ex["use_timeout"]) != use_to_int
                    or int(ex["sort_order"]) != int(cmd_obj.sort_order)
                ):
                    cur.execute(
                        """
                        UPDATE bot_commands
                        SET description = ?, help_text = ?, category = ?, handler_name = ?,
                            use_timeout = ?, sort_order = ?, updated_at = ?
                        WHERE command = ?
                        """,
                        (
                            cmd_obj.description,
                            cmd_obj.help_text,
                            cmd_obj.category,
                            cmd_obj.handler_name,
                            use_to_int,
                            cmd_obj.sort_order,
                            now_str,
                            cmd_obj.command,
                        ),
                    )
                    updated += 1

        con.commit()

    stats = {
        "total": len(active_map),
        "added": added,
        "updated": updated,
        "removed": removed,
    }
    logger.info(
        f"[CMD-DB] Sinkronisasi tabel bot_commands selesai: "
        f"total={stats['total']} (+{added} baru, ~{updated} diperbarui, -{removed} dihapus)"
    )
    return stats


def get_commands_from_db(only_menu: bool = True) -> list[dict[str, Any]]:
    """
    Baca daftar command dari tabel SQLite `bot_commands`.
    Jika `only_menu=True`, hanya kembalikan yang `show_in_menu = 1`.
    """
    init_commands_table()
    query = "SELECT * FROM bot_commands"
    if only_menu:
        query += " WHERE show_in_menu = 1"
    query += " ORDER BY sort_order ASC, command ASC"

    with scheduler_db._get_connection() as con:
        cur = con.cursor()
        cur.execute(query)
        return [dict(r) for r in cur.fetchall()]


def get_command_from_db(command: str) -> Optional[dict[str, Any]]:
    """Ambil 1 baris command dari tabel SQLite `bot_commands` berdasarkan nama command."""
    init_commands_table()
    cmd_norm = (command or "").strip().lstrip("/").split("@")[0].lower()
    if not cmd_norm:
        return None
    with scheduler_db._get_connection() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM bot_commands WHERE command = ?", (cmd_norm,))
        row = cur.fetchone()
        return dict(row) if row else None


def _md_to_html_help(text: str) -> str:
    """Konversi ringan formatting backtick & bold sederhana di help_text ke HTML Telegram yang aman."""
    escaped = html.escape(text or "")
    # `code` -> <code>code</code>
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    # *bold* -> <b>bold</b>
    escaped = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", escaped)
    return escaped


def build_command_help_text(command: str) -> str:
    """
    Susun teks bantuan detail (HTML) untuk sebuah command langsung dari tabel SQLite `bot_commands`.
    Dipanggil saat user mengetik `/menu help <cmd>`, `/menu <cmd>`, atau `/<cmd> help`.
    """
    cmd_norm = (command or "").strip().lstrip("/").split("@")[0].lower()
    row = get_command_from_db(cmd_norm)
    if not row:
        return (
            f"❌ Command <code>/{html.escape(cmd_norm)}</code> tidak ditemukan di database.\n"
            f"Ketik <code>/menu</code> untuk melihat daftar seluruh command yang tersedia."
        )

    cat_label = CATEGORY_LABELS.get(row["category"], row["category"])
    desc = html.escape(row["description"] or "")
    raw_help = (row.get("help_text") or "").strip()
    help_html = _md_to_html_help(raw_help) if raw_help else f"<code>/{html.escape(cmd_norm)}</code> — {desc}"

    return (
        f"📘 <b>Detail Command: /{html.escape(row['command'])}</b>\n"
        f"🏷️ <i>{html.escape(cat_label)}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Ringkasan:</b> {desc}\n\n"
        f"{help_html}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>Ketik</i> <code>/menu</code> <i>untuk kembali ke daftar ringkas.</i>"
    )


def build_concise_menu_text(category_filter: Optional[str] = None) -> str:
    """
    Susun teks `/menu` yang ringkas, rapi, dan diambil langsung dari tabel SQLite `bot_commands`.
    Hanya menampilkan list command dan info singkatnya; untuk detail lengkap diarahkan ke argumen `help`.
    """
    rows = get_commands_from_db(only_menu=True)
    if not rows:
        return "⚠️ Daftar command di database masih kosong."

    alias_kategori = {
        "livedb": "LIVE_DB",
        "live": "LIVE_DB",
        "live_db": "LIVE_DB",
        "report": "REPORT",
        "reports": "REPORT",
        "laporan": "REPORT",
        "scheduler": "SCHEDULER",
        "jadwal": "SCHEDULER",
        "jobs": "SCHEDULER",
        "job": "SCHEDULER",
        "wa": "WHATSAPP",
        "whatsapp": "WHATSAPP",
        "legacy": "LEGACY",
        "kpro": "LEGACY",
        "hadoop": "LEGACY",
        "utility": "UTILITY",
        "utilitas": "UTILITY",
        "utils": "UTILITY",
    }

    target_cat = None
    if category_filter:
        key = category_filter.strip().lower()
        target_cat = alias_kategori.get(key, key.upper())

    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        cat = r.get("category") or "REPORT"
        if target_cat and cat != target_cat:
            continue
        grouped.setdefault(cat, []).append(r)

    if not grouped:
        return (
            f"❓ Kategori atau command <code>{html.escape(category_filter or '')}</code> tidak ditemukan.\n"
            f"Gunakan: <code>/menu help &lt;nama_command&gt;</code> (contoh: <code>/menu help closingsql</code>)"
        )

    lines: list[str] = [
        "📋 <b>MENU BOT MONITORING RE JATENG-DIY</b>",
        "<i>Daftar ringkas command aktif. Untuk penjelasan lengkap, format argumen, &amp; jadwal:</i>",
        "👉 Ketik <code>/&lt;command&gt; help</code> atau <code>/menu help &lt;command&gt;</code>",
        "   <i>(Contoh:</i> <code>/closingsql help</code> <i>atau</i> <code>/menu help 7so</code><i>)</i>",
    ]

    ordered_cats = sorted(grouped.keys(), key=lambda c: CATEGORY_ORDER.get(c, 99))
    for cat in ordered_cats:
        cat_title = CATEGORY_LABELS.get(cat, cat)
        lines.append(f"\n<b>{html.escape(cat_title)}</b>")
        for item in grouped[cat]:
            cmd_str = html.escape(item["command"])
            raw_desc = (item["description"] or "").strip()
            # Jika tampil semua kategori, ringkas deskripsi agar seluruh 75 command muat dalam 1 pesan (<4096 char)
            if not target_cat and len(raw_desc) > 42:
                raw_desc = raw_desc[:40].rstrip() + "…"
            desc_str = html.escape(raw_desc)
            lines.append(f"• /{cmd_str} — {desc_str}")

    lines.append(
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🔎 <b>Cek Detail Command:</b> <code>/menu help &lt;command&gt;</code>\n"
        "📂 <b>Filter Kategori:</b> <code>/menu livedb</code> | <code>/menu report</code> | "
        "<code>/menu jadwal</code> | <code>/menu wa</code> | <code>/menu utilitas</code>"
    )
    return "\n".join(lines)


async def sync_telegram_menu_from_db(bot) -> int:
    """
    Ambil daftar command dari tabel SQLite `bot_commands` dan daftarkan secara
    otomatis & terprogram ke Menu Button Telegram (`set_my_commands` + `set_chat_menu_button`).
    Return jumlah command yang berhasil didaftarkan ke Telegram.
    """
    rows = get_commands_from_db(only_menu=True)
    bot_commands: list[BotCommand] = []
    for r in rows:
        cmd_str = str(r["command"]).strip().lower()
        desc_str = _clean_description(str(r["description"]), cmd_str)
        if _VALID_CMD_RE.match(cmd_str):
            bot_commands.append(BotCommand(command=cmd_str, description=desc_str))

    if len(bot_commands) > 100:
        logger.warning(
            f"[CMD-MENU] Jumlah command ({len(bot_commands)}) melebihi batas 100 Telegram API; "
            f"mengambil 100 command teratas berdasarkan sort_order."
        )
        bot_commands = bot_commands[:100]

    scopes = [
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
    ]
    for scope in scopes:
        await bot.set_my_commands(commands=bot_commands, scope=scope)

    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    logger.info(
        f"[CMD-MENU] Berhasil mendaftarkan {len(bot_commands)} command dari database SQLite "
        f"ke Menu Button Telegram."
    )
    return len(bot_commands)


async def post_init_sync_commands(application: Application) -> None:
    """
    Callback `post_init` yang otomatis dipanggil saat bot dinyalakan atau direstart:
      1. Sinkronkan seluruh objek `TelegramCommand` yang aktif di kode ke tabel SQLite `bot_commands`.
      2. Baca data dari tabel `bot_commands` tersebut dan daftarkan ke Menu Button Telegram.
    """
    try:
        stats = sync_commands_to_db()
        count = await sync_telegram_menu_from_db(application.bot)
        logger.info(
            f"[STARTUP-COMMANDS] Auto-sync command selesai: {count} command aktif di Menu Button Telegram "
            f"(DB: +{stats['added']} / ~{stats['updated']} / -{stats['removed']})."
        )
    except Exception:
        logger.exception("[STARTUP-COMMANDS] Gagal menyinkronkan daftar command ke Menu Button Telegram")
