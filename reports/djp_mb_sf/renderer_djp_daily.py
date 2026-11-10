"""
renderer_djp_daily.py — Daily grid: TERRITORY | SF REG | tgl 1..N | TOTAL MtD
Tone warna sama dengan renderer_djp.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import date
from config import REGION_NAME

C_BG        = "white"
C_HDR_MAIN  = "#1B3A6B"
C_HDR_TOTAL = "#8B2500"
C_HDR_SUB   = "#2C3E50"
C_REGION_BG = "#2C3E50"
C_BRANCH_BG = "#D5D8DC"
C_WOK_ODD   = "white"
C_WOK_EVEN  = "#F4F6F7"
C_SEP       = "#BDC3C7"
C_WHITE     = "white"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"
C_ZERO      = "#AAAAAA"   # warna angka 0
C_BLANK     = "#F0F0F0"   # background sel blank (future)


def render_daily_grid(data: dict, category: str = "DJP", cutoff: str = None) -> BytesIO:
    """
    data: output dari hitung_djp_daily() atau hitung_mb_daily()
    category: "DJP" atau "MB" — untuk judul
    """
    tgl       = data["tgl"]
    bi_label  = data["bi_label"]
    semua_tgl = data["semua_tgl"]
    region    = data["region"]
    branches  = data["branches"]
    woks      = data["woks"]

    all_rows = (
        [{"_t": "wok", **w} for w in woks] +
        [{"_t": "br",  **b} for b in branches] +
        [{"_t": "reg", **region}]
    )

    n_days = len(semua_tgl)

    # ── Lebar kolom ───────────────────────────────────────────────────────
    CW_BR    = 1.90
    CW_WOK   = 3.85
    CW_SFREG = 1.10
    CW_DAY   = 0.52   # tiap kolom tanggal
    CW_TOTAL = 1.20   # MtD Total

    col_widths = [CW_BR, CW_WOK, CW_SFREG] + [CW_DAY] * n_days + [CW_TOTAL]
    TW = sum(col_widths)

    RH  = 0.50
    HH1 = 0.44   # header baris 1 (judul group)
    HH2 = 0.34   # header baris 2 (angka tanggal)
    TH  = 0.72
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
    ax.text(MG, FH - 0.15,
            f"SF {category} IndiHome Jateng-DIY — {bi_label}",
            ha="left", va="top", fontsize=18, fontweight="bold", color=C_MID)
    subtitle = f"Bulan {bi_label}  |  Data s/d {tgl.strftime('%d-%m-%Y')}"
    ax.text(MG, FH - 0.46, subtitle,
            ha="left", va="top", fontsize=13, color="#7F8C8D")

    # ── Header helper ─────────────────────────────────────────────────────
    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=11):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt,
                ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3,
                multialignment="center")

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    # Row 1: TERRITORY | SF REG | [bulan] | MtD Total
    w_terr = CW_BR + CW_WOK
    w_days = CW_DAY * n_days

    hcell(xs[0], yh2, w_terr,  HH1 + HH2, "TERRITORY",      C_HDR_SUB,  fs=12)
    hcell(xs[2], yh2, CW_SFREG, HH1 + HH2, "SF\nREG",       C_HDR_SUB,  fs=11)
    hcell(xs[3], yh1, w_days,   HH1,        f"{bi_label}",   C_HDR_MAIN, fs=12)
    hcell(xs[3 + n_days], yh2, CW_TOTAL, HH1 + HH2, "Total\nMtD", C_HDR_TOTAL, fs=11)

    # Row 2: angka tanggal
    for i, t in enumerate(semua_tgl):
        ci = 3 + i
        is_future = t > tgl
        bg = "#0F2B52" if not is_future else "#2C4A7A"
        # Bold weekend
        is_weekend = t.weekday() >= 5
        hcell(xs[ci], yh2, col_widths[ci], HH2,
              str(t.day), bg, fs=9 if not is_weekend else 9)

    ax.add_patch(plt.Rectangle(
        (xs[0], yh2), TW, HH1 + HH2,
        fill=False, edgecolor=C_SEP, lw=0.4, zorder=4
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
            fg, fs, bold = C_DARK, 13.0, False
            wi += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def cell(ci, txt, color=None, italic=False):
            t_str = str(txt) if txt is not None else ""
            if not t_str:
                return
            f2 = fs
            while f2 > 5.5 and len(t_str) * 0.068 * f2 / 10 > col_widths[ci] - 0.06:
                f2 -= 0.3
            ax.text(cx(ci), mid_y, t_str,
                    ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl_cell(xi, txt, maxw):
            f2 = fs
            while f2 > 5.5 and len(txt) * 0.068 * f2 / 10 > maxw - 0.16:
                f2 -= 0.3
            ax.text(xi, mid_y, txt,
                    ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

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

        # SF REG
        cell(2, row.get("sf_reg", 0) or "-")

        # Daily per tanggal
        daily = row.get("daily", {})
        for i, t in enumerate(semua_tgl):
            ci  = 3 + i
            val = daily.get(t)
            if val is None:
                # future — blank cell dengan bg sedikit berbeda
                ax.add_patch(plt.Rectangle(
                    (xs[ci] + 0.02, cur_y + 0.04),
                    col_widths[ci] - 0.04, RH - 0.08,
                    color=C_BLANK, zorder=2
                ))
            elif val == 0:
                cell(ci, "0", color=C_ZERO if not bold else None)
            else:
                cell(ci, str(val))

        # MtD Total
        cell(3 + n_days, row.get("mtd_total", 0))

        lw = 0.7 if rtype in ("reg", "br") else 0.2
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.2, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_SEP, lw=0.2, zorder=5)

    # Garis tebal pemisah grup
    for gx in [xs[3], xs[3 + n_days], xs[-1] + col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=0.7, zorder=6)

    # Garis vertikal per tanggal lebih gelap (setiap 7 hari)
    for i in range(0, n_days, 7):
        gx = xs[3 + i]
        ax.plot([gx, gx], [cur_y, yh2], color="#888888", lw=0.4, zorder=6)

    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
        fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7
    ))

    footer = (
        f"Angka = unique SF yang melakukan {category} per hari  |  "
        f"Total MtD = unique SF dari tgl 1 s/d {tgl.day} {bi_label}  |  "
        f"Sumber: CSV Manual"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer,
            fontsize=6.0, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(180, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
