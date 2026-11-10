"""
commands/market_share.py — Handler Telegram /ms dan /msbranch berbasis BaseReport + kirim otomatis jam 10:00.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import GROUP_ID, REPORT_GROUP_ID, TOPIC_IDS
from reports.base import BaseReport, ReportOutput, sub_report
from reports.market_share import (
    hitung_market_share,
    hitung_market_share_branch,
    render_market_share,
    render_market_share_branch,
    render_market_share_mom,
    state,
    top_wow,
)

logger = logging.getLogger(__name__)

_WIB_TZ = timezone(timedelta(hours=7))
JAM_OTOMATIS, MENIT_OTOMATIS = 10, 0
TOPIC_KEY = "MARKET_SHARE"


def _caption(data, judul, top3=False):
    cap = f"📊 {judul}\nEvent date {data['event_date'].strftime('%d-%m-%Y')}"
    if top3:
        tinggi, rendah = top_wow(data)

        def baris(daftar):
            return "\n".join(f"{i}. {c} ({w:+.2f}%)" for i, (c, w) in enumerate(daftar, 1))

        cap += (
            f"\n\n🔼 Top 3 WoW tertinggi (TSEL Group):\n{baris(tinggi)}"
            f"\n\n🔽 Top 3 WoW terendah (TSEL Group):\n{baris(rendah)}"
        )
    return cap


def _gambar_laporan(data):
    """List (judul, nama_file, BytesIO) untuk 2 report."""
    tgl = data["event_date"].strftime("%Y%m%d")
    return [
        (
            "Market Share Per City Region Jateng-DIY",
            f"market_share_{tgl}.png",
            render_market_share(data),
        ),
        (
            "Market Share MOM Growth Per City Region Jateng-DIY",
            f"market_share_mom_{tgl}.png",
            render_market_share_mom(data),
        ),
    ]


def _gambar_laporan_auto(data, data_branch=None, selected_subs=None):
    """
    Urutan kirim otomatis: Market Share per Branch, per City, MOM Growth per City.
    List (judul, nama_file, BytesIO, data_untuk_caption, top3).
    """
    active = set(selected_subs or ("branch", "city", "mom"))
    tgl = data["event_date"].strftime("%Y%m%d")
    laporan = []
    if "branch" in active and data_branch is not None:
        laporan.append(
            (
                "Market Share Per Branch Region Jateng-DIY",
                f"market_share_branch_{tgl}.png",
                render_market_share_branch(data_branch),
                data_branch,
                False,
            )
        )
    if "city" in active:
        laporan.append(
            (
                "Market Share Per City Region Jateng-DIY",
                f"market_share_{tgl}.png",
                render_market_share(data),
                data,
                True,
            )
        )
    if "mom" in active:
        laporan.append(
            (
                "Market Share MOM Growth Per City Region Jateng-DIY",
                f"market_share_mom_{tgl}.png",
                render_market_share_mom(data),
                data,
                False,
            )
        )
    return laporan


KOLOM_PEMAIN = [
    "indihome", "tsel_orbit", "cbn_network", "icon_pln", "xl_home",
    "first_media", "indosat", "myrepublic", "mnc_play", "biznet", "others",
]


def buat_sql(tgl: date) -> str:
    """Bangun satu query SQL Console Rajawali berisi data report /ms dan /msbranch."""
    iso = tgl.strftime("%Y-%m-%d")
    kolom = ", ".join(KOLOM_PEMAIN) + ", status, closest_competitor"
    bagian = [
        f"SELECT 'city' AS q, JSON_ARRAY(event_date, city, {kolom}) AS j "
        f"FROM fixed_ms_city WHERE region = 'JATENG-DIY' AND event_date >= DATE_SUB('{iso}', INTERVAL 450 DAY)",
        f"SELECT 'branch' AS q, JSON_ARRAY(event_date, branch, {kolom}) AS j "
        f"FROM fixed_ms_branch WHERE region = 'JATENG-DIY' AND event_date >= DATE_SUB('{iso}', INTERVAL 450 DAY)",
        f"SELECT 'region' AS q, JSON_ARRAY(event_date, region, {kolom}) AS j "
        f"FROM fixed_ms_region WHERE region = 'JATENG-DIY' AND event_date >= DATE_SUB('{iso}', INTERVAL 450 DAY)",
    ]
    return "\nUNION ALL\n".join(bagian)


class ReportMarketShare(BaseReport):
    """
    /ms [DD-MM-YYYY] — Market Share per Branch + per City + MOM Growth (Jateng-DIY).
    """

    command_name = "ms"
    description = "Market Share Region Jateng-DIY (per Branch, per City, MOM Growth)"
    date_mode = "none"
    supports_rajawali = True
    rajawali_query_keys = ("ms",)
    example_date = "20-09-2026"

    @classmethod
    def build_rajawali_sql(cls, tgl: date, **kwargs) -> str:
        return buat_sql(tgl)

    def __init__(self, *, kirim_foto_fn: Callable[..., Any] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._kirim_foto_fn = kirim_foto_fn

    def parse_args(
        self, raw_args: list[str]
    ) -> tuple[date | None, list[str] | None, str | None]:
        sub_map = self.get_sub_reports()
        selected_subs: list[str] = []
        date_token: str | None = None

        for token in raw_args or []:
            low = token.strip().lower()
            if not low:
                continue
            if low in ("help", "list", "?"):
                return None, None, self.format_help()
            if low in sub_map:
                if low not in selected_subs:
                    selected_subs.append(low)
                continue
            if date_token is None:
                date_token = token.strip()
            else:
                return (
                    None,
                    None,
                    "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/ms 20-09-2026`",
                )

        tgl: date | None = None
        if date_token is not None:
            raw = date_token.replace("/", "-").replace(".", "-")
            try:
                tgl = datetime.strptime(raw, "%d-%m-%Y").date()
            except ValueError:
                return (
                    None,
                    None,
                    "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/ms 20-09-2026`",
                )
        return tgl, (selected_subs or None), None

    @sub_report("branch", "Market Share Per Branch Region Jateng-DIY")
    def build_branch(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("city", "Market Share Per City Region Jateng-DIY")
    def build_city(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    @sub_report("mom", "Market Share MOM Growth Per City Region Jateng-DIY")
    def build_mom(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        is_terjadwal = (
            type(ctx.bot).__name__ == "_BotKeTopic"
            or type(update).__name__ == "_UpdateKeTopic"
        )
        tgl, selected_subs, err = self.parse_args(list(ctx.args or []))
        if err is not None:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

        if not is_terjadwal:
            await update.message.reply_text(
                "⏳ Menyusun Market Share Jateng-DIY "
                + (
                    f"(event date <= {tgl.strftime('%d-%m-%Y')})..."
                    if tgl
                    else "(update terakhir)..."
                )
            )
        try:
            data = await asyncio.to_thread(hitung_market_share, tgl)
            if data is None:
                if not is_terjadwal:
                    msg = (
                        f"❌ Tidak ada data market share Jateng-DIY dengan event date <= "
                        f"{tgl.strftime('%d-%m-%Y')}."
                        if tgl
                        else "❌ Tidak ada data market share Jateng-DIY."
                    )
                    await update.message.reply_text(msg)
                else:
                    logger.warning("[JADWAL:MARKET_SHARE/ms] Tabel tidak punya data Jateng-DIY")
                return

            if is_terjadwal:
                terkirim = state.baca_event_date_terkirim()
                if terkirim is not None and data["event_date"] <= terkirim:
                    logger.info(
                        f"[JADWAL:MARKET_SHARE/ms] Belum ada update (event date terakhir "
                        f"{data['event_date']} sudah dikirim; tercatat di last_sent.json: {terkirim}) — dilewati"
                    )
                    return
                logger.info(
                    f"[JADWAL:MARKET_SHARE/ms] Event date baru {data['event_date']} "
                    f"(terakhir terkirim: {terkirim}) — kirim"
                )

            try:
                data_branch = await asyncio.to_thread(
                    hitung_market_share_branch, data["event_date"]
                )
            except Exception:
                data_branch = None

            laporan = await asyncio.to_thread(
                _gambar_laporan_auto, data, data_branch, selected_subs
            )
            for i, (judul, fname, buf, cap_data, top3) in enumerate(laporan):
                cap = _caption(cap_data, judul, top3=top3)
                await self._kirim_foto_fn(
                    ctx.bot,
                    update.effective_chat.id,
                    buf,
                    fname,
                    caption=cap,
                    label=f"ms{i + 1}",
                )
                if update.effective_chat.id != GROUP_ID:
                    await self._kirim_foto_fn(
                        ctx.bot,
                        GROUP_ID,
                        buf,
                        fname,
                        caption=cap,
                        label=f"ms_grup{i + 1}",
                    )
                if i == 0 and is_terjadwal:
                    state.simpan_event_date_terkirim(data["event_date"])
                    logger.info(
                        f"[JADWAL:MARKET_SHARE/ms] Event date {data['event_date']} "
                        f"ditandai terkirim ke last_sent.json"
                    )
        except Exception as e:
            logger.exception("Error /ms")
            await update.message.reply_text(
                f"❌ Error:\n`{str(e)[:600]}`", parse_mode="Markdown"
            )


class ReportMarketShareBranch(BaseReport):
    """
    /msbranch [DD-MM-YYYY] — Market Share per Branch (fixed_ms_branch), Jateng-DIY.
    """

    command_name = "msbranch"
    description = "Market Share Per Branch Region Jateng-DIY"
    date_mode = "none"
    supports_rajawali = True
    rajawali_query_keys = ("ms",)
    example_date = "20-09-2026"

    @classmethod
    def build_rajawali_sql(cls, tgl: date, **kwargs) -> str:
        return buat_sql(tgl)

    def __init__(self, *, kirim_foto_fn: Callable[..., Any] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._kirim_foto_fn = kirim_foto_fn

    def parse_args(
        self, raw_args: list[str]
    ) -> tuple[date | None, list[str] | None, str | None]:
        sub_map = self.get_sub_reports()
        selected_subs: list[str] = []
        date_token: str | None = None

        for token in raw_args or []:
            low = token.strip().lower()
            if not low:
                continue
            if low in ("help", "list", "?"):
                return None, None, self.format_help()
            if low in sub_map:
                if low not in selected_subs:
                    selected_subs.append(low)
                continue
            if date_token is None:
                date_token = token.strip()
            else:
                return (
                    None,
                    None,
                    "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/msbranch 20-09-2026`",
                )

        tgl: date | None = None
        if date_token is not None:
            raw = date_token.replace("/", "-").replace(".", "-")
            try:
                tgl = datetime.strptime(raw, "%d-%m-%Y").date()
            except ValueError:
                return (
                    None,
                    None,
                    "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/msbranch 20-09-2026`",
                )
        return tgl, (selected_subs or None), None

    @sub_report("main", "Market Share Per Branch Region Jateng-DIY")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        tgl, selected_subs, err = self.parse_args(list(ctx.args or []))
        if err is not None:
            await update.message.reply_text(err, parse_mode="Markdown")
            return

        await update.message.reply_text(
            "⏳ Menyusun Market Share per Branch "
            + (
                f"(event date <= {tgl.strftime('%d-%m-%Y')})..."
                if tgl
                else "(update terakhir)..."
            )
        )
        try:
            data = await asyncio.to_thread(hitung_market_share_branch, tgl)
            if data is None:
                await update.message.reply_text(
                    "❌ Tidak ada data market share per branch untuk tanggal itu."
                )
                return
            buf = await asyncio.to_thread(render_market_share_branch, data)
            fname = f"market_share_branch_{data['event_date'].strftime('%Y%m%d')}.png"
            cap = _caption(data, "Market Share Per Branch Region Jateng-DIY")
            await self._kirim_foto_fn(
                ctx.bot,
                update.effective_chat.id,
                buf,
                fname,
                caption=cap,
                label="msbranch",
            )
            if update.effective_chat.id != GROUP_ID:
                await self._kirim_foto_fn(
                    ctx.bot,
                    GROUP_ID,
                    buf,
                    fname,
                    caption=cap,
                    label="msbranch_grup",
                )
        except Exception as e:
            logger.exception("Error /msbranch")
            await update.message.reply_text(
                f"❌ Error:\n`{str(e)[:600]}`", parse_mode="Markdown"
            )


def register_handlers(
    app,
    timeout_wrapper=None,
    kirim_foto_fn=None,
    tunggu_db_fn=None,
    bot_topic_fn=None,
):
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)
    cmd_ms = ReportMarketShare(kirim_foto_fn=kirim_foto_fn).handle
    cmd_msbranch = ReportMarketShareBranch(kirim_foto_fn=kirim_foto_fn).handle

    async def job_ms_auto(context):
        """Tiap hari 10:00: kirim ke topic MARKET_SHARE kalau ada event_date baru."""
        label = f"{TOPIC_KEY}/ms"
        thread_id = TOPIC_IDS.get(TOPIC_KEY)
        if not thread_id:
            logger.error(f"[JADWAL:{label}] TOPIC_IDS['{TOPIC_KEY}'] belum diisi — dilewati")
            return
        try:
            if tunggu_db_fn is not None and not await tunggu_db_fn(context, label):
                return

            data = await asyncio.to_thread(hitung_market_share, None)
            if data is None:
                logger.warning(f"[JADWAL:{label}] Tabel tidak punya data Jateng-DIY")
                return
            terkirim = state.baca_event_date_terkirim()
            if terkirim is not None and data["event_date"] <= terkirim:
                logger.info(
                    f"[JADWAL:{label}] Belum ada update (event date terakhir "
                    f"{data['event_date']} sudah dikirim) — dilewati"
                )
                return

            logger.info(
                f"[JADWAL:{label}] Event date baru {data['event_date']} "
                f"(terakhir terkirim: {terkirim}) — kirim"
            )
            try:
                data_branch = await asyncio.to_thread(
                    hitung_market_share_branch, data["event_date"]
                )
            except Exception:
                logger.exception(f"[JADWAL:{label}] Data branch gagal — branch dilewati")
                data_branch = None
            if data_branch is None:
                logger.warning(
                    f"[JADWAL:{label}] Tidak ada data market share per branch — dilewati"
                )
            laporan = await asyncio.to_thread(_gambar_laporan_auto, data, data_branch)
            bot_topic = bot_topic_fn(context.bot, thread_id)
            for i, (judul, fname, buf, cap_data, top3) in enumerate(laporan):
                await kirim_foto_fn(
                    bot_topic,
                    REPORT_GROUP_ID,
                    buf,
                    fname,
                    caption=_caption(cap_data, judul, top3=top3),
                    label=f"ms_auto{i + 1}",
                )
                if i == 0:
                    state.simpan_event_date_terkirim(data["event_date"])
        except Exception as e:
            logger.exception(f"[JADWAL:{label}] GAGAL")
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=(
                        f"❌ Laporan terjadwal /ms (topic {TOPIC_KEY}) gagal: {str(e)[:300]}. "
                        f"Dicek ulang besok jam {JAM_OTOMATIS:02d}:{MENIT_OTOMATIS:02d}, "
                        f"atau jalankan /ms manual."
                    ),
                )
            except Exception:
                logger.exception(f"[JADWAL:{label}] Notifikasi gagal tidak terkirim")

    app.add_handler(CommandHandler("ms", _T(cmd_ms)))
    app.add_handler(CommandHandler("msbranch", _T(cmd_msbranch)))
    return cmd_ms, cmd_msbranch
