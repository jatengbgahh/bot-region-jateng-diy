"""
reports/c3mrnewch/renderer.py — Render tabel C3MR per BILL-N per Channel Group.

Tata letak & warna SAMA dengan renderer_c3mrnew.py (color-scale %C3MR
hijau=tinggi/merah=rendah, format angka) — fungsi format & color-scale
di-import langsung dari sana, TIDAK ditulis ulang. Bedanya cuma:
  - Baris = channel_group (single level), bukan WOK/BRANCH/REGION (3 level)
  - 1 kolom label ("CHANNEL GROUP"), bukan 2 (branch + wok)
  - Header TOTAL pakai warna maroon yang sama dgn BILL-1..6 (bukan biru)
"""

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import REGION_NAME
from renderer_c3mrnew import _pct_color_scale, _fmt_pct, _fmt_mom, _fmt_num

C_BG        = "white"
C_HDR_TERR  = "#2C3E50"
C_HDR_BILL  = "#8B2500"    # dark red — konsisten dgn C3MR, dipakai juga utk TOTAL
C_HDR_BILL_D= "#6b1c00"
C_REGION_BG = "#2C3E50"
C_ROW_ODD   = "white"
C_ROW_EVEN  = "#F4F6F7"
C_SEP       = "#BDC3C7"
C_WHITE     = "white"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"
C_POS       = "#1E8449"
C_NEG       = "#C0392B"


