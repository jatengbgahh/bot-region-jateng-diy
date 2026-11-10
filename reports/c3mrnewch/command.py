"""
reports/c3mrnewch/command.py — Implementasi ReportC3MRNewCh (/c3mrnewch) menggunakan BaseReport.
"""

from datetime import date
from typing import Callable, Optional

from config import REGION_NAME
from reports.base import BaseReport, ReportOutput, sub_report
from .calculator import CHANNEL_LABEL, hitung_c3mrnewch
from .renderer import render_c3mrnewch

REPORT_TITLE = "C3MR LoS 0-6 Bulan per Channel Group"


def _fp(v):
    return f"{v:.2f}%" if v is not None else "-"


def _fm(v):
    return f"{'+' if v > 0 else ''}{v:.2f}%" if v is not None else "-"


def _build_caption(result: dict) -> str:
    tgl = result["tgl_closing"]
    bl = result["bl_label"]
    bi = result["bi_label"]
    closing_mode = result["is_closing_mode"]
    channels = result["channels"]
    reg = result["region"]

    periode_info = f"\n⚠️ _Tgl 1-5: bill period {bi}_" if closing_mode else ""

    lines = [
        f"📊 *{REPORT_TITLE}*",
        f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs {bl}{periode_info}",
        "",
    ]
    for row in channels:
        label = CHANNEL_LABEL.get(row["name"], row["name"].title())
        lines.append(
            f"{label} | C3MR Total: {_fp(row.get('total_pct'))} "
            f"(MoM {_fm(row.get('total_mom'))})| Unpaid: {row.get('total_unpaid', 0):,}"
        )
    lines.append(
        f"{REGION_NAME} | C3MR Total: {_fp(reg.get('total_pct'))} "
        f"(MoM {_fm(reg.get('total_mom'))})| Unpaid: {reg.get('total_unpaid', 0):,}"
    )
    return "\n".join(lines)


class ReportC3MRNewCh(BaseReport):
    """
    /c3mrnewch DD-MM-YYYY — C3MR per BILL-N dikelompokkan per Channel Group.
    """

    name = "c3mrnewch"
    title = REPORT_TITLE
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("c3mr",)
    cutoff_table = "c3mr"
    done_private_text = f"✅ Laporan {REPORT_TITLE} sudah dikirim ke grup."

    @classmethod
    def build_rajawali_sql(cls, tgl: date, bagian: Optional[str] = "N", **kwargs) -> str:
        from reports.c3mr.report import buat_sql
        return buat_sql(tgl, bagian=bagian)

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan {REPORT_TITLE} untuk {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return hitung_c3mrnewch(tgl)

    @sub_report(
        key="main",
        title=REPORT_TITLE,
        aliases=("channel", "tabel"),
    )
    def render_main(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img = render_c3mrnewch({**data, "report_title": REPORT_TITLE}, cutoff=cutoff)
        caption = _build_caption(data)
        return ReportOutput(
            kind="photo",
            content=img,
            filename=f"c3mrnewch_{tgl.strftime('%d%m%Y')}.png",
            caption=caption,
        )


def register_handlers(app, timeout_wrapper=None, get_cutoff_fn=None):
    rep = ReportC3MRNewCh(get_cutoff_fn=get_cutoff_fn)
    return rep.register(app, timeout_wrapper=timeout_wrapper)
