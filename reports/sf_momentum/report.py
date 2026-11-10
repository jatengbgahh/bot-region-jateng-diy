"""
reports/sf_momentum/report.py — Implementasi Report5SO (/5so) dan Report7SO (/7so)
menggunakan BaseReport & SubReport.

Fitur yang otomatis didapat dari BaseReport:
  • /5so [DD-MM-YYYY]               -> kirim gambar 5SO Scorecard (kosong = H-1)
  • /7so [DD-MM-YYYY]               -> kirim gambar 7SO Scorecard + Excel SF Belum RE MTD + Excel per SF + RAW
  • /7so [DD-MM-YYYY] scorecard     -> hanya kirim gambar 7SO Scorecard
  • /7so [DD-MM-YYYY] belum_re      -> hanya kirim Excel SF Belum RE MTD (alias: excel, tidak_aktif)
  • /7so [DD-MM-YYYY] raw           -> hanya kirim Excel "5SO 7SO per SF + RAW" (alias: per_sf, persf)
  • /5so help  /  /7so help         -> tampilkan daftar sub-report & cara pakai
"""

from datetime import date, timedelta
from typing import Callable, Optional

from dateutil.relativedelta import relativedelta

from reports.base import BaseReport, ReportOutput, sub_report
from . import calculator_5so, calculator_7so, sf_rules
from .renderer import render_5so


def periode(tgl: date) -> dict:
    awal = tgl.replace(day=1)
    lm_awal = awal - relativedelta(months=1)
    lm_akhir = min(lm_awal + relativedelta(day=tgl.day), awal - timedelta(days=1))
    return {"ini": (awal, tgl), "lalu": (lm_awal, lm_akhir)}


def buat_sql(
    tgl: date,
    dengan_ordering: bool = False,
    dengan_djp_ini: bool = False,
    sf_ini_fallback: bool = False,
) -> str:
    """Bangun query SQL Rajawali untuk /5so dan /7so (sf_ini, sf_lalu, djp_lalu).

    sf_ini follows sf_rules.SF_SNAPSHOT_SOURCE_MONTH: for an overridden report month (Nov 2026)
    the rows are read from the source month table (database_sf_202610). The report date is later
    than every event_date in that table, so MAX(event_date) <= report date = its LAST snapshot
    (end of October). The rows are still exported under the sf_ini label, so csv_fake_db loads
    them as database_sf_<report month> and the calculator reads them without another redirect.
    Dummy SF are filtered in Python (calculator_5so), not in this SQL.
    """
    p = periode(tgl)
    f = lambda d: d.strftime("%Y%m")
    iso = lambda d: d.strftime("%Y-%m-%d")
    bagian = []
    for k in ("ini", "lalu"):
        a, b = p[k]
        ym = f(a)
        ym_sf = f(p["lalu"][0]) if (k == "ini" and sf_ini_fallback) else ym
        if k == "ini":
            ym_sf = sf_rules.sf_source_month(ym_sf)      # SF Registered snapshot override
        bagian.append(
            f"SELECT 'sf_{k}' AS q, JSON_ARRAY(kode, nama, wok, region, status, event_date) AS j "
            f"FROM database_sf_{ym_sf} WHERE region = 'JATENG-DIY' AND status = 'ACTIVE' "
            f"AND event_date = (SELECT MAX(event_date) FROM database_sf_{ym_sf} WHERE event_date <= '{iso(b)}')"
        )
        akhir_excl = iso(b + timedelta(days=1))
        if dengan_ordering:
            bagian.append(
                f"SELECT 'ord_{k}' AS q, JSON_ARRAY(order_id, sf_code, sf_name, kabupaten, event_date, region, order_type, "
                f"channel_group, product_commercial_name, ps_ts, re_ts) AS j "
                f"FROM indihome_ordering_detail_{ym} WHERE region LIKE 'JATENG%' AND order_type = 'NEW SALES' "
                f"AND UPPER(TRIM(channel_group)) = 'AGENCY' "
                f"AND (product_commercial_name NOT LIKE '%WIRELESS%' OR product_commercial_name IS NULL) "
                f"AND ((ps_ts >= '{iso(a)}' AND ps_ts < '{akhir_excl}') OR (re_ts >= '{iso(a)}' AND re_ts < '{akhir_excl}'))"
            )
        if k == "lalu" or dengan_djp_ini:
            bagian.append(
                f"SELECT 'djp_{k}' AS q, JSON_ARRAY(user_code, wok, odp_name, tugas_date, regional) AS j "
                f"FROM djp_daily_user_detailed_{ym} WHERE regional LIKE 'JATENG%' "
                f"AND tugas_date BETWEEN '{iso(a)}' AND '{iso(b)}'"
            )
    return "\nUNION ALL\n".join(bagian)