def render_c3mrnewch(data: dict, cutoff: str = None) -> BytesIO:
    tgl_closing  = data["tgl_closing"]
    bl_label     = data["bl_label"]
    bi_label     = data["bi_label"]
    region       = data["region"]
    channels     = data["channels"]
    bill_order   = data["bill_order"]
    bill_labels  = data["bill_labels"]
    closing_mode = data["is_closing_mode"]

    all_rows = (
        [{"_t": "ch", **c} for c in channels] +
        [{"_t": "reg", **region}]
    )

    # ── Color scale per BILL-N (range channel, EXCLUDE baris total) ────────
    bill_ranges = {}
    all_pcts = [r.get("total_pct") for r in all_rows
                if r["_t"] == "ch" and r.get("total_pct") is not None]
    bill_ranges["total"] = (min(all_pcts), max(all_pcts)) if all_pcts else (None, None)
    for n in bill_order:
        vals = [r.get(f"b{n}_pct") for r in all_rows
                if r["_t"] == "ch" and r.get(f"b{n}_pct") is not None]
        bill_ranges[n] = (min(vals), max(vals)) if vals else (None, None)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_CH  = 3.10
    CW_PCT = 1.20
    CW_MOM = 1.35
    CW_UNP = 1.00

    sub_cw = [CW_PCT, CW_MOM, CW_UNP]
    N_SUB  = len(sub_cw)
    N_BILL = len(bill_order)

    col_widths = [CW_CH] + sub_cw + sub_cw * N_BILL  # +sub_cw pertama untuk TOTAL
    TW = sum(col_widths)

    RH  = 0.52
    HH1 = 0.50
    HH2 = 0.34
    TH  = 0.75
    MG  = 0.25

    FH = TH + HH1 + HH2 + len(all_rows) * RH + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)

    def cx(i):
        return xs[i] + col_widths[i] / 2

    # ── Judul ─────────────────────────────────────────────────────────────
    judul = f"{data.get('report_title', 'C3MR LoS 0-6 Bulan per Channel Group')}  |  {REGION_NAME}"
    if closing_mode:
        judul += f"  |  Bill Period {bi_label}"
    ax.text(MG, FH - 0.18, judul,
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label}"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=13):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w/2, y + h/2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.2)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    hcell(xs[0], yh2, CW_CH, HH1 + HH2, "CHANNEL GROUP", C_HDR_TERR, fs=14)

    sub_labels = ["%C3MR", "MoM", "Unpaid"]

    # Header TOTAL — warna SAMA dgn BILL blocks (maroon), sesuai contoh
    hcell(xs[1], yh1, sum(sub_cw), HH1, "TOTAL", C_HDR_BILL, fs=13)
    for j, lbl in enumerate(sub_labels):
        hcell(xs[1 + j], yh2, sub_cw[j], HH2, lbl, C_HDR_BILL_D, fs=11)

    for gi, n in enumerate(bill_order):
        cs    = 1 + N_SUB + gi * N_SUB
        w_grp = sum(sub_cw)
        hcell(xs[cs], yh1, w_grp, HH1, bill_labels[n], C_HDR_BILL, fs=13)
        for j, lbl in enumerate(sub_labels):
            hcell(xs[cs + j], yh2, sub_cw[j], HH2, lbl, C_HDR_BILL_D, fs=11)

    ax.add_patch(plt.Rectangle(
        (xs[0], yh2), TW, HH1 + HH2,
        fill=False, edgecolor=C_SEP, lw=0.5, zorder=4
    ))

    # ── Baris data ────────────────────────────────────────────────────────
    cur_y = yh2
    ri    = 0

    for row in all_rows:
        rtype = row["_t"]
        cur_y -= RH

        if rtype == "reg":
            bg, fg, fs, bold = C_REGION_BG, C_WHITE, 16.0, True
        else:
            bg = C_ROW_ODD if ri % 2 == 0 else C_ROW_EVEN
            fg, fs, bold = C_DARK, 16.0, False
            ri += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def cell(ci, txt, color=None):
            t  = str(txt) if txt is not None else "-"
            f2 = fs
            while f2 > 6.0 and len(t) * 0.068 * f2 / 10 > col_widths[ci] - 0.10:
                f2 -= 0.4
            ax.text(cx(ci), mid_y, t,
                    ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl_cell(xi, txt, maxw):
            f2 = fs
            while f2 > 6.0 and len(txt) * 0.068 * f2 / 10 > maxw - 0.20:
                f2 -= 0.4
            ax.text(xi, mid_y, txt,
                    ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        def mom_cell(ci, v):
            if v is None: cell(ci, "-"); return
            color = fg if bold else (C_POS if v >= 0 else C_NEG)
            cell(ci, _fmt_mom(v), color=color)

        def pct_cell_cs(ci, v, vmin, vmax):
            txt = _fmt_pct(v)
            if rtype == "ch" and v is not None:
                bg_cs, fg_cs = _pct_color_scale(v, vmin, vmax)
                if bg_cs:
                    pad = 0.04
                    ax.add_patch(plt.Rectangle(
                        (xs[ci] + pad, cur_y + pad),
                        col_widths[ci] - pad*2, RH - pad*2,
                        color=bg_cs, zorder=2
                    ))
                    f2 = fs
                    while f2 > 6.0 and len(txt)*0.068*f2/10 > col_widths[ci]-0.10:
                        f2 -= 0.4
                    ax.text(cx(ci), mid_y, txt,
                            ha="center", va="center", fontsize=f2,
                            fontweight="bold" if bold else "normal",
                            color=fg_cs, zorder=3, clip_on=True)
                    return
            cell(ci, txt)

        lbl = row["name"] if rtype == "ch" else REGION_NAME
        lbl_cell(xs[0] + 0.08, lbl, CW_CH)

        vmin_t, vmax_t = bill_ranges["total"]
        pct_cell_cs(1, row.get("total_pct"), vmin_t, vmax_t)
        mom_cell(2,    row.get("total_mom"))
        cell(3,        _fmt_num(row.get("total_unpaid")))

        for gi, n in enumerate(bill_order):
            cs = 1 + N_SUB + gi * N_SUB
            vmin, vmax = bill_ranges[n]
            pct_cell_cs(cs,     row.get(f"b{n}_pct"), vmin, vmax)
            mom_cell(cs + 1,    row.get(f"b{n}_mom"))
            cell(cs + 2,        _fmt_num(row.get(f"b{n}_unpaid")))

        lw = 0.8 if rtype == "reg" else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    for gi in range(N_BILL + 1):
        gx = xs[1 + gi * N_SUB]
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)
    ax.plot([xs[-1] + col_widths[-1]]*2, [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"BILL-N = pelanggan ps_ts bulan ke-N sebelum bill period aktif  |  "
        f"Color scale %C3MR: hijau=tinggi, merah=rendah  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: bwmp_c3mr_dd + indihome_ordering_detail"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer,
            fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(180, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
