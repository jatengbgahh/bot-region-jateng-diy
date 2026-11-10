"""
reports/closing/report.py — Implementasi BaseReport untuk keluarga report Closing, Liveupdate, dan Daily RE+PS:
  - /liveupdate      (ReportLiveUpdate)
  - /liveupdateutoip (ReportLiveUpdateUtoip)
  - /liveupdatebk    (ReportLiveUpdateBK)
  - /closingsql      (ReportClosingSQL)
  - /closingutoip    (ReportClosingUtoip)
  - /closingbk       (ReportClosingBK)
  - /closing         (ReportClosingKPRO)
  - /closinghadoop   (ReportClosingHadoop)
  - /dailyreps       (ReportDailyREPS)
  - /closingdaily    (ReportClosingDaily)
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Callable

import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes

import db
from reports.base import BaseReport, ReportOutput, sub_report

logger = logging.getLogger(__name__)


class _LiveUpdateBase(BaseReport):
    date_mode = "none"
    data_source = "db"
    done_text = "✅ Laporan sudah dikirim ke grup manajemen."

    def __init__(self, *, kirim_laporan_sql_fn: Callable[..., Any], **kwargs):
        super().__init__(**kwargs)
        self._kirim_laporan_sql_fn = kirim_laporan_sql_fn

    @sub_report("main", "Paket Laporan Hourly Monitoring RE/PS")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        upload_time = datetime.now()
        await update.message.reply_text(self.format_progress(None, None))
        try:
            kw: dict[str, Any] = {
                "mode": "hourly",
                "reply_msg": update.message,
            }
            if self.data_source != "db":
                kw["data_source"] = self.data_source
            await self._kirim_laporan_sql_fn(
                ctx.bot,
                update.effective_chat.id,
                upload_time,
                **kw,
            )
            if self.forward_to_group and update.effective_chat.id != self.group_id:
                await update.message.reply_text(self.done_text)
        except Exception as e:
            logger.exception(f"Error /{self.command_name}")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


class ReportLiveUpdate(_LiveUpdateBase):
    command_name = "liveupdate"
    description = "Generate laporan liveupdate dari DB sekarang (dashboard_hourly_sales)"
    data_source = "db"
    send_wa = True
    supports_rajawali = True
    rajawali_query_keys = ("hourly",)
    done_text = "✅ Laporan sudah dikirim ke grup manajemen."

    @classmethod
    def build_rajawali_sql(cls, tgl: date | None = None, **kwargs) -> str:
        from dateutil.relativedelta import relativedelta

        hari_ini = tgl or date.today()
        ini, lalu = hari_ini.replace(day=1), hari_ini.replace(day=1) - relativedelta(months=1)
        bagian = (
            f"SELECT region, kabupaten, wok, cluster, activity_date, activity_hour, MAX(activity_time) AS activity_time, "
            f"SUM(io_trx) AS io_trx, SUM(re_trx) AS re_trx, SUM(ps_trx) AS ps_trx FROM dashboard_hourly_sales_{{m:%Y%m}} "
            f"WHERE region LIKE 'JATENG%' AND activity_date <= '{hari_ini:%Y-%m-%d}' "
            f"GROUP BY region, kabupaten, wok, cluster, activity_date, activity_hour"
        )
        return " UNION ALL ".join(bagian.format(m=m) for m in (lalu, ini))

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return "⏳ Mengambil data dari database, mohon tunggu..."


class ReportLiveUpdateUtoip(_LiveUpdateBase):
    command_name = "liveupdateutoip"
    description = "Backup /liveupdate dengan sumber data dari FMC API"
    data_source = "fmc"
    done_text = "✅ Laporan (backup FMC) sudah dikirim ke grup manajemen."

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return "⏳ Mengambil data dari FMC API (backup), mohon tunggu..."


class ReportLiveUpdateBK(_LiveUpdateBase):
    command_name = "liveupdatebk"
    description = "Backup /liveupdate dihitung ulang langsung dari tabel raw indihome_ordering_detail"
    data_source = "raw"
    done_text = "✅ Laporan (backup raw ordering_detail) sudah dikirim ke grup manajemen."

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return (
            "⏳ Mengambil data dari tabel raw ordering_detail (backup), mohon tunggu...\n"
            "⚠️ Sumber ini scan tabel mentah (bukan pre-aggregated), bisa makan waktu "
            "~5-10 menit — mohon jangan kirim ulang command selama menunggu."
        )


class _ClosingSQLBase(BaseReport):
    date_mode = "required"
    warn_future_date = False
    example_date = "03-05-2026"
    data_source = "db"
    validate_db_dates = False
    done_text = "✅ Laporan closing sudah dikirim ke grup."

    def __init__(self, *, kirim_laporan_sql_fn: Callable[..., Any], **kwargs):
        super().__init__(**kwargs)
        self._kirim_laporan_sql_fn = kirim_laporan_sql_fn

    def usage_text(self) -> str:
        return f"⚠️ Sertakan tanggal.\nContoh: `/{self.command_name} {self.example_date}`"

    @sub_report("main", "Paket Laporan Closing Monitoring RE/PS")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        if not raw_args:
            await update.message.reply_text(self.usage_text(), parse_mode="Markdown")
            return

        try:
            tgl_closing = datetime.strptime(raw_args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah. Gunakan: `DD-MM-YYYY`",
                parse_mode="Markdown",
            )
            return

        if self.validate_db_dates:
            try:
                tanggal_tersedia = db.query_tanggal_tersedia(tgl_closing)
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Gagal cek database:\n`{e}`", parse_mode="Markdown"
                )
                return

            if tgl_closing not in tanggal_tersedia:
                tgl_str = ", ".join(
                    t.strftime("%d-%m-%Y") for t in sorted(tanggal_tersedia)[-5:]
                )
                cutoff_line = ""
                try:
                    info = db.query_last_update()
                    if info.get("last_update"):
                        cutoff_line = (
                            f"\n🕐 Cutoff data: {info['last_update'].strftime('%d-%m-%Y %H:%M:%S')}"
                        )
                except Exception as e:
                    logger.warning(f"Gagal ambil info cutoff data: {e}")
                await update.message.reply_text(
                    f"❌ Data tanggal {tgl_closing.strftime('%d-%m-%Y')} belum tersedia di database."
                    f"{cutoff_line}\n"
                    f"Tanggal tersedia (5 terakhir): {tgl_str}"
                )
                return

        upload_time = datetime.now()
        await update.message.reply_text(self.format_progress(tgl_closing, None))

        try:
            kw: dict[str, Any] = {
                "mode": "closing",
                "tgl_closing": tgl_closing,
                "reply_msg": update.message,
            }
            if self.data_source != "db":
                kw["data_source"] = self.data_source
            await self._kirim_laporan_sql_fn(
                ctx.bot,
                update.effective_chat.id,
                upload_time,
                **kw,
            )
            if self.forward_to_group and update.effective_chat.id != self.group_id:
                await update.message.reply_text(self.done_text)
        except Exception as e:
            logger.exception(f"Error /{self.command_name}")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


class ReportClosingSQL(_ClosingSQLBase):
    command_name = "closingsql"
    description = "Laporan closing dari DB (dashboard_hourly_sales)"
    data_source = "db"
    send_wa = True
    supports_rajawali = True
    rajawali_query_keys = ("nasional_murmer", "iod_*")

    @classmethod
    def build_rajawali_sql(cls, tgl: date, **kwargs) -> str:
        return (
            f"SELECT * FROM indihome_ordering_detail_{tgl:%Y%m} "
            f"WHERE region LIKE 'JATENG%' AND order_type = 'NEW SALES'"
        )
    validate_db_dates = True
    done_text = "✅ Laporan closing sudah dikirim ke grup."

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return f"⏳ Generating closing DB {tgl.strftime('%d-%m-%Y')}..."


class ReportClosingUtoip(_ClosingSQLBase):
    command_name = "closingutoip"
    description = "Backup /closingsql dengan sumber data dari FMC API"
    data_source = "fmc"
    validate_db_dates = False
    done_text = "✅ Laporan closing (backup FMC) sudah dikirim ke grup."

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return (
            f"⏳ Generating closing FMC (backup) {tgl.strftime('%d-%m-%Y')}...\n"
            f"⚠️ Daily Performance City tetap dari DB (FMC tidak punya data kabupaten)."
        )


class ReportClosingBK(_ClosingSQLBase):
    command_name = "closingbk"
    description = "Backup /closingsql dihitung ulang langsung dari tabel raw indihome_ordering_detail"
    data_source = "raw"
    validate_db_dates = False
    done_text = "✅ Laporan closing (backup raw ordering_detail) sudah dikirim ke grup."

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        return (
            f"⏳ Generating closing raw ordering_detail (backup) {tgl.strftime('%d-%m-%Y')}...\n"
            f"⚠️ Sumber ini scan tabel mentah untuk Monitoring RE + Daily Performance "
            f"(bukan pre-aggregated), bisa makan waktu 10-20 menit total — mohon jangan "
            f"kirim ulang command selama menunggu."
        )


class ReportClosingKPRO(BaseReport):
    command_name = "closing"
    description = "Laporan closing dari data upload KPRO"
    date_mode = "required"
    warn_future_date = False
    example_date = "03-05-2026"

    def __init__(
        self,
        *,
        get_kpro_fn: Callable[[], tuple[Any, Any]],
        kirim_laporan_fn: Callable[..., Any],
        get_cutoff_upload_fn: Callable[[Any], str | None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_kpro_fn = get_kpro_fn
        self._kirim_laporan_fn = kirim_laporan_fn
        self._get_cutoff_upload_fn = get_cutoff_upload_fn

    @sub_report("main", "Laporan Closing KPRO")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        last_kpro, last_upload_time = self._get_kpro_fn()
        if last_kpro is None:
            await update.message.reply_text(
                "⚠️ Belum ada data KPRO.\nUpload file KPRO dulu sebelum generate closing."
            )
            return

        if not raw_args:
            await update.message.reply_text(
                "⚠️ Sertakan tanggal.\nContoh: `/closing 03-05-2026`",
                parse_mode="Markdown",
            )
            return

        try:
            tgl_closing = datetime.strptime(raw_args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah.\nGunakan: `DD-MM-YYYY`",
                parse_mode="Markdown",
            )
            return

        df_check = last_kpro.copy()
        df_check["DATECREATED"] = pd.to_datetime(df_check["DATECREATED"], errors="coerce")
        tanggal_tersedia = df_check["DATECREATED"].dt.date.unique()

        if tgl_closing not in tanggal_tersedia:
            tgl_list = sorted(tanggal_tersedia)
            tgl_str = ", ".join(t.strftime("%d-%m-%Y") for t in tgl_list[-5:])
            await update.message.reply_text(
                f"❌ Tanggal {tgl_closing.strftime('%d-%m-%Y')} tidak ada di data KPRO.\n"
                f"Tanggal tersedia (5 terakhir): {tgl_str}"
            )
            return

        upload_time = datetime.now()
        await update.message.reply_text(
            f"⏳ Generating laporan closing {tgl_closing.strftime('%d-%m-%Y')}..."
        )

        try:
            await self._kirim_laporan_fn(
                update,
                ctx,
                last_kpro,
                upload_time,
                mode="closing",
                tgl_closing=tgl_closing,
                cutoff=self._get_cutoff_upload_fn(last_upload_time),
            )
        except Exception as e:
            logger.exception("Error saat generate closing")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


class ReportDailyREPS(BaseReport):
    command_name = "dailyreps"
    description = "Laporan Daily RE & PS dari data upload Hadoop"
    date_mode = "none"

    def __init__(
        self,
        *,
        get_hadoop_fn: Callable[[], tuple[Any, Any]],
        kirim_laporan_daily_fn: Callable[..., Any],
        get_cutoff_upload_fn: Callable[[Any], str | None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_hadoop_fn = get_hadoop_fn
        self._kirim_laporan_daily_fn = kirim_laporan_daily_fn
        self._get_cutoff_upload_fn = get_cutoff_upload_fn

    @sub_report("main", "Laporan Daily RE & PS (Hadoop)")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        last_hadoop, last_upload_time = self._get_hadoop_fn()
        if last_hadoop is None:
            await update.message.reply_text(
                "⚠️ Belum ada data Hadoop.\nUpload file `ordering_detail_*.csv` dulu.",
                parse_mode="Markdown",
            )
            return

        upload_time = datetime.now()
        await update.message.reply_text("⏳ Generating laporan daily RE & PS...")
        try:
            await self._kirim_laporan_daily_fn(
                update,
                ctx,
                last_hadoop,
                upload_time,
                cutoff=self._get_cutoff_upload_fn(last_upload_time),
            )
        except Exception as e:
            logger.exception("Error /dailyreps")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


class ReportClosingDaily(BaseReport):
    command_name = "closingdaily"
    description = "Laporan Closing Daily RE+PS dari data upload Hadoop"
    date_mode = "required"
    warn_future_date = False
    example_date = "03-05-2026"

    def __init__(
        self,
        *,
        get_hadoop_fn: Callable[[], tuple[Any, Any]],
        kirim_laporan_daily_fn: Callable[..., Any],
        get_cutoff_upload_fn: Callable[[Any], str | None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_hadoop_fn = get_hadoop_fn
        self._kirim_laporan_daily_fn = kirim_laporan_daily_fn
        self._get_cutoff_upload_fn = get_cutoff_upload_fn

    @sub_report("main", "Laporan Closing Daily RE+PS (Hadoop)")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        last_hadoop, last_upload_time = self._get_hadoop_fn()
        if last_hadoop is None:
            await update.message.reply_text(
                "⚠️ Belum ada data Hadoop.\nUpload file `ordering_detail_*.csv` dulu.",
                parse_mode="Markdown",
            )
            return

        if not raw_args:
            await update.message.reply_text(
                "⚠️ Sertakan tanggal.\nContoh: `/closingdaily 03-05-2026`",
                parse_mode="Markdown",
            )
            return

        try:
            tgl_closing = datetime.strptime(raw_args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah. Gunakan: `DD-MM-YYYY`",
                parse_mode="Markdown",
            )
            return

        upload_time = datetime.now()
        await update.message.reply_text(
            f"⏳ Generating closing daily RE+PS {tgl_closing.strftime('%d-%m-%Y')}..."
        )
        try:
            await self._kirim_laporan_daily_fn(
                update,
                ctx,
                last_hadoop,
                upload_time,
                tgl_closing=tgl_closing,
                cutoff=self._get_cutoff_upload_fn(last_upload_time),
            )
        except Exception as e:
            logger.exception("Error /closingdaily")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


class ReportClosingHadoop(BaseReport):
    command_name = "closinghadoop"
    description = "Laporan Closing dari data upload Hadoop"
    date_mode = "required"
    warn_future_date = False
    example_date = "03-05-2026"

    def __init__(
        self,
        *,
        get_hadoop_fn: Callable[[], tuple[Any, Any]],
        kirim_laporan_fn: Callable[..., Any],
        get_cutoff_upload_fn: Callable[[Any], str | None],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._get_hadoop_fn = get_hadoop_fn
        self._kirim_laporan_fn = kirim_laporan_fn
        self._get_cutoff_upload_fn = get_cutoff_upload_fn

    @sub_report("main", "Laporan Closing Hadoop")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput | None:
        return None

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        raw_args = list(ctx.args or [])
        if raw_args and raw_args[0].strip().lower() in ("help", "list", "?"):
            await update.message.reply_text(self.format_help(), parse_mode="Markdown")
            return

        last_hadoop, last_upload_time = self._get_hadoop_fn()
        if last_hadoop is None:
            await update.message.reply_text(
                "⚠️ Belum ada data Hadoop.\nUpload file `ordering_detail_*.csv` dulu.",
                parse_mode="Markdown",
            )
            return

        if not raw_args:
            await update.message.reply_text(
                "⚠️ Sertakan tanggal.\nContoh: `/closinghadoop 03-05-2026`",
                parse_mode="Markdown",
            )
            return

        try:
            tgl_closing = datetime.strptime(raw_args[0], "%d-%m-%Y").date()
        except ValueError:
            await update.message.reply_text(
                "❌ Format tanggal salah.\nGunakan: `DD-MM-YYYY`",
                parse_mode="Markdown",
            )
            return

        df_check = last_hadoop.copy()
        tanggal_tersedia = df_check["DATECREATED"].dt.date.unique()

        if tgl_closing not in tanggal_tersedia:
            tgl_list = sorted(tanggal_tersedia)
            tgl_str = ", ".join(t.strftime("%d-%m-%Y") for t in tgl_list[-5:])
            await update.message.reply_text(
                f"❌ Tanggal {tgl_closing.strftime('%d-%m-%Y')} tidak ada di data Hadoop.\n"
                f"Tanggal tersedia (5 terakhir): {tgl_str}"
            )
            return

        upload_time = datetime.now()
        await update.message.reply_text(
            f"⏳ Generating laporan closing Hadoop {tgl_closing.strftime('%d-%m-%Y')}..."
        )
        try:
            await self._kirim_laporan_fn(
                update,
                ctx,
                last_hadoop,
                upload_time,
                mode="closing",
                tgl_closing=tgl_closing,
                source="hadoop",
                cutoff=self._get_cutoff_upload_fn(last_upload_time),
            )
        except Exception as e:
            logger.exception("Error /closinghadoop")
            await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")