def _build_scorecard_caption(title: str, result: dict, tgl: date) -> str:
    reg = result["rows"][0]
    brs = [r for r in result["rows"] if r["kind"] == "br"]
    basis = result["basis"]
    caption = (
        f"📊 *{title}*\n"
        f"MTD {tgl.strftime('%d-%m-%Y')} vs M1 {result['lm_akhir'].strftime('%d-%m-%Y')}\n\n"
        f"Jateng-DIY: *{reg['skor']}/{result['n_metrics']} {reg['status']}*\n"
        f"SF Aktif {basis} *{reg['sf_aktif_mtd']:,}* | SF Produktif *{reg['sf_prod_mtd']:,}* | "
        f"Produktivitas *{reg['prod_mtd'] or 0:.1f}*\n\n"
        + "\n".join(f"• {b['name']}: {b['skor']}/{result['n_metrics']} {b['status']}" for b in brs)
    )
    if result.get("sf_note"):
        caption += f"\n\nℹ️ {result['sf_note']}."
    djp_last = result.get("djp_last")
    if djp_last is None or (tgl - djp_last).days > 1:
        caption += (
            f"\n\n⚠️ Data DJP bulan ini baru s/d "
            f"{djp_last.strftime('%d-%m-%Y') if djp_last else '-'} — "
            f"metrik DJP (SF Aktif DJP, ODP Visited) belum valid."
        )
    return caption


