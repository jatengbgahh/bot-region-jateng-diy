"""
renderer_caps.py — Render tabel CAPS (Churn) per LoS
Tone warna mengikuti renderer_c3mr.py:
  - Header grup alternating navy / merah tua
  - Region = orange, Branch = grey, WOK = zebra
  - MoM: churn naik = merah (jelek), turun = hijau (bagus)
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import (col_width, FS_DATA, FS_LABEL, FS_HDR, FS_SUBHDR)

C_BG        = "white"
C_HDR_NAVY   = "#1B3A6B"
C_HDR_NAVY_D = "#152d54"
C_HDR_RED    = "#8B2500"
C_HDR_RED_D  = "#6b1c00"
C_HDR_TERR   = "#2C3E50"
C_REGION_BG  = "#2C3E50"
C_BRANCH_BG  = "#D5D8DC"
C_WOK_ODD    = "white"
C_WOK_EVEN   = "#F4F6F7"
C_SEP        = "#BDC3C7"
C_WHITE      = "white"
C_DARK       = "#1A1A1A"
C_MID        = "#2C3E50"
C_POS_BAD    = "#C0392B"   # churn naik = merah
C_NEG_GOOD   = "#1E8449"   # churn turun = hijau

GROUP_ORDER  = ["total", "new_sales", "m1_3", "m4_6", "m7_12", "y1_2", "gt2y"]
GROUP_LABEL  = {
    "total"     : "TOTAL All LoS",
    "new_sales" : "New Sales",
    "m1_3"      : "1-3 Bulan",
    "m4_6"      : "4-6 Bulan",
    "m7_12"     : "7-12 Bulan",
    "y1_2"      : "1-2 Tahun",
    "gt2y"      : ">2 Tahun",
}


def _fmt_num(v) -> str:
    if v is None:
        return "-"
    return f"{int(round(v)):,}"


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    return f"{v:.1f}%"


def _fmt_mom(v) -> str:
    if v is None:
        return "-"
    s = "+" if v > 0 else ""
    return f"{s}{v:.1f}%"


def _ach_color_scale(value, vmin, vmax):
    """
    Green-White-Red color scale utk Ach, KEBALIKAN dari %C3MR:
    Ach tinggi (churn banyak dibanding target) = merah, rendah = hijau.
    Return (bg_hex, fg_hex).
    """
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None

    t = (value - vmin) / (vmax - vmin)   # 0.0=hijau, 0.5=putih, 1.0=merah
    t = max(0.0, min(1.0, t))

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rwg_inv", ["#27AE60", "#FFFFFF", "#E74C3C"]
    )
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r*255), int(g*255), int(b*255))

    lum = 0.299*r + 0.587*g + 0.114*b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"

    return bg_hex, fg_hex


def _ach_color_scale(value, vmin, vmax):
    """
    Green-White-Red color scale utk Ach (Achievement churn thd target).
    Semakin TINGGI Ach = semakin merah (churn banyak = jelek).
    Semakin RENDAH Ach = semakin hijau (churn dikit = bagus).
    Return (bg_hex, fg_hex).
    """
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None

    t = (value - vmin) / (vmax - vmin)   # 0.0=hijau(rendah), 1.0=merah(tinggi)
    t = max(0.0, min(1.0, t))

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "gwr_inv", ["#27AE60", "#FFFFFF", "#E74C3C"]
    )
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r*255), int(g*255), int(b*255))

    lum = 0.299*r + 0.587*g + 0.114*b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"

    return bg_hex, fg_hex


def _clip_to_cell(ax, txt_obj, x, y, w, h):
    """Safety net: paksa clip teks ke area sel-nya sendiri, supaya walau
    pengukuran/estimasi meleset, teks tidak PERNAH crossing visual ke kolom
    lain (dipotong, bukan tumpang tindih)."""
    clip_rect = plt.Rectangle((x, y), w, h, transform=ax.transData)
    txt_obj.set_clip_path(clip_rect)


def render_caps(data: dict, cutoff: str = None, note: str = None) -> BytesIO:
    tgl_closing  = data["tgl_closing"]
    bi_label     = data["bi_label"]
    bl_label     = data["bl_label"]
    region       = data["region"]
    branches     = data["branches"]
    woks         = data["woks"]
    group_order  = data["group_order"]      # e.g. ["new_sales","m1_3",...]

    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "br",  **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    # ── Range Ach: WOK + Branch (Region dikecualikan) ──────────────────────
    ach_vals = [r.get("ach") for r in all_rows
                if r["_t"] in ("wok", "br") and r.get("ach") is not None]
    ach_min, ach_max = (min(ach_vals), max(ach_vals)) if ach_vals else (None, None)

    # ── Range Ach: WOK + Branch (Region dikecualikan) ──────────────────────
    ach_vals = [r.get("ach") for r in all_rows
                if r["_t"] in ("wok", "br") and r.get("ach") is not None]
    ach_min, ach_max = (min(ach_vals), max(ach_vals)) if ach_vals else (None, None)

    # ── Lebar kolom: dihitung dari isi pada FONT TETAP ────────────────────
    # (font tidak pernah dikecilkan; kolomnya yang menyesuaikan — lihat
    # renderer_caps_font.py)
    def _br_of(r):
        return r.get("name","") if r["_t"]=="br" else (REGION_NAME if r["_t"]=="reg" else r.get("branch",""))

    def _wok_of(r):
        return r.get("name","") if r["_t"]=="wok" else (REGION_NAME if r["_t"]=="reg" else "")

    CW_BR  = col_width([_br_of(r)  for r in all_rows], FS_LABEL, minw=1.75)
    CW_WOK = col_width([_wok_of(r) for r in all_rows], FS_LABEL, minw=3.10)

    # Lebar dihitung PER JENIS kolom, bukan satu lebar untuk semuanya: MoM
    # ("-100.0%") jauh lebih lebar dari angka LoS ("0"), dan kalau semua
    # disamakan ke yang terlebar, tabel melar — dengan 6 grup LoS gambarnya
    # kelewat lebar, dpi ke-cap, dan tulisan malah terlihat kecil.
    # Pola lebarnya tetap berulang sama di tiap grup, jadi grid tetap rapi.
    s_tgt  = ["Target"] + [_fmt_num(r.get("target")) for r in all_rows]
    s_tm1  = ["M-1"]    + [_fmt_num(r.get("m1"))     for r in all_rows]
    s_tm   = ["M"]      + [_fmt_num(r.get("m"))      for r in all_rows]
    s_tmom = ["MoM"]    + [_fmt_mom(r.get("mom"))    for r in all_rows]
    s_ach  = ["Ach"]    + [_fmt_pct(r.get("ach"))    for r in all_rows]

    s_gm1, s_gm, s_gmom = ["M-1"], ["M"], ["MoM"]
    for r in all_rows:
        for gkey in group_order:
            s_gm1.append(_fmt_num(r.get(f"{gkey}_m1")))
            s_gm.append(_fmt_num(r.get(f"{gkey}_m")))
            s_gmom.append(_fmt_mom(r.get(f"{gkey}_mom")))

    _w = lambda ss, mw: col_width(ss, FS_DATA, minw=mw, pad=0.20)
    total_cw = [_w(s_tgt, 1.00), _w(s_tm1, 0.95), _w(s_tm, 0.95),
                _w(s_tmom, 1.05), _w(s_ach, 1.00)]
    grp_cw   = [_w(s_gm1, 0.95), _w(s_gm, 0.95), _w(s_gmom, 1.05)]

    n_groups = len(group_order)
    col_widths = [CW_BR, CW_WOK] + total_cw + grp_cw * n_groups
    TW = sum(col_widths)

    # kolom offset awal tiap grup (index ke col_widths)
    off_total = 2
    off_grp   = [off_total + len(total_cw) + i * len(grp_cw) for i in range(n_groups)]

    RH  = 0.50
    HH1 = 0.52
    HH2 = 0.34
    TH  = 0.75 + (0.30 if note else 0.0)   # +1 baris keterangan sumber/tanggal
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
            "CAPS (Churn) IndiHome Jateng-DIY",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label} ({bi_label} vs {bl_label})"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")
    if note:
        ax.text(MG, FH - 0.80, note,
                ha="left", va="top", fontsize=13, color="#95A5A6", style="italic")

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=FS_HDR):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.2)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    hcell(xs[0], yh2, CW_BR + CW_WOK, HH1 + HH2, "TERRITORY", C_HDR_TERR, fs=FS_HDR)

    # Header grup: alternating navy / merah, mulai dari TOTAL All LoS = navy
    group_keys_full = ["total"] + list(group_order)
    group_starts     = [off_total] + off_grp
    group_widths_sum = [sum(total_cw)] + [sum(grp_cw)] * n_groups

    for gi, (gkey, gstart, gw) in enumerate(zip(group_keys_full, group_starts, group_widths_sum)):
        top_bg = C_HDR_NAVY if gi % 2 == 0 else C_HDR_RED
        sub_bg = C_HDR_NAVY_D if gi % 2 == 0 else C_HDR_RED_D
        hcell(xs[gstart], yh1, gw, HH1, GROUP_LABEL[gkey], top_bg, fs=FS_HDR)

        if gkey == "total":
            sub_labels = ["Target", "M-1", "M", "MoM", "Ach"]
            widths     = total_cw
        else:
            sub_labels = ["M-1", "M", "MoM"]
            widths     = grp_cw

        cur = gstart
        for j, lbl in enumerate(sub_labels):
            hcell(xs[cur], yh2, widths[j], HH2, lbl, sub_bg, fs=FS_SUBHDR)
            cur += 1

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
            bg, fg, bold = C_REGION_BG, C_WHITE, True
        elif rtype == "br":
            bg, fg, bold = C_BRANCH_BG, C_DARK,  True
        else:
            bg = C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN
            fg, bold = C_DARK, False
            wi += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def cell(ci, txt, color=None):
            t = str(txt) if txt is not None else "-"
            t_obj = ax.text(cx(ci), mid_y, t,
                    ha="center", va="center", fontsize=FS_DATA,
                    fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3)
            _clip_to_cell(ax, t_obj, xs[ci], cur_y, col_widths[ci], RH)

        def lbl_cell(ci, txt):
            maxw = col_widths[ci]
            t_obj = ax.text(xs[ci] + 0.08, mid_y, txt,
                    ha="left", va="center", fontsize=FS_LABEL,
                    fontweight="bold", color=fg, zorder=3)
            _clip_to_cell(ax, t_obj, xs[ci], cur_y, maxw, RH)

        def mom_cell(ci, v):
            if v is None:
                cell(ci, "-"); return
            # churn naik (v>0) = merah (jelek), turun (v<0) = hijau (bagus)
            color = fg if bold else (C_POS_BAD if v > 0 else (C_NEG_GOOD if v < 0 else fg))
            cell(ci, _fmt_mom(v), color=color)

        def ach_cell(ci, v):
            txt = _fmt_pct(v)
            if rtype in ("wok", "br") and v is not None:
                bg_cs, fg_cs = _ach_color_scale(v, ach_min, ach_max)
                if bg_cs:
                    pad = 0.04
                    ax.add_patch(plt.Rectangle(
                        (xs[ci] + pad, cur_y + pad),
                        col_widths[ci] - pad * 2, RH - pad * 2,
                        color=bg_cs, zorder=2
                    ))
                    t_obj = ax.text(cx(ci), mid_y, txt,
                            ha="center", va="center", fontsize=FS_DATA,
                            fontweight="bold" if bold else "normal",
                            color=fg_cs, zorder=3)
                    _clip_to_cell(ax, t_obj, xs[ci], cur_y, col_widths[ci], RH)
                    return
            cell(ci, txt)

        br_lbl  = row.get("name","") if rtype=="br" else (REGION_NAME if rtype=="reg" else row.get("branch",""))
        wok_lbl = row.get("name","") if rtype=="wok" else (REGION_NAME if rtype=="reg" else "")
        lbl_cell(0, br_lbl)
        lbl_cell(1, wok_lbl)

        # TOTAL All LoS
        cell(off_total + 0, _fmt_num(row.get("target")))
        cell(off_total + 1, _fmt_num(row.get("m1")))
        cell(off_total + 2, _fmt_num(row.get("m")))
        mom_cell(off_total + 3, row.get("mom"))
        ach_cell(off_total + 4, row.get("ach"))

        # Per grup LoS
        for gi, gkey in enumerate(group_order):
            base = off_grp[gi]
            cell(base + 0, _fmt_num(row.get(f"{gkey}_m1")))
            cell(base + 1, _fmt_num(row.get(f"{gkey}_m")))
            mom_cell(base + 2, row.get(f"{gkey}_mom"))

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    group_edge_xs = [xs[0]] + [xs[s] for s in group_starts] + [xs[-1] + col_widths[-1]]
    for gx in group_edge_xs:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"MoM: churn naik = merah, turun = hijau  |  Ach = M / Target x 100% "
        f"(color scale: tinggi=merah, rendah=hijau, range WOK+Branch)  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: churn_dd_YYYYMM"
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
