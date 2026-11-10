"""
renderer.py — Render tabel monitoring RE ke gambar PNG
Struktur: Region → Branch (semua) → WOK (semua)
v3: compact rows, bar untuk %Hourly & %FD, kolom Rank
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import textwrap
from io import BytesIO
from datetime import datetime
from config import REPORT_TITLE

# ── Warna ─────────────────────────────────────────────────────────────────────
C_HEADER_DARK  = "#2C1810"
C_HEADER_MID   = "#8B2500"
C_HEADER_LIGHT = "#C0392B"
C_HEADER_ACH   = "#E8D5A3"
C_HEADER_RANK  = "#2C3E50"
C_REGION_BG    = "#2C3E50"
C_SECTION_BG   = "#D5D8DC"
C_BRANCH_ROW   = "#FBEEE6"
C_WOK_ODD      = "#FFFFFF"
C_WOK_EVEN     = "#FAFAFA"
C_NEG_BG       = "#FADBD8"
C_POS_BG       = "#D5F5E3"
C_NEG_TEXT     = "#C0392B"
C_POS_TEXT     = "#1E8449"
C_ACH_BAR      = "#F39C12"
C_ACH_FILL     = "#FEF9E7"
C_NEG_BAR      = "#F1948A"
C_POS_BAR      = "#82E0AA"
C_BAR_FILL     = "#F2F3F4"
C_TEXT_MAIN    = "#1A1A1A"
C_TEXT_LIGHT   = "#FFFFFF"
C_TEXT_MID     = "#2C3E50"
C_GRID         = "#D5D8DC"

# ── Warna tabel Perbandingan D-7 (kanan) ───────────────────────────────────────
C_H7_HEADER_DARK  = "#1B4F72"
C_H7_HEADER_LIGHT = "#2E86C1"


def _fmt_pct(val) -> str:
    if val is None:
        return "-"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.0f}%"


def _fmt_gap(val) -> str:
    if val is None or val == 0:
        return "-"
    if val > 0:
        return str(val)
    return f"({abs(val)})"


def _fmt_num(val) -> str:
    if val is None:
        return "-"
    return str(int(val))


def _add_rankings(branches, woks):
    """Tambah field 'rank' ke setiap branch dan WOK berdasarkan pct_ach."""
    def rank_list(rows):
        scored = [(i, r) for i, r in enumerate(rows) if r.get("pct_ach") is not None]
        scored.sort(key=lambda x: x[1]["pct_ach"], reverse=True)
        rank_map = {}
        for rank, (i, _) in enumerate(scored, 1):
            rank_map[i] = rank
        for i, r in enumerate(rows):
            r["rank"] = rank_map.get(i, None)

    rank_list(branches)
    rank_list(woks)


def render_tabel(data: dict, source: str = "kpro", cutoff: str = None) -> BytesIO:
    region   = data["region"]
    branches = data["branches"]
    woks     = data["woks"]
    ts       = data["upload_time"]
    mode     = data.get("mode", "hourly")
    hari_ini = data.get("hari_ini")

    # Tambah ranking
    _add_rankings(branches, woks)

    # Jumlah baris: 1 region + 1 section + N branch + 1 section + N wok
    n_rows = 1 + 1 + len(branches) + 1 + len(woks)

    ROW_H   = 0.22   # lebih compact
    HEAD_H  = 0.70
    TITLE_H = 0.45
    PAD     = 0.12
    fig_h   = TITLE_H + HEAD_H + n_rows * ROW_H + PAD * 2

    # Kolom: Territory | Target | D-1FD | D-1Hourly | D | %Hourly | GapHourly | %FD | GapFD | %Ach | Rank
    COL_W = [2.5, 0.55, 0.55, 0.68, 0.55, 0.75, 0.68, 0.75, 0.58, 0.72, 0.40]

    # ── Tabel ke-2: Perbandingan H-1 (D-7 FD | D-7 Hourly | % Hourly) ──────
    has_table2 = "d7_fd" in region
    GAP2       = 0.5
    COL_W2     = [0.68, 0.78, 0.75]

    fig_w = sum(COL_W) + (GAP2 + sum(COL_W2) if has_table2 else 0) + 0.3

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    xs = [0.15]
    for w in COL_W[:-1]:
        xs.append(xs[-1] + w)

    def cx(col_idx):
        return xs[col_idx] + COL_W[col_idx] / 2

    xs2 = [xs[-1] + COL_W[-1] + GAP2]
    for w in COL_W2[:-1]:
        xs2.append(xs2[-1] + w)

    def cx2(col_idx):
        return xs2[col_idx] + COL_W2[col_idx] / 2

    # ── Judul ─────────────────────────────────────────────────────────────
    ax.text(0.15, fig_h - 0.15, REPORT_TITLE,
            fontsize=10, fontweight="bold", color=C_TEXT_MID, va="top")
    subtitle = (
        f"Closing {hari_ini.strftime('%d-%m-%Y')}"
        if mode == "closing" and hari_ini else
        f"Update {ts.strftime('%d-%m-%Y %H.%M')}"
    )
    ax.text(0.15, fig_h - 0.32, subtitle,
            fontsize=7.5, color="#7F8C8D", va="top")

    # ── Header ────────────────────────────────────────────────────────────
    y0_head = fig_h - TITLE_H - HEAD_H
    h1 = HEAD_H * 0.46
    h2 = HEAD_H - h1

    def hcell(x, y, w, h, text, bg, fg=C_TEXT_LIGHT, fs=7.5):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w/2, y + h/2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3)

    hcell(xs[0], y0_head, COL_W[0], HEAD_H, "TERRITORY",  C_HEADER_DARK, fs=8.5)
    hcell(xs[1], y0_head, COL_W[1], HEAD_H, "Target\nRE", C_HEADER_DARK, fs=7)

    w_real = COL_W[2] + COL_W[3] + COL_W[4]
    hcell(xs[2], y0_head + h2, w_real, h1, "Realisasi RE", C_HEADER_MID, fs=8)
    hcell(xs[2], y0_head, COL_W[2], h2, "D-1\nFD",     C_HEADER_MID, fs=6)
    hcell(xs[3], y0_head, COL_W[3], h2, "D-1\nHourly", C_HEADER_MID, fs=6)
    hcell(xs[4], y0_head, COL_W[4], h2, "D",           C_HEADER_MID, fs=6.5)

    w_dod = COL_W[5] + COL_W[6] + COL_W[7] + COL_W[8]
    hcell(xs[5], y0_head + h2, w_dod, h1, "DoD", C_HEADER_LIGHT, fs=8)
    hcell(xs[5], y0_head, COL_W[5], h2, "% Hourly",   C_HEADER_LIGHT, fs=6)
    hcell(xs[6], y0_head, COL_W[6], h2, "Gap Hourly", C_HEADER_LIGHT, fs=6)
    hcell(xs[7], y0_head, COL_W[7], h2, "% FD",       C_HEADER_LIGHT, fs=6)
    hcell(xs[8], y0_head, COL_W[8], h2, "Gap FD",     C_HEADER_LIGHT, fs=6)

    hcell(xs[9],  y0_head, COL_W[9],  HEAD_H, "%Ach\nRE",  C_HEADER_ACH, fg="#4A3000", fs=7)
    hcell(xs[10], y0_head, COL_W[10], HEAD_H, "Rank",       C_HEADER_RANK, fs=7)

    ax.add_patch(plt.Rectangle((xs[0], y0_head), sum(COL_W), HEAD_H,
                                fill=False, edgecolor=C_GRID, linewidth=0.5, zorder=4))

    # ── Garis pembatas antar kolom header (tabel utama) ─────────────────────
    def hdiv(x, y_bottom, y_top):
        ax.plot([x, x], [y_bottom, y_top], color="white",
                linewidth=0.7, alpha=0.55, zorder=5)

    FULL_H_BOUNDS = {1, 2, 5, 9, 10}   # batas antar kolom mandiri (bukan sub-kolom grup)
    for i in range(1, len(COL_W)):
        if i in FULL_H_BOUNDS:
            hdiv(xs[i], y0_head, y0_head + HEAD_H)
        else:
            hdiv(xs[i], y0_head, y0_head + h2)

    # ── Header tabel ke-2: Perbandingan D-7 ─────────────────────────────────
    if has_table2:
        hcell(xs2[0], y0_head + h2, sum(COL_W2), h1, "Perbandingan D-7", C_H7_HEADER_DARK, fs=8)
        hcell(xs2[0], y0_head, COL_W2[0], h2, "D-7 FD",     C_H7_HEADER_LIGHT, fs=6.5)
        hcell(xs2[1], y0_head, COL_W2[1], h2, "D-7 Hourly", C_H7_HEADER_LIGHT, fs=6.5)
        hcell(xs2[2], y0_head, COL_W2[2], h2, "% Hourly",   C_H7_HEADER_LIGHT, fs=6.5)

        ax.add_patch(plt.Rectangle((xs2[0], y0_head), sum(COL_W2), HEAD_H,
                                    fill=False, edgecolor=C_GRID, linewidth=0.5, zorder=4))

        for i in range(1, len(COL_W2)):
            hdiv(xs2[i], y0_head, y0_head + h2)

    cur_y = y0_head

    # ── Section header ────────────────────────────────────────────────────
    def draw_section(label):
        nonlocal cur_y
        sh = ROW_H * 0.8
        cur_y -= sh
        ax.add_patch(plt.Rectangle((xs[0], cur_y), sum(COL_W), sh,
                                   color=C_SECTION_BG, zorder=1))
        ax.text(xs[0] + 0.15, cur_y + sh/2, label,
                ha="left", va="center", fontsize=7.5, fontweight="bold",
                color=C_TEXT_MID, zorder=3)
        ax.plot([xs[0], xs[0] + sum(COL_W)], [cur_y, cur_y],
                color=C_GRID, linewidth=0.4, zorder=5)

    # ── Baris data ────────────────────────────────────────────────────────
    def draw_row(r, bg, text_col, fs=7.0, bold=False):
        nonlocal cur_y
        cur_y -= ROW_H
        ax.add_patch(plt.Rectangle((xs[0], cur_y), sum(COL_W), ROW_H,
                                   color=bg, zorder=1))

        def cell(col, text, color=None, ha="center"):
            ax.text(cx(col), cur_y + ROW_H/2, text,
                    ha=ha, va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal",
                    color=color or text_col, zorder=3)

        def gap_cell(col, text, val):
            """Cell dengan background merah/hijau untuk Gap"""
            if val is None:
                cell(col, text)
                return
            if val > 0:
                bg_c, fg_c = C_POS_BG, C_POS_TEXT
            elif val < 0:
                bg_c, fg_c = C_NEG_BG, C_NEG_TEXT
            else:
                cell(col, text)
                return
            ax.add_patch(plt.Rectangle(
                (xs[col] + 0.03, cur_y + 0.03),
                COL_W[col] - 0.06, ROW_H - 0.06,
                color=bg_c, zorder=2))
            ax.text(cx(col), cur_y + ROW_H/2, text,
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold", color=fg_c, zorder=3)

        def pct_bar_at(x0, w0, cx0, val):
            """Bar % generik — merah jika negatif, hijau jika positif"""
            if val is None:
                ax.text(cx0, cur_y + ROW_H/2, "-",
                        ha="center", va="center", fontsize=fs, color=text_col, zorder=3)
                return
            bar_w  = w0 - 0.12
            bar_h  = ROW_H * 0.36
            bx     = x0 + 0.06
            by     = cur_y + (ROW_H - bar_h) / 2
            center = bx + bar_w / 2

            # Background bar
            ax.add_patch(plt.Rectangle((bx, by), bar_w, bar_h,
                                       color=C_BAR_FILL, zorder=2))

            # Fill dari tengah ke kanan (positif) atau kiri (negatif)
            bar_col = C_POS_BAR if val >= 0 else C_NEG_BAR
            max_pct = 100.0
            fill_w  = min(abs(val) / max_pct, 1.0) * (bar_w / 2)

            if val >= 0:
                ax.add_patch(plt.Rectangle((center, by), fill_w, bar_h,
                                           color=bar_col, zorder=3))
            else:
                ax.add_patch(plt.Rectangle((center - fill_w, by), fill_w, bar_h,
                                           color=bar_col, zorder=3))

            # Garis tengah
            ax.plot([center, center], [by, by + bar_h],
                    color="#AAAAAA", linewidth=0.4, zorder=4)

            # Teks % — hitam agar lebih jelas
            sign = "+" if val > 0 else ""
            ax.text(cx0, cur_y + ROW_H/2,
                    f"{sign}{val:.0f}%",
                    ha="center", va="center", fontsize=fs - 0.5,
                    fontweight="bold",
                    color="#1A1A1A",
                    zorder=5)

        def pct_bar(col, val):
            """Bar untuk %Hourly dan %FD — merah jika negatif, hijau jika positif"""
            pct_bar_at(xs[col], COL_W[col], cx(col), val)

        def ach_bar(col, pct):
            """Progress bar untuk %Ach"""
            if pct is None:
                cell(col, "-")
                return
            bar_w = COL_W[col] - 0.12
            bar_h = ROW_H * 0.36
            bx    = xs[col] + 0.06
            by    = cur_y + (ROW_H - bar_h) / 2
            ax.add_patch(plt.Rectangle((bx, by), bar_w, bar_h,
                                       color=C_ACH_FILL, zorder=2))
            fill = min(pct / 100, 1.0) * bar_w
            if fill > 0:
                ax.add_patch(plt.Rectangle((bx, by), fill, bar_h,
                                           color=C_ACH_BAR, zorder=3))
            ax.text(bx + bar_w/2, cur_y + ROW_H/2,
                    f"{pct:.0f}%",
                    ha="center", va="center", fontsize=fs - 0.5,
                    fontweight="bold", color="#5D4000", zorder=4)

        def rank_cell(col, rank):
            if rank is None:
                return
            ax.text(cx(col), cur_y + ROW_H/2, str(rank),
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold", color=C_TEXT_MID, zorder=3)

        # Col 0: nama territory
        ax.text(xs[0] + 0.12, cur_y + ROW_H/2,
                r.get("name", ""), ha="left", va="center",
                fontsize=fs, fontweight="bold" if bold else "normal",
                color=text_col, zorder=3)

        cell(1, _fmt_num(r["target"]))
        cell(2, _fmt_num(r["d1_fd"]))
        cell(3, _fmt_num(r["d1_hourly"]))
        cell(4, _fmt_num(r["d"]))
        pct_bar(5, r["pct_hourly"])
        gap_cell(6, _fmt_gap(r["gap_hourly"]), r["gap_hourly"])
        pct_bar(7, r["pct_fd"])
        gap_cell(8, _fmt_gap(r["gap_fd"]), r["gap_fd"])
        ach_bar(9, r["pct_ach"])
        rank_cell(10, r.get("rank"))

        ax.plot([xs[0], xs[0] + sum(COL_W)], [cur_y, cur_y],
                color=C_GRID, linewidth=0.25, zorder=5)

        # ── Tabel ke-2: Perbandingan H-1 (D-7 FD | D-7 Hourly | % Hourly) ──
        if has_table2:
            ax.add_patch(plt.Rectangle((xs2[0], cur_y), sum(COL_W2), ROW_H,
                                       color=bg, zorder=1))
            ax.text(cx2(0), cur_y + ROW_H/2, _fmt_num(r.get("d7_fd")),
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal", color=text_col, zorder=3)
            ax.text(cx2(1), cur_y + ROW_H/2, _fmt_num(r.get("d7_hourly")),
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal", color=text_col, zorder=3)
            pct_bar_at(xs2[2], COL_W2[2], cx2(2), r.get("pct_d7_hourly"))
            ax.plot([xs2[0], xs2[0] + sum(COL_W2)], [cur_y, cur_y],
                    color=C_GRID, linewidth=0.25, zorder=5)

    # ── Render baris ──────────────────────────────────────────────────────
    draw_section("Region")
    region["rank"] = None
    draw_row(region, C_REGION_BG, C_TEXT_LIGHT, fs=7.5, bold=True)

    draw_section("Branch")
    for br in branches:
        draw_row(br, C_BRANCH_ROW, C_TEXT_MAIN, fs=7.0, bold=True)

    draw_section("WOK")
    for i, wok in enumerate(woks):
        bg = C_WOK_ODD if i % 2 == 0 else C_WOK_EVEN
        draw_row(wok, bg, C_TEXT_MAIN, fs=6.8)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, y0_head],
                color=C_GRID, linewidth=0.3, zorder=5)
    ax.plot([xs[-1] + COL_W[-1], xs[-1] + COL_W[-1]],
            [cur_y, y0_head], color=C_GRID, linewidth=0.3, zorder=5)

    # Border luar
    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), sum(COL_W), y0_head - cur_y + HEAD_H,
        fill=False, edgecolor="#7F8C8D", linewidth=0.8, zorder=6))

    # ── Grid & border tabel ke-2 ─────────────────────────────────────────
    if has_table2:
        for x in xs2:
            ax.plot([x, x], [cur_y, y0_head],
                    color=C_GRID, linewidth=0.3, zorder=5)
        ax.plot([xs2[-1] + COL_W2[-1], xs2[-1] + COL_W2[-1]],
                [cur_y, y0_head], color=C_GRID, linewidth=0.3, zorder=5)

        ax.add_patch(plt.Rectangle(
            (xs2[0], cur_y), sum(COL_W2), y0_head - cur_y + HEAD_H,
            fill=False, edgecolor="#7F8C8D", linewidth=0.8, zorder=6))

        footer2 = (
            "*D-7 FD: closing 7 hari lalu (full day) | "
            "*D-7 Hourly: RE 7 hari lalu s/d jam yg sama | "
            "*% Hourly: D vs D-7 Hourly (jam yg sama)"
        )
        footer2_wrapped = textwrap.fill(footer2, width=int(sum(COL_W2) / 0.028))
        ax.text(xs2[0], cur_y - 0.05, footer2_wrapped,
                fontsize=4.6, color="#95A5A6", va="top", style="italic",
                linespacing=1.4)

    # Catatan kaki
    if source == "hadoop":
        footer = (
            "*D-1 FD: closing kemarin (full day)  |  "
            "*D-1 Hourly: RE kemarin s/d jam yang sama  |  "
            "**Sumber: Hadoop IndiHome_Ordering_Detail"
        )
    elif source == "sql":
        footer = (
            "*D-1 FD: closing kemarin (full day)  |  "
            "*D-1 Hourly: RE kemarin s/d jam yang sama  |  "
            "**Sumber: Rajawali dashboard_hourly_sales (WOK baru)"
        )
    elif source == "ordering":
        footer = (
            "*D-1 FD: closing kemarin (full day)  |  "
            "*D-1 Hourly: RE kemarin s/d jam yang sama  |  "
            "**Sumber: Rajawali indihome_ordering_detail"
        )
    elif source == "fmc":
        footer = (
            "*D-1 FD: closing kemarin (full day)  |  "
            "*D-1 Hourly: RE kemarin s/d jam yang sama  |  "
            "**Sumber: FMC Dashboard KPRO Funneling (backup)"
        )
    elif source == "raw":
        footer = (
            "*D-1 FD: closing kemarin (full day)  |  "
            "*D-1 Hourly: RE kemarin s/d jam yang sama  |  "
            "**Sumber: MySQL indihome_ordering_detail (raw, backup)"
        )
    else:
        footer = (
            "*D-1 FD: closing kemarin (full day)  |  "
            "*D-1 Hourly: RE kemarin s/d jam yang sama  |  "
            "**Sumber: KPRO Endstate"
        )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.05, footer,
            fontsize=5.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(300, int(8500 / (fig_w + fig_h)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
