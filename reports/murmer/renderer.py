"""
reports/murmer/renderer.py — Render tabel PNG untuk /murmer.

Layout PERSIS port dari skrip standalone murmer.py (generate_image), mengikuti
sheet 'rekap' Excel: title navy, header 2 baris merge, data polos + gradasi
warna ACH YTD. Bedanya cuma hasilnya BytesIO (dikirim langsung ke Telegram),
bukan file PNG di disk.
"""

import sys
from datetime import date
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd

from .calculator import ach_color

C_NAVY = "#263D54"   # warna header sesuai Excel (dark navy + 10% tint)
C_WHITE = "#FFFFFF"
C_BORDER = "#263D54"

COL_W = {
    "REGION": 2.4,
    "TARGET": 0.9,
    "D_IO": 0.55, "D_RE": 0.55, "D_PS": 0.55,
    "MTD_IO": 0.55, "MTD_RE": 0.55, "MTD_PS": 0.55,
    "YTD_IO": 0.55, "YTD_RE": 0.55, "YTD_PS": 0.55,
    "ACH_YTD": 1.0,
}


def render_murmer(df: pd.DataFrame, cutoff: date) -> BytesIO:
    x_pos = {}
    x = 0.15
    for col in COL_W:
        x_pos[col] = x
        x += COL_W[col]
    table_x0 = 0.15
    table_x1 = x
    total_w = x + 0.15

    row_h = 0.32
    title_h = 0.42
    n_data = len(df)
    fig_h = 0.1 + title_h + row_h * 2 + n_data * row_h + 0.15

    fig, ax = plt.subplots(figsize=(total_w, fig_h))
    ax.set_xlim(0, total_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    top = fig_h - 0.1

    # --- Title bar (navy, full table width) ---
    ax.add_patch(Rectangle((table_x0, top - title_h), table_x1 - table_x0, title_h,
                           lw=1.2, edgecolor=C_BORDER, facecolor=C_NAVY))
    ax.text((table_x0 + table_x1) / 2, top - title_h / 2,
            f"Report Eznet Wireless Murmer | {cutoff.strftime('%d-%b-%y')}",
            ha="center", va="center", fontsize=12, fontweight="bold", color="white")

    header_y = top - title_h
    data_top = header_y - row_h * 2  # y bawah header row 2

    day_label = (cutoff.strftime("%-d-%b-%y") if sys.platform != "win32"
                 else cutoff.strftime("%#d-%b-%y"))
    mtd_label = f"MTD {cutoff.strftime('%b').upper()}"

    # --- Header Row 1 ---
    sections = [
        ("REGION",  x_pos["REGION"],  COL_W["REGION"],  True),
        ("TARGET",  x_pos["TARGET"],  COL_W["TARGET"],  True),
        (day_label, x_pos["D_IO"],    COL_W["D_IO"] + COL_W["D_RE"] + COL_W["D_PS"], False),
        (mtd_label, x_pos["MTD_IO"],  COL_W["MTD_IO"] + COL_W["MTD_RE"] + COL_W["MTD_PS"], False),
        ("YTD",     x_pos["YTD_IO"],  COL_W["YTD_IO"] + COL_W["YTD_RE"] + COL_W["YTD_PS"], False),
        ("ACH YTD", x_pos["ACH_YTD"], COL_W["ACH_YTD"], True),
    ]

    for label, xpos, width, merge in sections:
        h = row_h * 2 if merge else row_h
        y = header_y - h
        ax.add_patch(Rectangle((xpos, y), width, h,
                               lw=1.0, edgecolor="white", facecolor=C_NAVY))
        text_y = header_y - row_h if merge else header_y - row_h / 2
        ax.text(xpos + width / 2, text_y, label,
                ha="center", va="center", fontsize=9, fontweight="bold", color="white")

    # --- Header Row 2: IO / RE / PS ---
    for col_group in [["D_IO", "D_RE", "D_PS"],
                      ["MTD_IO", "MTD_RE", "MTD_PS"],
                      ["YTD_IO", "YTD_RE", "YTD_PS"]]:
        for col in col_group:
            ax.add_patch(Rectangle((x_pos[col], data_top), COL_W[col], row_h,
                                   lw=1.0, edgecolor="white", facecolor=C_NAVY))
            ax.text(x_pos[col] + COL_W[col] / 2, data_top + row_h / 2,
                    col.split("_")[1], ha="center", va="center",
                    fontsize=8, fontweight="bold", color="white")

    # --- Data rows (putih polos + border tipis, seperti Excel) ---
    ach_min = df["ACH_YTD"].min()
    ach_max = df["ACH_YTD"].max()

    for ri, row in df.iterrows():
        y0 = data_top - (ri + 1) * row_h

        ax.add_patch(Rectangle((x_pos["REGION"], y0), COL_W["REGION"], row_h,
                               lw=0.6, edgecolor="#BBBBBB", facecolor=C_WHITE))
        ax.text(x_pos["REGION"] + COL_W["REGION"] / 2, y0 + row_h / 2, row["REGION"],
                ha="center", va="center", fontsize=8, fontweight="bold", color="#222")

        ax.add_patch(Rectangle((x_pos["TARGET"], y0), COL_W["TARGET"], row_h,
                               lw=0.6, edgecolor="#BBBBBB", facecolor=C_WHITE))
        ax.text(x_pos["TARGET"] + COL_W["TARGET"] / 2, y0 + row_h / 2, f"{int(row['TARGET']):,}",
                ha="center", va="center", fontsize=8, color="#222")

        for col in ["D_IO", "D_RE", "D_PS",
                    "MTD_IO", "MTD_RE", "MTD_PS",
                    "YTD_IO", "YTD_RE", "YTD_PS"]:
            ax.add_patch(Rectangle((x_pos[col], y0), COL_W[col], row_h,
                                   lw=0.6, edgecolor="#BBBBBB", facecolor=C_WHITE))
            ax.text(x_pos[col] + COL_W[col] / 2, y0 + row_h / 2, f"{int(row[col])}",
                    ha="center", va="center", fontsize=8, color="#222")

        ach_bg = ach_color(row["ACH_YTD"], ach_min, ach_max)
        ax.add_patch(Rectangle((x_pos["ACH_YTD"], y0), COL_W["ACH_YTD"], row_h,
                               lw=0.6, edgecolor="#BBBBBB", facecolor=ach_bg))
        ax.text(x_pos["ACH_YTD"] + COL_W["ACH_YTD"] / 2, y0 + row_h / 2,
                f"{row['ACH_YTD']:.2f}%",
                ha="center", va="center", fontsize=8, fontweight="bold", color="#333")

    table_y0 = data_top - n_data * row_h
    ax.add_patch(Rectangle((table_x0, table_y0), table_x1 - table_x0, top - table_y0,
                           lw=1.5, edgecolor=C_BORDER, facecolor="none"))

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
