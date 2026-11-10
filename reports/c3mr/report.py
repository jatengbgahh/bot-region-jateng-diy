"""
reports/c3mr/report.py — Implementasi keluarga C3MR (/c3mr, /c3mr10s, /c3mrnew, /payment)
menggunakan BaseReport & SubReport.
"""

from datetime import date
from io import BytesIO
from typing import Callable, Optional
from dateutil.relativedelta import relativedelta
import pandas as pd

import db
from reports.base import BaseReport, ReportOutput, sub_report
from . import (
    calculator_c3mr,
    calculator_c3mr10s,
    calculator_c3mrnew,
    renderer_c3mr,
    renderer_c3mr10s,
    renderer_c3mr10s_seg,
    renderer_c3mr_los,
    renderer_c3mrnew,
)


def _fp(v):
    return f"{v:.2f}%" if v is not None else "-"


def _fm(v):
    return f"{'+' if v > 0 else ''}{v:.2f}%" if v is not None else "-"


def _bottom3(rows, key_pct):
    valid = [(w["name"], w.get(key_pct)) for w in rows if w.get(key_pct) is not None]
    valid.sort(key=lambda x: x[1])
    return valid[:3]


def _fmt_bottom3(rows):
    return "\n".join(f"   {w} ({_fp(p)})" for w, p in rows)


