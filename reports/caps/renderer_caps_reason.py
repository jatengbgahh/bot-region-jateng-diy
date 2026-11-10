"""
renderer_caps_reason.py — Render tabel Top 5 Reason CAPS (DO) per Branch & Region
Layout: TERRITORY (merge 5 baris) | NO | SUB REASON CAPS | M-1 | MtD | Cont. | MoM

Tone warna SAMA dengan renderer_caps.py / renderer_caps_segment.py /
renderer_caps_channel.py:
  - Header navy tua
  - Territory: Region = orange, Branch = grey
  - Baris data zebra; blok Region diberi tint orange muda supaya konsisten
    dgn baris Region di report CAPS lainnya tanpa menenggelamkan angkanya
  - MtD pakai data bar merah muda (in-cell bar), skala per blok territory
  - Cont. polos tanpa background, sama seperti kolom Cont. di /caps by Segmen
  - MoM: warna teks saja tanpa background — churn naik (+) = merah,
    turun (-) = hijau (konvensi semua report CAPS)
  - Ukuran font dipatok di renderer_caps_font.py; lebar kolom yang menyesuaikan
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from renderer_caps_font import (col_width, FS_DATA, FS_LABEL, FS_HDR)

C_BG         = "white"
C_HDR_NAVY   = "#1B3A6B"
C_HDR_RED    = "#8B2500"
C_HDR_TERR   = "#2C3E50"
C_REGION_BG  = "#2C3E50"
C_REGION_ROW = "#FDF2E0"
C_BRANCH_BG  = "#D5D8DC"
C_ROW_ODD    = "white"
C_ROW_EVEN   = "#F4F6F7"
C_SEP        = "#BDC3C7"
C_BLOCK_SEP  = "#7F8C8D"
C_WHITE      = "white"
C_DARK       = "#1A1A1A"
C_MID        = "#2C3E50"
C_BAR        = "#F1948A"   # data bar MtD
C_BAR_EDGE   = "#C0392B"
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
    """Safety net: teks tidak pernah crossing visual ke kolom lain (dipotong)."""
    clip_rect = plt.Rectangle((x, y), w, h, transform=ax.transData)
    txt_obj.set_clip_path(clip_rect)


def render_caps_reason(data: dict, cutoff: str = None, note: str = None) -> BytesIO:
    tgl_closing = data["tgl_closing"]
    bl_label    = data["bl_label"]
    blocks      = data["blocks"]

    # ── Lebar kolom: dihitung dari isi pada FONT TETAP ────────────────────
    # (font tidak pernah dikecilkan; kolomnya yang menyesuaikan — lihat
    # renderer_caps_font.py)
    semua_rows = [r for b in blocks for r in b["rows"]]

    CW_TERR = col_width(
        [b["name"] for b in blocks] + [f"Total CAPS {_fmt_num(b['total'])}" for b in blocks],
        FS_LABEL, minw=2.20
    )
    CW_NO     = 0.70
    CW_REASON = col_width([r["reason"] for r in semua_rows], FS_LABEL, minw=7.40)

    # Semua kolom angka sama lebar biar gridnya rapi & angka pasti muat
    num_samples = ["M-1", "Cont.", "MoM"]
    for r in semua_rows:
        num_samples += [_fmt_num(r["m1"]), _fmt_num(r["mtd"]),
                        _fmt_pct(r["cont"]), _fmt_mom(r["mom"])]
    W_NUM = col_width(num_samples, FS_DATA, minw=1.10)

    NUM_ZONE  = W_NUM                    # zona angka MtD (sisanya buat data bar)
    BAR_ZONE  = 1.05                     # panjang maksimum data bar
    CW_M1     = W_NUM
    CW_MTD    = NUM_ZONE + BAR_ZONE
    CW_CONT   = W_NUM
    CW_MOM    = W_NUM

    col_widths = [CW_TERR, CW_NO, CW_REASON, CW_M1, CW_MTD, CW_CONT, CW_MOM]
    HEADERS    = ["REGION / BRANCH", "NO", "SUB REASON CAPS", "M-1", "MtD", "Cont.", "MoM"]
    TW = sum(col_widths)

    n_rows = len(semua_rows)

    RH = 0.52
    HH = 0.62
    TH = 0.78 + (0.30 if note else 0.0)   # +1 baris keterangan sumber/tanggal
    MG = 0.25

    FH = TH + HH + n_rows * RH + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)
    x_end = xs[-1] + col_widths[-1]

    def cx(i):
        return xs[i] + col_widths[i] / 2

    # ── Judul ─────────────────────────────────────────────────────────────
    ax.text(MG, FH - 0.18,
            "Top 5 Reason CAPS (DO) IndiHome Jateng-DIY",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label}"
    ax.text(MG, FH - 0.52, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")
    # Keterangan sumber + tanggal data (selalu ditampilkan). Teks dari bot.py.
    if note:
        ax.text(MG, FH - 0.82, note,
                ha="left", va="top", fontsize=13, color="#95A5A6", style="italic")

    # ── Header ────────────────────────────────────────────────────────────
    yh = FH - TH - HH
    for i, htxt in enumerate(HEADERS):
        bg = C_HDR_TERR if i < 2 else (C_HDR_NAVY if i < 3 else C_HDR_RED)
        ax.add_patch(plt.Rectangle((xs[i], yh), col_widths[i], HH, color=bg, zorder=2))
        ax.text(cx(i), yh + HH / 2, htxt,
                ha="center", va="center", fontsize=FS_HDR,
                fontweight="bold", color=C_WHITE, zorder=3)

    # ── Baris data ────────────────────────────────────────────────────────
    cur_y = yh
    block_bounds = []      # (y_atas, y_bawah) tiap blok, utk garis pemisah tebal

    for blk in blocks:
        is_reg  = blk["level"] == "REGION"
        rows    = blk["rows"]
        y_top   = cur_y

        # skala data bar: relatif thd reason terbesar di blok itu
        mtd_vals = [r["mtd"] for r in rows if r["mtd"] is not None]
        mtd_max  = max(mtd_vals) if mtd_vals else 0

        for ri, r in enumerate(rows):
            cur_y -= RH
            mid_y = cur_y + RH / 2

            if is_reg:
                bg = C_REGION_ROW
            else:
                bg = C_ROW_ODD if ri % 2 == 0 else C_ROW_EVEN
            ax.add_patch(plt.Rectangle((xs[1], cur_y), TW - col_widths[0], RH,
                                       color=bg, zorder=1))

            fg   = C_DARK
            bold = is_reg

            def cell(ci, txt, color=None, ha="center", fs=FS_DATA):
                if ha == "left":
                    px = xs[ci] + 0.10
                elif ha == "right":
                    px = xs[ci] + col_widths[ci] - 0.10
                else:
                    px = cx(ci)
                t_obj = ax.text(px, mid_y, str(txt),
                                ha=ha, va="center", fontsize=fs,
                                fontweight="bold" if bold else "normal",
                                color=color or fg, zorder=4)
                _clip_to_cell(ax, t_obj, xs[ci], cur_y, col_widths[ci], RH)

            cell(1, r["no"] if r["mtd"] is not None else "-")
            cell(2, r["reason"], ha="left", fs=FS_LABEL)
            cell(3, _fmt_num(r["m1"]))

            # MtD: data bar tumbuh dari kiri, angka rata kanan di zona bebas bar
            # (bar dibatasi BAR_ZONE supaya tidak pernah menimpa angkanya)
            if r["mtd"] is not None and mtd_max:
                bar_pad = 0.06
                bar_w   = (BAR_ZONE - bar_pad) * (r["mtd"] / mtd_max)
                ax.add_patch(plt.Rectangle(
                    (xs[4] + bar_pad, cur_y + bar_pad),
                    max(bar_w, 0.02), RH - bar_pad * 2,
                    facecolor=C_BAR, edgecolor=C_BAR_EDGE, lw=0.4, zorder=2
                ))
            cell(4, _fmt_num(r["mtd"]), ha="right")

            # Cont.: tanpa background, samakan dgn kolom Cont. di /caps by Segmen
            cell(5, _fmt_pct(r["cont"]))

            # MoM: warna teks saja (bukan achievement thd target)
            v = r["mom"]
            mom_color = fg if v is None else (
                C_POS_BAD if v > 0 else (C_NEG_GOOD if v < 0 else fg))
            cell(6, _fmt_mom(v), color=mom_color)

            # garis tipis antar baris di dalam blok (kecuali baris terakhir blok)
            if ri < len(rows) - 1:
                ax.plot([xs[1], x_end], [cur_y, cur_y],
                        color=C_SEP, lw=0.3, zorder=5)

        # ── Sel TERRITORY (merge setinggi blok) ───────────────────────────
        y_bot   = cur_y
        blk_h   = y_top - y_bot
        terr_bg = C_REGION_BG if is_reg else C_BRANCH_BG
        terr_fg = C_WHITE     if is_reg else C_DARK
        ax.add_patch(plt.Rectangle((xs[0], y_bot), col_widths[0], blk_h,
                                   color=terr_bg, zorder=2))
        t_obj = ax.text(cx(0), y_bot + blk_h / 2 + 0.14, blk["name"],
                        ha="center", va="center", fontsize=FS_LABEL,
                        fontweight="bold", color=terr_fg, zorder=3)
        _clip_to_cell(ax, t_obj, xs[0], y_bot, col_widths[0], blk_h)

        # total CAPS territory, kecil di bawah nama
        tot_obj = ax.text(cx(0), y_bot + blk_h / 2 - 0.22,
                          f"Total CAPS {_fmt_num(blk['total'])}",
                          ha="center", va="center", fontsize=FS_DATA - 3.0,
                          color=terr_fg, zorder=3)
        _clip_to_cell(ax, tot_obj, xs[0], y_bot, col_widths[0], blk_h)

        block_bounds.append((y_top, y_bot))

    # ── Garis pemisah antar blok (tebal) ──────────────────────────────────
    for _, y_bot in block_bounds:
        ax.plot([xs[0], x_end], [y_bot, y_bot], color=C_BLOCK_SEP, lw=1.0, zorder=6)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for i, x in enumerate(xs):
        ax.plot([x, x], [cur_y, yh + HH], color=C_MID if i <= 1 else C_SEP,
                lw=0.8 if i <= 1 else 0.35, zorder=6)
    ax.plot([x_end, x_end], [cur_y, yh + HH], color=C_MID, lw=0.8, zorder=6)

    # ── Border luar + garis bawah header ──────────────────────────────────
    ax.plot([xs[0], x_end], [yh, yh], color=C_MID, lw=0.9, zorder=7)
    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, (yh + HH) - cur_y,
        fill=False, edgecolor=C_BLOCK_SEP, lw=1.0, zorder=7
    ))

    footer = (
        f"Top 5 reason per Branch & Region, diurutkan dari MtD terbanyak  |  "
        f"Cont. = MtD reason / total CAPS territory tsb  |  "
        f"MoM: churn naik = merah, turun = hijau (MoM vs MtD {bl_label})  |  "
        f"Sumber: retensi_dd_YYYYMM (retention_category = DO)"
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
