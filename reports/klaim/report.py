"""
reports/klaim/report.py — Implementasi ReportKlaim (/klaim) menggunakan BaseReport.
"""

from datetime import date
from io import BytesIO
from typing import Callable, Optional
import pandas as pd

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_klaim, renderer_klaim


class ReportKlaim(BaseReport):
    """
    /klaim [rekap|unpaid] — Rekap Data Pelanggan Klaim per Nama Program:
      1) rekap  : 3 gambar (detail, geo/branch, program) + pesan teks ringkasan
      2) unpaid : file Excel raw_klaim_unpaid_<cutoff>.xlsx (Paid Flag 0/X)
    """

    name = "klaim"
    title = "Rekap Data Pelanggan Klaim"
    date_mode = "none"
    supports_rajawali = False
    done_private_text = "✅ Rekap Data Pelanggan Klaim sudah dikirim ke grup."

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return "⏳ Memproses Rekap Data Pelanggan Klaim (refresh Paid Flag live dari DB)..."

    def fetch_data(self, tgl: Optional[date], selected_subs: set[str], extra_args: list[str]) -> dict:
        try:
            return calculator_klaim.hitung_klaim()
        except FileNotFoundError as e:
            return {"_abort_message": f"❌ File klaim tidak ditemukan:\n`{e}`"}

    @sub_report(
        key="rekap",
        title="Rekap Data Pelanggan Klaim (3 Gambar + Ringkasan)",
        aliases=("main", "tabel", "gambar"),
    )
    def render_rekap(self, data: dict, tgl: Optional[date], cutoff: Optional[str]) -> list[ReportOutput]:
        cutoff_dt = data["cutoff"]
        bp = data["bill_period"]

        db_lu = data.get("db_last_update")
        db_lu_str = db_lu.strftime("%d %b %Y, %H:%M") if db_lu else "tidak diketahui"
        db_stale_note = ""
        if db_lu and db_lu.date() < cutoff_dt:
            db_stale_note = (
                " ⚠️ (belum ada refresh baru hari ini — kalau angka sama dengan "
                "sebelumnya, ini sebabnya, bukan bot gagal query)"
            )

        n_missing = data["n_total"] - data["n_found_db"]
        missing_note = ""
        if n_missing:
            missing_note = (
                f"\n⚠️ {n_missing} dari {data['n_total']} Nomor Internet tidak ketemu di "
                f"bwmp_c3mr_dd bill_period {bp.strftime('%b %Y')} — Paid Flag fallback ke data upload."
            )

        program_lines = "\n".join(
            f"{i+1}. {r['Nama Program']} : {r['pct_c3mr']:.1f}%"
            for i, r in enumerate(data["program_rows"])
        )

        caption = (
            f"📊 C3MR Program Diskon Tagihan\n"
            f"cut off {cutoff_dt.strftime('%d %b %Y')}\n"
            f"data DB (bwmp_c3mr_dd) terakhir update: {db_lu_str}{db_stale_note}\n\n"
            f"{program_lines}"
            f"{missing_note}"
        )

        img_detail = renderer_klaim.render_klaim_detail(data)
        img_geo = renderer_klaim.render_klaim_geo(data)
        img_program = renderer_klaim.render_klaim_program(data)

        return [
            ReportOutput(kind="photo", content=img_detail, filename="klaim_detail.png", parse_mode=None),
            ReportOutput(kind="photo", content=img_geo, filename="klaim_geo.png", parse_mode=None),
            ReportOutput(kind="photo", content=img_program, filename="klaim_program.png", parse_mode=None),
            ReportOutput(kind="text", content=caption, parse_mode=None),
        ]

    @sub_report(
        key="unpaid",
        title="Raw Data Klaim UNPAID (Excel)",
        aliases=("raw", "excel", "xlsx"),
        run_in_thread=True,
    )
    def render_unpaid(self, data: dict, tgl: Optional[date], cutoff: Optional[str]) -> Optional[ReportOutput]:
        df_raw_unpaid = data.get("raw_unpaid_df")
        if df_raw_unpaid is None or df_raw_unpaid.empty:
            return None
        cutoff_dt = data["cutoff"]
        xlsx_buf = BytesIO()
        with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
            df_raw_unpaid.to_excel(writer, sheet_name="All Klaim", index=False)
        xlsx_buf.seek(0)
        fname_raw = f"raw_klaim_unpaid_{cutoff_dt.strftime('%d%m%Y')}.xlsx"
        caption_raw = (
            f"📎 Raw data Klaim UNPAID per {cutoff_dt.strftime('%d-%m-%Y')} — "
            f"{len(df_raw_unpaid):,} pelanggan (Paid Flag 0/X, yang sudah paid dihilangkan)"
        )
        return ReportOutput(
            kind="document",
            content=xlsx_buf,
            filename=fname_raw,
            caption=caption_raw,
            parse_mode=None,
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
):
    rep = ReportKlaim()
    return rep.register(app, timeout_wrapper=timeout_wrapper)
