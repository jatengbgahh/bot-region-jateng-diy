"""
reports/caps/report.py — Implementasi ReportCaps (/caps) menggunakan BaseReport & SubReport.

Fitur yang otomatis didapat dari BaseReport:
  • /caps DD-MM-YYYY                  -> kirim 4 gambar (per LOS, by Segmen, by Channel, by Reason)
  • /caps DD-MM-YYYY los              -> hanya kirim gambar CAPS per LOS
  • /caps DD-MM-YYYY segment          -> hanya kirim gambar CAPS by Segmen Pelanggan
  • /caps DD-MM-YYYY channel          -> hanya kirim gambar CAPS by Channel
  • /caps DD-MM-YYYY reason           -> hanya kirim gambar CAPS by Reason
  • /caps help                        -> tampilkan daftar sub-report & cara pakai
"""

import inspect
from datetime import date
from typing import Callable, Optional

from reports.base import BaseReport, ReportOutput, sub_report
from . import (
    calculator_caps,
    calculator_caps_channel,
    calculator_caps_reason,
    calculator_caps_segment,
    renderer_caps,
    renderer_caps_channel,
    renderer_caps_reason,
    renderer_caps_segment,
)


def bottom_woks_caps(woks, n=3):
    valid = [w for w in woks if w.get("ach") is not None]
    if not valid:
        return []
    valid_sorted = sorted(valid, key=lambda r: r["ach"], reverse=True)
    return [(w["name"], w["ach"], w.get("mom")) for w in valid_sorted[:n]]


def top_segments_by_cont(segments: dict, segment_label: dict, n=3):
    valid = [(seg, sm) for seg, sm in segments.items() if sm.get("cont") is not None]
    if not valid:
        return []
    valid_sorted = sorted(valid, key=lambda x: x[1]["cont"], reverse=True)
    return [(segment_label.get(seg, seg), sm["jml"], sm["cont"]) for seg, sm in valid_sorted[:n]]


def top_segments_by_mom(segments: dict, segment_label: dict, n=3):
    valid = [(seg, sm) for seg, sm in segments.items() if sm.get("mom") is not None]
    if not valid:
        return []
    valid_sorted = sorted(valid, key=lambda x: x[1]["mom"], reverse=True)
    return [(segment_label.get(seg, seg), sm["jml"], sm["mom"]) for seg, sm in valid_sorted[:n]]


def top_channels_by_cont(channels: dict, channel_label: dict, n=3):
    valid = [(ch, cm) for ch, cm in channels.items() if cm.get("cont") is not None]
    if not valid:
        return []
    valid.sort(key=lambda x: x[1]["cont"], reverse=True)
    return [(channel_label.get(ch, ch), cm["mtd"], cm["cont"]) for ch, cm in valid[:n]]


def top_channels_by_mom(channels: dict, channel_label: dict, n=3):
    valid = [(ch, cm) for ch, cm in channels.items() if cm.get("mom") is not None]
    if not valid:
        return []
    valid.sort(key=lambda x: x[1]["mom"], reverse=True)
    return [(channel_label.get(ch, ch), cm["mtd"], cm["mom"]) for ch, cm in valid[:n]]


def caps_ket(src: str, tgl_data: date, tgl_diminta: date) -> str:
    s = f"(sumber {src}, data s/d {tgl_data.strftime('%d-%m-%Y')}"
    if tgl_data < tgl_diminta:
        s += f", diminta {tgl_diminta.strftime('%d-%m-%Y')}"
    return s + ")"


def caps_ket_md(src: str, tgl_data: date, tgl_diminta: date) -> str:
    return caps_ket(src, tgl_data, tgl_diminta).replace("_", "\\_")


def _fp(v):
    return f"{v:.1f}%" if v is not None else "-"


def _fm(v):
    return f"{'+' if v > 0 else ''}{v:.1f}%" if v is not None else "-"


def _fi(v):
    return f"{int(round(v)):,}" if v is not None else "-"


