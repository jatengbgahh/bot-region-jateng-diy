"""
reports/promo/report.py — Implementasi ReportPromo (/promo) menggunakan BaseReport.
"""

from datetime import date
from typing import Callable, Optional

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_promo, renderer_promo


class ReportPromo(BaseReport):
    """
    /promo [DD-MM-YYYY] — PS Paket One Dynamic (New Sales) s/d tanggal yang diminta:
    breakdown per BRANCH, per WOK, dan per CITY dalam satu gambar. Kosong = H-1.
    """

    name = "promo"
    title = "Promo One Dynamic"
    date_mode = "optional"
    default_date_offset = 1
    cutoff_table = "ordering detail"
    done_private_text = "✅ Laporan Promo One Dynamic sudah dikirim ke grup manajemen."

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Generating laporan Promo One Dynamic {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_promo.hitung_promo(tgl)

    @sub_report(
        key="main",
        title="PS Paket One Dynamic — JATENG-DIY (Branch • WOK • City)",
        aliases=("tabel", "all"),
    )
    def render_main(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        periode = f"{data['bulan_label']} — s/d {tgl.strftime('%d-%m-%Y')}"
        img = renderer_promo.render_promo(data, cutoff=cutoff)
        cap = (
            f"📊 *PS Paket One Dynamic — JATENG-DIY*\n"
            f"Breakdown Branch • WOK • City\n{periode}"
        )
        return ReportOutput(
            kind="photo",
            content=img,
            filename="promo_one_dynamic.png",
            caption=cap,
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
):
    rep = ReportPromo(get_cutoff_fn=get_cutoff_fn)
    return rep.register(app, timeout_wrapper=timeout_wrapper)
