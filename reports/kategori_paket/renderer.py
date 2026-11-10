"""
reports/kategori_paket/renderer.py — Render tabel Sales by Kategori Paket IndiHome Jateng-DIY
Style & tone warna mengikuti renderer_channel.py.
Kolom: BRANCH | WOK | Tsel One (MtD/MoM/Cont/MoM Cont) | EZnet (...) | IH Reguler (...)
MoM & MoM Cont: angka % berwarna hijau/merah. Cont: angka % polos (bukan growth).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs

C_BG          = "white"
C_HEADER_TSEL = "#1B3A6B"
C_HEADER_EZ   = "#8B2500"
C_HEADER_IHR  = "#1E6B31"
C_HEADER_SUB  = "#2C3E50"
C_REGION_BG   = "#2C3E50"
C_BRANCH_BG   = "#D5D8DC"
C_WOK_ODD     = "white"
C_WOK_EVEN    = "#F4F6F7"
C_SEP         = "#BDC3C7"
C_WHITE       = "white"
C_DARK        = "#1A1A1A"
C_MID         = "#2C3E50"
C_POS         = "#1E8449"
C_NEG         = "#C0392B"

CATEGORIES = ["TSEL_ONE", "EZNET", "IH_REGULER"]
CAT_LABEL  = {"TSEL_ONE": "TSEL ONE", "EZNET": "EZNET", "IH_REGULER": "IH REGULER"}
CAT_COLORS = [C_HEADER_TSEL, C_HEADER_EZ, C_HEADER_IHR]


def _fmt(v, pct=False):
    if v is None:
        return "-"
    if pct:
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.1f}%"
    return f"{int(v):,}"


def render_kategori_paket(data: dict, cutoff: str = None) -> BytesIO:
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
    # Per kategori: [MtD, MoM, Cont, MoM Cont] → 4 sub-kolom
    CW_BR    = 2.15
    CW_WOK   = 4.75
    CW_TOTAL = 1.55   # All Sales (total sebelum breakdown)
    CW_NUM   = 1.05   # MtD angka
    CW_MOM   = 1.25   # MoM %
    CW_CONT  = 1.15   # Cont %
    CW_MOMC  = 1.35   # MoM Cont %

    sub_cw = [CW_NUM, CW_MOM, CW_CONT, CW_MOMC]
    n_sub  = len(sub_cw)

    col_widths = [CW_BR, CW_WOK, CW_TOTAL] + sub_cw * 3
    TW         = sum(col_widths)

    # ── Ukuran figure ─────────────────────────────────────────────────────
    RH  = 0.52
    HH1 = 0.54   # nama kategori
    HH2 = 0.38   # MtD | MoM | Cont | MoM Cont
    TH  = 0.75
    MG  = 0.25

    FH = TH + HH1 + HH2 + len(all_rows) * RH + MG * 2
    FW = TW + MG * 2

    # Telegram menolak foto dengan rasio lebar:tinggi > 20:1 — tambah margin
    # bawah kalau baris dikit tapi kolom banyak (lihat renderer_channel.py).
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
            "Sales by Kategori Paket IndiHome Jateng-DIY",
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

    # Row 1: TERRITORY + ALL SALES + nama kategori
    hcell(xs[0], yh2, CW_BR + CW_WOK, HH1 + HH2, "TERRITORY", C_HEADER_SUB, fs=14)
    hcell(xs[2], yh2, CW_TOTAL, HH1 + HH2, "ALL\nSALES", C_HEADER_SUB, fs=12)

    grp_starts = [3, 3 + n_sub, 3 + n_sub * 2]

    for cs, cat, col in zip(grp_starts, CATEGORIES, CAT_COLORS):
        w = sum(col_widths[cs: cs + n_sub])
        hcell(xs[cs], yh1, w, HH1, CAT_LABEL[cat], col, fs=14)

    # Row 2: MtD | MoM | Cont | MoM Cont
    darker = {
        C_HEADER_TSEL: "#152d54",
        C_HEADER_EZ:   "#6b1c00",
        C_HEADER_IHR:  "#174d25",
    }
    sub_h2 = ["MtD", "MoM", "Cont", "MoM Cont"]
    for cs, col in zip(grp_starts, CAT_COLORS):
        dc = darker[col]
        for j, lbl in enumerate(sub_h2):
            ci = cs + j
            hcell(xs[ci], yh2, col_widths[ci], HH2, lbl, dc, fs=10.5)

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

        def cont_cell(ci, v):
            # Cont = share %, angka polos (bukan growth) -> tidak diwarnai
            cell(ci, "-" if v is None else f"{v:.1f}%")

        def mom_cell(ci, v):
            if v is None:
                cell(ci, "-")
                return
            # Kalau bold (region/branch), pakai warna row; WOK pakai hijau/merah
            color = fg if bold else (C_POS if v >= 0 else C_NEG)
            cell(ci, _fmt(v, pct=True), color=color)

        def mom_cont_cell(ci, v):
            # Selisih Cont bulan M - Cont bulan M-1, ditampilkan pakai format %
            if v is None:
                cell(ci, "-")
                return
            color = fg if bold else (C_POS if v >= 0 else C_NEG)
            cell(ci, _fmt(v, pct=True), color=color)

        # Territory
        br_lbl  = (row.get("name", "") if rtype == "br"
                   else (REGION_NAME if rtype == "reg" else row.get("branch", "")))
        wok_lbl = (row.get("name", "") if rtype == "wok"
                   else (REGION_NAME if rtype == "reg" else ""))
        lbl_cell(xs[0] + 0.08, br_lbl,  CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)
        cell(2, _fmt(row.get("total")))

        # Data per kategori
        cats = row.get("categories", {})
        for cs, cat in zip(grp_starts, CATEGORIES):
            c = cats.get(cat, {})
            num_cell(cs,      c.get("mtd"))
            mom_cell(cs + 1,  c.get("mom"))
            cont_cell(cs + 2, c.get("cont"))
            mom_cont_cell(cs + 3, c.get("mom_cont"))

        lw = 0.8 if rtype in ("reg", "br") else 0.25
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)

    for gx in [xs[2], xs[3], xs[3 + n_sub], xs[3 + n_sub * 2], xs[-1] + col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.8, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))
    footer = (
        f"PS = Pasang Sukses (NEW SALES, exclude HWA & WIRELESS)  |  "
        f"Tsel One = paket \"Dynamic\"  |  EZnet = paket \"EZnet\"  |  "
        f"IH Reguler = sisanya  |  Cont = kontribusi thd total PS wilayah  |  "
        f"MoM Cont = selisih Cont bulan ini - Cont {bl_label}  |  "
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
