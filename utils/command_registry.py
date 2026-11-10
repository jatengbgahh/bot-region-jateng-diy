"""
utils/command_registry.py — Class Command OOP, Auto-Sync SQLite, dan Auto-Update Menu Button Telegram.

Arsitektur:
  1. `TelegramCommand`: Class representasi command Telegram. Setiap command didaftarkan
     sebagai objek dari class ini (memiliki atribut `command`, `handler`, `description`,
     `category`, `use_timeout`, `show_in_menu`, `sort_order`).
  2. `CommandRegistry`: Menyimpan seluruh objek `TelegramCommand` yang aktif di kode saat ini,
     sekaligus mem-wrapping `app.add_handler` agar `CommandHandler` dari sub-modul mana pun
     otomatis terkonversi/tercatat sebagai objek `TelegramCommand`.
  3. Sinkronisasi Database SQLite (`bot_commands` di `storage/state/scheduler.db`):
     - Saat bot dinyalakan/direstart, daftar `TelegramCommand` yang terdaftar di kode
       otomatis disinkronkan ke tabel `bot_commands`.
     - Jika ada penambahan command di kode -> otomatis di-INSERT ke tabel `bot_commands`.
     - Jika ada pengurangan/penghapusan command di kode -> otomatis dihapus dari tabel `bot_commands`.
  4. Auto-Update Telegram Command Menu Button (`set_my_commands` & `set_chat_menu_button`):
     - Mengambil daftar command langsung dari tabel SQLite `bot_commands`.
     - Mendaftarkan daftar tersebut secara otomatis dan terprogram ke Menu Button Telegram
       setiap kali bot dinyalakan atau direstart (`post_init`).
"""

from __future__ import annotations

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
)
from telegram.ext import Application, BaseHandler, CommandHandler

from utils import scheduler_db

logger = logging.getLogger(__name__)

# Validasi format command Telegram: 1-32 karakter, huruf kecil, angka, dan underscore
_VALID_CMD_RE = re.compile(r"^[a-z0-9_]{1,32}$")

# Urutan prioritas kategori di Menu Button Telegram
CATEGORY_ORDER: dict[str, int] = {
    "UTILITY": 10,
    "SCHEDULER": 20,
    "LIVE_DB": 30,
    "REPORT": 40,
    "WHATSAPP": 50,
    "LEGACY": 60,
}

