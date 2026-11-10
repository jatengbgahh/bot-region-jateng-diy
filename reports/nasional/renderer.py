"""
reports/nasional/renderer.py — Render tabel Performance MtD Sales IndiHome level Region nasional
(IO/RE/PS + PS to IO/RE + Revenue + ARPU New Sales; Area 1-4 + National).
Gaya mengikuti renderer_city_performance / renderer_daily_performance.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from dateutil.relativedelta import relativedelta

C_BG          = "#FFFFFF"
C_HEADER_IO   = "#1B3A6B"
C_HEADER_RE   = "#8B2500"
C_HEADER_PS   = "#1E6B31"
C_HEADER_CONV = "#4A235A"
C_HEADER_REV  = "#1A5276"
C_HEADER_ARPU = "#784212"
C_HEADER_SUB  = "#2C3E50"
C_TOTAL_BG    = "#2C3E50"
C_AREA_BG     = "#D5D8DC"
C_ROW_ODD     = "#FFFFFF"
C_ROW_EVEN    = "#F4F6F7"
C_SEP         = "#BDC3C7"
C_WHITE       = "#FFFFFF"
C_DARK        = "#1A1A1A"
C_MID         = "#2C3E50"
C_POS         = "#1E8449"
C_NEG         = "#C0392B"
C_ACH_BAR      = "#F39C12"
C_ACH_FILL     = "#FEF9E7"


def _fmt(v, dec=0, pct=False):
    if v is None: return "-"
    if pct:
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.{dec}f}%"
    if isinstance(v, float): return f"{v:,.{dec}f}"
    return f"{int(v):,}"


def _kosong(r) -> bool:
    """Baris UNMAPPED yang tidak punya data sama sekali tidak ditampilkan."""
    return all(not r.get(k) for k in ("io_now", "io_prev", "re_now", "re_prev", "ps_now", "ps_prev"))


def render_national(data: dict, cutoff: str = None) -> BytesIO:
    tgl_closing = data["tgl_closing"]
    bl = (tgl_closing - relativedelta(months=1)).strftime("%b").upper()
    bi = tgl_closing.strftime("%b").upper()

    all_rows = []
    for r in data["regions"]:
        if r["name"] == "UNMAPPED" and _kosong(r): continue
        all_rows.append({"_type": "region", **r})
    for r in data["areas"]:
        if r["name"] == "UNMAPPED" and _kosong(r): continue
        all_rows.append({"_type": "area", **r})
    all_rows.append({"_type": "national", **data["national"]})

    CW = {
        "name": 4.2,
        "num": 1.11, "mom": 1.37, "ach": 1.18, "conv": 1.33,
        "rev": 2.10, "arpu": 1.27, "momr": 1.21,
    }
    COLS = (
        [("name", CW["name"])] +
        [("io_tgt", CW["num"]), ("io_prev", CW["num"]), ("io_now", CW["num"]),
         ("io_mom", CW["mom"]), ("io_ach", CW["ach"])] +
        [("re_tgt", CW["num"]), ("re_prev", CW["num"]), ("re_now", CW["num"]),
         ("re_mom", CW["mom"]), ("re_ach", CW["ach"])] +
        [("ps_tgt", CW["num"]), ("ps_prev", CW["num"]), ("ps_now", CW["num"]),
         ("ps_mom", CW["mom"]), ("ps_ach", CW["ach"])] +
        [("ps_to_io", CW["conv"]), ("ps_to_re", CW["conv"])] +
        [("rev_prev", CW["rev"]), ("rev_now", CW["rev"]), ("mom_rev", CW["momr"])] +
        [("arpu_prev", CW["arpu"]), ("arpu_now", CW["arpu"]), ("mom_arpu", CW["momr"])]
    )
    col_widths = [c[1] for c in COLS]
    total_w    = sum(col_widths)

    FS_ROW    = 16.0
    FS_HEAD1  = 14.0
    FS_HEAD2  = 12.0
    FS_TITLE  = 15.0

    ROW_H   = 0.52
    HEAD_H1 = 0.38
    HEAD_H2 = 0.32
    TITLE_H = 0.60
    MARGIN  = 0.25
    PAD     = 0.20

    fig_w = total_w + MARGIN*2
    fig_h = TITLE_H + HEAD_H1 + HEAD_H2 + len(all_rows)*ROW_H + PAD*2

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w); ax.set_ylim(0, fig_h)
    ax.axis("off"); fig.patch.set_facecolor(C_BG)

    xs = [MARGIN]
    for w in col_widths[:-1]:
        xs.append(xs[-1]+w)
    def cx(i): return xs[i]+col_widths[i]/2

    ax.text(MARGIN, fig_h-0.15,
            "Daily Tracking IndiHome Performance — Region Level",
            ha="left", va="top", fontsize=FS_TITLE+2, fontweight="bold", color=C_MID)
    ax.text(MARGIN, fig_h-0.42, f"Update {tgl_closing.strftime('%d-%m-%Y')}",
            ha="left", va="top", fontsize=FS_TITLE, color="#7F8C8D")

    def hcell(x, y, w, h, text, bg, fg=C_WHITE, fs=16):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x+w/2, y+h/2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3)

    y_h1 = fig_h - TITLE_H - HEAD_H1
    y_h2 = y_h1 - HEAD_H2

    hcell(xs[0], y_h2, CW["name"], HEAD_H1+HEAD_H2, "REGION", C_HEADER_SUB, fs=FS_HEAD1)

    groups = [
        (1,  6,  "IO (EXCL HWA)", C_HEADER_IO),
        (6,  11, "RE (EXCL HWA)",          C_HEADER_RE),
        (11, 16, "PS (EXCL HWA)",          C_HEADER_PS),
        (16, 18, "CONVERSION",             C_HEADER_CONV),
        (18, 21, "Revenue New Sales", C_HEADER_REV),
        (21, 24, "ARPU New Sales",         C_HEADER_ARPU),
    ]
    for (cs, ce, lbl, color) in groups:
        w = sum(col_widths[cs:ce])
        hcell(xs[cs], y_h1, w, HEAD_H1, lbl, color, fs=FS_HEAD1)

    sub_io   = ["Target", bl, bi, "MoM", "ACH(%)"]
    sub_conv = ["PS to IO", "PS to RE"]
    sub_rev  = [bl, bi, "MoM"]
    sub_arpu = [bl, bi, "MoM"]
    colors_h2 = ([C_HEADER_IO]*5 + [C_HEADER_RE]*5 + [C_HEADER_PS]*5 + [C_HEADER_CONV]*2 +
                 [C_HEADER_REV]*3 + [C_HEADER_ARPU]*3)
    sub_labels = sub_io*3 + sub_conv + sub_rev + sub_arpu
    for i, (lbl, col) in enumerate(zip(sub_labels, colors_h2)):
        ci = i+1
        hcell(xs[ci], y_h2, col_widths[ci], HEAD_H2, lbl, col, fs=FS_HEAD2)

    ax.add_patch(plt.Rectangle((xs[0], y_h2), total_w, HEAD_H1+HEAD_H2,
                               fill=False, edgecolor=C_SEP, linewidth=0.5, zorder=4))

    cur_y = y_h2
    reg_i = 0
    nat_y = None

    for row in all_rows:
        rtype = row["_type"]
        cur_y -= ROW_H

        if rtype == "national":
            nat_y = cur_y
            bg, fg, fs, bold = C_TOTAL_BG, C_WHITE, FS_ROW, True
        elif rtype == "area":
            bg, fg, fs, bold = C_AREA_BG, C_DARK, FS_ROW, True
        else:
            bg = C_ROW_ODD if reg_i % 2 == 0 else C_ROW_EVEN
            fg, fs, bold = C_DARK, FS_ROW, False
            reg_i += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), total_w, ROW_H, color=bg, zorder=1))
        mid_y = cur_y + ROW_H/2
        solid = rtype in ("national",)

        def txt(ci, text, color=None, ha="center"):
            t = str(text) if text is not None else "-"
            cw = col_widths[ci]
            fitted = fs
            while fitted > 5.5:
                if len(t)*0.07*fitted/10 <= cw-0.10: break
                fitted -= 0.5
            ax.text(cx(ci), mid_y, t, ha=ha, va="center",
                    fontsize=fitted, fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def fit_label(xi, text, max_w):
            fitted = fs
            while fitted > 5.5:
                if len(text)*0.07*fitted/10 <= max_w-0.15: break
                fitted -= 0.5
            ax.text(xi, mid_y, text, ha="left", va="center",
                    fontsize=fitted, fontweight="bold" if rtype != "region" else "normal",
                    color=fg, zorder=3, clip_on=True)

        def num_cell(ci, v): txt(ci, _fmt(v))
        def pct_cell(ci, v):
            if v is None: txt(ci, "-"); return
            txt(ci, _fmt(v, dec=1, pct=True),
                color=fg if solid else (C_POS if v >= 0 else C_NEG))
        def bar_cell(ci, v):
            """Progress bar persen (gaya kolom %Ach RE di report monitoring RE hourly)."""
            if v is None: txt(ci, "-"); return
            bar_w = col_widths[ci] - 0.12
            bar_h = ROW_H * 0.70
            bx    = xs[ci] + 0.06
            by    = cur_y + (ROW_H - bar_h) / 2
            ax.add_patch(plt.Rectangle((bx, by), bar_w, bar_h,
                                       color=C_ACH_FILL, zorder=2))
            fill = min(max(v, 0) / 100, 1.0) * bar_w
            if fill > 0:
                ax.add_patch(plt.Rectangle((bx, by), fill, bar_h,
                                           color=C_ACH_BAR, zorder=3))
            ax.text(bx + bar_w/2, cur_y + ROW_H/2, f"{v:.1f}%",
                    ha="center", va="center", fontsize=fs - 1,
                    fontweight="bold", color="#5D4000", zorder=4)
        def ach_cell(ci, v):  bar_cell(ci, v)
        def conv_cell(ci, v): bar_cell(ci, v)
        def rev_cell(ci, v):  txt(ci, "-" if v is None else f"{round(v):,}")
        def arpu_cell(ci, v): txt(ci, "-" if v is None else f"{round(v):,}")

        fit_label(xs[0]+0.10, row.get("name", ""), CW["name"])

        num_cell(1, row.get("io_tgt")); num_cell(2, row.get("io_prev"))
        num_cell(3, row.get("io_now")); pct_cell(4, row.get("io_mom"))
        ach_cell(5, row.get("io_ach"))

        num_cell(6, row.get("re_tgt")); num_cell(7, row.get("re_prev"))
        num_cell(8, row.get("re_now")); pct_cell(9, row.get("re_mom"))
        ach_cell(10, row.get("re_ach"))

        num_cell(11, row.get("ps_tgt")); num_cell(12, row.get("ps_prev"))
        num_cell(13, row.get("ps_now")); pct_cell(14, row.get("ps_mom"))
        ach_cell(15, row.get("ps_ach"))

        conv_cell(16, row.get("ps_to_io")); conv_cell(17, row.get("ps_to_re"))

        rev_cell(18, row.get("rev_prev")); rev_cell(19, row.get("rev_now"))
        pct_cell(20, row.get("mom_rev"))
        arpu_cell(21, row.get("arpu_prev")); arpu_cell(22, row.get("arpu_now"))
        pct_cell(23, row.get("mom_arpu"))

        lw = 0.8 if rtype in ("national", "area") else 0.3
        ax.plot([xs[0], xs[0]+total_w], [cur_y, cur_y], color=C_SEP, linewidth=lw, zorder=5)

    for x in xs:
        ax.plot([x, x], [cur_y, y_h2], color=C_SEP, linewidth=0.3, zorder=5)
    ax.plot([xs[-1]+col_widths[-1]]*2, [cur_y, y_h2], color=C_SEP, linewidth=0.3, zorder=5)

    for gx in [xs[1], xs[6], xs[11], xs[16], xs[18], xs[21], xs[-1]+col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, y_h1], color=C_MID, linewidth=0.8, zorder=6)

    # Baris NATIONAL (latar navy): pembatas putih yang jelas, garis atas tebal dan pemisah antar kolom
    if nat_y is not None:
        ax.plot([xs[0], xs[0]+total_w], [nat_y+ROW_H, nat_y+ROW_H],
                color=C_WHITE, linewidth=2.6, zorder=8)
        for x in xs[1:] + [xs[-1]+col_widths[-1]]:
            ax.plot([x, x], [nat_y, nat_y+ROW_H], color=C_WHITE, linewidth=0.9, zorder=8)
        for gx in [xs[1], xs[6], xs[11], xs[16], xs[18], xs[21]]:
            ax.plot([gx, gx], [nat_y, nat_y+ROW_H], color=C_WHITE, linewidth=2.0, zorder=9)

    ax.add_patch(plt.Rectangle((xs[0], cur_y), total_w, y_h2-cur_y+HEAD_H1+HEAD_H2,
                               fill=False, edgecolor="#7F8C8D", linewidth=1.0, zorder=7))
    footer = ("Excl HWA  |  Revenue = price_package order PS (Rp)  |  "
              "Sumber: Rajawali indihome_ordering_detail")
    if cutoff:
        footer += f"  |  {cutoff}"
    ax.text(xs[0], cur_y-0.08, footer,
            fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(300, int(8500 / (fig_w + fig_h)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
