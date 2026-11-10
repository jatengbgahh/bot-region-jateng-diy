"""
reports/kategori_promo/command.py — Caption report Sales by Kategori Promo Paket.

Report ini tidak punya command sendiri: dikirim otomatis dari alur /closingsql
di bot.py (kirim foto + salinan ke GROUP_ID memakai _kirim_foto_retry).
"""

REPORT_TITLE = "Sales by Kategori Promo Paket IndiHome Jateng-DIY"


def build_caption(result: dict) -> str:
    return (
        f"📊 {REPORT_TITLE}\n"
        f"MtD {result['tgl_closing'].strftime('%d-%m-%Y')}  |  "
        f"MoM vs {result['bl_label']}"
    )
