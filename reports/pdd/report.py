"""
reports/pdd/report.py — Implementasi ReportPDD (/pdd) menggunakan BaseReport.
"""

from datetime import date
from typing import Callable, Optional

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_pdd, renderer_pdd


class ReportPDD(BaseReport):
    """
    /pdd DD-MM-YYYY — Laporan PDD per BRANCH/WOK IndiHome Jateng-DIY (MtD s/d tanggal).
    """

    name = "pdd"
    title = "PDD IndiHome Jateng-DIY"
    date_mode = "required"
    cutoff_table = "ordering detail"
    done_private_text = "✅ Laporan PDD sudah dikirim ke grup manajemen."

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan PDD untuk {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_pdd.hitung_pdd(tgl)

    @sub_report(
        key="main",
        title="PDD IndiHome Jateng-DIY per BRANCH/WOK",
        aliases=("tabel", "all"),
    )
    def render_main(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img = renderer_pdd.render_pdd(data, cutoff=cutoff)
        caption = (
            f"📊 *PDD IndiHome Jateng-DIY*\n"
            f"MtD {tgl.strftime('%d-%m-%Y')}  ({data['bi_label']})"
        )
        return ReportOutput(
            kind="photo",
            content=img,
            filename="pdd_report.png",
            caption=caption,
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
):
    rep = ReportPDD(get_cutoff_fn=get_cutoff_fn)
    return rep.register(app, timeout_wrapper=timeout_wrapper)
