"""
reports/addon/report.py — Implementasi ReportAddon (/addon) menggunakan BaseReport.
"""

from datetime import date
from typing import Callable, Optional

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_addon, renderer_addon

_BRANCH_CAPTION_ALIAS = {"YOGYAKARTA": "Yogya"}


def build_caption_addon(result: dict, tgl_closing: date) -> str:
    total_branch = len(result["branches"])
    lines = [
        f"Update Addon IndiHome Jateng-DIY MTD {tgl_closing.strftime('%b')}'{tgl_closing.strftime('%y')} "
        f"(s.d. {tgl_closing.strftime('%d %b')})",
        "Total achievement:",
        "",
    ]
    for prod in result["product_order"]:
        label = result["product_labels"][prod]
        reg_m = result["region"]["products"][prod]
        m0 = int(reg_m.get("m0") or 0)
        target = reg_m.get("target")
        ach = reg_m.get("ach")
        target_str = f"{int(round(target)):,}" if target else "-"
        ach_str = f"{ach:.2f}%" if ach is not None else "-"

        lines.append(f"• {label}: {m0:,} / {target_str} (Ach {ach_str})")

        active_branches = [
            b for b in result["branches"]
            if b["products"][prod].get("has_target") and b["products"][prod].get("ach") is not None
        ]
        prefix = ""
        if active_branches and len(active_branches) < total_branch:
            prefix = f"Dibuka di {len(active_branches)} branch: "

        if active_branches:
            best = max(active_branches, key=lambda b: b["products"][prod]["ach"])
            best_ach = best["products"][prod]["ach"]
            best_name = _BRANCH_CAPTION_ALIAS.get(best["name"], best["name"].title())
            lines.append(f"{prefix}Best Branch {best_name} (Ach {best_ach:.2f}%)")
        elif prefix:
            lines.append(f"{prefix}Best Branch -")

        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


class ReportAddon(BaseReport):
    """
    /addon DD-MM-YYYY — Laporan Addon (FTTR / IP Camera / Mesh Wifi) per BRANCH/WOK.
    """

    name = "addon"
    title = "Addon (FTTR / IP Camera / Mesh Wifi)"
    date_mode = "required"
    cutoff_table = "ordering detail"
    retry_max_tries = 3
    done_private_text = "✅ Laporan Addon sudah dikirim ke grup manajemen."

    def __init__(
        self,
        get_cutoff_fn: Optional[Callable] = None,
        get_target_fn: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(get_cutoff_fn=get_cutoff_fn, **kwargs)
        self.get_target_fn = get_target_fn

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan Addon untuk {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        target_dfs = self.get_target_fn() if self.get_target_fn else {}
        return calculator_addon.hitung_addon(tgl, target_dfs=target_dfs)

    @sub_report(
        key="main",
        title="Laporan Addon FTTR / IP Camera / Mesh Wifi per BRANCH/WOK",
        aliases=("tabel", "all"),
    )
    def render_main(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img = renderer_addon.render_addon(data, cutoff=cutoff)
        caption = build_caption_addon(data, tgl)
        if data.get("target_is_default"):
            caption += (
                f"\n⚠️ Sheet target Addon belum di-upload — Target ditampilkan sementara "
                f"= *{int(data['default_target'])}* utk semua WOK/produk, bukan target riil."
            )
        return ReportOutput(
            kind="photo",
            content=img,
            filename="addon_report.png",
            caption=caption,
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
    get_target_fn: Optional[Callable] = None,
):
    rep = ReportAddon(get_cutoff_fn=get_cutoff_fn, get_target_fn=get_target_fn)
    return rep.register(app, timeout_wrapper=timeout_wrapper)
