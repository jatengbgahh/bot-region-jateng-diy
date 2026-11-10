"""
renderer_addon.py — Render tabel Laporan Addon (FTTR / IP Camera / Mesh Wifi) per BRANCH/WOK
IndiHome Jateng-DIY.

Tone & tema warna PERSIS mengikuti renderer_pdd.py / renderer_caps.py (palet yang sama
dipakai di semua report existing bot ini):
  - Header BRANCH/WOK = navy tua (#1B3A6B)
  - Header tiap produk (FTTR/IP Camera/Mesh Wifi) = merah tua (#8B2500), seragam
  - WOK rows = zebra putih/abu muda, BRANCH rows = abu muda (#D5D8DC, sama seperti
    C_BRANCH_BG di renderer_pdd/caps), REGION = orange gelap (#B9770E)
    dgn teks putih — baris total paling bawah, section WOK/BRANCH dipisah baris kosong
  - %Contr = data-bar biru horizontal di dalam sel (meniru conditional formatting Excel)
  - ACH to Target = color scale merah-putih-hijau (rendah=merah, tinggi=hijau)
  - WOK yang tidak punya target untuk suatu produk (has_target=False) -> blok 7 kolom
    produk itu digambar abu-abu polos tanpa angka, sesuai desain report existing.
    Berlaku juga di baris BRANCH/REGION kalau semua anggotanya tidak punya target.
  - Kolom YTD tidak ditampilkan (dihilangkan sesuai request). %Contr dan ACH to Target
    sama-sama dihitung dari bulan terakhir (m0, MTD bulan berjalan) saja, bukan YTD.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs

C_BG        = "white"
C_HDR_NAVY  = "#1B3A6B"
C_HDR_RED   = "#8B2500"
C_REGION_BG = "#2C3E50"
C_BRANCH_BG = "#D5D8DC"
C_WOK_ODD   = "white"
C_WOK_EVEN  = "#F4F6F7"
C_SEP       = "#BDC3C7"
C_GRID_THIN = "#8C97A2"   # garis tipis pemisah sub-kolom & baris WOK — dipertegas dari C_SEP
C_WHITE     = "white"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"   # dipakai juga sbg warna garis tebal (batas kolom/produk, outer border)
C_NODATA    = "#8C8C8C"
C_BAR       = "#5B9BD5"
C_BAR_BG    = "#EAF1FA"

SUB_LABELS = ["Target", None, None, None, "MoM", "% Contr", "ACH to Target\n(%)"]


def _fmt_num(v) -> str:
    if v is None:
        return "-"
    return f"{int(round(v)):,}"


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    v = round(v, 2)
    num = f"{v:.0f}" if v == int(v) else f"{v:.2f}"
    return f"{num}%"


def _fmt_mom(v) -> str:
    if v is None:
        return "-"
    v = round(v, 2)
    s = "+" if v > 0 else ""
    num = f"{v:.0f}" if v == int(v) else f"{v:.2f}"
    return f"{s}{num}%"


def _ach_color_scale(value, vmin, vmax):
    """Merah-Putih-Hijau: ACH tinggi = hijau (bagus), rendah = merah."""
    if value is None or vmin is None or vmax is None or vmax == vmin:
        return None, None
    t = (value - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "rwg", ["#E74C3C", "#FFFFFF", "#27AE60"]
    )
    r, g, b, _ = cmap(t)
    bg_hex = "#{:02X}{:02X}{:02X}".format(int(r * 255), int(g * 255), int(b * 255))
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    fg_hex = "#FFFFFF" if lum < 0.40 else "#1A1A1A"
    return bg_hex, fg_hex


def render_addon(data: dict, cutoff: str = None) -> BytesIO:
    tgl_closing   = data["tgl_closing"]
    bi_label      = data["bi_label"]
    label_m2      = data["label_m2"]
    label_m1      = data["label_m1"]
    label_m0      = data["label_m0"]
    product_order = data["product_order"]
    product_labels = data["product_labels"]
    target_is_default = data.get("target_is_default", False)
    default_target     = data.get("default_target")
    region   = data["region"]
    branches = data["branches"]
    woks     = data["woks"]

    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "gap"}] +
        [{"_t": "br", **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    # ── Range ACH per produk, WOK dan BRANCH DIPISAH ────────────────────────
    # Kalau digabung, satu color-scale dipakai bareng utk WOK & BRANCH — WOK
    # (nilai individual) dan BRANCH (agregat, cenderung lebih rata) punya
    # skala/distribusi yang beda, jadi warna "ach tertinggi" jadi tidak
    # representatif di masing-masing level. Range dihitung terpisah per
    # (level, produk) supaya WOK terbaik & BRANCH terbaik sama-sama kelihatan
    # hijau di levelnya sendiri.
    ach_range = {}
    for prod in product_order:
        for lvl in ("wok", "br"):
            vals = [
                r["products"][prod]["ach"] for r in all_rows
                if r["_t"] == lvl and r["products"][prod].get("ach") is not None
            ]
            ach_range[(lvl, prod)] = (min(vals), max(vals)) if vals else (None, None)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_BR = 2.15
    CW_WOK = 4.55

    CW_TARGET = 1.00
    CW_MONTH  = 0.72
    CW_MOM    = 1.00
    CW_CONTR  = 1.05
    CW_ACH    = 1.15
    prod_cw = [CW_TARGET, CW_MONTH, CW_MONTH, CW_MONTH, CW_MOM, CW_CONTR, CW_ACH]

    n_prod = len(product_order)
    col_widths = [CW_BR, CW_WOK] + prod_cw * n_prod
    TW = sum(col_widths)

    off_prod = [2 + i * len(prod_cw) for i in range(n_prod)]

    RH     = 0.52
    RH_GAP = 0.26
    HH1    = 0.50
    HH2    = 0.62
    TH     = 0.75 + (0.30 if target_is_default else 0.0)
    MG     = 0.25

    n_data_rows = sum(1 for r in all_rows if r["_t"] != "gap")
    n_gap_rows  = sum(1 for r in all_rows if r["_t"] == "gap")
    FH = TH + HH1 + HH2 + n_data_rows * RH + n_gap_rows * RH_GAP + MG * 2
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
             "Laporan Addon (FTTR / IP Camera / Mesh Wifi) IndiHome Jateng-DIY",
             ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    subtitle = f"{label_m2} - {label_m1} - {label_m0} {tgl_closing.year}  (s/d {tgl_closing.strftime('%d-%m-%Y')})"
    ax.text(MG, FH - 0.50, subtitle,
            ha="left", va="top", fontsize=16, color="#7F8C8D")
    if target_is_default:
        ax.text(MG, FH - 0.78,
                f"⚠ Sheet target Addon belum di-upload — Target ditampilkan sementara = "
                f"{int(default_target)} utk semua WOK/produk, bukan target riil.",
                ha="left", va="top", fontsize=11.5, fontweight="bold", color="#B71C1C")

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=13):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.1)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    hcell(xs[0], yh2, CW_BR, HH1 + HH2, "BRANCH", C_HDR_NAVY, fs=13)
    hcell(xs[1], yh2, CW_WOK, HH1 + HH2, "WOK", C_HDR_NAVY, fs=13)

    month_labels = ["Target", label_m2, label_m1, f"MTD\n{label_m0.replace('MTD ', '')}",
                    "MoM", "% Contr", "ACH to Target\n(%)"]

    for pi, prod in enumerate(product_order):
        gstart = off_prod[pi]
        gw = sum(prod_cw)
        hcell(xs[gstart], yh1, gw, HH1, product_labels[prod], C_HDR_RED, fs=14)
        cur = gstart
        for j, lbl in enumerate(month_labels):
            hcell(xs[cur], yh2, prod_cw[j], HH2, lbl, C_HDR_RED, fs=9)
            cur += 1

    # ── Baris data ────────────────────────────────────────────────────────
    cur_y = yh2
    wi = 0

    for row in all_rows:
        rtype = row["_t"]

        if rtype == "gap":
            cur_y -= RH_GAP
            # Pembatas tegas antara section WOK & section total per BRANCH — baris kosong
            # diisi bar solid navy (bukan cuma spasi putih/garis tipis) supaya batasnya
            # kelihatan jelas dari kejauhan.
            pad = 0.04
            ax.add_patch(plt.Rectangle(
                (xs[0], cur_y + pad), TW, RH_GAP - pad * 2,
                color=C_HDR_NAVY, zorder=6
            ))
            continue

        cur_y -= RH

        if rtype == "reg":
            bg, fg, fs, bold = C_REGION_BG, C_WHITE, 14.0, True
        elif rtype == "br":
            bg, fg, fs, bold = C_BRANCH_BG, C_DARK, 14.0, True
        else:
            bg = C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN
            fg, fs, bold = C_DARK, 13.5, False
            wi += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def cell(ci, txt, color=None, fsize=None):
            t = str(txt) if txt is not None else "-"
            f2 = fsize or fs
            while f2 > 6.0 and len(t) * 0.068 * f2 / 10 > col_widths[ci] - 0.08:
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

        def contr_bar_cell(ci, v):
            txt = _fmt_pct(v)
            pad = 0.035
            ax.add_patch(plt.Rectangle(
                (xs[ci] + pad, cur_y + pad),
                col_widths[ci] - pad * 2, RH - pad * 2,
                color=C_BAR_BG, zorder=2
            ))
            if v is not None and v > 0:
                frac = max(0.0, min(1.0, v / 100.0))
                ax.add_patch(plt.Rectangle(
                    (xs[ci] + pad, cur_y + pad),
                    (col_widths[ci] - pad * 2) * frac, RH - pad * 2,
                    color=C_BAR, zorder=2.5, alpha=0.55 if rtype == "wok" else 0.75
                ))
            f2 = fs
            while f2 > 6.0 and len(txt) * 0.068 * f2 / 10 > col_widths[ci] - 0.08:
                f2 -= 0.4
            ax.text(cx(ci), mid_y, txt,
                    ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal",
                    color=C_DARK, zorder=3, clip_on=True)

        def ach_cell(ci, v, prod):
            txt = _fmt_pct(v)
            if rtype in ("wok", "br") and v is not None:
                vmin, vmax = ach_range[(rtype, prod)]
                bg_cs, fg_cs = _ach_color_scale(v, vmin, vmax)
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

        # BRANCH / WOK label
        br_lbl  = row.get("name", "") if rtype == "br" else (REGION_NAME if rtype == "reg" else row.get("branch", ""))
        wok_lbl = row.get("name", "") if rtype == "wok" else (REGION_NAME if rtype == "reg" else "")
        lbl_cell(xs[0] + 0.08, br_lbl, CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)

        # Per-produk block — produk berturut-turut yang sama-sama tidak punya
        # target digabung jadi SATU blok abu-abu (bukan satu blok per produk),
        # dan digambar di zorder di atas garis grid supaya tidak ada garis
        # pemisah yang keliatan motong-motong di dalam blok gabungan.
        pi = 0
        while pi < len(product_order):
            prod = product_order[pi]
            m = row["products"][prod]

            if not m.get("has_target"):
                run_start = pi
                while (pi < len(product_order)
                       and not row["products"][product_order[pi]].get("has_target")):
                    pi += 1
                run_end = pi - 1

                x_start = xs[off_prod[run_start]]
                x_end   = xs[off_prod[run_end]] + sum(prod_cw)
                pad = 0.03
                ax.add_patch(plt.Rectangle(
                    (x_start + pad, cur_y + pad),
                    (x_end - x_start) - pad * 2, RH - pad * 2,
                    color=C_NODATA, zorder=6.5
                ))
                continue

            base = off_prod[pi]
            cell(base + 0, _fmt_num(m.get("target")))
            cell(base + 1, _fmt_num(m.get("m2")))
            cell(base + 2, _fmt_num(m.get("m1")))
            cell(base + 3, _fmt_num(m.get("m0")))
            cell(base + 4, _fmt_mom(m.get("mom")))
            contr_bar_cell(base + 5, m.get("contr"))
            ach_cell(base + 6, m.get("ach"), prod)
            pi += 1

        # Baris BRANCH disamakan dengan baris WOK (tipis) — cuma REGION (baris
        # total) yang tetap dipertegas sebagai penutup tabel.
        lw = 1.0 if rtype == "reg" else 0.45
        gc = C_MID if rtype == "reg" else C_GRID_THIN
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=gc, lw=lw, zorder=5)

    # ── Grid ──────────────────────────────────────────────────────────────
    top_y = FH - TH   # atas header (baris nama produk)

    # Garis vertikal: seragam tipis untuk semua garis kolom (sub-kolom & batas
    # produk/BRANCH|WOK/tepi tabel) — bedanya cuma tinggi garisnya, bukan
    # ketebalannya. Sub-kolom dari baris sub-header (yh1) turun sampai baris
    # data paling bawah (tidak masuk row1/kolom BRANCH-WOK karena sel merge).
    for x in xs[2:]:
        ax.plot([x, x], [cur_y, yh1], color=C_GRID_THIN, lw=0.6, zorder=5)

    # Batas tepi kiri/kanan tabel, BRANCH|WOK, & antar produk — tembus penuh
    # dari baris data paling bawah sampai atas header (termasuk row1 merge),
    # ketebalan disamakan dengan garis sub-kolom di atas.
    major_xs = [xs[0], xs[1]] + [xs[s] for s in off_prod] + [xs[-1] + col_widths[-1]]
    for gx in major_xs:
        ax.plot([gx, gx], [cur_y, top_y], color=C_GRID_THIN, lw=0.6, zorder=6)

    # Garis horizontal: pemisah row1 (nama produk) / row2 (sub-header) — cuma di atas
    # kolom produk, BRANCH/WOK dilewati krn merge penuh dari row1 s/d row2.
    ax.plot([xs[2], xs[0] + TW], [yh1, yh1], color=C_MID, lw=1.0, zorder=6)
    # Garis horizontal: pemisah header (row2) / baris data pertama, penuh selebar tabel.
    ax.plot([xs[0], xs[0] + TW], [yh2, yh2], color=C_MID, lw=1.2, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, top_y - cur_y,
        fill=False, edgecolor=C_MID, lw=1.6, zorder=7
    ))

    footer = (
        f"PS = order_id dgn ps_ts valid, order_type MODIFICATION - ADDON  |  "
        f"YTD = {label_m2} + {label_m1} + {label_m0}  |  "
        f"MoM = ({label_m0} - {label_m1}) / {label_m1}  |  "
        f"%Contr = {label_m0} WOK / total {label_m0} WOK ber-target, produk sama  |  "
        f"ACH to Target = {label_m0} / Target  |  "
        f"Blok abu-abu = WOK belum ada target (>0) di sheet TARGET_MONTHLY_FTTR/IN CAMERA/MESH_WIFI  |  "
        f"Sumber: indihome_ordering_detail"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer,
            fontsize=6.0, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(220, int(9000 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
