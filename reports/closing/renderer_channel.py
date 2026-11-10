"""
renderer_channel.py — Render tabel IO RE PS by Channel
Style mengikuti renderer_daily_performance.py
Kolom: TERRITORY | IO (TOTAL+MoM, 4 channel×MtD+MoM) | RE | PS
MoM: angka % berwarna hijau/merah, tanpa bar
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs

C_BG         = "white"
C_HEADER_IO  = "#1B3A6B"
C_HEADER_RE  = "#8B2500"
C_HEADER_PS  = "#1E6B31"
C_HEADER_SUB = "#2C3E50"
C_REGION_BG  = "#2C3E50"
C_BRANCH_BG  = "#D5D8DC"
C_WOK_ODD    = "white"
C_WOK_EVEN   = "#F4F6F7"
C_SEP        = "#BDC3C7"
C_WHITE      = "white"
C_DARK       = "#1A1A1A"
C_MID        = "#2C3E50"
C_POS        = "#1E8449"
C_NEG        = "#C0392B"

CHANNELS = ["AGENCY", "GRAPARI", "DIGITAL", "COMMUNITY"]


def _fmt(v, dec=0, pct=False):
    if v is None:
        return "-"
    if pct:
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.1f}%"
    return f"{int(v):,}"


def render_channel(data: dict, cutoff: str = None) -> BytesIO:
    tgl_closing = data["tgl_closing"]
    bl_label    = data["bl_label"]
    region      = data["region"]
    branches    = data["branches"]
    woks        = data["woks"]

    # ── Susun baris: WOK → Branch → Region ───────────────────────────────
    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "br",  **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    # ── Lebar kolom ───────────────────────────────────────────────────────
    # Per grup: [TOTAL_MtD, TOTAL_MoM, AG_MtD, AG_MoM, GR_MtD, GR_MoM,
    #            DIG_MtD, DIG_MoM, COM_MtD, COM_MoM]  → 10 sub-kolom
    CW_BR = 2.15
    CW_WOK = 4.75
    CW_NUM = 1.05   # MtD angka
    CW_MOM = 1.25   # MoM %

    sub_cw = [CW_NUM, CW_MOM] + [CW_NUM, CW_MOM] * 4  # 10 kolom per grup
    n_sub  = len(sub_cw)

    col_widths = [CW_BR, CW_WOK] + sub_cw * 3
    TW         = sum(col_widths)

    # ── Ukuran figure ─────────────────────────────────────────────────────
    RH  = 0.52
    HH1 = 0.54   # IO / RE / PS
    HH2 = 0.38   # TOTAL | channel names
    HH3 = 0.32   # MtD | MoM
    TH  = 0.75
    MG  = 0.25

    FH = TH + HH1 + HH2 + HH3 + len(all_rows) * RH + MG * 2
    FW = TW + MG * 2

    # Telegram menolak foto dengan rasio lebar:tinggi > 20:1 (error
    # "Photo_invalid_dimensions") — kalau baris dikit, FW (banyak kolom
    # tetap) vs FH (dikit baris) bisa melewati itu. Tambah margin bawah
    # (blank space, tidak ganggu tabel — semua elemen digambar relatif ke
    # atas FH) supaya rasio aman.
    MAX_RATIO = 15.0
    if FH > 0 and FW / FH > MAX_RATIO:
        FH = FW / MAX_RATIO

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
            "IO RE PS by Channel IndiHome Jateng-DIY",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs {bl_label}"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    # ── Header helper ─────────────────────────────────────────────────────
    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=14):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2
    yh3 = yh2 - HH3

    # Row 1: TERRITORY + IO / RE / PS
    hcell(xs[0], yh3, CW_BR + CW_WOK, HH1 + HH2 + HH3, "TERRITORY", C_HEADER_SUB, fs=14)

    grp_colors = [C_HEADER_IO, C_HEADER_RE, C_HEADER_PS]
    grp_labels = ["IO", "RE", "PS"]
    grp_starts = [2, 2 + n_sub, 2 + n_sub * 2]

    for cs, lbl, col in zip(grp_starts, grp_labels, grp_colors):
        w = sum(col_widths[cs: cs + n_sub])
        hcell(xs[cs], yh1, w, HH1, lbl, col, fs=14)

    # Row 2: TOTAL | AGENCY | GRAPARI | DIGITAL | COMMUNITY
    for cs, col in zip(grp_starts, grp_colors):
        hcell(xs[cs], yh2, CW_NUM + CW_MOM, HH2, "TOTAL", col, fs=12)
        for ci, ch in enumerate(CHANNELS):
            xi = cs + 2 + ci * 2
            hcell(xs[xi], yh2, CW_NUM + CW_MOM, HH2, ch, col, fs=11)

    # Row 3: MtD | MoM per pasangan
    darker = {
        C_HEADER_IO: "#152d54",
        C_HEADER_RE: "#6b1c00",
        C_HEADER_PS: "#174d25",
    }
    sub_h3 = ["MtD", "MoM"] * 5
    for cs, col in zip(grp_starts, grp_colors):
        dc = darker[col]
        for j, lbl in enumerate(sub_h3):
            ci = cs + j
            hcell(xs[ci], yh3, col_widths[ci], HH3, lbl, dc, fs=11)

    ax.add_patch(plt.Rectangle(
        (xs[0], yh3), TW, HH1 + HH2 + HH3,
        fill=False, edgecolor=C_SEP, lw=0.5, zorder=4
    ))

    # ── Baris data ────────────────────────────────────────────────────────
    cur_y = yh3
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
            # auto-shrink font jika terlalu lebar. Estimasi lebar karakter
            # 0.085*f2/10 inch (bukan 0.068) — dikalibrasi ke lebar rata-rata
            # glyph bold DejaVu Sans (~0.6em), 0.068 lama meremehkan lebar
            # asli sehingga angka panjang bisa nyenggol kolom sebelah.
            # Floor diturunkan ke 4.5 (dari 6.0) supaya SELALU bisa menyusut
            # sampai benar-benar muat — presisi angka lebih penting daripada
            # ukuran font minimum, dan tidak boleh ada digit yang dipotong.
            f2 = fs
            while f2 > 4.5 and len(t) * 0.085 * f2 / 10 > col_widths[ci] - 0.12:
                f2 -= 0.3
            ax.text(cx(ci), mid_y, t, ha="center", va="center",
                    fontsize=f2, fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl_cell(xi, txt, maxw):
            f2 = fit_fs(txt, fs, maxw, floor=4.5)
            ax.text(xi, mid_y, txt, ha="left", va="center",
                    fontsize=f2, fontweight="bold",
                    color=fg, zorder=3, clip_on=True)

        def num_cell(ci, v):
            cell(ci, _fmt(v))

        def mom_cell(ci, v):
            if v is None:
                cell(ci, "-")
                return
            # Kalau bold (region/branch), pakai warna row; WOK pakai hijau/merah
            color = fg if bold else (C_POS if v >= 0 else C_NEG)
            cell(ci, _fmt(v, pct=True), color=color)

        # Territory
        br_lbl  = (row.get("name", "") if rtype == "br"
                   else (REGION_NAME if rtype == "reg" else row.get("branch", "")))
        wok_lbl = (row.get("name", "") if rtype == "wok"
                   else (REGION_NAME if rtype == "reg" else ""))
        lbl_cell(xs[0] + 0.08, br_lbl,  CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)

        # Data per grup
        metrics = [
            ("total_io", "mom_io",
             ["AGENCY_io", "GRAPARI_io", "DIGITAL_io", "COMMUNITY_io"]),
            ("total_re", "mom_re",
             ["AGENCY_re", "GRAPARI_re", "DIGITAL_re", "COMMUNITY_re"]),
            ("total_ps", "mom_ps",
             ["AGENCY_ps", "GRAPARI_ps", "DIGITAL_ps", "COMMUNITY_ps"]),
        ]
        for g, (tot_key, mom_key, ch_keys) in enumerate(metrics):
            cs = grp_starts[g]
            num_cell(cs,     row.get(tot_key))
            mom_cell(cs + 1, row.get(mom_key))
            for ci_ch, ch_key in enumerate(ch_keys):
                xi = cs + 2 + ci_ch * 2
                num_cell(xi,     row.get(ch_key))
                mom_cell(xi + 1, row.get(f"{ch_key}_mom"))

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh3], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh3], color=C_SEP, lw=0.25, zorder=5)

    for gx in [xs[2], xs[2 + n_sub], xs[2 + n_sub * 2], xs[-1] + col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh3 - cur_y + HH1 + HH2 + HH3,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))
    footer = (
        f"IO = Input Order  |  RE = Realisasi  |  PS = Pasang Sukses  |  "
        f"MoM vs MtD {bl_label}  |  Sumber: indihome_ordering_detail"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer,
            fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(300, int(9500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
