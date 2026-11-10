"""
renderer_c3mr10s.py — Render tabel C3MR per Customer Segment (12 segment)
Layout: TERRITORY | Seg1[%C3MR, MoM] | Seg2[%C3MR, MoM] | ... | Seg12[%C3MR, MoM]
Color scale %C3MR: green-white-red (range WOK+Branch)
Style mengikuti renderer_c3mr.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs
from calculator_c3mr10s import SEGMENT_ORDER, SEGMENT_LABEL

C_BG        = "white"
C_HDR_BASE  = "#8B2500"   # header utama — dark red
C_HDR_SUB   = "#6b1c00"   # sub-header
C_HDR_TERR  = "#2C3E50"
C_REGION_BG = "#2C3E50"
C_BRANCH_BG = "#D5D8DC"
C_WOK_ODD   = "white"
C_WOK_EVEN  = "#F4F6F7"
C_SEP       = "#BDC3C7"
C_WHITE     = "white"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"
C_POS       = "#1E8449"
C_NEG       = "#C0392B"

# Warna header per segment — alternating biar mudah dibaca
SEG_COLORS_UNUSED = [
    "#1B3A6B", "#8B2500", "#1E6B31", "#4A235A", "#784212",
    "#1A5276", "#5D4037", "#1B3A6B", "#8B2500", "#1E6B31",
    "#4A235A", "#2C3E50",
]


def _pct_color_scale(value, vmin, vmax):
    """Green-White-Red, hijau=tinggi, merah=rendah."""
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None
    t = max(0.0, min(1.0, (value - vmin) / (vmax - vmin)))
    cmap = mcolors.LinearSegmentedColormap.from_list("gwr", ["#E74C3C", "#FFFFFF", "#27AE60"])
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r*255), int(g*255), int(b*255))
    lum    = 0.299*r + 0.587*g + 0.114*b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"
    return bg_hex, fg_hex


def _fmt_pct(v):
    return "-" if v is None else f"{v:.2f}%"

def _fmt_mom(v):
    if v is None: return "-"
    return f"{'+'if v>0 else''}{v:.2f}%"


def render_c3mr10s(data: dict, cutoff: str = None) -> BytesIO:
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

    # ── Hitung range %C3MR per segment (WOK+Branch) untuk color scale ────
    seg_ranges = {}
    for seg in SEGMENT_ORDER:
        vals = [
            r["segments"][seg]["pct"]
            for r in all_rows
            if r["_t"] in ("wok", "br") and r["segments"][seg]["pct"] is not None
        ]
        seg_ranges[seg] = (min(vals), max(vals)) if vals else (None, None)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_BR = 2.15
    CW_WOK = 4.75
    CW_PCT = 1.10   # %C3MR per segment
    CW_MOM = 1.20   # MoM per segment

    N_SEG = len(SEGMENT_ORDER)
    col_widths = [CW_BR, CW_WOK] + [CW_PCT, CW_MOM] * N_SEG
    TW = sum(col_widths)

    RH  = 0.52
    HH1 = 0.54   # nama segment (bisa 2 baris)
    HH2 = 0.34   # %C3MR | MoM
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
            "C3MR by Customer Segment IndiHome Jateng-DIY",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label}"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=11):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w/2, y + h/2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.15)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    # TERRITORY header (span 2 baris)
    hcell(xs[0], yh2, CW_BR + CW_WOK, HH1 + HH2, "TERRITORY", C_HDR_TERR, fs=13)

    # Header per segment
    _renderer = fig.canvas.get_renderer()

    for si, seg in enumerate(SEGMENT_ORDER):
        ci_pct = 2 + si * 2
        ci_mom = ci_pct + 1
        w_grp  = CW_PCT + CW_MOM
        col    = C_HDR_TERR

        # Label segment dengan nomor, bisa 2 baris
        lbl = SEGMENT_LABEL[seg]
        # Split jadi 2 baris di spasi tengah
        words = lbl.split()
        mid   = len(words) // 2
        lbl2  = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])

        hcell(xs[ci_pct], yh1, w_grp, HH1, lbl2, col, fs=13)
        hcell(xs[ci_pct], yh2, CW_PCT, HH2, "%C3MR", col,       fs=9)
        hcell(xs[ci_mom], yh2, CW_MOM, HH2, "MoM",   C_HDR_TERR, fs=9)

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
            bg, fg, fs, bold = C_REGION_BG, C_WHITE, 14.0, True
        elif rtype == "br":
            bg, fg, fs, bold = C_BRANCH_BG, C_DARK,  14.0, True
        else:
            bg = C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN
            fg, fs, bold = C_DARK, 14.0, False
            wi += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def cell(ci, txt, color=None):
            t  = str(txt) if txt is not None else "-"
            f2 = fs
            while f2 > 5.5 and len(t) * 0.068 * f2 / 10 > col_widths[ci] - 0.08:
                f2 -= 0.3
            ax.text(cx(ci), mid_y, t,
                    ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl_cell(xi, txt, maxw):
            f2 = fit_fs(txt, fs, maxw, floor=5.5, pad=0.15)
            ax.text(xi, mid_y, txt,
                    ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        # Territory
        br_lbl  = row.get("name","") if rtype=="br" else (REGION_NAME if rtype=="reg" else row.get("branch",""))
        wok_lbl = row.get("name","") if rtype=="wok" else (REGION_NAME if rtype=="reg" else "")
        lbl_cell(xs[0] + 0.08, br_lbl,  CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)

        # Per segment
        for si, seg in enumerate(SEGMENT_ORDER):
            ci_pct = 2 + si * 2
            ci_mom = ci_pct + 1
            sm     = row["segments"][seg]
            pct_v  = sm["pct"]
            mom_v  = sm["mom"]

            # %C3MR dengan color scale untuk WOK+Branch
            if rtype in ("wok", "br") and pct_v is not None:
                vmin, vmax = seg_ranges[seg]
                bg_cs, fg_cs = _pct_color_scale(pct_v, vmin, vmax)
                if bg_cs:
                    pad = 0.03
                    ax.add_patch(plt.Rectangle(
                        (xs[ci_pct] + pad, cur_y + pad),
                        col_widths[ci_pct] - pad*2, RH - pad*2,
                        color=bg_cs, zorder=2
                    ))
                    t  = _fmt_pct(pct_v)
                    f2 = fs
                    while f2 > 5.5 and len(t)*0.068*f2/10 > col_widths[ci_pct]-0.08:
                        f2 -= 0.3
                    ax.text(cx(ci_pct), mid_y, t,
                            ha="center", va="center", fontsize=f2,
                            fontweight="bold" if bold else "normal",
                            color=fg_cs, zorder=3, clip_on=True)
                else:
                    cell(ci_pct, _fmt_pct(pct_v))
            else:
                cell(ci_pct, _fmt_pct(pct_v))

            # MoM
            if mom_v is None:
                cell(ci_mom, "-")
            else:
                color = fg if bold else (C_POS if mom_v >= 0 else C_NEG)
                cell(ci_mom, _fmt_mom(mom_v), color=color)

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    # Garis tebal tiap batas segment
    for si in range(N_SEG + 1):
        gx = xs[2 + si * 2] if si < N_SEG else xs[-1] + col_widths[-1]
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.6, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"Color scale %C3MR: hijau=tinggi, merah=rendah (per segment, range WOK+Branch)  |  "
        f"Unmapped = account_num tidak ditemukan di ih_ten_segment_detail  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: bwmp_c3mr_dd + ih_ten_segment_detail"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer,
            fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(180, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
