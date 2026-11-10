"""
renderer_pdd.py — Render tabel Sales PDD (Pembayaran di Depan) per WOK/BRANCH IndiHome Jateng-DIY
Style & tone warna mengikuti renderer_sf.py / renderer_djp.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs

C_BG        = "white"
C_HDR_SFACT = "#1B3A6B"
C_HDR_PDD   = "#8B2500"
C_HDR_TRX   = "#1E6B31"
C_HDR_CONTR = "#4A235A"
C_HDR_SUB   = "#2C3E50"
C_REGION_BG = "#2C3E50"
C_BRANCH_BG = "#D5D8DC"
C_WOK_ODD   = "white"
C_WOK_EVEN  = "#F4F6F7"
C_SEP       = "#BDC3C7"
C_WHITE     = "white"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"

CHANNEL_ORDER = ["AGENCY", "GRAPARI", "SOBI", "WEB_APPS"]
CHANNEL_LABEL = {"AGENCY": "Agency", "GRAPARI": "GraPARI", "SOBI": "SOBI", "WEB_APPS": "Web & Apps"}


def _fmt(v, dec=0, pct=False, no_sign=False):
    if v is None:
        return "-"
    if pct:
        if no_sign:
            return f"{v:.1f}%"
        s = "+" if v > 0 else ""
        return f"{s}{v:.1f}%"
    if dec > 0:
        return f"{v:.{dec}f}"
    return f"{int(v):,}"


def _pct_color_scale(value, vmin, vmax):
    """Green-White-Red: %SF Active tinggi = hijau (bagus), rendah = merah."""
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None
    t = (value - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rwg", ["#E74C3C", "#FFFFFF", "#27AE60"]
    )
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r*255), int(g*255), int(b*255))
    lum = 0.299*r + 0.587*g + 0.114*b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"
    return bg_hex, fg_hex


def render_pdd(data: dict, cutoff: str = None) -> BytesIO:
    tgl      = data["tgl_closing"]
    bi_label = data["bi_label"]
    region   = data["region"]
    branches = data["branches"]
    woks     = data["woks"]

    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "br",  **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    # ── Range %SF Active: WOK + Branch (Region dikecualikan) ────────────────
    pct_vals = [r.get("pct_sf_active") for r in all_rows
                if r["_t"] in ("wok", "br") and r.get("pct_sf_active") is not None]
    pct_min, pct_max = (min(pct_vals), max(pct_vals)) if pct_vals else (None, None)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_BR = 2.15
    CW_WOK = 4.75
    CW_NUM  = 1.15
    CW_PCT  = 1.30
    CW_AVG  = 1.15

    # Struktur: [0]=BR [1]=WOK [2]=SF ACTIVE
    #   PDD:    [3]=SF Active [4]=%SF Active [5]=New Sales [6]=Avg Sales
    #   TRX:    [7]=Agency [8]=GraPARI [9]=SOBI [10]=Web&Apps
    #   Contr:  [11]=Agency [12]=GraPARI [13]=SOBI [14]=Web&Apps
    col_widths = [
        CW_BR, CW_WOK, CW_NUM,
        CW_NUM, CW_PCT, CW_NUM, CW_AVG,
        CW_NUM, CW_NUM, CW_NUM, CW_NUM,
        CW_PCT, CW_PCT, CW_PCT, CW_PCT,
    ]
    TW = sum(col_widths)

    RH  = 0.52
    HH1 = 0.50
    HH2 = 0.56
    TH  = 0.75
    MG  = 0.25

    FH = TH + HH1 + HH2 + len(all_rows) * RH + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW)
    ax.set_ylim(0, FH)
    ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)

    def cx(i):
        return xs[i] + col_widths[i] / 2

    # ── Judul ─────────────────────────────────────────────────────────────
    ax.text(MG, FH - 0.18,
            "Sales PDD (Pembayaran di Depan) Indihome Jateng DIY",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl.strftime('%d-%m-%Y')}  ({bi_label})"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    # ── Header helper ─────────────────────────────────────────────────────
    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=13):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.15)

    _renderer = fig.canvas.get_renderer()

    def _text_width_inches(txt, fs):
        t = ax.text(0, -999, txt, fontsize=fs, fontweight="bold",
                    ha="center", va="center")
        bb = t.get_window_extent(renderer=_renderer)
        t.remove()
        return bb.width / fig.dpi

    def hcell_fit(ci, y, h, txt, bg, fg=C_WHITE, target_fs=12, min_fs=8):
        w = col_widths[ci]
        avail = w - 0.12
        fs = target_fs
        if _text_width_inches(txt, fs) <= avail:
            hcell(xs[ci], y, w, h, txt, bg, fg=fg, fs=fs)
            return
        words = txt.split()
        best_split = None
        if len(words) >= 2:
            mid = len(words) // 2
            for split_at in [mid, mid-1, mid+1]:
                if 0 < split_at < len(words):
                    line1 = " ".join(words[:split_at])
                    line2 = " ".join(words[split_at:])
                    max_w = max(_text_width_inches(line1, fs), _text_width_inches(line2, fs))
                    if max_w <= avail:
                        best_split = f"{line1}\n{line2}"
                        break
        if best_split:
            hcell(xs[ci], y, w, h, best_split, bg, fg=fg, fs=fs)
            return
        while fs > min_fs:
            fs -= 0.5
            if _text_width_inches(txt, fs) <= avail:
                break
        hcell(xs[ci], y, w, h, txt, bg, fg=fg, fs=fs)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    # Row 1: TERRITORY | SF ACTIVE | PDD | TRX BY CHANNEL | CONTR PDD BY CHANNEL
    w_terr   = CW_BR + CW_WOK
    w_pdd    = CW_NUM + CW_PCT + CW_NUM + CW_AVG
    w_trx    = CW_NUM * 4
    w_contr  = CW_PCT * 4

    hcell(xs[0],  yh2, w_terr,  HH1 + HH2, "TERRITORY", C_HDR_SUB,   fs=14)
    hcell(xs[2],  yh2, CW_NUM,  HH1 + HH2, "SF\nACTIVE", C_HDR_SFACT, fs=12)
    hcell(xs[3],  yh1, w_pdd,   HH1,       "PDD",        C_HDR_PDD,   fs=14)
    hcell(xs[7],  yh1, w_trx,   HH1,       "TRX BY CHANNEL", C_HDR_TRX, fs=14)
    hcell(xs[11], yh1, w_contr, HH1,       "CONTR PDD BY CHANNEL", C_HDR_CONTR, fs=13)

    # Row 2: sub-header
    hcell_fit(3, yh2, HH2, "SF Active", C_HDR_PDD)
    hcell_fit(4, yh2, HH2, "%SF Active", C_HDR_PDD)
    hcell_fit(5, yh2, HH2, "New Sales PDD by SF", C_HDR_PDD)
    hcell_fit(6, yh2, HH2, "Avg Sales PDD by SF", C_HDR_PDD)

    for i, ch in enumerate(CHANNEL_ORDER):
        hcell_fit(7 + i,  yh2, HH2, CHANNEL_LABEL[ch], C_HDR_TRX)
        hcell_fit(11 + i, yh2, HH2, CHANNEL_LABEL[ch], C_HDR_CONTR)

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
            t = str(txt) if txt is not None else "-"
            f2 = fs
            while f2 > 6.0 and len(t) * 0.068 * f2 / 10 > col_widths[ci] - 0.10:
                f2 -= 0.4
            ax.text(cx(ci), mid_y, t,
                    ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl_cell(xi, txt, maxw):
            f2 = fit_fs(txt, fs, maxw, floor=6.0)
            ax.text(xi, mid_y, txt,
                    ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        def num_cell(ci, v, dec=0):
            cell(ci, _fmt(v, dec=dec))

        def pct_color_cell(ci, v):
            txt = _fmt(v, pct=True, no_sign=True) if v is not None else "-"
            if rtype in ("wok", "br") and v is not None:
                bg_cs, fg_cs = _pct_color_scale(v, pct_min, pct_max)
                if bg_cs:
                    pad = 0.04
                    ax.add_patch(plt.Rectangle(
                        (xs[ci] + pad, cur_y + pad),
                        col_widths[ci] - pad * 2, RH - pad * 2,
                        color=bg_cs, zorder=2
                    ))
                    f2 = fs
                    while f2 > 6.0 and len(txt) * 0.068 * f2 / 10 > col_widths[ci] - 0.08:
                        f2 -= 0.4
                    ax.text(cx(ci), mid_y, txt,
                            ha="center", va="center", fontsize=f2,
                            fontweight="bold" if bold else "normal",
                            color=fg_cs, zorder=3, clip_on=True)
                    return
            cell(ci, txt)

        # Territory
        br_lbl = (
            row.get("name", "") if rtype == "br"
            else (REGION_NAME   if rtype == "reg"
                  else row.get("branch", ""))
        )
        wok_lbl = (
            row.get("name", "") if rtype == "wok"
            else (REGION_NAME   if rtype == "reg" else "")
        )
        lbl_cell(xs[0] + 0.08, br_lbl,  CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)

        # SF ACTIVE (base)
        num_cell(2, row.get("sf_active"))

        # PDD group
        num_cell(3, row.get("sf_active_pdd"))
        pct_color_cell(4, row.get("pct_sf_active"))
        num_cell(5, row.get("new_sales_pdd_by_sf"))
        v_avg = row.get("avg_sales_pdd_by_sf")
        cell(6, _fmt(v_avg, dec=1) if v_avg is not None else "-")

        # TRX by Channel
        for i, ch in enumerate(CHANNEL_ORDER):
            num_cell(7 + i, row.get(f"trx_{ch}"))

        # Contr PDD by Channel
        for i, ch in enumerate(CHANNEL_ORDER):
            v = row.get(f"contr_{ch}")
            cell(11 + i, _fmt(v, pct=True, no_sign=True) if v is not None else "-")

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    for gx in [xs[3], xs[7], xs[11], xs[-1] + col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"PS = order_id dgn ps_ts valid, order_type NEW SALES  |  "
        f"SF Active PDD = unique SF dengan PS & pdd_enabled=1  |  "
        f"New Sales PDD by SF = PS pdd_enabled=1 channel Agency  |  "
        f"Sumber: indihome_ordering_detail"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer,
            fontsize=6.0, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(300, int(9500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
