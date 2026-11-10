"""
reports/childps/report.py — Implementasi BaseReport untuk /childps (Child per PS Telkomsel One by WOK).
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from telegram import Update
from telegram.ext import ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_childps, childps_bot, config_childps, renderer_childps

logger = logging.getLogger(__name__)

TABEL = "tselone_to_msisdn_{yyyymm}"
KOLOM = ["bln", "city", "cluster", "ps", "child"]


def periode(tgl: date):
    """(awal_lalu, batas_lalu, batas_ini): tanggal 1 bulan lalu, tanggal pembanding bulan lalu, cutoff."""
    lalu = tgl - relativedelta(months=1)
    akhir_bulan = tgl.day == calendar.monthrange(tgl.year, tgl.month)[1]
    hari_lalu = calendar.monthrange(lalu.year, lalu.month)[1] if akhir_bulan else tgl.day
    return lalu.replace(day=1), lalu.replace(day=hari_lalu), tgl


def buat_sql(tgl: date) -> str:
    """Bangun query agregat SQL Console Rajawali / MySQL untuk /childps."""
    awal_lalu, batas_lalu, batas_ini = periode(tgl)
    awal_ini = tgl.replace(day=1)
    t_lalu = TABEL.format(yyyymm=awal_lalu.strftime("%Y%m"))
    t_ini = TABEL.format(yyyymm=awal_ini.strftime("%Y%m"))
    pilih = (
        "SELECT bb_id, msisdn_parent, msisdn_child, activation_date_ih, city, cluster "
        "FROM {t} WHERE region LIKE 'JATENG%' AND LEFT(activation_date_ih, 10) BETWEEN '{a}' AND '{b}'"
    )
    dalam = " UNION ALL ".join([
        pilih.format(t=t_lalu, a=awal_lalu.isoformat(), b=batas_ini.isoformat()),
        pilih.format(t=t_ini, a=awal_lalu.isoformat(), b=batas_ini.isoformat()),
    ])
    return (
        "SELECT LEFT(activation_date_ih, 7) AS bln, city, cluster, "
        "COUNT(DISTINCT bb_id) AS ps, "
        "COUNT(DISTINCT CASE WHEN msisdn_child IS NOT NULL AND msisdn_child <> '' "
        "AND msisdn_child <> msisdn_parent THEN msisdn_child END) AS child "
        f"FROM ({dalam}) x "
        f"WHERE (LEFT(activation_date_ih, 10) BETWEEN '{awal_lalu.isoformat()}' AND '{batas_lalu.isoformat()}') "
        f"OR (LEFT(activation_date_ih, 10) BETWEEN '{awal_ini.isoformat()}' AND '{batas_ini.isoformat()}') "
        "GROUP BY LEFT(activation_date_ih, 7), city, cluster"
    )


class ReportChildPS(BaseReport):
    """
    /childps [DD-MM-YYYY] — Report Child per PS Telkomsel One by WOK.
    Urutan sumber data:
      1. export Rajawali yang dimuat report_pagi_csv.py (childps_bot._childps_export)
      2. file upload terakhir — HANYA command manual
      3. query agregat langsung ke MySQL
    """

    command_name = "childps"
    description = "Child per PS Telkomsel One by WOK"
    date_mode = "none"
    supports_rajawali = True
    rajawali_query_keys = ("childps",)
    example_date = "03-11-2026"

    @classmethod
    def build_rajawali_sql(cls, tgl: date, **kwargs) -> str:
        return buat_sql(tgl)

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
                return None, None, "❌ Format: /childps DD-MM-YYYY  (contoh: /childps 03-11-2026)"

        tgl: date | None = None
        if date_token is not None:
            try:
                tgl = datetime.strptime(date_token, "%d-%m-%Y").date()
            except ValueError:
                return None, None, "❌ Format: /childps DD-MM-YYYY  (contoh: /childps 03-11-2026)"

        return tgl, (selected_subs or None), None

    @sub_report("main", "Tabel Child per PS Telkomsel One by WOK")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> list[ReportOutput]:
        res = data["res"]
        sumber = data["sumber"]
        img = data["img"]
        caption = calculator_childps.buat_caption(res)
        fname = f"childps_tselone_{res['tgl'].strftime('%Y%m%d')}.png"
        outputs = [
            ReportOutput(
                kind="photo",
                buf=img,
                filename=fname,
                caption=caption,
                parse_mode=None,
            )
        ]
        if res["tanpa_wok"]:
            outputs.append(
                ReportOutput(
                    kind="text",
                    text=(
                        f"ℹ️ {res['tanpa_wok']:,} PS tidak masuk WOK mana pun "
                        f"(city & cluster kosong / di luar mapping) — tidak dihitung. Sumber: {sumber}"
                    ),
                    parse_mode=None,
                )
            )
        return outputs

    async def handle(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        headless = getattr(ctx, "application", None) is None

        tgl, selected_subs, err = self.parse_args(list(ctx.args or []))
        if err is not None:
            parse_mode = "Markdown" if err.startswith("📋") else None
            await msg.reply_text(err, parse_mode=parse_mode)
            return

        try:
            if childps_bot._childps_export is not None:
                await childps_bot._kirim(
                    update,
                    ctx,
                    childps_bot._childps_export,
                    tgl or (date.today() - timedelta(days=1)),
                    "export Rajawali",
                )
            elif childps_bot._childps_df is not None and not headless:
                await msg.reply_text(
                    f"⏳ Memproses Child per PS dari file upload terakhir "
                    f"({childps_bot._childps_upload_time.strftime('%d-%m-%Y %H:%M')})..."
                )
                await childps_bot._kirim(
                    update, ctx, childps_bot._childps_df, tgl, "file upload terakhir"
                )
            else:
                tgl = tgl or (date.today() - timedelta(days=1))
                await msg.reply_text(
                    f"⏳ Query DB Child per PS s.d. {tgl.strftime('%d-%m-%Y')}..."
                )
                df = await asyncio.to_thread(
                    calculator_childps.query_db, tgl, config_childps.CHILDPS_SQL
                )
                if df.empty:
                    await msg.reply_text("⚠️ Hasil query kosong.")
                    return
                await childps_bot._kirim(update, ctx, df, tgl, "DB")
        except Exception as e:
            logger.exception("Error cmd_childps")
            await msg.reply_text(f"❌ Gagal membuat report Child per PS:\n{e}")