def buat_sql(tgl: date, bagian: Optional[str] = None) -> str:
    """
    Bangun query agregat SQL Console Rajawali untuk 5 report C3MR
    (/c3mr, /c3mrnew, /c3mrnewch, /c3mr10s, /c3mrsvp).
    bagian:
      None : A + N (default untuk seluruh report C3MR)
      "C"  : hanya c3mr + c3mrsvp (bwmp saja)
      "A"  : c3mr + c3mrsvp + c3mr10s (bwmp + segment)
      "N"  : c3mrnew + c3mrnewch (cohort BILL-1..6)
      "U"  : data unpaid per pelanggan untuk lampiran CSV /c3mrnew
    """
    import wilayah

    bp_ini = (tgl - relativedelta(months=1)).replace(day=1) if tgl.day <= 5 else tgl.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)
    cut_ini, cut_lalu = tgl, tgl - relativedelta(months=1)
    ok_city = wilayah.sql_terpetakan("city")
    ok_city_a = wilayah.sql_terpetakan("a.city")
    ym = lambda d: d.strftime("%Y%m")
    ymd = lambda d: d.strftime("%Y-%m-%d")

    def parte_a(tag, bp, cutoff):
        return f"""SELECT '{tag}' AS q, JSON_ARRAY(city, los_category, segment, subs, bill, paid_subs, clearing, unpaid) AS j FROM (
  SELECT a.city AS city, TRIM(a.los_category) AS los_category,
         COALESCE(TRIM(b.customer_segment), 'Unmapped') AS segment,
         COUNT(*) AS subs, SUM(a.bill_amount) AS bill,
         COUNT(CASE WHEN a.payment_date IS NOT NULL AND a.payment_date <= '{ymd(cutoff)}' THEN 1 END) AS paid_subs,
         SUM(CASE WHEN a.payment_date IS NOT NULL AND a.payment_date <= '{ymd(cutoff)}' THEN a.clearing_amount END) AS clearing,
         SUM(COALESCE(a.paid_flag, 0) = 0) AS unpaid
  FROM bwmp_c3mr_dd_{ym(bp)} a
  LEFT JOIN ih_cb_cvm_prfl_mm_{ym(bp - relativedelta(months=1))} b ON a.bb_id = b.bb_id AND b.region LIKE 'JATENG%'
  WHERE a.region LIKE 'JATENG%' AND a.bill_period = '{ymd(bp)}' AND {ok_city_a}
  GROUP BY a.city, TRIM(a.los_category), COALESCE(TRIM(b.customer_segment), 'Unmapped')
) t"""

    def parte_c(tag, bp, cutoff):
        return f"""SELECT '{tag}' AS q, JSON_ARRAY(city, los_category, subs, bill, paid_subs, clearing, unpaid) AS j FROM (
  SELECT a.city AS city, TRIM(a.los_category) AS los_category,
         COUNT(*) AS subs, SUM(a.bill_amount) AS bill,
         COUNT(CASE WHEN a.payment_date IS NOT NULL AND a.payment_date <= '{ymd(cutoff)}' THEN 1 END) AS paid_subs,
         SUM(CASE WHEN a.payment_date IS NOT NULL AND a.payment_date <= '{ymd(cutoff)}' THEN a.clearing_amount END) AS clearing,
         SUM(COALESCE(a.paid_flag, 0) = 0) AS unpaid
  FROM bwmp_c3mr_dd_{ym(bp)} a
  WHERE a.region LIKE 'JATENG%' AND a.bill_period = '{ymd(bp)}' AND {ok_city_a}
  GROUP BY a.city, TRIM(a.los_category)
) t"""

    def _union_ordering(bp):
        u = []
        for n in range(1, 7):
            od = bp - relativedelta(months=n)
            dari, sampai = od.replace(day=1), od.replace(day=1) + relativedelta(months=1)
            u.append(f"""    SELECT bb_id, ps_ts, channel_group, sf_code, sf_company_name, product_commercial_name, {n} AS bill_n
    FROM indihome_ordering_detail_{ym(od)}
    WHERE region LIKE 'JATENG%' AND order_type = 'NEW SALES'
      AND ps_ts >= '{ymd(dari)}' AND ps_ts < '{ymd(sampai)}'
      AND ps_ts IS NOT NULL AND ps_ts != '0000-00-00 00:00:00'""")
        return "\n    UNION ALL\n".join(u)

    def parte_n(tag, bp, cutoff):
        union = _union_ordering(bp)
        return f"""SELECT '{tag}' AS q, JSON_ARRAY(city, bill_n, channel_group, subs, bill, clearing, unpaid) AS j FROM (
  SELECT b.city AS city, x.bill_n AS bill_n, x.channel_group AS channel_group, COUNT(*) AS subs,
         SUM(b.bill_amount) AS bill,
         SUM(CASE WHEN b.payment_date IS NOT NULL AND b.payment_date <= '{ymd(cutoff)}' THEN b.clearing_amount END) AS clearing,
         SUM(COALESCE(b.paid_flag, 0) = 0) AS unpaid
  FROM (
    SELECT bb_id, ps_ts, channel_group, sf_code, sf_company_name, product_commercial_name, MIN(bill_n) AS bill_n
    FROM (
{union}
    ) u
    GROUP BY bb_id, ps_ts, channel_group, sf_code, sf_company_name, product_commercial_name
  ) x
  JOIN (
    SELECT bb_id, city, bill_amount, clearing_amount, paid_flag, payment_date
    FROM (
      SELECT bb_id, city, bill_amount, clearing_amount, paid_flag, payment_date,
             ROW_NUMBER() OVER (PARTITION BY bb_id ORDER BY payment_date DESC) AS rn_b
      FROM bwmp_c3mr_dd_{ym(bp)}
      WHERE region LIKE 'JATENG%' AND {ok_city}
    ) t1
    WHERE rn_b = 1
  ) b ON x.bb_id = b.bb_id
  GROUP BY b.city, x.bill_n, x.channel_group
) t"""

    def parte_u(tag, bp, cutoff):
        union = _union_ordering(bp)
        return f"""SELECT '{tag}' AS q, JSON_ARRAY(bb_id, ps_ts, channel_group, sf_code, sf_company_name, product_commercial_name, city, los_category, bill_n, bill_amount, clearing_amount, paid_flag, payment_date) AS j FROM (
  SELECT x.bb_id AS bb_id, x.ps_ts AS ps_ts, x.channel_group AS channel_group, x.sf_code AS sf_code,
         x.sf_company_name AS sf_company_name, x.product_commercial_name AS product_commercial_name,
         b.city AS city, b.los_category AS los_category, x.bill_n AS bill_n, b.bill_amount AS bill_amount,
         b.clearing_amount AS clearing_amount, b.paid_flag AS paid_flag, b.payment_date AS payment_date
  FROM (
    SELECT bb_id, ps_ts, channel_group, sf_code, sf_company_name, product_commercial_name, MIN(bill_n) AS bill_n
    FROM (
{union}
    ) u
    GROUP BY bb_id, ps_ts, channel_group, sf_code, sf_company_name, product_commercial_name
  ) x
  JOIN (
    SELECT bb_id, city, los_category, bill_amount, clearing_amount, paid_flag, payment_date
    FROM (
      SELECT bb_id, city, los_category, bill_amount, clearing_amount, paid_flag, payment_date,
             ROW_NUMBER() OVER (PARTITION BY bb_id ORDER BY payment_date DESC) AS rn_b
      FROM bwmp_c3mr_dd_{ym(bp)}
      WHERE region LIKE 'JATENG%' AND {ok_city}
    ) t1
    WHERE rn_b = 1
  ) b ON x.bb_id = b.bb_id
  WHERE COALESCE(b.paid_flag, 0) = 0
) t"""

    bagian_sql = []
    if bagian == "U":
        bagian_sql += [parte_u("U_ini", bp_ini, cut_ini)]
    if bagian == "C":
        bagian_sql += [parte_c("C_ini", bp_ini, cut_ini), parte_c("C_lalu", bp_lalu, cut_lalu)]
    if bagian in (None, "A"):
        bagian_sql += [parte_a("A_ini", bp_ini, cut_ini), parte_a("A_lalu", bp_lalu, cut_lalu)]
    if bagian in (None, "N"):
        bagian_sql += [parte_n("N_ini", bp_ini, cut_ini), parte_n("N_lalu", bp_lalu, cut_lalu)]
    return "\nUNION ALL\n".join(bagian_sql)