# Kamus deskripsi default untuk seluruh command agar tampilan di Menu Button Telegram rapi & informatif
DEFAULT_COMMAND_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    # (Deskripsi Menu Telegram, Kategori)
    # 1. UTILITAS & MENU
    "start": ("Panduan lengkap penggunaan bot", "UTILITY"),
    "menu": ("Tampilkan daftar lengkap menu & fitur bot", "UTILITY"),
    "status": ("Cek status bot, target tersimpan, & koneksi DB", "UTILITY"),
    "dbstatus": ("Cek status koneksi & tabel database bulan berjalan", "UTILITY"),
    "dbinfo": ("Cek waktu update terakhir data di database", "UTILITY"),
    "modequery": ("Lihat atau ubah mode query (langsung / rajawali / auto)", "UTILITY"),
    "rajawali": ("Jalankan report paksa lewat otomasi Rajawali Dashboard", "UTILITY"),
    "target": ("Lihat ringkasan target RE/PS per WOK yang tersimpan", "UTILITY"),
    "gp": ("Cek status & sambungkan VPN GlobalProtect di server", "UTILITY"),
    # 2. MANAJEMEN JADWAL & COMMAND (SQLITE)
    "jadwal": ("Tampilkan daftar jadwal laporan otomatis yang aktif", "SCHEDULER"),
    "reports_schedule": ("Tabel gambar jadwal report otomatis (Telegram & WA)", "SCHEDULER"),
    "jobs": ("Manajemen jadwal report dinamis (SQLite)", "SCHEDULER"),
    "jobs_toggle": ("Aktifkan / nonaktifkan slot jadwal report (on/off)", "SCHEDULER"),
    "jobs_edit": ("Ubah jam/hari jadwal report tanpa restart bot", "SCHEDULER"),
    "jobs_run": ("Jalankan manual slot jadwal report sekarang juga", "SCHEDULER"),
    "jobs_logs": ("Lihat riwayat eksekusi jadwal report terakhir", "SCHEDULER"),
    "jobs_reload": ("Muat ulang jadwal & sinkronkan menu command dari DB", "SCHEDULER"),
    # 3. LIVE DB & CLOSING HARIAN
    "liveupdate": ("Monitoring RE & RE-PS hari ini secara live dari DB", "LIVE_DB"),
    "closingsql": ("Laporan closing harian IO-RE-PS, WOK, City & Channel", "LIVE_DB"),
    "dailyre": ("Monitoring Daily RE terhadap target weekday/weekend", "LIVE_DB"),
    "nasional": ("Daily Tracking IndiHome tingkat Nasional (12 Region)", "LIVE_DB"),
    "dod": ("PS Harian & %DoD PS per Branch dan WOK", "LIVE_DB"),
    "liveupdateutoip": ("Backup /liveupdate dari sumber FMC API", "LIVE_DB"),
    "liveupdatebk": ("Backup /liveupdate dari raw ordering_detail", "LIVE_DB"),
    "closingutoip": ("Backup /closingsql dari sumber FMC API", "LIVE_DB"),
    "closingbk": ("Backup /closingsql dari raw ordering_detail", "LIVE_DB"),
    # 4. REPORT PENJUALAN, SF, C3MR, CAPS, PRANPC, HOMEPASS
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
    # 5. WHATSAPP MANUAL TRIGGER
    "liveupdate_wa": ("Kirim laporan /liveupdate ke WhatsApp via WAHA", "WHATSAPP"),
    "closingsql_wa": ("Kirim laporan /closingsql ke WhatsApp via WAHA", "WHATSAPP"),
    "agresif_wa": ("Kirim laporan /agresif ke WhatsApp via WAHA", "WHATSAPP"),
    # 6. ALUR LAMA (KPRO / HADOOP UPLOAD)
    "closing": ("Laporan closing dari file upload KPRO [DD-MM-YYYY]", "LEGACY"),
    "closinghadoop": ("Laporan closing dari file upload Hadoop CSV", "LEGACY"),
    "dailyreps": ("Ulang laporan daily RE & PS dari upload terakhir", "LEGACY"),
    "closingdaily": ("Laporan closing daily RE & PS dari upload terakhir", "LEGACY"),
}


def _clean_description(desc: str, fallback_cmd: str) -> str:
    """Bersihkan deskripsi agar valid untuk BotCommand Telegram (1-256 karakter, satu baris)."""
    text = (desc or "").strip()
    if not text:
        text = f"Jalankan perintah /{fallback_cmd}"
    # Buang prefix seperti "/cmd — " atau "/cmd - " bila ada di docstring
    text = re.sub(r"^/[a-zA-Z0-9_]+(?:\s+\[[^\]]+\]|\s+<[^>]+>)*\s*[\-—:]+\s*", "", text).strip()
    # Ambil baris pertama yang tidak kosong
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    one_line = lines[0] if lines else f"Jalankan perintah /{fallback_cmd}"
    # Hilangkan karakter markdown berlebih
    one_line = one_line.replace("*", "").replace("`", "")
    if len(one_line) > 256:
        one_line = one_line[:253] + "..."
    return one_line


