"""
reports/base.py — Fondasi standar (BaseReport, SubReport, ReportOutput) untuk semua report bot.

Setiap command report yang mewarisi `BaseReport` otomatis mendapatkan:
  1. Parsing argumen fleksibel:
     - Tanggal (`DD-MM-YYYY` atau `DD/MM/YYYY`), wajib (`required`), opsional (`optional`, default H-N
       atau `None`), atau tanpa tanggal (`none`).
     - Pemilihan sub-report (mis. `/caps los`, `/c3mr city`, `/7so belum_re`, `/homepass main`),
       posisi tanggal dan nama sub-report bebas dibolak-balik, dipisah spasi atau koma.
     - Bantuan otomatis (`/<cmd> help` atau `/<cmd> ?`) yang menampilkan daftar sub-report.
  2. Alur eksekusi standar:
     - Pre-check opsional (`pre_check`), validasi tanggal masa depan (`warn_future_date`),
       dan validasi ketersediaan tanggal di DB (`check_date_in_db`).
     - Kirim pesan progres (`⏳ Memproses ...`).
     - Ambil informasi cutoff tabel DB (`cutoff_table` / `get_cutoff_fn`).
     - Jalankan penarikan data/kalkulasi (`fetch_data`) di background thread (`asyncio.to_thread`).
     - Render & kirim tiap sub-report yang diminta secara berurutan.
     - Isolasi error per sub-report: jika sub-report ke-2 gagal, sub-report ke-1 yang sudah
       terkirim tidak ikut batal.
  3. Pengiriman otomatis ke peminta + salinan ke `GROUP_ID` (bila dipanggil dari japri),
     lengkap dengan retry otomatis untuk timeout jaringan dan pemecahan caption >1024 karakter,
     serta kompatibel penuh dengan `_UpdateKeTopic` / `_PesanKeTopic` (scheduler & `report_pagi_csv.py`).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Callable, Iterable, Literal, Optional

from telegram import InputFile, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import CommandHandler, ContextTypes

from config import GROUP_ID

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$")
MAX_CAPTION_LEN = 1024


class ReportOutput:
    """Satu item keluaran report yang siap dikirim ke Telegram / WhatsApp."""
    kind: Literal["photo", "document", "text"]
    content: BytesIO | bytes | str
    filename: Optional[str] = None
    caption: Optional[str] = None
    parse_mode: Optional[str] = "Markdown"
    split_long_caption: bool = True
    wa_send_as_photo: bool = True
    copy_to_group: Optional[bool] = None  # None = ikuti BaseReport.copy_to_group

    def __init__(
        self,
        kind: Literal["photo", "document", "text"],
        content: BytesIO | bytes | str | None = None,
        *,
        buf: BytesIO | bytes | None = None,
        text: Optional[str] = None,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "Markdown",
        split_long_caption: bool = True,
        wa_send_as_photo: bool = True,
        copy_to_group: Optional[bool] = None,
    ):
        self.kind = kind
        if content is not None:
            self.content = content
        elif buf is not None:
            self.content = buf
        else:
            self.content = text or ""
        self.filename = filename
        self.caption = caption
        self.parse_mode = parse_mode
        self.split_long_caption = split_long_caption
        self.wa_send_as_photo = wa_send_as_photo
        self.copy_to_group = copy_to_group

    @property
    def buf(self) -> BytesIO | bytes | str:
        return self.content

    @property
    def text(self) -> str:
        return str(self.content)

    def get_bytes_io(self) -> BytesIO:
        """Kembalikan BytesIO baru yang siap dikirim (aman dipakai berulang untuk salinan grup)."""
        if isinstance(self.content, BytesIO):
            self.content.seek(0)
            return BytesIO(self.content.read())
        if isinstance(self.content, (bytes, bytearray)):
            return BytesIO(bytes(self.content))
        return BytesIO(str(self.content).encode("utf-8"))


class _SubReportList(list):
    """List SubReport yang juga mendukung operasi mirip dict (.keys(), `key in subs`, `subs[key]`)."""

    def keys(self) -> list[str]:
        return [s.key for s in self]

    def values(self) -> list["SubReport"]:
        return list(self)

    def items(self) -> list[tuple[str, "SubReport"]]:
        return [(s.key, s) for s in self]

    def __contains__(self, item) -> bool:
        if isinstance(item, str):
            low = item.lower().strip()
            return any(s.key == low or low in s.aliases for s in self)
        return super().__contains__(item)

    def __getitem__(self, key):
        if isinstance(key, str):
            low = key.lower().strip()
            for s in self:
                if s.key == low or low in s.aliases:
                    return s
            raise KeyError(key)
        return super().__getitem__(key)


@dataclass
class SubReport:
    """Metadata satu sub-report di dalam sebuah class BaseReport."""
    key: str
    title: str
    method_name: str
    aliases: tuple[str, ...] = ()
    default: bool = True
    run_in_thread: bool = False
    error_label: Optional[str] = None
    order: int = 0


_SUB_REPORT_ORDER_COUNTER = 0


def sub_report(
    key: str,
    title: str,
    *,
    aliases: Iterable[str] = (),
    default: bool = True,
    run_in_thread: bool = False,
    error_label: Optional[str] = None,
):
    """
    Dekorator untuk menandai method pada subclass `BaseReport` sebagai sub-report.

    Method yang didekorasi menerima `(self, data: dict, tgl: date | None, cutoff: str | None)`
    dan mengembalikan `ReportOutput`, `list[ReportOutput]`, atau `None`.
    Default `run_in_thread=False` (sinkron di event loop sesuai invariant Matplotlib bot ini);
    set `run_in_thread=True` bila method melakukan I/O atau pembuatan Excel berat.
    """
    global _SUB_REPORT_ORDER_COUNTER
    _SUB_REPORT_ORDER_COUNTER += 1
    order_idx = _SUB_REPORT_ORDER_COUNTER

    def _decorator(fn: Callable):
        fn._sub_report_meta = SubReport(
            key=key.lower().strip(),
            title=title,
            method_name=fn.__name__,
            aliases=tuple(a.lower().strip() for a in aliases),
            default=default,
            run_in_thread=run_in_thread,
            error_label=error_label,
            order=order_idx,
        )
        return fn

    return _decorator


async def _send_with_retry(coro_factory: Callable, label: str = "report", max_tries: int = 2, delay: float = 3.0):
    """Jalankan pengiriman Telegram dengan retry ringan bila terkena TimedOut / NetworkError."""
    attempt = 0
    while True:
        try:
            return await coro_factory()
        except (TimedOut, NetworkError) as e:
            attempt += 1
            if attempt >= max_tries:
                logger.warning(f"[{label}] gagal kirim setelah {max_tries}x percobaan: {e}")
                raise
            logger.warning(f"[{label}] {type(e).__name__} ({attempt}/{max_tries - 1}) — retry dalam {delay}s...")
            await asyncio.sleep(delay)


class BaseReport:
    """
    Class induk untuk seluruh command report Telegram.

    Subclass cukup mendefinisikan atribut metadata (`name`, `title`, dst.),
    mengimplementasikan `fetch_data()`, dan menambahkan minimal 1 method `@sub_report(...)`.
    """

    # ── 1. Identitas Command ──
    name: str = ""
    title: str = ""
    command_name: str = ""
    description: str = ""

    # ── 2. Aturan Tanggal ──
    date_mode: Literal["required", "optional", "none"] = "required"
    default_date_offset: Optional[int] = 1  # H-1 jika int; None = biarkan tgl=None saat kosong
    warn_future_date: bool = True
    check_date_in_db: bool = False
    example_date: str = "08-10-2026"

    # ── 3. Sumber Data, Rajawali & Cutoff ──
    source_type: Literal[
        "mysql_vpn",
        "mysql_indiana",
        "web",
        "fmc_api",
        "local_file",
    ] = "mysql_vpn"
    supports_rajawali: bool = False
    rajawali_query_keys: tuple[str, ...] = ()
    cutoff_table: Optional[str] = None
    cutoff_table_key: Optional[str] = None
    eta_hint: Optional[str] = None

    # ── 4. Perilaku Pengiriman ──
    copy_to_group: bool = True
    forward_to_group: bool = True
    group_id: int = GROUP_ID
    notify_done_in_private: bool = True
    done_private_text: Optional[str] = None
    retry_max_tries: int = 2
    send_wa: bool = False  # True jika laporan terjadwal otomatis diteruskan ke WhatsApp (WAHA)

    # ── 5. Jadwal Otomatis Deklaratif (Self-Registering) ──
    # Jika diisi dict, bot otomatis mendaftarkan jadwal ini ke SQLite jika belum ada di database.
    # Contoh: {"jam": 16, "menit": 30, "topic": "SALES", "offset": 1, "hari": None, "kirim_wa": True}
    schedule: Optional[dict[str, Any]] = None

    _REPORT_CLASSES: list[type] = []

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "command_name" in cls.__dict__ and "name" not in cls.__dict__:
            cls.name = cls.command_name
        elif "name" in cls.__dict__ and "command_name" not in cls.__dict__:
            cls.command_name = cls.name
        if "description" in cls.__dict__ and "title" not in cls.__dict__:
            cls.title = cls.description
        elif "title" in cls.__dict__ and "description" not in cls.__dict__:
            cls.description = cls.title
        if "cutoff_table_key" in cls.__dict__ and "cutoff_table" not in cls.__dict__:
            cls.cutoff_table = cls.cutoff_table_key
        elif "cutoff_table" in cls.__dict__ and "cutoff_table_key" not in cls.__dict__:
            cls.cutoff_table_key = cls.cutoff_table
        if "forward_to_group" in cls.__dict__ and "copy_to_group" not in cls.__dict__:
            cls.copy_to_group = cls.forward_to_group
        elif "copy_to_group" in cls.__dict__ and "forward_to_group" not in cls.__dict__:
            cls.forward_to_group = cls.copy_to_group
        if getattr(cls, "rajawali_query_keys", ()) and "supports_rajawali" not in cls.__dict__:
            cls.supports_rajawali = True

        if cls not in BaseReport._REPORT_CLASSES:
            BaseReport._REPORT_CLASSES.append(cls)

    def __init__(self, get_cutoff_fn: Optional[Callable] = None, **kwargs):
        self.get_cutoff_fn = get_cutoff_fn
        for k, v in kwargs.items():
            setattr(self, k, v)

    @classmethod
    def get_sub_reports(cls) -> _SubReportList:
        """Kumpulkan semua SubReport dari hirarki class sesuai urutan deklarasi."""
        collected: dict[str, SubReport] = {}
        for base in reversed(cls.__mro__):
            for attr_name, attr_val in base.__dict__.items():
                meta: Optional[SubReport] = getattr(attr_val, "_sub_report_meta", None)
                if meta is not None:
                    if meta.key in collected:
                        prev_order = collected[meta.key].order
                        collected[meta.key] = SubReport(
                            key=meta.key,
                            title=meta.title,
                            method_name=attr_name,
                            aliases=meta.aliases,
                            default=meta.default,
                            run_in_thread=meta.run_in_thread,
                            error_label=meta.error_label,
                            order=prev_order,
                        )
                    else:
                        collected[meta.key] = meta
        return _SubReportList(sorted(collected.values(), key=lambda s: s.order))

    def format_help(self) -> str:
        """Alias untuk _build_help_text() (menampilkan daftar sub-report)."""
        return self._build_help_text()

    def usage_text(self) -> str:
        """Teks bantuan singkat format tanggal."""
        cmd = self.name or self.command_name
        return f"❌ Format: `/{cmd} DD-MM-YYYY`\nContoh: `/{cmd} {self.example_date}`"

    async def get_cutoff(self, key: Optional[str] = None) -> Optional[str]:
        """Alias pembantu untuk mengambil string cutoff tabel DB."""
        if not self.get_cutoff_fn:
            return None
        target_key = key or self.cutoff_table or self.cutoff_table_key
        sig = inspect.signature(self.get_cutoff_fn)
        res = self.get_cutoff_fn(target_key) if len(sig.parameters) >= 1 else self.get_cutoff_fn()
        if inspect.isawaitable(res):
            return await res
        return res

    @classmethod
    def build_rajawali_sql(cls, tgl: date, **kwargs) -> Optional[str]:
        """
        Bangun query SQL untuk SQL Console Rajawali Dashboard (mode_query='rajawali').
        Di-override pada subclass report yang membutuhkan query Rajawali spesifik.
        """
        return None

    @classmethod
    def save_rajawali_sql(
        cls,
        tgl: date,
        filename: Optional[str] = None,
        copy_to_clipboard: bool = False,
        **kwargs,
    ) -> str:
        """
        Simpan hasil `build_rajawali_sql(tgl, **kwargs)` ke folder `storage/sql_packets/`
        dan kembalikan string SQL-nya.
        """
        import os
        import subprocess

        sql = cls.build_rajawali_sql(tgl, **kwargs)
        if not sql:
            raise NotImplementedError(f"{cls.__name__} belum mengimplementasikan build_rajawali_sql()")
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        paket_dir = os.path.join(base_dir, "storage", "sql_packets")
        os.makedirs(paket_dir, exist_ok=True)
        fname = filename or f"{cls.name or cls.command_name}_{tgl:%Y%m%d}.sql"
        path = os.path.join(paket_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(sql)
        if copy_to_clipboard:
            try:
                subprocess.run("clip", input=sql.encode("utf-16"), check=True)
            except Exception:
                pass
        return sql

    def should_use_rajawali(self, db_reachable: Optional[bool] = None) -> bool:
        """Cek apakah report ini harus dijalankan lewat Rajawali Dashboard sesuai mode_query aktif."""
        if not self.supports_rajawali:
            return False
        import mode_query
        if db_reachable is None:
            return mode_query.ambil() == "rajawali"
        return mode_query.pakai_rajawali(db_reachable)

    def build_outputs(
        self,
        data: dict,
        tgl: Optional[date],
        selected_subs: Optional[list] = None,
        cutoff: Optional[str] = None,
    ) -> list[ReportOutput]:
        """Bangun list ReportOutput dari sub-report yang dipilih."""
        all_subs = self.get_sub_reports()
        if not selected_subs:
            active = [s for s in all_subs if s.default] or list(all_subs)
        else:
            active = [
                all_subs[s] if isinstance(s, str) else s
                for s in selected_subs
            ]
        outputs: list[ReportOutput] = []
        for sub in active:
            method = getattr(self, sub.method_name)
            sig = inspect.signature(method)
            if len(sig.parameters) >= 3:
                raw = method(data, tgl, cutoff)
            else:
                raw = method(data, tgl)
            if raw is None:
                continue
            if isinstance(raw, ReportOutput):
                outputs.append(raw)
            else:
                outputs.extend(raw)
        return outputs

    async def send_outputs(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        outputs: list[ReportOutput],
    ) -> bool:
        """Kirim seluruh ReportOutput secara berurutan."""
        any_copied = False
        for out in outputs:
            if await self._deliver_output(update, ctx, out):
                any_copied = True
        return any_copied

    @classmethod
    def get_schedule_descriptions(cls) -> list[str]:
        """Daftar judul sub-report default (untuk /jadwal & /reports_schedule)."""
        return [s.title for s in cls.get_sub_reports() if s.default]

    def _build_help_text(self) -> str:
        subs = self.get_sub_reports()
        if self.date_mode == "required":
            fmt_tgl = "DD-MM-YYYY"
        elif self.date_mode == "optional":
            ket = f"H-{self.default_date_offset}" if self.default_date_offset is not None else "terbaru"
            fmt_tgl = f"[DD-MM-YYYY] (kosong = {ket})"
        else:
            fmt_tgl = ""

        lines = [
            f"📘 *Panduan /{self.name}* — {self.title}",
            f"Format: `/{self.name} {fmt_tgl} [sub_report]`".strip(),
            "",
            "*Daftar Sub-Report:*",
        ]
        for s in subs:
            alias_info = f" (alias: `{', '.join(s.aliases)}`)" if s.aliases else ""
            def_info = "" if s.default else " _(opsional)_"
            lines.append(f"• `{s.key}`{alias_info} — {s.title}{def_info}")
        if len(subs) > 1:
            contoh_sub = subs[0].key
            lines.extend([
                "",
                "*Contoh pemakaian:*",
                f"• `/{self.name}{' 08-10-2026' if self.date_mode == 'required' else ''}` — kirim semua sub-report utama",
                f"• `/{self.name}{' 08-10-2026' if self.date_mode != 'none' else ''} {contoh_sub}` — hanya kirim `{contoh_sub}`",
            ])
        return "\n".join(lines)

    def parse_args(self, raw_args: list[str]):
        """
        Uraikan argumen command menjadi:
          (tgl, selected_sub_reports, extra_args, error_msg, is_help)
        """
        args = list(raw_args or [])
        if any(a.lower().strip() in ("help", "?", "--help", "-h") for a in args):
            return None, [], [], None, True

        subs = self.get_sub_reports()
        alias_map: dict[str, SubReport] = {}
        for s in subs:
            alias_map[s.key] = s
            for al in s.aliases:
                alias_map[al] = s

        tgl: Optional[date] = None
        requested_keys: list[str] = []
        extra_args: list[str] = []

        for token in args:
            if self.date_mode != "none" and _DATE_RE.match(token):
                norm = re.sub(r"[/.]", "-", token)
                try:
                    tgl = datetime.strptime(norm, "%d-%m-%Y").date()
                except ValueError:
                    return None, [], [], (
                        f"❌ Format tanggal salah. Gunakan: `DD-MM-YYYY`\n"
                        f"Contoh: `/{self.name} 08-10-2026`"
                    ), False
                continue

            parts = [p.strip().lower() for p in token.split(",") if p.strip()]
            all_known = bool(parts) and all(p in alias_map for p in parts)
            if all_known:
                for p in parts:
                    canonical = alias_map[p].key
                    if canonical not in requested_keys:
                        requested_keys.append(canonical)
            else:
                if (
                    self.date_mode in ("required", "optional")
                    and tgl is None
                    and not self.accepts_extra_args()
                    and any(c.isdigit() for c in token)
                ):
                    return None, [], [], (
                        f"❌ Format tanggal salah. Gunakan: `DD-MM-YYYY`\n"
                        f"Contoh: `/{self.name} 08-10-2026`"
                    ), False
                extra_args.append(token)

        if self.date_mode == "required" and tgl is None:
            return None, [], [], (
                f"❌ Format: `/{self.name} DD-MM-YYYY`\n"
                f"Contoh: `/{self.name} 08-10-2026`"
            ), False
        if self.date_mode == "optional" and tgl is None and self.default_date_offset is not None:
            tgl = date.today() - timedelta(days=self.default_date_offset)

        if extra_args and not self.accepts_extra_args():
            valid_list = ", ".join(f"`{s.key}`" for s in subs)
            return None, [], [], (
                f"❌ Argumen atau sub-report tidak dikenal: `{', '.join(extra_args)}`\n"
                f"Sub-report yang tersedia: {valid_list}\n"
                f"Ketik `/{self.name} help` untuk panduan."
            ), False

        if requested_keys:
            key_to_sub = {s.key: s for s in subs}
            selected = [key_to_sub[k] for k in requested_keys]
        else:
            selected = [s for s in subs if s.default]

        return tgl, selected, extra_args, None, False

    def accepts_extra_args(self) -> bool:
        """Override jadi True bila subclass menerima argumen kustom selain tanggal & sub-report."""
        return False

    async def pre_check(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, tgl: Optional[date]) -> bool:
        """
        Hook validasi awal sebelum pesan '⏳ Memproses...' dikirim.
        Return True untuk lanjut, False jika sudah membalas pesan error dan ingin berhenti.
        """
        return True

    def format_progress_message(self, tgl: Optional[date], selected_subs: list[SubReport], extra_args: list[str]) -> str:
        """Pesan progres saat report mulai diproses."""
        tgl_str = f" {tgl.strftime('%d-%m-%Y')}" if tgl else ""
        eta_str = f" ({self.eta_hint})" if self.eta_hint else ""
        return f"⏳ Memproses {self.title}{tgl_str}...{eta_str}"

    async def resolve_cutoff(self, tgl: Optional[date], data: Optional[dict] = None) -> Optional[str]:
        """Ambil string cutoff dari `get_cutoff_fn` bila tersedia."""
        if not self.get_cutoff_fn:
            return None
        try:
            sig = inspect.signature(self.get_cutoff_fn)
            if len(sig.parameters) >= 1 and self.cutoff_table:
                res = self.get_cutoff_fn(self.cutoff_table)
            else:
                res = self.get_cutoff_fn()
            if inspect.isawaitable(res):
                return await res
            return res
        except Exception as e:
            logger.warning(f"[{self.name}] gagal ambil cutoff: {e}")
            return None

    def fetch_data(self, tgl: Optional[date], selected_subs: set[str], extra_args: list[str]) -> dict:
        """
        Tarik data & jalankan kalkulasi utama (dijalankan di worker thread via asyncio.to_thread).
        Wajib diimplementasikan oleh subclass (boleh sync atau async).
        """
        raise NotImplementedError

    async def _deliver_output(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        out: ReportOutput,
    ) -> bool:
        """
        Kirim 1 ReportOutput ke chat peminta (+ salin ke GROUP_ID bila dipanggil dari japri).
        Return True bila dikirim ke GROUP_ID dari japri.
        """
        copied_to_group = False
        should_copy = self.copy_to_group if out.copy_to_group is None else out.copy_to_group
        is_private_or_other = should_copy and (update.effective_chat.id != GROUP_ID)

        if out.kind == "text":
            text = str(out.content)
            await update.message.reply_text(text, parse_mode=out.parse_mode)
            if is_private_or_other:
                await ctx.bot.send_message(
                    chat_id=GROUP_ID, text=text, parse_mode=out.parse_mode
                )
                copied_to_group = True
            return copied_to_group

        caption = out.caption or ""
        overflow_text = None
        if out.split_long_caption and caption and len(caption) > MAX_CAPTION_LEN:
            overflow_text = caption
            caption = None

        fname = out.filename or ("report.png" if out.kind == "photo" else "report.bin")
        pm = out.parse_mode if caption else None

        if out.kind == "photo":
            await _send_with_retry(
                lambda: update.message.reply_photo(
                    photo=InputFile(out.get_bytes_io(), filename=fname),
                    caption=caption,
                    parse_mode=pm,
                    write_timeout=180,
                    read_timeout=120,
                ),
                label=f"{self.name}_photo",
                max_tries=self.retry_max_tries,
            )
            if is_private_or_other:
                await _send_with_retry(
                    lambda: ctx.bot.send_photo(
                        chat_id=GROUP_ID,
                        photo=InputFile(out.get_bytes_io(), filename=fname),
                        caption=caption,
                        parse_mode=pm,
                        write_timeout=180,
                        read_timeout=120,
                    ),
                    label=f"{self.name}_photo_grup",
                    max_tries=self.retry_max_tries,
                )
                copied_to_group = True
        elif out.kind == "document":
            await _send_with_retry(
                lambda: update.message.reply_document(
                    document=InputFile(out.get_bytes_io(), filename=fname),
                    caption=caption,
                    parse_mode=pm,
                    write_timeout=180,
                    read_timeout=120,
                ),
                label=f"{self.name}_doc",
                max_tries=self.retry_max_tries,
            )
            if is_private_or_other:
                await _send_with_retry(
                    lambda: ctx.bot.send_document(
                        chat_id=GROUP_ID,
                        document=InputFile(out.get_bytes_io(), filename=fname),
                        caption=caption,
                        parse_mode=pm,
                        write_timeout=180,
                        read_timeout=120,
                    ),
                    label=f"{self.name}_doc_grup",
                    max_tries=self.retry_max_tries,
                )
                copied_to_group = True

        if overflow_text:
            await update.message.reply_text(overflow_text, parse_mode=out.parse_mode)
            if is_private_or_other:
                await ctx.bot.send_message(
                    chat_id=GROUP_ID, text=overflow_text, parse_mode=out.parse_mode
                )

        return copied_to_group

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Handler utama Telegram untuk command ini."""
        parsed = self.parse_args(ctx.args)
        if len(parsed) == 5:
            tgl, selected_subs, extra_args, err_msg, is_help = parsed
        else:
            tgl, raw_subs, err_msg = parsed
            extra_args = []
            is_help = False
            all_subs = self.get_sub_reports()
            if raw_subs:
                selected_subs = [all_subs[s] if isinstance(s, str) else s for s in raw_subs]
            else:
                selected_subs = [s for s in all_subs if s.default] or list(all_subs)

        if is_help:
            await update.message.reply_text(self._build_help_text(), parse_mode="Markdown")
            return

        if err_msg:
            await update.message.reply_text(err_msg, parse_mode="Markdown")
            return

        if not await self.pre_check(update, ctx, tgl):
            return

        if self.check_date_in_db and tgl is not None:
            import db
            try:
                tanggal_tersedia = await asyncio.to_thread(db.query_tanggal_tersedia, tgl)
            except Exception as e:
                await update.message.reply_text(f"❌ Gagal cek database:\n`{e}`", parse_mode="Markdown")
                return
            if tgl not in tanggal_tersedia:
                tgl_str = ", ".join(t.strftime("%d-%m-%Y") for t in sorted(tanggal_tersedia)[-5:])
                await update.message.reply_text(
                    f"❌ Data tanggal {tgl.strftime('%d-%m-%Y')} belum tersedia di database.\n"
                    f"Tanggal tersedia (5 terakhir): {tgl_str}"
                )
                return

        if self.warn_future_date and tgl and tgl > date.today():
            await update.message.reply_text(
                f"⚠️ Tanggal *{tgl.strftime('%d-%m-%Y')}* belum terjadi "
                f"(hari ini {date.today().strftime('%d-%m-%Y')}).\nData mungkin belum lengkap atau tidak tersedia.",
                parse_mode="Markdown",
            )

        selected_keys = {s.key for s in selected_subs}
        if hasattr(self, "format_progress"):
            prog = self.format_progress(tgl, list(selected_keys))
        else:
            prog = self.format_progress_message(tgl, selected_subs, extra_args)
        if prog:
            await update.message.reply_text(prog)

        try:
            cutoff_str = await self.resolve_cutoff(tgl)
            sig_fetch = inspect.signature(self.fetch_data)
            params_fetch = list(sig_fetch.parameters.keys())
            if "update" in params_fetch and "ctx" in params_fetch:
                if inspect.iscoroutinefunction(self.fetch_data):
                    data = await self.fetch_data(tgl, update, ctx, selected_subs=list(selected_keys))
                else:
                    data = await asyncio.to_thread(
                        self.fetch_data, tgl, update, ctx, list(selected_keys)
                    )
            else:
                if inspect.iscoroutinefunction(self.fetch_data):
                    data = await self.fetch_data(tgl, selected_keys, extra_args)
                else:
                    data = await asyncio.to_thread(self.fetch_data, tgl, selected_keys, extra_args)
            if isinstance(data, dict) and data.get("_abort_message"):
                await update.message.reply_text(
                    data["_abort_message"],
                    parse_mode=data.get("_abort_parse_mode", "Markdown"),
                )
                return
        except Exception as e:
            logger.exception(f"Error cmd_{self.name}")
            await update.message.reply_text(
                f"❌ Error saat generate laporan {self.title}:\n`{e}`",
                parse_mode="Markdown",
            )
            return

        # Jika subclass meng-override send_outputs sendiri, gunakan build_outputs + send_outputs
        if type(self).send_outputs is not BaseReport.send_outputs:
            outputs = self.build_outputs(data, tgl, selected_subs=selected_subs, cutoff=cutoff_str)
            await self.send_outputs(update, ctx, outputs)
            return

        any_copied_to_group = False
        for idx, sub in enumerate(selected_subs):
            method = getattr(self, sub.method_name)
            sig_m = inspect.signature(method)
            n_params = len(sig_m.parameters)
            try:
                if inspect.iscoroutinefunction(method):
                    raw_out = await (method(data, tgl, cutoff_str) if n_params >= 3 else method(data, tgl))
                elif sub.run_in_thread:
                    raw_out = await (
                        asyncio.to_thread(method, data, tgl, cutoff_str)
                        if n_params >= 3
                        else asyncio.to_thread(method, data, tgl)
                    )
                else:
                    raw_out = method(data, tgl, cutoff_str) if n_params >= 3 else method(data, tgl)

                if raw_out is None:
                    continue
                outputs = [raw_out] if isinstance(raw_out, ReportOutput) else list(raw_out)

                for out in outputs:
                    copied = await self._deliver_output(update, ctx, out)
                    if copied:
                        any_copied_to_group = True
            except Exception as e:
                err_lbl = sub.error_label or sub.title
                logger.exception(f"Error sub-report {self.name}.{sub.key}")
                if idx == 0 and len(selected_subs) == 1:
                    await update.message.reply_text(
                        f"❌ Error saat generate laporan {self.title}:\n`{e}`",
                        parse_mode="Markdown",
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Error {err_lbl}:\n`{str(e)[:600]}`",
                        parse_mode="Markdown",
                    )

        if any_copied_to_group and self.notify_done_in_private:
            done_txt = self.done_private_text or f"✅ Laporan {self.title} sudah dikirim ke grup."
            await update.message.reply_text(done_txt)

    def register(self, app, timeout_wrapper: Optional[Callable] = None):
        """Daftarkan CommandHandler ke `app` Telegram dan kembalikan fungsi handler-nya."""
        _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
        app.add_handler(CommandHandler(self.name, _T(self.handle)))
        return self.handle
