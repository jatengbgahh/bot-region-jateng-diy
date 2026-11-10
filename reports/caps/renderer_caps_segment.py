"""
renderer_caps_segment.py — Render tabel CAPS (Churn) per Customer Segment
Layout: TERRITORY | Seg1[Jml, Cont., MoM] | Seg2[Jml, Cont., MoM] | ...
Tone warna SAMA dengan renderer_caps.py:
  - Header grup alternating navy / merah tua
  - Region = orange, Branch = grey, WOK = zebra
  - MoM: TIDAK pakai background/color-scale (bukan metrik achievement thd
    target) — cuma warna teks: churn naik (+) = merah, turun (-) = hijau
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import (col_width, FS_DATA, FS_LABEL, FS_HDR, FS_SUBHDR)

C_BG         = "white"
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


def _clip_to_cell(ax, txt_obj, x, y, w, h):
    """Safety net: paksa clip teks ke area sel-nya sendiri, supaya teks tidak
    PERNAH crossing visual ke kolom lain (dipotong, bukan tumpang tindih)."""
    clip_rect = plt.Rectangle((x, y), w, h, transform=ax.transData)
    txt_obj.set_clip_path(clip_rect)


def render_caps_segment(data: dict, cutoff: str = None, note: str = None) -> BytesIO:
    tgl_closing   = data["tgl_closing"]
    bl_label      = data["bl_label"]
    region        = data["region"]
    branches      = data["branches"]
    woks          = data["woks"]
    segment_order = data["segment_order"]
    segment_label = data["segment_label"]

    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "br",  **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    # ── Lebar kolom: dihitung dari isi pada FONT TETAP ────────────────────
    # (font tidak pernah dikecilkan; kolomnya yang menyesuaikan — lihat
    # renderer_caps_font.py)
    def _br_of(r):
        return r.get("name","") if r["_t"]=="br" else (REGION_NAME if r["_t"]=="reg" else r.get("branch",""))

    def _wok_of(r):
        return r.get("name","") if r["_t"]=="wok" else (REGION_NAME if r["_t"]=="reg" else "")

    CW_BR  = col_width([_br_of(r)  for r in all_rows], FS_LABEL, minw=1.75)
    CW_WOK = col_width([_wok_of(r) for r in all_rows], FS_LABEL, minw=3.10)

    # Lebar dihitung PER JENIS kolom (Jml / Cont. / MoM), bukan satu lebar untuk
    # semuanya: MoM ("+233.3%") jauh lebih lebar dari Jml ("13"), dan kalau
    # semua disamakan ke yang terlebar, tabel jadi melar — dengan 11 segmen
    # gambarnya kelewat lebar, dpi ke-cap, dan tulisan malah terlihat kecil.
    # Pola lebarnya tetap berulang sama di tiap segmen, jadi grid tetap rapi.
    s_jml, s_cont, s_mom = ["Jml"], ["Cont."], ["MoM"]
    for r in all_rows:
        for seg in segment_order:
            sm = r["segments"][seg]
            s_jml.append(_fmt_num(sm["jml"]))
            s_cont.append(_fmt_pct(sm["cont"]))
            s_mom.append(_fmt_mom(sm["mom"]))

    sub_cw = [col_width(s_jml,  FS_DATA, minw=0.85, pad=0.20),
              col_width(s_cont, FS_DATA, minw=0.85, pad=0.20),
              col_width(s_mom,  FS_DATA, minw=0.95, pad=0.20)]

    n_seg = len(segment_order)
    col_widths = [CW_BR, CW_WOK] + sub_cw * n_seg
    TW = sum(col_widths)

    seg_starts = [2 + i * len(sub_cw) for i in range(n_seg)]

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
            "CAPS (Churn) by Customer Segment IndiHome Jateng-DIY",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label}"
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
                multialignment="center", linespacing=1.15)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    hcell(xs[0], yh2, CW_BR + CW_WOK, HH1 + HH2, "TERRITORY", C_HDR_TERR, fs=FS_HDR)

    # Header per segment: alternating navy / merah tua (sama seperti CAPS per-LoS)
    for si, seg in enumerate(segment_order):
        gstart = seg_starts[si]
        top_bg = C_HDR_NAVY if si % 2 == 0 else C_HDR_RED
        sub_bg = C_HDR_NAVY_D if si % 2 == 0 else C_HDR_RED_D
        gw = sum(sub_cw)

        lbl = segment_label[seg]
        words = lbl.split()
        mid = max(1, len(words) // 2)
        lbl2 = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
        hcell(xs[gstart], yh1, gw, HH1, lbl2, top_bg, fs=FS_HDR)

        sub_labels = ["Jml", "Cont.", "MoM"]
        cur = gstart
        for j, lbl_s in enumerate(sub_labels):
            hcell(xs[cur], yh2, sub_cw[j], HH2, lbl_s, sub_bg, fs=FS_SUBHDR)
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
            txt = _fmt_mom(v)
            # bukan achievement thd target -> tanpa background, cuma warna teks:
            # churn naik (+) = merah (jelek), turun (-) = hijau (bagus)
            color = fg if bold else (C_POS_BAD if (v or 0) > 0 else (C_NEG_GOOD if (v or 0) < 0 else fg))
            cell(ci, txt, color=color if v is not None else None)

        br_lbl  = row.get("name","") if rtype=="br" else (REGION_NAME if rtype=="reg" else row.get("branch",""))
        wok_lbl = row.get("name","") if rtype=="wok" else (REGION_NAME if rtype=="reg" else "")
        lbl_cell(0, br_lbl)
        lbl_cell(1, wok_lbl)

        for si, seg in enumerate(segment_order):
            base = seg_starts[si]
            sm = row["segments"][seg]
            cell(base + 0, _fmt_num(sm["jml"]))
            cell(base + 1, _fmt_pct(sm["cont"]))
            mom_cell(base + 2, sm["mom"])

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    group_edge_xs = [xs[0]] + [xs[s] for s in seg_starts] + [xs[-1] + col_widths[-1]]
    for gx in group_edge_xs:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"MoM: churn naik = merah, turun = hijau  |  "
        f"Cont. = Jml segmen / Jml total churn baris tsb  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: churn_dd_YYYYMM + ih_cb_cvm_prfl_mm_YYYYMM (bulan N-1)"
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
