"""
renderer_simple.py — Render tabel monitoring IO, RE & PS hourly (simpel)
Kolom: WOK | IO (TARGET, TODAY, %ACH) | RE (TARGET, TODAY, %ACH) | PS (TARGET, TODAY, %ACH)
Urutan: Region → Branch → WOK
%ACH pakai progress bar (gaya sama dengan renderer.py / Monitoring RE hourly)

Tabel ke-2 (kanan, dipisah GAP2, header lebih pendek dari tabel utama —
atasnya "nongol" lebih rendah tapi bawahnya sejajar krn baris data berbagi
cur_y yang sama): IO/RE/PS x (D-1, Gap, D-7, Gap), basis HOURLY (s.d. jam
yang sama dengan hari ini, apple-to-apple) — dari io_d1/io_d7_hourly,
re_d1_hourly/re_d7_hourly, ps_d1/ps_d7_hourly (lihat calculator_sql.py).
Gap = TODAY dikurangi D-1/D-7 Hourly.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import textwrap
from io import BytesIO
from datetime import datetime
from config import REPORT_TITLE, REGION_NAME

# ── Warna ──────────────────────────────────────────────────────────────────────
C_HEADER_IO     = "#1B3A6B"
C_HEADER_RE     = "#C0392B"
C_HEADER_PS     = "#1E6B31"
C_HEADER_SUB_IO = "#2980B9"
C_HEADER_SUB_RE = "#E74C3C"
C_HEADER_SUB_PS = "#27AE60"
C_HEADER_COL    = "#2C3E50"
C_REGION_BG     = "#BDC3C7"
C_BRANCH_BG     = "#FBEEE6"
C_WOK_ODD       = "#FFFFFF"
C_WOK_EVEN      = "#FAFAFA"
C_SEP           = "#D5D8DC"
C_TEXT_LIGHT    = "#FFFFFF"
C_TEXT_DARK     = "#1A1A1A"
C_TEXT_MID      = "#2C3E50"
C_ACH_BAR       = "#F39C12"
C_ACH_FILL      = "#FEF9E7"

# ── Warna tabel ke-2: D-1/Gap/D-7/Gap ────────────────────────────────────────
C_POS_BG   = "#D5F5E3"
C_NEG_BG   = "#FADBD8"
C_POS_TEXT = "#1E8449"
C_NEG_TEXT = "#C0392B"

ACH_GREEN  = 100.0
ACH_YELLOW = 70.0


def _fmt_num(v) -> str:
    return "-" if v is None else f"{int(v):,}"


def render_simple(data: dict, source: str = "sql", cutoff: str = None) -> BytesIO:
    """
    Render tabel monitoring IO, RE & PS hourly simpel.
    data dict sama dengan output hitung_re_ps_sql():
      region, branches, woks, upload_time, hari_ini, mode
    """
    region   = data["region"]
    branches = data["branches"]
    woks     = data["woks"]
    ts       = data["upload_time"]
    mode     = data.get("mode", "hourly")
    hari_ini = data.get("hari_ini")

    # Urutan baris: Region → Branch → WOK
    all_rows = (
        [{"_type": "region", **region}] +
        [{"_type": "branch", **b} for b in branches] +
        [{"_type": "wok",    **w} for w in woks]
    )
    n_rows = len(all_rows)

    # Kolom: Territory | IO TARGET | IO TODAY | IO %ACH | RE TARGET | RE TODAY | RE %ACH | PS TARGET | PS TODAY | PS %ACH
    CW_TERR = 2.20
    CW_NUM  = 0.60
    CW_PCT  = 0.65

    COL_W = [CW_TERR] + [CW_NUM, CW_NUM, CW_PCT] * 3

    # ── Tabel ke-2: IO/RE/PS x (D-1, Gap, D-7, Gap), basis Hourly ──────────
    has_table2 = "io_d7_hourly" in region
    GAP2       = 0.45
    CW2_SUB    = [0.55, 0.48, 0.55, 0.48]   # D-1 | Gap | D-7 | Gap
    COL_W2     = CW2_SUB * 3 if has_table2 else []

    ROW_H   = 0.24
    HEAD_H1 = 0.28
    HEAD_H2 = 0.26
    TITLE_H = 0.55
    PAD     = 0.15
    MARGIN  = 0.15

    total_w = sum(COL_W)
    fig_w   = total_w + MARGIN * 2 + (GAP2 + sum(COL_W2) if has_table2 else 0)
    fig_h   = TITLE_H + HEAD_H1 + HEAD_H2 + n_rows * ROW_H + PAD * 2

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    xs = [MARGIN]
    for w in COL_W[:-1]:
        xs.append(xs[-1] + w)

    def cx(ci):
        return xs[ci] + COL_W[ci] / 2

    xs2 = [xs[-1] + COL_W[-1] + GAP2] if has_table2 else []
    for w in COL_W2[:-1]:
        xs2.append(xs2[-1] + w)

    # ── Judul ─────────────────────────────────────────────────────────────
    ax.text(MARGIN, fig_h - 0.10,
            f"Monitoring RE PS IndiHome {REGION_NAME}",
            ha="left", va="top", fontsize=9, fontweight="bold", color=C_TEXT_MID)
    subtitle = (
        f"Closing {hari_ini.strftime('%d-%m-%Y')}"
        if mode == "closing" and hari_ini else
        f"Update {ts.strftime('%d-%m-%Y %H.%M')}"
    )
    ax.text(MARGIN, fig_h - 0.30, subtitle,
            ha="left", va="top", fontsize=7.5, color="#7F8C8D")

    # ── Header baris 1 ────────────────────────────────────────────────────
    y_h1 = fig_h - TITLE_H - HEAD_H1

    def hcell(x, y, w, h, text, bg, fg=C_TEXT_LIGHT, fs=7.5):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3)

    w_io = sum(COL_W[1:4])
    w_re = sum(COL_W[4:7])
    w_ps = sum(COL_W[7:10])

    hcell(xs[0], y_h1, CW_TERR, HEAD_H1, "WOK",  C_HEADER_COL, fs=8.5)
    hcell(xs[1], y_h1, w_io,    HEAD_H1, "IO",   C_HEADER_IO,  fs=9)
    hcell(xs[4], y_h1, w_re,    HEAD_H1, "RE",   C_HEADER_RE,  fs=9)
    hcell(xs[7], y_h1, w_ps,    HEAD_H1, "PS",   C_HEADER_PS,  fs=9)

    # ── Header baris 2: sub-kolom ─────────────────────────────────────────
    y_h2 = y_h1 - HEAD_H2
    sub_labels = ["TARGET", "TODAY", "%ACH"]

    ax.add_patch(plt.Rectangle((xs[0], y_h2), CW_TERR, HEAD_H2,
                               color=C_HEADER_COL, zorder=2))

    for i, lbl in enumerate(sub_labels):
        hcell(xs[1 + i], y_h2, COL_W[1 + i], HEAD_H2, lbl, C_HEADER_SUB_IO, fs=6.5)
        hcell(xs[4 + i], y_h2, COL_W[4 + i], HEAD_H2, lbl, C_HEADER_SUB_RE, fs=6.5)
        hcell(xs[7 + i], y_h2, COL_W[7 + i], HEAD_H2, lbl, C_HEADER_SUB_PS, fs=6.5)

    # Border header
    ax.add_patch(plt.Rectangle((xs[0], y_h2), total_w, HEAD_H1 + HEAD_H2,
                               fill=False, edgecolor=C_SEP, linewidth=0.6, zorder=4))

    # ── Header tabel ke-2: IO/RE/PS x D-1/Gap/D-7/Gap ───────────────────────
    # Header tabel ke-2 DIBUAT LEBIH PENDEK dari tabel utama — dasarnya
    # (y_h2) sama dgn tabel utama supaya baris data tetap sejajar/"bawah
    # disamakan", tapi total tinggi header-nya lebih kecil dari
    # HEAD_H1+HEAD_H2 sehingga atas tabel ke-2 "nongol" lebih rendah (lebih
    # pendek) dari tabel utama. Keterangan "Indihome Sales GAP" ditulis
    # sebagai teks polos DI LUAR tabel (bukan baris header/kolom), rata kiri
    # mepet ke pojok kiri-atas tabel ke-2 — sama pola dgn judul utama yang
    # juga teks polos di luar tabel kiri.
    T2_GRP_H = 0.16
    T2_SUB_H = 0.14
    if has_table2:
        y_sub2 = y_h2
        y_grp2 = y_sub2 + T2_SUB_H

        ax.text(xs2[0], y_grp2 + T2_GRP_H + 0.04,
                "Indihome Sales GAP Hourly (Yesterday and Last Week)",
                ha="left", va="bottom", fontsize=7, fontweight="bold",
                color=C_TEXT_MID)

        metric_hdrs = [("IO", C_HEADER_IO, C_HEADER_SUB_IO),
                       ("RE", C_HEADER_RE, C_HEADER_SUB_RE),
                       ("PS", C_HEADER_PS, C_HEADER_SUB_PS)]
        for mi, (lbl, col, subcol) in enumerate(metric_hdrs):
            base = mi * 4
            hcell(xs2[base], y_grp2, sum(CW2_SUB), T2_GRP_H, lbl, col, fs=8)
            for j, sub in enumerate(["D-1", "Gap", "D-7", "Gap"]):
                hcell(xs2[base + j], y_sub2, CW2_SUB[j], T2_SUB_H, sub, subcol, fs=6)

        ax.add_patch(plt.Rectangle(
            (xs2[0], y_sub2), sum(COL_W2), T2_GRP_H + T2_SUB_H,
            fill=False, edgecolor=C_SEP, linewidth=0.6, zorder=4))

    cur_y = y_h2

    # ── Render baris ──────────────────────────────────────────────────────
    for idx, row in enumerate(all_rows):
        rtype = row["_type"]
        cur_y -= ROW_H

        if rtype == "region":
            bg, fg, fs, bold = C_REGION_BG, C_TEXT_DARK, 7.5, True
        elif rtype == "branch":
            bg, fg, fs, bold = C_BRANCH_BG, C_TEXT_DARK,  7.0, True
        else:
            bg = C_WOK_ODD if idx % 2 == 0 else C_WOK_EVEN
            fg, fs, bold = C_TEXT_DARK, 6.8, False

        ax.add_patch(plt.Rectangle((xs[0], cur_y), total_w, ROW_H,
                                   color=bg, zorder=1))
        mid_y = cur_y + ROW_H / 2

        # ── Bar %ACH (gaya sama dengan renderer.py) ────────────────────────
        def ach_bar(col, pct, fs=fs):
            if pct is None:
                ax.text(cx(col), mid_y, "-", ha="center", va="center",
                        fontsize=fs, color=fg, zorder=3)
                return
            bar_w = COL_W[col] - 0.12
            bar_h = ROW_H * 0.55
            bx    = xs[col] + 0.06
            by    = mid_y - bar_h / 2
            ax.add_patch(plt.Rectangle((bx, by), bar_w, bar_h,
                                       color=C_ACH_FILL, zorder=2))
            fill = min(pct / 100, 1.0) * bar_w
            if fill > 0:
                ax.add_patch(plt.Rectangle((bx, by), fill, bar_h,
                                           color=C_ACH_BAR, zorder=3))
            ax.text(bx + bar_w / 2, mid_y, f"{pct:.0f}%",
                    ha="center", va="center", fontsize=fs - 0.5,
                    fontweight="bold", color="#5D4000", zorder=4)

        # Territory
        ax.text(xs[0] + 0.10, mid_y, row["name"],
                ha="left", va="center", fontsize=fs,
                fontweight="bold" if bold else "normal",
                color=fg, zorder=3)

        # IO cols (1-3)
        ax.text(cx(1), mid_y, _fmt_num(row.get("io_target")),
                ha="center", va="center", fontsize=fs, color=fg, zorder=3)
        ax.text(cx(2), mid_y, _fmt_num(row.get("io_today")),
                ha="center", va="center", fontsize=fs, fontweight="bold",
                color=fg, zorder=3)
        ach_bar(3, row.get("io_pct_ach"))

        # RE cols (4-6)
        ax.text(cx(4), mid_y, _fmt_num(row.get("re_target")),
                ha="center", va="center", fontsize=fs, color=fg, zorder=3)
        ax.text(cx(5), mid_y, _fmt_num(row.get("re_today")),
                ha="center", va="center", fontsize=fs, fontweight="bold",
                color=fg, zorder=3)
        ach_bar(6, row.get("re_pct_ach"))

        # PS cols (7-9)
        ax.text(cx(7), mid_y, _fmt_num(row.get("ps_target")),
                ha="center", va="center", fontsize=fs, color=fg, zorder=3)
        ax.text(cx(8), mid_y, _fmt_num(row.get("ps_today")),
                ha="center", va="center", fontsize=fs, fontweight="bold",
                color=fg, zorder=3)
        ach_bar(9, row.get("ps_pct_ach"))

        lw = 0.5 if rtype in ("region", "branch") else 0.25
        ax.plot([xs[0], xs[0] + total_w], [cur_y, cur_y],
                color=C_SEP, linewidth=lw, zorder=5)

        # ── Tabel ke-2: IO/RE/PS x D-1/Gap/D-7/Gap (Hourly) ─────────────────
        if has_table2:
            ax.add_patch(plt.Rectangle((xs2[0], cur_y), sum(COL_W2), ROW_H,
                                       color=bg, zorder=1))

            def num_cell2(x0, w0, text):
                ax.text(x0 + w0 / 2, mid_y, text, ha="center", va="center",
                        fontsize=fs, fontweight="bold" if bold else "normal",
                        color=fg, zorder=3)

            def gap_cell2(x0, w0, val):
                text = "-" if val is None else f"{val:,}"
                if val is None or val == 0:
                    num_cell2(x0, w0, text)
                    return
                bg_c, fg_c = (C_POS_BG, C_POS_TEXT) if val > 0 else (C_NEG_BG, C_NEG_TEXT)
                ax.add_patch(plt.Rectangle((x0 + 0.025, cur_y + 0.025),
                                           w0 - 0.05, ROW_H - 0.05,
                                           color=bg_c, zorder=2))
                ax.text(x0 + w0 / 2, mid_y, text, ha="center", va="center",
                        fontsize=fs, fontweight="bold", color=fg_c, zorder=3)

            metrics2 = [
                ("io_today", "io_d1", "io_d7_hourly"),
                ("re_today", "re_d1_hourly", "re_d7_hourly"),
                ("ps_today", "ps_d1", "ps_d7_hourly"),
            ]
            ci = 0
            for k_d, k_d1, k_d7 in metrics2:
                d   = row.get(k_d)  or 0
                d1  = row.get(k_d1) or 0
                d7  = row.get(k_d7) or 0
                # Gap = TODAY - D1/D7 apa adanya, TANPA guard "> 0" — D1/D7
                # bernilai 0 itu valid (mis. 0 transaksi jam segini 7 hari
                # lalu), bukan berarti datanya kosong, jadi gap-nya tetap
                # harus dihitung (bukan "-").
                num_cell2(xs2[ci], COL_W2[ci], _fmt_num(d1)); ci += 1
                gap_cell2(xs2[ci], COL_W2[ci], d - d1); ci += 1
                num_cell2(xs2[ci], COL_W2[ci], _fmt_num(d7)); ci += 1
                gap_cell2(xs2[ci], COL_W2[ci], d - d7); ci += 1

            ax.plot([xs2[0], xs2[0] + sum(COL_W2)], [cur_y, cur_y],
                    color=C_SEP, linewidth=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    y_top = y_h2
    y_bot = cur_y
    for x in xs:
        ax.plot([x, x], [y_bot, y_top], color=C_SEP, linewidth=0.3, zorder=5)
    ax.plot([xs[-1] + COL_W[-1], xs[-1] + COL_W[-1]],
            [y_bot, y_top], color=C_SEP, linewidth=0.3, zorder=5)

    # Border luar
    ax.add_patch(plt.Rectangle(
        (xs[0], y_bot), total_w, y_top - y_bot + HEAD_H1 + HEAD_H2,
        fill=False, edgecolor="#7F8C8D", linewidth=0.8, zorder=6))

    # ── Grid & border tabel ke-2 ─────────────────────────────────────────
    if has_table2:
        for x in xs2:
            ax.plot([x, x], [y_bot, y_top], color=C_SEP, linewidth=0.3, zorder=5)
        ax.plot([xs2[-1] + COL_W2[-1], xs2[-1] + COL_W2[-1]],
                [y_bot, y_top], color=C_SEP, linewidth=0.3, zorder=5)
        for base in (4, 8):
            ax.plot([xs2[base], xs2[base]], [y_bot, y_top],
                    color="#7F8C8D", linewidth=0.5, zorder=6)

        ax.add_patch(plt.Rectangle(
            (xs2[0], y_bot), sum(COL_W2),
            y_top - y_bot + T2_GRP_H + T2_SUB_H,
            fill=False, edgecolor="#7F8C8D", linewidth=0.8, zorder=6))

        footer2 = (
            "*D-1/D-7: kemarin / 7 hari lalu s.d. jam yang sama (hourly) | "
            "*Gap: TODAY dikurangi D-1/D-7 Hourly"
        )
        footer2_wrapped = textwrap.fill(footer2, width=int(sum(COL_W2) / 0.024))
        ax.text(xs2[0], cur_y - 0.05, footer2_wrapped,
                fontsize=4.6, color="#95A5A6", va="top", style="italic",
                linespacing=1.4)

    # Catatan kaki
    if source == "sql":
        footer = "**Sumber: Rajawali dashboard_hourly_sales (WOK baru)"
    elif source == "hadoop":
        footer = "**Sumber: Hadoop IndiHome_Ordering_Detail"
    elif source == "fmc":
        footer = "**Sumber: FMC Dashboard KPRO Funneling (backup)"
    elif source == "ordering":
        footer = "**Sumber: Rajawali indihome_ordering_detail"
    elif source == "raw":
        footer = "**Sumber: MySQL indihome_ordering_detail (raw, backup)"
    else:
        footer = "**Sumber: KPRO Endstate"
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"

    ax.text(xs[0], cur_y - 0.05, footer,
            fontsize=5.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(180, int(8500 / (fig_w + fig_h)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