def _extract_handler_info(command: str, handler: Callable) -> tuple[str, str, str]:
    """
    Kembalikan (description, category, handler_name) dari handler function/method
    atau dari kamus DEFAULT_COMMAND_DESCRIPTIONS.
    """
    cmd_norm = command.lower().strip().lstrip("/")
    default_desc, default_cat = DEFAULT_COMMAND_DESCRIPTIONS.get(cmd_norm, ("", "REPORT"))

    # Nama simbol handler untuk pencatatan di database
    self_obj = getattr(handler, "__self__", None)
    if self_obj is not None:
        handler_name = f"{self_obj.__class__.__module__}.{self_obj.__class__.__name__}.{getattr(handler, '__name__', 'handle')}"
    else:
        mod = getattr(handler, "__module__", "") or ""
        qual = getattr(handler, "__qualname__", getattr(handler, "__name__", str(handler)))
        handler_name = f"{mod}.{qual}" if mod else qual

    # Jika ada di kamus default, prioritaskan deskripsi kamus yang sudah diringkas untuk Menu Button
    if default_desc:
        return _clean_description(default_desc, cmd_norm), default_cat, handler_name

    # Jika handler berasal dari instance BaseReport, ambil description atau title-nya
    if self_obj is not None:
        rep_desc = getattr(self_obj, "description", None) or getattr(self_obj, "title", None)
        if rep_desc:
            return _clean_description(str(rep_desc), cmd_norm), default_cat, handler_name

    # Fallback ke docstring fungsi handler
    doc = inspect.getdoc(handler) or ""
    if doc:
        return _clean_description(doc, cmd_norm), default_cat, handler_name

    return f"Jalankan perintah /{cmd_norm}", default_cat, handler_name


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

        auto_desc, auto_cat, handler_name = _extract_handler_info(self.command, handler)
        self.description: str = _clean_description(description, self.command) if description else auto_desc
        self.category: str = (category or auto_cat or "REPORT").upper()
        self.handler_name: str = handler_name

        if sort_order is not None:
            self.sort_order: int = int(sort_order)
        else:
            # Urutan default berdasarkan kategori + posisi di DEFAULT_COMMAND_DESCRIPTIONS
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

    def register(self, app: Application, timeout_wrapper: Optional[Callable] = None) -> Callable:
        """
        Daftarkan objek command ini ke `CommandRegistry` dan pasang `CommandHandler`-nya ke `app`.
        Kembalikan fungsi handler aslinya (untuk kompatibilitas pemanggil).
        """
        CommandRegistry.register_command_object(self)
        effective_handler = (
            timeout_wrapper(self.handler)
            if (self.use_timeout and timeout_wrapper is not None)
            else self.handler
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
    _hook_installed: bool = False

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
        target_app = app or getattr(cls, "_app_ref", None)
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
    """Pastikan tabel `bot_commands` sudah ada di database SQLite."""
    with scheduler_db._get_connection() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
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
        con.execute("CREATE INDEX IF NOT EXISTS idx_bot_commands_order ON bot_commands(sort_order, command);")


def sync_commands_to_db(commands: Optional[list[TelegramCommand]] = None) -> dict[str, int]:
    """
    Sinkronkan seluruh objek `TelegramCommand` yang terdaftar saat startup ke tabel `bot_commands`.
    - Command baru di kode -> INSERT otomatis ke database.
    - Command yang berubah deskripsi/kategori/urutan/handler -> UPDATE otomatis di database.
    - Command yang sudah dihapus dari kode/handler -> DELETE otomatis dari database
      agar tidak lagi muncul di Menu Button Telegram.
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
            "SELECT command, description, category, handler_name, use_timeout, show_in_menu, sort_order FROM bot_commands"
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
                        command, description, category, handler_name,
                        use_timeout, show_in_menu, sort_order, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cmd_obj.command,
                        cmd_obj.description,
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
                    or ex["category"] != cmd_obj.category
                    or ex["handler_name"] != cmd_obj.handler_name
                    or int(ex["use_timeout"]) != use_to_int
                    or int(ex["sort_order"]) != int(cmd_obj.sort_order)
                ):
                    cur.execute(
                        """
                        UPDATE bot_commands
                        SET description = ?, category = ?, handler_name = ?,
                            use_timeout = ?, sort_order = ?, updated_at = ?
                        WHERE command = ?
                        """,
                        (
                            cmd_obj.description,
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

    # Batas maksimal Bot API Telegram untuk setMyCommands adalah 100 command per scope
    if len(bot_commands) > 100:
        logger.warning(
            f"[CMD-MENU] Jumlah command ({len(bot_commands)}) melebihi batas 100 Telegram API; "
            f"mengambil 100 command teratas berdasarkan sort_order."
        )
        bot_commands = bot_commands[:100]

    # Pasang ke semua scope (Default, Private Chats, dan Group Chats) agar tombol Menu selalu terupdate
    scopes = [
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
    ]
    for scope in scopes:
        await bot.set_my_commands(commands=bot_commands, scope=scope)

    # Pastikan tombol Menu di chat menampilkan daftar command
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