def buat_sql(tgl: date) -> str:
    """Bangun satu query SQL Console Rajawali untuk ke-4 gambar report /caps."""
    from dateutil.relativedelta import relativedelta

    ini = tgl.replace(day=1)
    lalu = ini - relativedelta(months=1)
    fmt = lambda d: d.strftime("%Y%m")
    churn_ini, churn_lalu = f"churn_dd_{fmt(ini)}", f"churn_dd_{fmt(lalu)}"
    seg_ini = f"ih_cb_cvm_prfl_mm_{fmt(ini - relativedelta(months=1))}"
    seg_lalu = f"ih_cb_cvm_prfl_mm_{fmt(lalu - relativedelta(months=1))}"
    ret_ini, ret_lalu = f"retensi_dd_{fmt(ini)}", f"retensi_dd_{fmt(lalu)}"

    def churn(tag, t):
        return (
            f"SELECT '{tag}' AS q, JSON_ARRAY(bb_id, kabupaten, region, los_category, deactivation_date) AS j "
            f"FROM {t} WHERE region LIKE 'JATENG%'"
        )

    def seg(tag, t, churn_t):
        return (
            f"SELECT '{tag}' AS q, JSON_ARRAY(bb_id, customer_segment) AS j FROM {t} "
            f"WHERE bb_id IN (SELECT bb_id FROM {churn_t} WHERE region LIKE 'JATENG%')"
        )

    def ret(tag, t):
        return (
            f"SELECT '{tag}' AS q, JSON_ARRAY(bb_id, kabupaten, region_sales, unit_type, reason, "
            f"deactivation_date, retention_category) AS j FROM {t} "
            f"WHERE retention_category = 'DO' AND region_sales LIKE '%JATENG%'"
        )

    return "\nUNION ALL\n".join([
        churn("churn_ini", churn_ini),
        churn("churn_lalu", churn_lalu),
        seg("seg_ini", seg_ini, churn_ini),
        seg("seg_lalu", seg_lalu, churn_lalu),
        ret("ret_ini", ret_ini),
        ret("ret_lalu", ret_lalu),
    ])


