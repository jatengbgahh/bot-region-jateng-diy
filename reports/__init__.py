"""
Package reports — laporan yang punya cukup banyak file pendukung (query/kalkulasi/
render/command) sehingga tidak pantas ditumpuk lepas di root, tapi juga tidak
terpakai lintas fitur seperti db.py/config.py. Tiap laporan = 1 sub-package.

Fondasi standar class report ada di `reports.base` (`BaseReport`, `SubReport`,
`ReportOutput`, `@sub_report`).

Dilengkapi `_LegacyReportModuleFinder` di `sys.meta_path` supaya kode lama atau
aplikasi pendamping (`report_pagi_csv.py`, `csv_fake_db.py`, `liveupdate_core.py`,
`c3mr_app/`, `caps_app/`, `whatsapp/`) yang masih melakukan `import calculator_xxx`
atau `import renderer_xxx` dari root tetap mendapatkan objek modul yang SAMA PERSIS
dengan `reports.<grup>.<modul>`.
"""

import importlib
import importlib.abc
import importlib.machinery
import sys

from .base import BaseReport, ReportOutput, SubReport, sub_report

LEGACY_MODULE_MAP = {
    # sf_momentum
    "calculator_5so": "reports.sf_momentum.calculator_5so",
    "calculator_7so": "reports.sf_momentum.calculator_7so",
    "renderer_5so": "reports.sf_momentum.renderer",
    # dod
    "calculator_dod": "reports.dod.calculator_dod",
    "renderer_dod": "reports.dod.renderer_dod",
    # promo
    "calculator_promo": "reports.promo.calculator_promo",
    "renderer_promo": "reports.promo.renderer_promo",
    # pdd
    "calculator_pdd": "reports.pdd.calculator_pdd",
    "renderer_pdd": "reports.pdd.renderer_pdd",
    # addon
    "calculator_addon": "reports.addon.calculator_addon",
    "renderer_addon": "reports.addon.renderer_addon",
    # klaim
    "calculator_klaim": "reports.klaim.calculator_klaim",
    "renderer_klaim": "reports.klaim.renderer_klaim",
    # dailyre
    "calculator_dailyre": "reports.dailyre.calculator_dailyre",
    "renderer_dailyre": "reports.dailyre.renderer_dailyre",
    # caps
    "calculator_caps": "reports.caps.calculator_caps",
    "calculator_caps_segment": "reports.caps.calculator_caps_segment",
    "calculator_caps_channel": "reports.caps.calculator_caps_channel",
    "calculator_caps_reason": "reports.caps.calculator_caps_reason",
    "renderer_caps": "reports.caps.renderer_caps",
    "renderer_caps_segment": "reports.caps.renderer_caps_segment",
    "renderer_caps_channel": "reports.caps.renderer_caps_channel",
    "renderer_caps_reason": "reports.caps.renderer_caps_reason",
    "renderer_caps_font": "reports.caps.renderer_caps_font",
    # c3mr
    "calculator_c3mr": "reports.c3mr.calculator_c3mr",
    "calculator_c3mr10s": "reports.c3mr.calculator_c3mr10s",
    "calculator_c3mrnew": "reports.c3mr.calculator_c3mrnew",
    "renderer_c3mr": "reports.c3mr.renderer_c3mr",
    "renderer_c3mr_los": "reports.c3mr.renderer_c3mr_los",
    "renderer_c3mr10s": "reports.c3mr.renderer_c3mr10s",
    "renderer_c3mr10s_seg": "reports.c3mr.renderer_c3mr10s_seg",
    "renderer_c3mrnew": "reports.c3mr.renderer_c3mrnew",
    # pranpc
    "calculator_pranpc": "reports.pranpc.calculator_pranpc",
    "renderer_pranpc": "reports.pranpc.renderer_pranpc",
    "pranpc_data": "reports.pranpc.pranpc_data",
    "pranpc_ref": "reports.pranpc.pranpc_ref",
    # djp_mb_sf
    "calculator_djp": "reports.djp_mb_sf.calculator_djp",
    "calculator_djp_daily": "reports.djp_mb_sf.calculator_djp_daily",
    "calculator_mb": "reports.djp_mb_sf.calculator_mb",
    "calculator_mb_daily": "reports.djp_mb_sf.calculator_mb_daily",
    "calculator_sf": "reports.djp_mb_sf.calculator_sf",
    "renderer_djp": "reports.djp_mb_sf.renderer_djp",
    "renderer_djp_daily": "reports.djp_mb_sf.renderer_djp_daily",
    "renderer_mb": "reports.djp_mb_sf.renderer_mb",
    "renderer_sf": "reports.djp_mb_sf.renderer_sf",
    # djpprio
    "calculator_djpprio": "reports.djpprio.calculator_djpprio",
    "renderer_djpprio": "reports.djpprio.renderer_djpprio",
    # performance
    "calculator_performance": "reports.performance.calculator_performance",
    "performance_browser": "reports.performance.performance_browser",
    # leads
    "leads_browser": "reports.leads.leads_browser",
    # childps
    "childps_bot": "reports.childps.childps_bot",
    "calculator_childps": "reports.childps.calculator_childps",
    "renderer_childps": "reports.childps.renderer_childps",
    "config_childps": "reports.childps.config_childps",
    "calculator_sql_woknew": "reports.childps.calculator_sql_woknew",
    # agresif
    "agresif_colors": "reports.agresif.agresif_colors",
    "agresif_data": "reports.agresif.agresif_data",
    "agresif_geocode": "reports.agresif.agresif_geocode",
    "agresif_lite": "reports.agresif.agresif_lite",
    "agresif_native": "reports.agresif.agresif_native",
    "agresif_refdata": "reports.agresif.agresif_refdata",
    "calculator_agresif": "reports.agresif.calculator_agresif",
    "renderer_agresif": "reports.agresif.renderer_agresif",
    "renderer_agresif_lite": "reports.agresif.renderer_agresif_lite",
    # wireless
    "calculator_wireless": "reports.wireless.calculator_wireless",
    "renderer_wireless": "reports.wireless.renderer_wireless",
    # closing & liveupdate
    "calculator": "reports.closing.calculator",
    "calculator_sql": "reports.closing.calculator_sql",
    "calculator_daily": "reports.closing.calculator_daily",
    "calculator_channel": "reports.closing.calculator_channel",
    "renderer": "reports.closing.renderer",
    "renderer_daily": "reports.closing.renderer_daily",
    "renderer_simple": "reports.closing.renderer_simple",
    "renderer_daily_performance": "reports.closing.renderer_daily_performance",
    "renderer_city_performance": "reports.closing.renderer_city_performance",
    "renderer_channel": "reports.closing.renderer_channel",
    "calculator_stock_alert": "reports.closing.calculator_stock_alert",
    "program_tracking": "reports.closing.program_tracking",
    # rajawali sql builders (dipindahkan ke masing-masing class report)
    "sfo_sql": "reports.sf_momentum.report",
    "c3mr_sql": "reports.c3mr.report",
    "caps_sql": "reports.caps.report",
    "childps_sql": "reports.childps.report",
    "homepass_sql": "reports.homepass.command",
    "ms_sql": "commands.market_share",
    "pagi_sql": "commands.nasional",
    "gp_control": "utils.gp_control",
}


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target_module: str):
        self.target_module = target_module

    def create_module(self, spec):
        return importlib.import_module(self.target_module)

    def exec_module(self, module):
        pass


class _LegacyReportModuleFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if path is not None:
            return None
        target_mod = LEGACY_MODULE_MAP.get(fullname)
        if not target_mod:
            return None
        return importlib.machinery.ModuleSpec(fullname, _AliasLoader(target_mod))


def install_legacy_aliases():
    if not any(isinstance(f, _LegacyReportModuleFinder) for f in sys.meta_path):
        # Taruh di akhir sys.meta_path supaya kalau file di root masih ada,
        # import normal jalan dulu; begitu file dipindah ke reports/<grup>/,
        # otomatis fallback ke modul di reports.<grup>.<modul>.
        sys.meta_path.append(_LegacyReportModuleFinder())


install_legacy_aliases()

__all__ = ["BaseReport", "ReportOutput", "SubReport", "sub_report", "install_legacy_aliases"]
