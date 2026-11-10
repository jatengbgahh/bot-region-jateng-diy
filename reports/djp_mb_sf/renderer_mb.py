"""
renderer_mb.py — Render tabel MB (Morning Briefing) SF Performance
Kolom: TERRITORY (Branch|WOK) | SF REG | TODAY: SF MB | MtD: SF MB | MoM | %SF MB | MoM
Tone warna sama dengan renderer_djp.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO
from config import REGION_NAME

C_BG        = "white"
C_HDR_TODAY = "#1B3A6B"
C_HDR_MTD   = "#8B2500"
C_HDR_SUB   = "#2C3E50"
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
_DARKER_MTD = "#6b1c00"


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
    """
    Green-White-Red color scale untuk %SF MB (conditional formatting,
    gaya sama dengan Ach di renderer_caps.py — arahnya KEBALIKAN dari CAPS:
    %SF MB tinggi (SF aktif MB banyak dibanding SF Reg) = hijau (bagus),
    %SF MB rendah = merah (jelek).
    Return (bg_hex, fg_hex).
    """
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None

    t = (value - vmin) / (vmax - vmin)   # 0.0=merah(rendah), 1.0=hijau(tinggi)
    t = max(0.0, min(1.0, t))

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rwg", ["#E74C3C", "#FFFFFF", "#27AE60"]
    )
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r*255), int(g*255), int(b*255))

    lum = 0.299*r + 0.587*g + 0.114*b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"

    return bg_hex, fg_hex


def render_mb(data: dict, cutoff: str = None) -> BytesIO:
    tgl      = data["tgl"]
    bl_label = data["bl_label"]
    region   = data["region"]
    branches = data["branches"]
    woks     = data["woks"]

    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "br",  **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    # ── Range %SF MB: WOK + Branch (Region dikecualikan) ───────────────────
    pct_vals = [r.get("mtd_pct_sf_mb") for r in all_rows
                if r["_t"] in ("wok", "br") and r.get("mtd_pct_sf_mb") is not None]
    pct_min, pct_max = (min(pct_vals), max(pct_vals)) if pct_vals else (None, None)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_BR     = 1.90
    CW_WOK    = 3.85
    CW_SFREG  = 1.20   # SF REG
    CW_SFMB   = 1.20   # SF MB (TODAY & MtD)
    CW_MOM    = 1.25   # MoM
    CW_PCT    = 1.55   # %SF MB

    # [0]=BR [1]=WOK [2]=SF REG
    # TODAY: [3]=SF MB
    # MtD:   [4]=SF MB [5]=MoM [6]=%SF MB [7]=MoM
    col_widths = [
        CW_BR, CW_WOK, CW_SFREG,
        CW_SFMB,                        # TODAY
        CW_SFMB, CW_MOM, CW_PCT, CW_MOM,  # MtD
    ]
    TW = sum(col_widths)

    RH  = 0.52
    HH1 = 0.50
    HH2 = 0.46
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
            "Evaluasi Aktivitas Morning Briefing SF IndiHome Jateng-DIY",
            ha="left", va="top", fontsize=18, fontweight="bold", color=C_MID)
    subtitle = f"Update {tgl.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label}"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=14, color="#7F8C8D")

    # ── Header helper ─────────────────────────────────────────────────────
    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=13):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.15)

    _renderer = fig.canvas.get_renderer()

    def _text_w(txt, fs):
        t = ax.text(0, -999, txt, fontsize=fs, fontweight="bold")
        bb = t.get_window_extent(renderer=_renderer)
        t.remove()
        return bb.width / fig.dpi

    def hcell_fit(ci, y, h, txt, bg, fg=C_WHITE, target_fs=13, min_fs=9):
        w = col_widths[ci]; avail = w - 0.12
        fs = target_fs
        if _text_w(txt, fs) <= avail:
            hcell(xs[ci], y, w, h, txt, bg, fg=fg, fs=fs)
            return
        words = txt.split()
        if len(words) >= 2:
            mid = len(words) // 2
            for split_at in [mid, mid-1, mid+1]:
                if 0 < split_at < len(words):
                    l1 = " ".join(words[:split_at])
                    l2 = " ".join(words[split_at:])
                    if max(_text_w(l1, fs), _text_w(l2, fs)) <= avail:
                        hcell(xs[ci], y, w, h, f"{l1}\n{l2}", bg, fg=fg, fs=fs)
                        return
        while fs > min_fs:
            fs -= 0.5
            if _text_w(txt, fs) <= avail:
                break
        hcell(xs[ci], y, w, h, txt, bg, fg=fg, fs=fs)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    # Row 1: TERRITORY | SF REG | TODAY | MtD
    w_terr  = CW_BR + CW_WOK
    w_today = CW_SFMB
    w_mtd   = CW_SFMB + CW_MOM + CW_PCT + CW_MOM

    hcell(xs[0], yh2, w_terr,  HH1 + HH2, "TERRITORY", C_HDR_SUB,   fs=14)
    hcell(xs[2], yh2, CW_SFREG, HH1 + HH2, "SF REG",   C_HDR_SUB,   fs=13)
    hcell(xs[3], yh1, w_today, HH1,        "TODAY",     C_HDR_TODAY, fs=14)
    hcell(xs[4], yh1, w_mtd,   HH1,        "MtD",       C_HDR_MTD,   fs=14)

    # Row 2: sub-header
    hcell_fit(3, yh2, HH2, "SF MB",    C_HDR_TODAY)
    hcell_fit(4, yh2, HH2, "SF MB",    C_HDR_MTD)
    hcell_fit(5, yh2, HH2, "MoM",      _DARKER_MTD)
    hcell_fit(6, yh2, HH2, "%SF MB",   C_HDR_MTD)
    hcell_fit(7, yh2, HH2, "MoM",      _DARKER_MTD)

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
            t = str(txt) if txt is not None else "-"
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

        def num_cell(ci, v):
            cell(ci, _fmt(v))

        def mom_cell(ci, v):
            if v is None:
                cell(ci, "-"); return
            color = fg if bold else (C_POS if v >= 0 else C_NEG)
            cell(ci, _fmt(v, pct=True), color=color)

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

        # Data
        num_cell(2, row.get("sf_reg"))         # SF REG
        num_cell(3, row.get("today_sf_mb"))    # TODAY SF MB
        num_cell(4, row.get("mtd_sf_mb"))      # MtD SF MB
        mom_cell(5, row.get("mtd_sf_mb_mom"))  # MoM SF MB
        pct_color_cell(6, row.get("mtd_pct_sf_mb"))  # %SF MB (conditional formatting)
        mom_cell(7, row.get("mtd_pct_sf_mb_mom"))  # MoM %SF MB

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    for gx in [xs[3], xs[4], xs[-1] + col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"SF MB = SF yang melakukan Morning Briefing  |  "
        f"%SF MB = SF MB / SF REG bulan N  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: CSV Manual"
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
