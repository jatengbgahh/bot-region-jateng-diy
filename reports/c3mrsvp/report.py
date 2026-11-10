"""
reports/c3mrsvp/report.py — Implementasi ReportC3MRSVP (/c3mrsvp) menggunakan BaseReport.
"""

from datetime import date
from typing import Callable, Optional

from config import REGION_NAME
from reports.base import BaseReport, ReportOutput, sub_report
from .calculator import hitung_c3mrsvp
from .renderer import DEFAULT_TITLE as REPORT_TITLE, render_c3mrsvp


def _fp(v):
    return f"{v:.2f}%" if v is not None else "-"


def _fm(v):
    return f"{'+' if v > 0 else ''}{v:.2f}%" if v is not None else "-"


def _build_caption(result: dict, per_city: bool = False) -> str:
    tgl = result["tgl_closing"]
    reg = result["region"]
    lvl = " City" if per_city else ""

    valid = [w for w in result["cities" if per_city else "woks"] if w.get("pct") is not None]
    top3 = sorted(valid, key=lambda w: w["pct"], reverse=True)[:3]
    bot3 = sorted(valid, key=lambda w: w["pct"])[:3]

    def _fmt(rows):
        if not rows:
            return "   -"
        return "\n".join(
            f"   {i}. {w['name']} ({_fp(w['pct'])} | MoM {_fm(w['mom'])})"
            for i, w in enumerate(rows, 1)
        )

    periode_info = (
        f"\n⚠️ _Tgl 1-5: bill period {result['bi_label']}_"
        if result["is_closing_mode"] else ""
    )
    return (
        f"📊 *{REPORT_TITLE}{' per City' if per_city else ''}*\n"
        f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs {result['bl_label']}{periode_info}\n\n"
        f"*{REGION_NAME}*\n"
        f"Subs: *{reg['subs']:,}*  |  Unpaid: *{reg['unpaid']:,}*\n"
        f"%C3MR: *{_fp(reg['pct'])}*  |  MoM: *{_fm(reg['mom'])}*\n\n"
        f"🔝 *Top 3 C3MR{lvl}*\n{_fmt(top3)}\n\n"
        f"🔻 *Bottom 3 C3MR{lvl}*\n{_fmt(bot3)}"
    )


class ReportC3MRSVP(BaseReport):
    """
    /c3mrSVP DD-MM-YYYY [wok|city] — C3MR Fokus SVP (Pelanggan LOS <=24 Bulan):
      1) wok  : per WOK/Branch
      2) city : per City
    """

    name = "c3mrsvp"
    title = REPORT_TITLE
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("c3mr",)
    cutoff_table = "c3mr"
    done_private_text = f"✅ Laporan {REPORT_TITLE} sudah dikirim ke grup."

    @classmethod
    def build_rajawali_sql(cls, tgl: date, bagian: Optional[str] = "C", **kwargs) -> str:
        from reports.c3mr.report import buat_sql
        return buat_sql(tgl, bagian=bagian)

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan {REPORT_TITLE} untuk {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return hitung_c3mrsvp(tgl)

    @sub_report(
        key="wok",
        title=f"{REPORT_TITLE} per WOK/Branch",
        aliases=("main", "branch"),
    )
    def render_wok(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img = render_c3mrsvp(data, cutoff=cutoff, per_city=False)
        caption = _build_caption(data, per_city=False)
        return ReportOutput(
            kind="photo",
            content=img,
            filename=f"c3mrsvp_{tgl.strftime('%d%m%Y')}.png",
            caption=caption,
        )

    @sub_report(
        key="city",
        title=f"{REPORT_TITLE} per City",
        aliases=("kabupaten",),
    )
    def render_city(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img = render_c3mrsvp(data, cutoff=cutoff, per_city=True)
        caption = _build_caption(data, per_city=True)
        return ReportOutput(
            kind="photo",
            content=img,
            filename=f"c3mrsvp_city_{tgl.strftime('%d%m%Y')}.png",
            caption=caption,
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
):
    rep = ReportC3MRSVP(get_cutoff_fn=get_cutoff_fn)
    return rep.register(app, timeout_wrapper=timeout_wrapper)