class ReportCaps(BaseReport):
    """
    /caps DD-MM-YYYY [los|segment|channel|reason] — Laporan CAPS (Churn) IndiHome Jateng-DIY:
      1) los     : CAPS per LOS & WOK/Branch (sumber churn_dd)
      2) segment : CAPS by Segmen Pelanggan (sumber churn_dd + ih_cb_cvm_prfl_mm)
      3) channel : CAPS by Channel (sumber retensi_dd)
      4) reason  : CAPS by Reason Top 5 per Branch & Region (sumber retensi_dd)
    """

    name = "caps"
    title = "CAPS (Churn)"
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("caps",)
    cutoff_table = "caps"
    done_private_text = "✅ Laporan CAPS sudah dikirim ke grup."

    @classmethod
    def build_rajawali_sql(cls, tgl: date, **kwargs) -> str:
        return buat_sql(tgl)

    def __init__(
        self,
        get_cutoff_fn: Optional[Callable] = None,
        get_target_fn: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(get_cutoff_fn=get_cutoff_fn, **kwargs)
        self.get_target_fn = get_target_fn

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan CAPS (Churn) untuk {tgl.strftime('%d-%m-%Y')}..."

    async def resolve_cutoff(self, tgl: Optional[date], data: Optional[dict] = None):
        if not self.get_cutoff_fn:
            return {"caps": None, "retensi": None}
        c_caps = self.get_cutoff_fn("caps")
        if inspect.isawaitable(c_caps):
            c_caps = await c_caps
        c_ret = self.get_cutoff_fn("retensi")
        if inspect.isawaitable(c_ret):
            c_ret = await c_ret
        return {"caps": c_caps, "retensi": c_ret}

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        out = {}
        target_df = self.get_target_fn() if self.get_target_fn else None
        if "los" in selected_subs:
            out["los"] = calculator_caps.hitung_caps(tgl, target_df=target_df)
        if "segment" in selected_subs:
            out["segment"] = calculator_caps_segment.hitung_caps_segment(tgl)
        if "channel" in selected_subs:
            out["channel"] = calculator_caps_channel.hitung_caps_channel(tgl)
        if "reason" in selected_subs:
            out["reason"] = calculator_caps_reason.hitung_caps_reason(tgl)
        return out

    @sub_report(
        key="los",
        title="CAPS (Churn) IndiHome Jateng-DIY per LOS",
        aliases=("main", "wok"),
    )
    def render_los(self, data: dict, tgl: date, cutoff) -> ReportOutput:
        result = data["los"]
        cutoff_str = cutoff.get("caps") if isinstance(cutoff, dict) else cutoff
        k_args = (
            result.get("src_label", "churn_dd"),
            result.get("tgl_data", tgl),
            result.get("tgl_diminta", tgl),
        )
        ket_los = caps_ket(*k_args)
        ket_los_md = caps_ket_md(*k_args)
        img_buf = renderer_caps.render_caps(result, cutoff=cutoff_str, note=ket_los)
        bl = result["bl_label"]
        reg = result["region"]

        caption = (
            f"📊 *CAPS (Churn) IndiHome Jateng-DIY*\n"
            f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl}\n"
            f"{ket_los_md}\n\n"
            f"Target: *{_fi(reg['target'])}*  |  M-1: *{_fi(reg['m1'])}*  |  M: *{_fi(reg['m'])}*\n"
            f"MoM: *{_fm(reg['mom'])}*  |  Ach: *{_fp(reg['ach'])}*"
        )
        bottom_woks = bottom_woks_caps(result["woks"], n=3)
        if bottom_woks:
            caption += "\n\n🏳️ *Bottom WOK*\n"
            for name, ach, mom in bottom_woks:
                caption += f"• {name}  Ach {_fp(ach)}  MoM {_fm(mom)}\n"
            caption = caption.rstrip("\n")

        return ReportOutput(
            kind="photo",
            content=img_buf,
            filename="caps_report.png",
            caption=caption,
        )

    @sub_report(
        key="segment",
        title="CAPS by Segmen Pelanggan IndiHome Jateng-DIY",
        aliases=("segmen", "seg"),
    )
    def render_segment(self, data: dict, tgl: date, cutoff) -> ReportOutput:
        result_seg = data["segment"]
        cutoff_str = cutoff.get("caps") if isinstance(cutoff, dict) else cutoff
        ks_args = (
            result_seg.get("src_label", "churn_dd"),
            result_seg.get("tgl_data", tgl),
            result_seg.get("tgl_diminta", tgl),
        )
        ket_seg = caps_ket(*ks_args)
        ket_seg_md = caps_ket_md(*ks_args)
        img_buf_seg = renderer_caps_segment.render_caps_segment(result_seg, cutoff=cutoff_str, note=ket_seg)

        reg_segs = result_seg["region"]["segments"]
        seg_label = result_seg["segment_label"]
        top_cont = top_segments_by_cont(reg_segs, seg_label, n=3)
        top_mom = top_segments_by_mom(reg_segs, seg_label, n=3)

        seg_lines = [
            "📊 *CAPS by Segmen Pelanggan IndiHome Jateng-DIY*",
            f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs MtD {result_seg['bl_label']}",
            ket_seg_md,
        ]
        if top_cont:
            seg_lines.append("\n*Top Segmen by Cont*")
            for label, jml, cont in top_cont:
                seg_lines.append(f"- {label}: {_fp(cont)} ({jml:,})")
        if top_mom:
            seg_lines.append("\n*Top Segment by MoM*")
            for label, jml, mom in top_mom:
                seg_lines.append(f"- {label}: {_fm(mom)} ({jml:,})")
        caption_seg = "\n".join(seg_lines)

        return ReportOutput(
            kind="photo",
            content=img_buf_seg,
            filename="caps_segment_report.png",
            caption=caption_seg,
        )

    @sub_report(
        key="channel",
        title="CAPS by Channel Jateng-DIY",
        aliases=("ch",),
    )
    def render_channel(self, data: dict, tgl: date, cutoff) -> ReportOutput:
        result_ch = data["channel"]
        cutoff_ret = cutoff.get("retensi") if isinstance(cutoff, dict) else cutoff
        ket_ch = caps_ket("retensi_dd", result_ch["tgl_closing"], result_ch["tgl_diminta"])
        ket_ch_md = caps_ket_md("retensi_dd", result_ch["tgl_closing"], result_ch["tgl_diminta"])
        img_buf_ch = renderer_caps_channel.render_caps_channel(result_ch, cutoff=cutoff_ret, note=ket_ch)

        reg_chans = result_ch["region"]["channels"]
        ch_label = result_ch["channel_label"]
        tgl_ch = result_ch["tgl_closing"]
        ch_lines = [
            "📊 *CAPS by Channel Jateng-DIY*",
            f"MtD {tgl_ch.strftime('%d-%m-%Y')}  |  MoM vs MtD {result_ch['bl_label']}",
            ket_ch_md,
            "",
            f"Total CAPS: *{_fi(result_ch['region']['mtd'])}*  |  "
            f"M-1: *{_fi(result_ch['region']['m1'])}*  |  MoM: *{_fm(result_ch['region']['mom'])}*",
        ]
        top_ch_mom = top_channels_by_mom(reg_chans, ch_label, n=3)
        if top_ch_mom:
            ch_lines.append("\n⚠️ *Top Channel by MoM*")
            for label, mtd, mom in top_ch_mom:
                ch_lines.append(f"- {label}: {_fm(mom)} (MtD {mtd:,})")
        top_ch_cont = top_channels_by_cont(reg_chans, ch_label, n=3)
        if top_ch_cont:
            ch_lines.append("\n⚠️ *Top Channel by Cont*")
            for label, mtd, cont in top_ch_cont:
                ch_lines.append(f"- {label}: {_fp(cont)} (MtD {mtd:,})")
        caption_ch = "\n".join(ch_lines)

        return ReportOutput(
            kind="photo",
            content=img_buf_ch,
            filename="caps_channel_report.png",
            caption=caption_ch,
        )

    @sub_report(
        key="reason",
        title="CAPS by Reason Jateng-DIY (Top 5)",
        aliases=("rsn", "alasan"),
    )
    def render_reason(self, data: dict, tgl: date, cutoff) -> ReportOutput:
        result_rsn = data["reason"]
        cutoff_ret = cutoff.get("retensi") if isinstance(cutoff, dict) else cutoff
        ket_rsn = caps_ket("retensi_dd", result_rsn["tgl_closing"], result_rsn["tgl_diminta"])
        ket_rsn_md = caps_ket_md("retensi_dd", result_rsn["tgl_closing"], result_rsn["tgl_diminta"])
        img_buf_rsn = renderer_caps_reason.render_caps_reason(result_rsn, cutoff=cutoff_ret, note=ket_rsn)

        reg_blk = result_rsn["region"]
        tgl_rsn = result_rsn["tgl_closing"]
        rsn_lines = [
            "📊 *CAPS by Reason Jateng-DIY*",
            f"MtD {tgl_rsn.strftime('%d-%m-%Y')}  |  MoM vs MtD {result_rsn['bl_label']}",
            ket_rsn_md,
            "",
            f"Total CAPS: *{_fi(reg_blk['total'])}*  |  "
            f"M-1: *{_fi(reg_blk['total_l'])}*  |  MoM: *{_fm(reg_blk['mom'])}*",
            "\n⚠️ *Top 5 Reason*",
        ]
        for r in reg_blk["rows"]:
            if r["mtd"] is None:
                continue
            rsn_lines.append(
                f"{r['no']}. {r['reason']}  MtD {r['mtd']:,} | "
                f"Cont {_fp(r['cont'])} | MoM {_fm(r['mom'])}"
            )
        caption_rsn = "\n".join(rsn_lines)

        return ReportOutput(
            kind="photo",
            content=img_buf_rsn,
            filename="caps_reason_report.png",
            caption=caption_rsn,
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
    get_target_fn: Optional[Callable] = None,
):
    rep = ReportCaps(get_cutoff_fn=get_cutoff_fn, get_target_fn=get_target_fn)
    return rep.register(app, timeout_wrapper=timeout_wrapper)
