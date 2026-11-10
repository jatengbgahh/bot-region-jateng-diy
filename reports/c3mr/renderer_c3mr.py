"""
renderer_c3mr.py — Render tabel C3MR
v3:
  - Color scale %C3MR: green-white-red (hijau=tinggi, merah=rendah), berlaku WOK + Branch
  - Bill Amount & Saldo: angka saja tanpa "Rp"
  - Judul: C3MR IndiHome Jateng-DIY
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs

C_BG        = "white"
C_HDR_ET    = "#1B3A6B"
C_HDR_ET_D  = "#152d54"
C_HDR_AL    = "#8B2500"
C_HDR_AL_D  = "#6b1c00"
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


def _fmt_num(v) -> str:
    if v is None:
        return "-"
    return f"{int(round(v)):,}"


def _fmt_bill(v) -> str:
    if v is None:
        return "-"
    return f"{int(round(v)):,}"


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}%"


def _fmt_mom(v) -> str:
    if v is None:
        return "-"
    s = "+" if v > 0 else ""
    return f"{s}{v:.2f}%"


def _pct_color_scale(value, vmin, vmax):
    """
    Green-White-Red color scale seperti Excel conditional formatting.
    Tinggi = hijau, tengah = putih, rendah = merah.
    Return (bg_hex, fg_hex).
    """
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None

    t = (value - vmin) / (vmax - vmin)   # 0.0=merah, 0.5=putih, 1.0=hijau
    t = max(0.0, min(1.0, t))

    # Green-White-Red: hijau (#27AE60) → putih → merah (#E74C3C)
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "gwr", ["#E74C3C", "#FFFFFF", "#27AE60"]
    )
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r*255), int(g*255), int(b*255))

    # Teks: hitam untuk bg terang/putih, putih untuk bg sangat gelap
    lum = 0.299*r + 0.587*g + 0.114*b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"

    return bg_hex, fg_hex


def render_c3mr(data: dict, cutoff: str = None, per_city: bool = False) -> BytesIO:
    """per_city=True → baris per City (kabupaten) + Region, kolom TERRITORY Branch | WOK | City."""
    tgl_closing = data["tgl_closing"]
    bl_label    = data["bl_label"]
    region      = data["region"]

    if per_city:
        all_rows = [{"_t": "wok", **c} for c in data["cities"]] + [{"_t": "reg", **region}]
    else:
        all_rows = (
            [{"_t": "wok", **w} for w in data["woks"]] +
            [{"_t": "br",  **b} for b in data["branches"]] +
            [{"_t": "reg", **region}]
        )

    # ── Range %C3MR: WOK + Branch (Region dikecualikan) ───────────────────
    et_vals = [r.get("et_pct") for r in all_rows
               if r["_t"] in ("wok", "br") and r.get("et_pct") is not None]
    al_vals = [r.get("al_pct") for r in all_rows
               if r["_t"] in ("wok", "br") and r.get("al_pct") is not None]
    et_min, et_max = (min(et_vals), max(et_vals)) if et_vals else (None, None)
    al_min, al_max = (min(al_vals), max(al_vals)) if al_vals else (None, None)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_BR = 2.15
    CW_WOK = 4.75
    CW_SUBS = 1.00
    CW_BILL = 2.50
    CW_PCT  = 1.20
    CW_MOM  = 1.35
    CW_SAL  = 2.50
    CW_UNP  = 1.00
    CW_CITY = 3.30

    sub_cw = [CW_SUBS, CW_BILL, CW_PCT, CW_MOM, CW_SAL, CW_UNP]
    N_SUB  = len(sub_cw)

    lbl_cw     = [CW_BR, CW_WOK, CW_CITY] if per_city else [CW_BR, CW_WOK]
    N_LBL      = len(lbl_cw)
    col_widths = lbl_cw + sub_cw + sub_cw
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
            "C3MR IndiHome Jateng-DIY" + (" per City" if per_city else ""),
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label}"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=13):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.2)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    hcell(xs[0], yh2, sum(lbl_cw), HH1 + HH2, "TERRITORY", C_HDR_TERR, fs=14)

    cs_et = N_LBL
    cs_al = N_LBL + N_SUB
    w_grp = sum(sub_cw)

    hcell(xs[cs_et], yh1, w_grp, HH1, "Early Tenure (Los 0-6 bln)", C_HDR_ET, fs=13)
    hcell(xs[cs_al], yh1, w_grp, HH1, "All LOS",                    C_HDR_AL, fs=13)

    sub_labels = ["Subs", "Bill Amount", "%C3MR", "MoM", "Saldo", "Unpaid"]
    for j, lbl in enumerate(sub_labels):
        hcell(xs[cs_et + j], yh2, sub_cw[j], HH2, lbl, C_HDR_ET_D, fs=11)
        hcell(xs[cs_al + j], yh2, sub_cw[j], HH2, lbl, C_HDR_AL_D, fs=11)

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
            f2 = fit_fs(txt, fs, maxw, floor=6.0)
            ax.text(xi, mid_y, txt,
                    ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        def mom_cell(ci, v):
            if v is None:
                cell(ci, "-"); return
            color = fg if bold else (C_POS if v >= 0 else C_NEG)
            cell(ci, _fmt_mom(v), color=color)

        def pct_cell_colored(ci, v, vmin, vmax):
            txt = _fmt_pct(v)
            # Color scale berlaku untuk WOK dan Branch, tidak untuk Region
            if rtype in ("wok", "br") and v is not None:
                bg_cs, fg_cs = _pct_color_scale(v, vmin, vmax)
                if bg_cs:
                    pad = 0.04
                    ax.add_patch(plt.Rectangle(
                        (xs[ci] + pad, cur_y + pad),
                        col_widths[ci] - pad * 2, RH - pad * 2,
                        color=bg_cs, zorder=2
                    ))
                    f2 = fs
                    while f2 > 6.0 and len(txt) * 0.068 * f2 / 10 > col_widths[ci] - 0.10:
                        f2 -= 0.4
                    ax.text(cx(ci), mid_y, txt,
                            ha="center", va="center", fontsize=f2,
                            fontweight="bold" if bold else "normal",
                            color=fg_cs, zorder=3, clip_on=True)
                    return
            cell(ci, txt)

        br_lbl  = row.get("name","") if rtype=="br" else (REGION_NAME if rtype=="reg" else row.get("branch",""))
        wok_lbl = row.get("name","") if rtype=="wok" else (REGION_NAME if rtype=="reg" else "")
        if per_city and rtype == "wok":
            br_lbl, wok_lbl = row.get("branch", ""), row.get("wok", "")
        lbl_cell(xs[0] + 0.08, br_lbl,  CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)
        if per_city:
            lbl_cell(xs[2] + 0.08, "" if rtype == "reg" else row.get("name", ""), CW_CITY)

        # Early Tenure
        cell(cs_et + 0, _fmt_num(row.get("et_subs")))
        cell(cs_et + 1, _fmt_bill(row.get("et_bill")))
        pct_cell_colored(cs_et + 2, row.get("et_pct"), et_min, et_max)
        mom_cell(cs_et + 3, row.get("et_mom"))
        cell(cs_et + 4, _fmt_bill(row.get("et_saldo")))
        cell(cs_et + 5, _fmt_num(row.get("et_unpaid")))

        # All LOS
        cell(cs_al + 0, _fmt_num(row.get("al_subs")))
        cell(cs_al + 1, _fmt_bill(row.get("al_bill")))
        pct_cell_colored(cs_al + 2, row.get("al_pct"), al_min, al_max)
        mom_cell(cs_al + 3, row.get("al_mom"))
        cell(cs_al + 4, _fmt_bill(row.get("al_saldo")))
        cell(cs_al + 5, _fmt_num(row.get("al_unpaid")))

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    for gx in [xs[cs_et], xs[cs_al], xs[-1] + col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"Early Tenure = los_category: 0-3bln, 4-6bln, PSB 01-10, PSB 11-20, PSB 21-31  |  "
        f"Color scale %C3MR: hijau=tinggi, merah=rendah (range {'City' if per_city else 'WOK+Branch'})  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: bwmp_c3mr_dd"
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
