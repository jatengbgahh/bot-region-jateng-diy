"""
reports/dailyre/report.py — Implementasi ReportDailyRE (/dailyre) menggunakan BaseReport.
"""

from datetime import date
from typing import Callable, Optional

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_dailyre, renderer_dailyre


class ReportDailyRE(BaseReport):
    """
    /dailyre DD/MM/YYYY — Monitoring New Daily RE (target base weekday/weekend + gap kemarin).
    """

    name = "dailyre"
    title = "Monitoring Daily RE"
    date_mode = "required"
    warn_future_date = False
    done_private_text = "✅ Laporan sudah dikirim ke grup manajemen."

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Menyusun Monitoring Daily RE {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_dailyre.hitung_dailyre(tgl)

    @sub_report(
        key="main",
        title="Monitoring New Daily RE per WOK/Branch",
        aliases=("tabel", "all"),
        run_in_thread=True,
    )
    def render_main(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img_buf = renderer_dailyre.render_dailyre(data)
        caption = renderer_dailyre.build_caption(data)
        fname = f"monitoring_daily_re_{tgl.strftime('%Y%m%d')}.png"
        return ReportOutput(
            kind="photo",
            content=img_buf,
            filename=fname,
            caption=caption,
            parse_mode="Markdown",
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
):
    rep = ReportDailyRE()
    return rep.register(app, timeout_wrapper=timeout_wrapper)