class Report5SO(BaseReport):
    """
    /5so [DD-MM-YYYY] — SF Momentum basis PS (AGENCY) per Region/Branch/WOK baru:
    6 metrik M1 vs MTD + Momentum Skor & Status. Kosong = H-1.
    """

    name = "5so"
    title = "5SO Scorecard"
    date_mode = "optional"
    default_date_offset = 1
    source_type = "mysql_vpn"
    supports_rajawali = True
    rajawali_query_keys = ("sfo", "iod_*")
    cutoff_table = "ordering detail"
    eta_hint = "±3 menit"
    copy_to_group = True
    notify_done_in_private = True

    @classmethod
    def build_rajawali_sql(
        cls,
        tgl: date,
        dengan_ordering: bool = False,
        dengan_djp_ini: bool = False,
        sf_ini_fallback: bool = False,
        **kwargs,
    ) -> str:
        return buat_sql(
            tgl,
            dengan_ordering=dengan_ordering,
            dengan_djp_ini=dengan_djp_ini,
            sf_ini_fallback=sf_ini_fallback,
        )

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_5so.hitung_5so(tgl)

    @sub_report(
        key="scorecard",
        title="5SO Scorecard Jateng-DIY (SF Momentum basis PS)",
        aliases=("main", "tabel"),
        run_in_thread=True,
    )
    def render_scorecard(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        img_buf = render_5so(data, cutoff)
        caption = _build_scorecard_caption(self.title, data, tgl)
        return ReportOutput(
            kind="photo",
            content=img_buf,
            filename=f"sf_momentum_{self.name}.png",
            caption=caption,
        )


class Report7SO(Report5SO):
    """
    /7so [DD-MM-YYYY] — 7SO Scorecard basis RE (AGENCY): 7 metrik (SF Aktif DJP, ODP Visit,
    DJP/SF/Day, SF Aktif, SF Produktif, Produktivitas, SF Registered) + Excel SF Belum RE MTD.
    """

    name = "7so"
    title = "7SO Scorecard Jateng-DIY"

    def fetch_data(self, tgl: date, selected_subs: set[str], extra_args: list[str]) -> dict:
        return calculator_7so.hitung_7so(tgl)

    @sub_report(
        key="scorecard",
        title="7SO Scorecard Jateng-DIY (SF Momentum basis RE)",
        aliases=("main", "tabel"),
        run_in_thread=True,
    )
    def render_scorecard(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        return super().render_scorecard(data, tgl, cutoff)

    @sub_report(
        key="belum_re",
        title="SF Belum RE MTD (Excel, termasuk yang belum RE M1)",
        aliases=("excel", "tidak_aktif"),
        run_in_thread=True,
        error_label="export SF Tidak Aktif RE",
    )
    def render_belum_re(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        xlsx, fname, rows = calculator_7so.export_sf_tidak_aktif(data)
        reg = data["rows"][0]
        bln = calculator_7so._BULAN[tgl.month - 1]
        per_wok = rows.groupby("WOK", sort=False).size()
        caption = (
            f"SF Registered: *{reg['sf_reg_mtd']:,} SF*\n"
            f"SF Aktif RE Mtd {bln}: *{reg['sf_aktif_mtd']:,} SF*\n"
            f"SF Belum RE Mtd {bln}: *{len(rows):,} SF*\n\n"
            + "\n".join(f"• {w}: {n}" for w, n in per_wok.items())
        )
        return ReportOutput(
            kind="document",
            content=xlsx,
            filename=fname,
            caption=caption,
        )

    @sub_report(
        key="raw",
        title="5SO 7SO per SF + RAW (Excel, dengan Team Leader)",
        aliases=("per_sf", "persf"),
        run_in_thread=True,
        error_label="export 5SO 7SO per SF + RAW",
    )
    def render_raw(self, data: dict, tgl: date, cutoff: Optional[str]) -> ReportOutput:
        from . import raw_export

        gambar = {"7SO": (render_5so(data, cutoff), _build_scorecard_caption(self.title, data, tgl))}
        try:                                    # 5SO hanya untuk sheet GAMBAR 5SO; gagal -> sheet tanpa gambar
            d5 = calculator_5so.hitung_5so(tgl)
            gambar["5SO"] = (render_5so(d5, cutoff), _build_scorecard_caption(Report5SO.title, d5, tgl))
        except Exception as e:
            calculator_5so.db.logger.warning(f"5SO untuk sheet GAMBAR 5SO gagal: {e}")
        xlsx, fname, info = raw_export.build_excel(tgl, gambar)
        caption = (
            f"5SO 7SO per SF + RAW {tgl.strftime('%d-%m-%Y')}\n"
            f"SF per SF: *{info['n_sf']:,}* | RAW PS *{info['n_ps']:,}* | RAW RE *{info['n_re']:,}* | "
            f"RAW DJP *{info['n_djp']:,}*"
        )
        return ReportOutput(kind="document", content=xlsx, filename=fname, caption=caption)


def register_handlers(
    app,
    timeout_wrapper: Optional[Callable] = None,
    get_cutoff_fn: Optional[Callable] = None,
):
    """
    Daftarkan command /5so dan /7so ke aplikasi Telegram.
    Return (cmd_5so, cmd_7so) supaya bisa dipakai scheduler (JADWAL_LAPORAN) & report_pagi_csv.py.
    """
    rep_5so = Report5SO(get_cutoff_fn=get_cutoff_fn)
    rep_7so = Report7SO(get_cutoff_fn=get_cutoff_fn)
    cmd_5so = rep_5so.register(app, timeout_wrapper=timeout_wrapper)
    cmd_7so = rep_7so.register(app, timeout_wrapper=timeout_wrapper)
    return cmd_5so, cmd_7so