class ReportC3MR(BaseReport):
    """
    /c3mr DD-MM-YYYY [wok|city|los] — C3MR Early Tenure & All LOS:
      1) wok  : Early Tenure vs All LOS per WOK/Branch
      2) city : Early Tenure vs All LOS per City
      3) los  : C3MR per LOS group (dikirim sebagai document PNG)
    """

    name = "c3mr"
    title = "C3MR"
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("c3mr",)
    cutoff_table = "c3mr"
    done_private_text = "✅ Laporan C3MR sudah dikirim ke grup."

    @classmethod
    def build_rajawali_sql(cls, tgl: date, bagian: Optional[str] = None, **kwargs) -> str:
        return buat_sql(tgl, bagian=bagian)

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan C3MR untuk {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_c3mr.hitung_c3mr(tgl)

    @sub_report(
        key="wok",
        title="C3MR Early Tenure vs All LOS per WOK/Branch",
        aliases=("main", "branch"),
    )
    def render_wok(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        bl = data["bl_label"]
        bi = data["bi_label"]
        reg = data["region"]
        woks = data["woks"]
        periode_info = f"\n⚠️ _Tgl 1-5: bill period {bi}_" if data["is_closing_mode"] else ""

        img1 = renderer_c3mr.render_c3mr(data, cutoff=cutoff)
        et_bot = _bottom3(woks, "et_pct")
        al_bot = _bottom3(woks, "al_pct")

        caption1 = (
            f"📊 *C3MR IndiHome Jateng-DIY*\n"
            f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs {bl}"
            f"{periode_info}\n\n"
            f"*Early Tenure (Los 0-6 bln)*\n"
            f"Subs: *{reg['et_subs']:,}*  |  Unpaid: *{reg['et_unpaid']:,}*\n"
            f"%C3MR: *{_fp(reg['et_pct'])}*  |  MoM: *{_fm(reg['et_mom'])}*\n"
            f"Bottom 3 WOK:\n{_fmt_bottom3(et_bot)}\n\n"
            f"*All LOS*\n"
            f"Subs: *{reg['al_subs']:,}*  |  Unpaid: *{reg['al_unpaid']:,}*\n"
            f"%C3MR: *{_fp(reg['al_pct'])}*  |  MoM: *{_fm(reg['al_mom'])}*\n"
            f"Bottom 3 WOK:\n{_fmt_bottom3(al_bot)}"
        )
        return ReportOutput(
            kind="photo",
            content=img1,
            filename="c3mr_report.png",
            caption=caption1,
        )

    @sub_report(
        key="city",
        title="C3MR Early Tenure vs All LOS per City",
        aliases=("kabupaten",),
    )
    def render_city(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        bl = data["bl_label"]
        bi = data["bi_label"]
        reg = data["region"]
        cities = data["cities"]
        periode_info = f"\n⚠️ _Tgl 1-5: bill period {bi}_" if data["is_closing_mode"] else ""

        img_city = renderer_c3mr.render_c3mr(data, cutoff=cutoff, per_city=True)
        caption_city = (
            f"📊 *C3MR IndiHome Jateng-DIY per City*\n"
            f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs {bl}"
            f"{periode_info}\n\n"
            f"*Early Tenure (Los 0-6 bln)*: {_fp(reg['et_pct'])} (MoM {_fm(reg['et_mom'])})\n"
            f"Bottom 3 City:\n{_fmt_bottom3(_bottom3(cities, 'et_pct'))}\n\n"
            f"*All LOS*: {_fp(reg['al_pct'])} (MoM {_fm(reg['al_mom'])})\n"
            f"Bottom 3 City:\n{_fmt_bottom3(_bottom3(cities, 'al_pct'))}"
        )
        return ReportOutput(
            kind="photo",
            content=img_city,
            filename="c3mr_city_report.png",
            caption=caption_city,
        )

    @sub_report(
        key="los",
        title="C3MR per LOS Group IndiHome Jateng-DIY",
        aliases=("los_group",),
    )
    def render_los(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        bl = data["bl_label"]
        bi = data["bi_label"]
        reg = data["region"]
        woks = data["woks"]
        closing_mode = data["is_closing_mode"]

        img2 = renderer_c3mr_los.render_c3mr_los(data, cutoff=cutoff)
        los_display = {
            "0-3 bulan": "0-3 bln (incl PSB)",
            "4-6 bulan": "4-6 bln",
            "7-12 bulan": "7-12 bln",
            "12-24 bulan": "12-24 bln",
            ">24 bulan": ">24 bln",
        }
        lines2 = [
            "📊 *C3MR per LOS IndiHome Jateng-DIY*",
            f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs {bl}"
            + (f"\n⚠️ _Bill period {bi}_" if closing_mode else ""),
            "",
        ]
        for g in calculator_c3mr.LOS_ORDER:
            key = g.replace(" ", "_").replace(">", "gt")
            pct_v = reg.get(f"los_{key}_pct")
            mom_v = reg.get(f"los_{key}_mom")
            lines2.append(f"*{los_display[g]}*: {_fp(pct_v)} (MoM {_fm(mom_v)})")
            bot3 = _bottom3(woks, f"los_{key}_pct")
            lines2.append(f"Bottom 3 WOK:\n{_fmt_bottom3(bot3)}")
            lines2.append("")

        return ReportOutput(
            kind="document",
            content=img2,
            filename="c3mr_los_report.png",
            caption="\n".join(lines2).strip(),
        )


class ReportC3MR10S(BaseReport):
    """
    /c3mr10s DD-MM-YYYY — C3MR per Customer Segment (12 segment).
    """

    name = "c3mr10s"
    title = "C3MR per Segment"
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("c3mr",)
    warn_future_date = False
    cutoff_table = "c3mr10s"
    done_private_text = "✅ Laporan C3MR per Segment sudah dikirim ke grup."

    @classmethod
    def build_rajawali_sql(cls, tgl: date, bagian: Optional[str] = "A", **kwargs) -> str:
        return buat_sql(tgl, bagian=bagian)

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan C3MR per Segment untuk {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_c3mr10s.hitung_c3mr10s(tgl)

    @sub_report(
        key="segment",
        title="C3MR by Customer Segment IndiHome Jateng-DIY",
        aliases=("main", "tabel"),
    )
    def render_segment(self, data: dict, tgl: date, cutoff: Optional[str]) -> list[ReportOutput]:
        img_buf = renderer_c3mr10s.render_c3mr10s(data, cutoff=cutoff)
        bl = data["bl_label"]
        bi = data["bi_label"]
        periode_info = f"\n⚠️ _Tgl 1-5: bill period {bi}_" if data.get("is_closing_mode") else ""

        reg_segs = data["region"]["segments"]
        total_subs = sum(int(reg_segs[s].get("subs", 0) or 0) for s in calculator_c3mr10s.SEGMENT_ORDER)

        caption = (
            f"📊 *C3MR by Segment IndiHome Jateng-DIY*\n"
            f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs {bl}{periode_info}"
        )
        det = [
            f"📊 *C3MR by Segment IndiHome Jateng-DIY* — MtD {tgl.strftime('%d-%m-%Y')}",
            "_Customer Segment : Jumlah Pelanggan | Contribusi Jumlah Pelanggan | C3MR | MoM | Unpaid_\n",
        ]
        for seg in calculator_c3mr10s.SEGMENT_ORDER:
            sm = reg_segs[seg]
            subs = int(sm.get("subs", 0) or 0)
            unpaid = int(sm.get("unpaid", 0) or 0)
            contrib = f"{subs / total_subs * 100:.1f}%" if total_subs else "-"
            pct = f"{sm['pct']:.2f}%" if sm["pct"] is not None else "-"
            mom = f"MoM {'+' if sm['mom'] > 0 else ''}{sm['mom']:.2f}%" if sm["mom"] is not None else "MoM -"
            det.append(
                f"*{calculator_c3mr10s.SEGMENT_LABEL[seg]}*: {subs:,} SSL | {contrib} | "
                f"{pct} | {mom} | Unpaid {unpaid:,} SSL"
            )
        detail_txt = "\n".join(det)

        return [
            ReportOutput(kind="photo", content=img_buf, filename="c3mr10s_report.png", caption=caption),
            ReportOutput(kind="text", content=detail_txt),
        ]

    @sub_report(
        key="paid_unpaid",
        title="Paid & Unpaid per Customer Segment",
        aliases=("paid", "seg_detail"),
        default=False,
    )
    def render_paid_unpaid(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img_buf2 = renderer_c3mr10s_seg.render_c3mr10s_segment(data, cutoff=cutoff)
        return ReportOutput(
            kind="photo",
            content=img_buf2,
            filename="c3mr10s_segment_detail.png",
            caption=f"📊 *Paid & Unpaid per Customer Segment* — MtD {tgl.strftime('%d-%m-%Y')}",
        )


def _build_c3mrnew_caption(result: dict, reg: dict, woks_list: list, label: str, tgl: date) -> str:
    bl = result["bl_label"]
    bi = result["bi_label"]
    closing_mode = result["is_closing_mode"]
    bill_order = result["bill_order"]
    bill_labels = result["bill_labels"]
    periode_info = f"\n⚠️ _Tgl 1-5: bill period {bi}_" if closing_mode else ""

    def _bottom3_bill(n):
        valid = [(w["name"], w.get(f"b{n}_pct")) for w in woks_list if w.get(f"b{n}_pct") is not None]
        valid.sort(key=lambda x: x[1])
        return valid[:3]

    lines = [
        f"📊 *{label}*",
        f"MtD {tgl.strftime('%d-%m-%Y')}  |  MoM vs {bl}{periode_info}",
        "",
    ]
    for n in bill_order:
        pct_v = reg.get(f"b{n}_pct")
        mom_v = reg.get(f"b{n}_mom")
        unp_v = reg.get(f"b{n}_unpaid", 0)
        lines.append(f"*{bill_labels[n]}*: {_fp(pct_v)} (MoM {_fm(mom_v)}) | Unpaid: {unp_v:,}")
        bot3 = _bottom3_bill(n)
        if bot3:
            lines.append("Bottom 3 WOK:")
            for w, p in bot3:
                lines.append(f"   {w} ({_fp(p)})")
        lines.append("")
    return "\n".join(lines).strip()


class ReportC3MRNew(BaseReport):
    """
    /c3mrnew DD-MM-YYYY [all|agency|unpaid] — C3MR New Sales per BILL-N (BILL-1 s/d BILL-6):
      1) all    : All Channel Jateng-DIY
      2) agency : Channel Agency Jateng-DIY
      3) unpaid : Lampiran CSV unpaid C3MR New Sales
    """

    name = "c3mrnew"
    title = "C3MR New Sales"
    date_mode = "required"
    supports_rajawali = True
    rajawali_query_keys = ("c3mr", "c3mr_u")
    cutoff_table = "c3mr"
    retry_max_tries = 3
    done_private_text = "✅ Laporan C3MR New Sales sudah dikirim ke grup."

    @classmethod
    def build_rajawali_sql(cls, tgl: date, bagian: Optional[str] = None, **kwargs) -> str:
        return buat_sql(tgl, bagian=bagian)

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        return f"⏳ Memproses laporan C3MR New Sales untuk {tgl.strftime('%d-%m-%Y')}..."

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_c3mrnew.hitung_c3mrnew(tgl)

    @sub_report(
        key="all",
        title="C3MR LoS 0-6 Bulan All Channel Jateng-DIY",
        aliases=("all_channel", "main"),
    )
    def render_all(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        title_all = "C3MR LoS 0-6 Bulan All Channel Jateng-DIY"
        result_all = {**data, "report_title": title_all}
        img1 = renderer_c3mrnew.render_c3mrnew(result_all, cutoff=cutoff)
        cap1 = _build_c3mrnew_caption(data, data["region"], data["woks"], title_all, tgl)
        return ReportOutput(
            kind="photo",
            content=img1,
            filename="c3mrnew_all.png",
            caption=cap1,
        )

    @sub_report(
        key="agency",
        title="C3MR LoS 0-6 Bulan Channel Agency Jateng-DIY",
        aliases=("ag",),
    )
    def render_agency(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        title_ag = "C3MR LoS 0-6 Bulan Channel Agency Jateng-DIY"
        result_ag = {
            **data,
            "region": data["region_ag"],
            "branches": data["branches_ag"],
            "woks": data["woks_ag"],
            "report_title": title_ag,
        }
        img2 = renderer_c3mrnew.render_c3mrnew(result_ag, cutoff=cutoff)
        cap2 = _build_c3mrnew_caption(data, data["region_ag"], data["woks_ag"], title_ag, tgl)
        return ReportOutput(
            kind="photo",
            content=img2,
            filename="c3mrnew_agency.png",
            caption=cap2,
        )

    @sub_report(
        key="unpaid",
        title="Data Unpaid C3MR New Sales (CSV)",
        aliases=("csv", "raw"),
        run_in_thread=True,
    )
    def render_unpaid(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        df_unpaid = data.get("df_unpaid")
        if df_unpaid is not None and not df_unpaid.empty:
            csv_buf = BytesIO()
            df_unpaid.to_csv(csv_buf, index=False)
            csv_buf.seek(0)
            fname = f"unpaid_c3mrnew_{tgl.strftime('%d%m%Y')}.csv"
            caption_csv = f"📎 Data unpaid C3MR New Sales per {tgl.strftime('%d-%m-%Y')} — {len(df_unpaid):,} pelanggan"
            return ReportOutput(
                kind="document",
                content=csv_buf,
                filename=fname,
                caption=caption_csv,
                parse_mode=None,
            )
        return ReportOutput(
            kind="text",
            content="ℹ️ Tidak ada data unpaid untuk periode ini.",
            parse_mode=None,
            copy_to_group=False,
        )


class ReportPayment(BaseReport):
    """
    /payment DD-MM-YYYY — Raw data payment C3MR -> CSV.
    """

    name = "payment"
    title = "Data Payment C3MR"
    date_mode = "required"
    supports_rajawali = False
    done_private_text = "✅ Data payment sudah dikirim ke grup koordinasi."

    def format_progress_message(self, tgl: Optional[date], selected_subs, extra_args) -> str:
        if tgl.day <= 5:
            tabel_bulan = (tgl - relativedelta(months=1)).strftime("%Y%m")
            info_tabel = f" _(tgl 1-5 → tabel bulan sebelumnya: {tabel_bulan})_"
        else:
            info_tabel = ""
        return f"⏳ Mengambil data payment untuk {tgl.strftime('%d-%m-%Y')}...{info_tabel}"

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        tabel_bulan = (tgl - relativedelta(months=1)).strftime("%Y%m") if tgl.day <= 5 else tgl.strftime("%Y%m")
        rows = db.query_payment(tgl)
        if not rows:
            return {
                "_abort_message": (
                    f"⚠️ Tidak ada data payment untuk tanggal "
                    f"*{tgl.strftime('%d-%m-%Y')}* di tabel "
                    f"`bwmp_c3mr_dd_{tabel_bulan}`."
                ),
            }
        return {"rows": rows, "tabel_bulan": tabel_bulan}

    @sub_report(
        key="csv",
        title="Raw Data Payment C3MR (CSV)",
        aliases=("main", "raw"),
        run_in_thread=True,
    )
    def render_csv(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        df = pd.DataFrame(data["rows"])
        csv_buf = BytesIO()
        df.to_csv(csv_buf, index=False)
        csv_buf.seek(0)
        fname = f"payment_{tgl.strftime('%d%m%Y')}.csv"
        caption = (
            f"📎 Raw data payment per {tgl.strftime('%d-%m-%Y')}\n"
            f"Tabel: `bwmp_c3mr_dd_{data['tabel_bulan']}`\n"
            f"Jumlah baris: *{len(df):,}*"
        )
        return ReportOutput(
            kind="document",
            content=csv_buf,
            filename=fname,
            caption=caption,
        )


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
):
    rep_c3mr = ReportC3MR(get_cutoff_fn=get_cutoff_fn)
    rep_10s = ReportC3MR10S(get_cutoff_fn=get_cutoff_fn)
    rep_new = ReportC3MRNew(get_cutoff_fn=get_cutoff_fn)
    rep_pay = ReportPayment()
    return (
        rep_c3mr.register(app, timeout_wrapper=timeout_wrapper),
        rep_10s.register(app, timeout_wrapper=timeout_wrapper),
        rep_new.register(app, timeout_wrapper=timeout_wrapper),
        rep_pay.register(app, timeout_wrapper=timeout_wrapper),
    )
