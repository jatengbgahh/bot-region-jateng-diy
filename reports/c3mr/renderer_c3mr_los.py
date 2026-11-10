"""
renderer_c3mr_los.py — Render tabel C3MR per LOS Group
5 group: 0-3 bulan | 4-6 bulan | 7-12 bulan | 12-24 bulan | >24 bulan
Kolom per group: Subs | Bill Amount | %C3MR | MoM | Saldo | Unpaid
Style identik dengan renderer_c3mr.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs
from calculator_c3mr import LOS_ORDER

C_BG        = "white"
C_HDR_TERR  = "#2C3E50"
C_REGION_BG = "#2C3E50"
C_BRANCH_BG = "#D5D8DC"
C_WOK_ODD   = "white"
C_WOK_EVEN  = "#F4F6F7"
C_SEP       = "#BDC3C7"
C_GRID      = "#7F8C8D"   # garis grid kolom (tegas)
C_WHITE     = "white"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"
C_POS       = "#1E8449"
C_NEG       = "#C0392B"

# Warna header per LOS group
LOS_COLORS = {
    "0-3 bulan" : "#1B3A6B",   # dark blue
    "4-6 bulan" : "#8B2500",   # dark red
    "7-12 bulan": "#1E6B31",   # dark green
    "12-24 bulan": "#4A235A",  # dark purple
    ">24 bulan" : "#1B5E6B",   # dark teal
}
LOS_DARKER = {
    "0-3 bulan" : "#152d54",
    "4-6 bulan" : "#6b1c00",
    "7-12 bulan": "#174d25",
    "12-24 bulan": "#371a42",
    ">24 bulan" : "#134650",
}

LOS_LABELS = {
    "0-3 bulan" : "0-3 Bulan\n(incl. PSB)",
    "4-6 bulan" : "4-6 Bulan",
    "7-12 bulan": "7-12 Bulan",
    "12-24 bulan": "12-24 Bulan",
    ">24 bulan" : ">24 Bulan",
}


def _los_key(g):
    return g.replace(" ", "_").replace(">", "gt")


def _pct_color_scale(value, vmin, vmax):
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None
    t = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
    cmap = mcolors.LinearSegmentedColormap.from_list("gwr", ["#E74C3C", "#FFFFFF", "#27AE60"])
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r*255), int(g*255), int(b*255))
    lum    = 0.299*r + 0.587*g + 0.114*b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"
    return bg_hex, fg_hex


def _fmt_num(v):
    return "-" if v is None else f"{int(round(v)):,}"

def _fmt_bill(v):
    return "-" if v is None else f"{int(round(v)):,}"

def _fmt_pct(v):
    return "-" if v is None else f"{v:.2f}%"

def _fmt_mom(v):
    if v is None: return "-"
    return f"{'+'if v>0 else''}{v:.2f}%"


def render_c3mr_los(data: dict, cutoff: str = None) -> BytesIO:
    tgl_closing = data["tgl_closing"]
    bl_label    = data["bl_label"]
    region      = data["region"]
    branches    = data["branches"]
    woks        = data["woks"]

    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "br",  **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    # ── Color scale per LOS group (range WOK+Branch) ──────────────────────
    los_ranges = {}
    for g in LOS_ORDER:
        key  = _los_key(g)
        vals = [r.get(f"los_{key}_pct") for r in all_rows
                if r["_t"] in ("wok", "br") and r.get(f"los_{key}_pct") is not None]
        los_ranges[g] = (min(vals), max(vals)) if vals else (None, None)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_BR = 2.15
    CW_WOK = 4.75
    CW_SUBS = 1.30
    CW_BILL = 2.50
    CW_PCT  = 1.40
    CW_MOM  = 1.50
    CW_SAL  = 2.50
    CW_UNP  = 1.20

    sub_cw = [CW_SUBS, CW_BILL, CW_PCT, CW_MOM, CW_SAL, CW_UNP]
    N_SUB  = len(sub_cw)
    N_GRP  = len(LOS_ORDER)

    col_widths = [CW_BR, CW_WOK] + sub_cw * N_GRP
    GRP_STEP = N_SUB
    TW = sum(col_widths)

    RH  = 0.52
    HH1 = 0.54
    HH2 = 0.36
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
    ax.text(MG, FH - 0.18,
            "C3MR per LOS IndiHome Jateng-DIY",
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

    # Territory header
    hcell(xs[0], yh2, CW_BR + CW_WOK, HH1 + HH2, "TERRITORY", C_HDR_TERR, fs=14)

    # Header per LOS group
    sub_labels = ["Subs", "Bill Amount", "%C3MR", "MoM", "Saldo", "Unpaid"]
    for gi, g in enumerate(LOS_ORDER):
        cs  = 2 + gi * GRP_STEP
        col = LOS_COLORS[g]
        drk = LOS_DARKER[g]
        w_grp = sum(sub_cw)
        hcell(xs[cs], yh1, w_grp, HH1, LOS_LABELS[g], col, fs=13)
        for j, lbl in enumerate(sub_labels):
            hcell(xs[cs + j], yh2, sub_cw[j], HH2, lbl, drk, fs=11)

    ax.add_patch(plt.Rectangle(
        (xs[0], yh2), TW, HH1 + HH2,
        fill=False, edgecolor=C_SEP, lw=0.5, zorder=4
    ))

    # ── Baris data ────────────────────────────────────────────────────────
    cur_y = yh2
    wi    = 0

    for row in all_rows:
        rtype = row["_t"]
        cur_y -= RH

        if rtype == "reg":
            bg, fg, fs, bold = C_REGION_BG, C_WHITE, 16.0, True
        elif rtype == "br":
            bg, fg, fs, bold = C_BRANCH_BG, C_DARK,  16.0, True
        else:
            bg = C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN
            fg, fs, bold = C_DARK, 16.0, False
            wi += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def cell(ci, txt, color=None):
            t  = str(txt) if txt is not None else "-"
            f2 = fs
            while f2 > 6.0 and len(t) * 0.068 * f2 / 10 > col_widths[ci] - 0.30:
                f2 -= 0.4
            ax.text(cx(ci), mid_y, t,
                    ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl_cell(xi, txt, maxw):
            f2 = fit_fs(txt, fs, maxw, floor=6.0, pad=0.20)
            ax.text(xi, mid_y, txt,
                    ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        def mom_cell(ci, v):
            if v is None: cell(ci, "-"); return
            color = fg if bold else (C_POS if v >= 0 else C_NEG)
            cell(ci, _fmt_mom(v), color=color)

        def pct_cell_cs(ci, v, vmin, vmax):
            txt = _fmt_pct(v)
            if rtype in ("wok", "br") and v is not None:
                bg_cs, fg_cs = _pct_color_scale(v, vmin, vmax)
                if bg_cs:
                    pad = 0.04
                    ax.add_patch(plt.Rectangle(
                        (xs[ci] + pad, cur_y + pad),
                        col_widths[ci] - pad*2, RH - pad*2,
                        color=bg_cs, zorder=2
                    ))
                    f2 = fs
                    while f2 > 6.0 and len(txt)*0.068*f2/10 > col_widths[ci]-0.30:
                        f2 -= 0.4
                    ax.text(cx(ci), mid_y, txt,
                            ha="center", va="center", fontsize=f2,
                            fontweight="bold" if bold else "normal",
                            color=fg_cs, zorder=3, clip_on=True)
                    return
            cell(ci, txt)

        # Territory
        br_lbl  = row.get("name","") if rtype=="br" else (REGION_NAME if rtype=="reg" else row.get("branch",""))
        wok_lbl = row.get("name","") if rtype=="wok" else (REGION_NAME if rtype=="reg" else "")
        lbl_cell(xs[0] + 0.08, br_lbl,  CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)

        # Per LOS group
        for gi, g in enumerate(LOS_ORDER):
            cs  = 2 + gi * GRP_STEP
            key = _los_key(g)
            vmin, vmax = los_ranges[g]

            cell(cs + 0, _fmt_num(row.get(f"los_{key}_subs")))
            cell(cs + 1, _fmt_bill(row.get(f"los_{key}_bill")))
            pct_cell_cs(cs + 2, row.get(f"los_{key}_pct"), vmin, vmax)
            mom_cell(cs + 3, row.get(f"los_{key}_mom"))
            cell(cs + 4, _fmt_bill(row.get(f"los_{key}_saldo")))
            cell(cs + 5, _fmt_num(row.get(f"los_{key}_unpaid")))

        lw = 1.6 if rtype in ("reg", "br") else 0.6
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_GRID, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_GRID, lw=0.9, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_GRID, lw=0.9, zorder=5)

    # Pemisah antar grup LOS (lebih tebal)
    for gi in range(N_GRP + 1):
        gx = xs[2 + gi * N_SUB] if gi < N_GRP else xs[-1] + col_widths[-1]
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=2.0, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor=C_MID, lw=1.6, zorder=7
    ))

    footer = (
        f"0-3 bln incl. PSB 01-10, PSB 11-20, PSB 21-31  |  "
        f"Color scale %C3MR: hijau=tinggi, merah=rendah (per LOS group)  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: bwmp_c3mr_dd"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer,
            fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Dikirim sebagai document (bukan foto) -> tidak kena batas ~10000px
    # Telegram dan tidak dikompres, jadi dpi bisa tetap tinggi.
    plt.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
