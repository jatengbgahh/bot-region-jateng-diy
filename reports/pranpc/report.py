"""
reports/pranpc/report.py — Implementasi BaseReport untuk keluarga report PraNPC:
  - /pranpcall   (ReportPranpcAll)
  - /pranpcagent (ReportPranpcAgent)
  - /moretensi   (ReportMoRetensi)
  - /pranpcsp    (ReportPranpcSP)
  - /pranpcprio  (ReportPranpcPrio)
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_pranpc, renderer_pranpc


def _pranpc_note_mundur(tgl_minta: date | None, tgl: date) -> list[str]:
    if tgl_minta and tgl != tgl_minta:
        return [f"_(data status baru s/d {tgl.strftime('%d-%m-%Y')}, diminta {tgl_minta.strftime('%d-%m-%Y')})_"]
    return []


class PranpcBaseReport(BaseReport):
    """Base class bersama untuk kelima report PraNPC (tanpa argumen tanggal = data terakhir di DB)."""

    date_mode = "none"
    example_date = "14-10-2026"
    progress_label = "PraNPC"
    report_group_name = "PraNPC"

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
                return None, None, self.usage_text()

        tgl: date | None = None
        if date_token is not None:
            try:
                tgl = datetime.strptime(date_token, "%d-%m-%Y").date()
            except ValueError:
                return (
                    None,
                    None,
                    f"❌ Format tanggal salah. Gunakan: `/{self.command_name} DD-MM-YYYY`\n"
                    f"Contoh: `/{self.command_name} {self.example_date}`",
                )
        return tgl, (selected_subs or None), None

    def format_progress(self, tgl: date | None, sub_keys: list[str] | None = None) -> str:
        label = tgl.strftime("%d-%m-%Y") if tgl else "data terakhir"
        return f"⏳ Memproses {self.progress_label} ({label})..."

    async def send_outputs(
        self,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        outputs: list[ReportOutput],
    ) -> None:
        await super().send_outputs(update, ctx, outputs)
        if self.forward_to_group and update.effective_chat.id != self.group_id and outputs:
            await update.message.reply_text(f"✅ Laporan {self.report_group_name} sudah dikirim ke grup.")


class ReportPranpcAll(PranpcBaseReport):
    command_name = "pranpcall"
    description = "Recovery Rate (SSL) PraNPC All WO per WOK"
    progress_label = "Recovery Rate PraNPC All LoS"
    report_group_name = "PraNPC All LoS"

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(calculator_pranpc.hitung_pranpc_all, tgl)
        return {"result": result, "tgl_minta": tgl}

    @sub_report("main", "Recovery Rate PraNPC All LoS per WOK")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        tgl_minta = data["tgl_minta"]
        img_buf = renderer_pranpc.render_pranpc_all(result)
        reg = result["region"]
        tgl_actual = result["tgl"]

        def _p(v): return f"{v:.2f}%" if v is not None else "-"
        def _pm(v): return f"{round(v, 2) + 0.0:.2f}%" if v is not None else "-"

        lines = [
            "📊 Recovery Rate PraNPC All LoS",
            renderer_pranpc._tgl_id(tgl_actual, panjang=True),
            "",
            f"Paid MtD: {reg['paid']} ssl",
            f"MoM Paid (%): {_pm(reg['mom_paid'])}",
            f"RR MtD: {_p(reg['rr'])}",
            f"MoM RR: {_pm(reg['mom_rr'])}",
        ] + _pranpc_note_mundur(tgl_minta, tgl_actual)
        top = calculator_pranpc.top_woks(result, n=5)
        if top:
            lines += ["", "Top WOK", "WOK | RR ssl | MoM"]
            lines += [f"{w['name']}: {_p(w['rr'])} | {_pm(w['mom_rr'])}" for w in top]
        bottom = calculator_pranpc.bottom_woks(result, n=5)
        if bottom:
            lines += ["", "Bottom WOK", "WOK | RR ssl | MoM"]
            lines += [f"{w['name']}: {_p(w['rr'])} | {_pm(w['mom_rr'])}" for w in bottom]
        caption = "\n".join(lines)

        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="pranpc_all.png",
            caption=caption,
            parse_mode="Markdown",
        )


class ReportPranpcAgent(PranpcBaseReport):
    command_name = "pranpcagent"
    description = "Report PraNPC per Channel Agent (per WOK)"
    progress_label = "Report PraNPC per Channel Agent"
    report_group_name = "PraNPC per Channel Agent"

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(calculator_pranpc.hitung_pranpc_agent, tgl)
        return {"result": result, "tgl_minta": tgl}

    @sub_report("main", "Report PraNPC per Channel Agent")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        tgl_minta = data["tgl_minta"]
        img_buf = renderer_pranpc.render_pranpc_agent(result)
        reg = result["region"]
        tgl_actual = result["tgl"]

        def _p(v): return f"{v:.2f}%" if v is not None else "-"

        lines = [
            "📊 Report PraNPC per Channel Agent",
            tgl_actual.strftime("%d %b %Y"),
            "",
            f"WO PraNPC : {reg['wo']}",
            f"Paid : {reg['paid']}",
            f"%RR SSL : {_p(reg['rr'])}",
        ] + _pranpc_note_mundur(tgl_minta, tgl_actual) + ["", "WO | Paid | %RR SSL"]
        for k, nama in calculator_pranpc.CHANNELS:
            ch = reg[k]
            lines.append(f"{nama} | {ch['wo']} | {ch['paid']} | {_p(ch['rr'])}")
        lines += [
            "",
            f"Unpaid (Suspect New CT0): {reg['unpaid']}",
            f"Unpaid Rate: {_p(reg['unpaid_rate'])}",
        ]
        caption = "\n".join(lines)

        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="pranpc_agent.png",
            caption=caption,
            parse_mode="Markdown",
        )


class ReportMoRetensi(PranpcBaseReport):
    command_name = "moretensi"
    description = "Retensi PraNPC All LoS per WOK (MO Retensi, Prepaid, DO, New CT0)"
    progress_label = "Report Retensi PraNPC"
    report_group_name = "Retensi PraNPC"

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(calculator_pranpc.hitung_pranpc_retensi, tgl)
        return {"result": result, "tgl_minta": tgl}

    @sub_report("main", "Report Retensi PraNPC (All LoS)")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        tgl_minta = data["tgl_minta"]
        img_buf = renderer_pranpc.render_pranpc_retensi(result)
        reg = result["region"]
        tgl_actual = result["tgl"]

        def _p(v, d=2): return f"{v:.{d}f}%" if v is not None else "-"
        def _pm(v, d=2): return f"{round(v, d) + 0.0:.{d}f}%" if v is not None else "-"

        lines = [
            "📊 Report Retensi PraNPC (All LoS)",
            renderer_pranpc._tgl_id(tgl_actual, panjang=True),
            "",
            "Secara Region,",
            f"%Paket Eksisting: {_p(reg['pct_eks'])}",
            f"%MO Paket Retensi: {_p(reg['pct_mo'])}",
            f"%MO Prepaid: {_p(reg['pct_pre'])}",
            f"%Ach to Target Retensi: {_p(reg['ach'])}",
            f"Gap to Target: {reg['gap']}",
            f"%CAPS (DO): {_p(reg['pct_do'])}",
            f"Suspect New CT0: {reg['new_ct0']}",
        ] + _pranpc_note_mundur(tgl_minta, tgl_actual)
        bottom = calculator_pranpc.bottom_woks_retensi(result, n=5)
        if bottom:
            lines += [
                "",
                "WOK dengan %MO Retensi\\* Terendah",
                "WOK | %MO Retensi to Total Paid | MoM",
            ]
            lines += [f"{w['name']} | {_p(w['pct_mo'], 1)} | {_pm(w['mom'], 1)}" for w in bottom]
            lines += ["", "\\*Non Prepaid, terhadap total paid"]
        caption = "\n".join(lines)

        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="pranpc_retensi.png",
            caption=caption,
            parse_mode="Markdown",
        )


class ReportPranpcSP(PranpcBaseReport):
    command_name = "pranpcsp"
    description = "Recovery Rate + Caring PraNPC channel Agency & Super Partner per WOK"
    progress_label = "PraNPC Agency & Super Partner"
    report_group_name = "PraNPC Agency & Super Partner"

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(calculator_pranpc.hitung_pranpc_sp, tgl)
        return {"result": result, "tgl_minta": tgl}

    @sub_report("main", "Recovery Rate PraNPC Agency & Super Partner")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        tgl_minta = data["tgl_minta"]
        img_buf = renderer_pranpc.render_pranpc_sp(result)
        tgl_actual = result["tgl"]

        def _p(v): return f"{v:.1f}%" if v is not None else "-"
        def _pm(v): return f"{round(v, 1) + 0.0:.1f}%" if v is not None else "-"

        lines = [
            "📊 Recovery Rate PraNPC Agency & Super Partner",
            renderer_pranpc._tgl_id(tgl_actual, panjang=True),
        ] + _pranpc_note_mundur(tgl_minta, tgl_actual)
        bottom = calculator_pranpc.bottom_woks_rr(result, n=5)
        if bottom:
            lines += ["", "Bottom WOK dengan %RR SSL Terendah", "WOK | %RR SSL | MoM Paid"]
            lines += [f"{w['name']} | {_p(w['rr'])} | {_pm(w['mom_paid'])}" for w in bottom]
        caption = "\n".join(lines)

        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="pranpc_sp.png",
            caption=caption,
            parse_mode="Markdown",
        )


class ReportPranpcPrio(PranpcBaseReport):
    command_name = "pranpcprio"
    description = "PraNPC by Prioritas (Branch x P1/P2/P3/TACTICAL Transkom)"
    progress_label = "Report PraNPC per Prioritas"
    report_group_name = "PraNPC per Prioritas"

    async def fetch_data(
        self,
        tgl: date | None,
        update: Update,
        ctx: ContextTypes.DEFAULT_TYPE,
        selected_subs: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(calculator_pranpc.hitung_pranpc_prio, tgl)
        return {"result": result, "tgl_minta": tgl}

    @sub_report("main", "Report PraNPC per Prioritas")
    def build_main(self, data: dict[str, Any], tgl: date | None) -> ReportOutput:
        result = data["result"]
        tgl_minta = data["tgl_minta"]
        img_buf = renderer_pranpc.render_pranpc_prio(result)
        tgl_actual = result["tgl"]

        def _p(v): return f"{v:.1f}%" if v is not None else "-"

        lines = [
            "📊 Report PraNPC per Prioritas",
            renderer_pranpc._tgl_id(tgl_actual, panjang=True),
        ] + _pranpc_note_mundur(tgl_minta, tgl_actual) + [""]
        per_branch: dict[str, dict[str, Any]] = {}
        for r in result["woks"]:
            per_branch.setdefault(r["branch"], {})[r["name"]] = r
        for br, prios in per_branch.items():
            lines.append(br)
            lines.append(
                " | ".join(
                    f"{p}: {_p(prios[p]['pct_visit_x'])}"
                    for p in ("P1", "P2", "P3")
                    if p in prios
                )
            )
        caption = "\n".join(lines)

        return ReportOutput(
            kind="photo",
            buf=img_buf,
            filename="pranpc_prio.png",
            caption=caption,
            parse_mode="Markdown",
        )
