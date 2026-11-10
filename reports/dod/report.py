"""
reports/dod/report.py — Implementasi ReportDoD (/dod) menggunakan BaseReport.
"""

from datetime import date
from typing import Callable, Optional

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_dod, renderer_dod


class ReportDoD(BaseReport):
    """
    /dod DD-MM-YYYY [count|pct|city] — Laporan PS Harian & %DoD PS IndiHome JATENG-DIY:
      1) count : Angka PS harian per BRANCH/WOK (default)
      2) pct   : %DoD (Day over Day) PS harian per BRANCH/WOK (default)
      3) city  : DoD Performance FMC City per CITY (opsional, dipanggil via `/dod DD-MM-YYYY city`)
    """

    name = "dod"
    title = "PS Harian & %DoD PS IndiHome JATENG-DIY"
    date_mode = "required"
    cutoff_table = "ordering detail"
    done_private_text = "✅ Laporan PS & %DoD sudah dikirim ke grup manajemen."

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Generating laporan %DoD {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        out = {}
        if "count" in selected_subs or "pct" in selected_subs:
            out["main"] = calculator_dod.hitung_dod(tgl)
        if "city" in selected_subs:
            out["city"] = calculator_dod.hitung_dod_city(tgl)
        return out

    @sub_report(
        key="count",
        title="PS Harian IndiHome JATENG-DIY per BRANCH/WOK",
        aliases=("ps", "angka"),
    )
    def render_count(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        result = data["main"]
        periode = f"{result['bulan_label']} — s/d {tgl.strftime('%d-%m-%Y')}"
        img = renderer_dod.render_dod_count(result, cutoff=cutoff)
        return ReportOutput(
            kind="photo",
            content=img,
            filename="dod_count_report.png",
            caption=f"📊 *PS Harian IndiHome JATENG-DIY*\n{periode}",
        )

    @sub_report(
        key="pct",
        title="%DoD (Day over Day) PS IndiHome JATENG-DIY per BRANCH/WOK",
        aliases=("dod", "persen"),
    )
    def render_pct(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        result = data["main"]
        periode = f"{result['bulan_label']} — s/d {tgl.strftime('%d-%m-%Y')}"
        img = renderer_dod.render_dod_pct(result, cutoff=cutoff)
        return ReportOutput(
            kind="photo",
            content=img,
            filename="dod_pct_report.png",
            caption=f"📊 *%DoD (Day over Day) PS IndiHome JATENG-DIY*\n{periode}",
        )

    @sub_report(
        key="city",
        title="DoD Performance FMC City per Kabupaten",
        aliases=("kabupaten", "fmc"),
        default=False,
    )
    def render_city(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        result_city = data["city"]
        periode = f"{result_city['bulan_label']} — s/d {tgl.strftime('%d-%m-%Y')}"
        img = renderer_dod.render_dod_city(result_city, cutoff=cutoff)
        return ReportOutput(
            kind="photo",
            content=img,
            filename="dod_city_report.png",
            caption=f"📊 *DoD Performance FMC City — JATENG-DIY*\n{periode}",
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
):
    rep = ReportDoD(get_cutoff_fn=get_cutoff_fn)
    return rep.register(app, timeout_wrapper=timeout_wrapper)
