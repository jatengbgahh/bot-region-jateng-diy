"""
renderer_promo.py — Render 1 report gabungan PS harian paket 'One Dynamic':
  • Section TERITORI : baris WOK (dikelompok per branch) + ringkasan BRANCH
                       + grand total JATENG-DIY
  • Section CITY     : breakdown per kabupaten, dikelompokkan di bawah branch

Layout & tone warna mengikuti renderer_dod (report angka /dod ke-1).
Kolom tanggal hanya 1 s/d data["n_days"] + kolom TOTAL (MTD) + kolom
%DoD (hari terakhir vs hari sebelumnya).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO

from config import BRANCH_ORDER

# City yang diberi keterangan "(Boundaries City)" di kolom nama (section CITY).
# Dicocokkan case-insensitive terhadap nama kabupaten (format Title Case).
BOUNDARIES_CITY = {"SUKOHARJO", "WONOSOBO", "KOTA YOGYAKARTA"}

# ── warna (ikut renderer_dod) ─────────────────────────────────────────────
C_BG        = "white"
C_HEADER_SUB= "#2C3E50"   # header kolom BRANCH/WOK & section bar
C_HEADER_PS = "#1E6B31"   # accent hijau (angka PS)
C_REGION_BG = "#2C3E50"   # grand total JATENG-DIY (oranye)
C_BRANCH_BG = "#D5D8DC"   # ringkasan BRANCH (abu terang)
C_ZEBRA1    = "white"
C_ZEBRA0    = "#F4F6F7"
C_TOTALCOL  = "#EAF3EC"   # shading kolom TOTAL
C_SEP       = "#BDC3C7"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"
C_WHITE     = "white"
C_POS       = "#1E8449"
C_NEG       = "#C0392B"
C_BORDER    = "#7F8C8D"

# ── ukuran padat ──────────────────────────────────────────────────────────
CW_BR  = 1.05
CW_SUB = 2.15
CW_DAY = 0.34
CW_TOT = 0.55
CW_DOD = 0.58
RH     = 0.205
HH     = 0.40
SECBAR = 0.24
SEP    = 0.09
MG     = 0.14
TH     = 0.52
LBL_PAD= 0.05


def _fmt_count(v):
    return "-" if not v else f"{int(v):,}".replace(",", ".")


def _fmt_pct(v):
    if v is None:
        return "-"
    return f"{'+' if v > 0 else ''}{v:.0f}%"


def _pct_dod(cur, prev):
    return round((cur - prev) / prev * 100, 1) if prev and prev > 0 else None


def render_promo(data: dict, cutoff: str = None) -> BytesIO:
    n_days   = data["n_days"]
    woks     = data["woks"]
    branches = data["branches"]
    total    = data["total"]
    cities   = data.get("cities", [])
    days     = list(range(1, n_days + 1))

    col_widths = [CW_BR, CW_SUB] + [CW_DAY] * n_days + [CW_TOT, CW_DOD]
    TW = sum(col_widths)
    FW = TW + MG * 2

    # jumlah baris & tinggi total
    n_data_rows = len(woks) + len(branches) + 1
    city_groups = [b for b in BRANCH_ORDER if any(c["branch"] == b for c in cities)]
    n_city_rows = len(cities)
    city_block  = (SECBAR + n_city_rows * RH + len(city_groups) * 0) if cities else 0.0

    FH = (TH + HH + n_data_rows * RH + SEP + SEP
          + (SECBAR + n_city_rows * RH if cities else 0.0) + MG * 2)

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)
    IDX_TOT = 1 + n_days + 1
    IDX_DOD = 1 + n_days + 2

    def cx(i):
        return xs[i] + col_widths[i] / 2

    def autofs(txt, w, fs0, fs_min=4.0):
        f = fs0
        while f > fs_min and len(txt) * 0.099 * f / 10 > w - 0.05:
            f -= 0.2
        return f

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=8, ha="center"):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        px = x + w / 2 if ha == "center" else x + LBL_PAD
        ax.text(px, y + h / 2, txt, ha=ha, va="center",
                fontsize=autofs(txt, w, fs), fontweight="bold", color=fg, zorder=3)

    # ── Judul & subjudul ─────────────────────────────────────────────────────
    ax.text(MG, FH - MG, f"Paket {data['promo_label']} — Daily PS (New Sales)",
            ha="left", va="top", fontsize=13.5, fontweight="bold", color=C_MID)
    sub = f"Territori • WOK • City   |   {data['bulan_label']}   |   Update {data['tgl_closing'].strftime('%d-%m-%Y')}"
    ax.text(MG, FH - MG - 0.25, sub, ha="left", va="top", fontsize=9, color="#7F8C8D")

    y_top = FH - MG - TH
    yh    = y_top - HH

    # ── Header kolom ─────────────────────────────────────────────────────────
    hcell(xs[0], yh, CW_BR,  HH, "BRANCH", C_HEADER_SUB, fs=8)
    hcell(xs[1], yh, CW_SUB, HH, "WOK / CITY", C_HEADER_SUB, fs=8)
    for d in days:
        hcell(xs[1 + d], yh, CW_DAY, HH, str(d), C_HEADER_PS, fs=6)
    hcell(xs[IDX_TOT], yh, CW_TOT, HH, "TOTAL", C_HEADER_PS, fs=6.5)
    dod_label = f"DoD\n{n_days}/{n_days-1}" if n_days >= 2 else "DoD"
    hcell(xs[IDX_DOD], yh, CW_DOD, HH, dod_label, C_HEADER_SUB, fs=6)

    def draw_row(cur_y, lbl_br, lbl_sub, daily, bg, fg, bold, is_total=False):
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        if not is_total:
            ax.add_patch(plt.Rectangle((xs[IDX_TOT], cur_y), CW_TOT, RH,
                                       color=C_TOTALCOL, zorder=1))
        mid = cur_y + RH / 2
        if lbl_br is not None:
            ax.text(xs[0] + LBL_PAD, mid, lbl_br, ha="left", va="center",
                    fontsize=autofs(lbl_br, CW_BR, 6.6), fontweight="bold" if bold else "normal",
                    color=fg, zorder=3, clip_on=True)
        if lbl_sub is not None:
            ax.text(xs[1] + LBL_PAD, mid, lbl_sub, ha="left", va="center",
                    fontsize=autofs(lbl_sub, CW_SUB, 6.6), fontweight="bold" if bold else "normal",
                    color=fg, zorder=3, clip_on=True)
        tot = 0
        for d in days:
            v = int(daily.get(d, 0)); tot += v
            ax.text(cx(1 + d), mid, _fmt_count(v), ha="center", va="center",
                    fontsize=autofs(_fmt_count(v), CW_DAY, 5.8, 3.0), fontweight="bold",
                    color=fg if is_total else C_DARK, zorder=3, clip_on=True)
        ax.text(cx(IDX_TOT), mid, _fmt_count(tot), ha="center", va="center",
                fontsize=autofs(_fmt_count(tot), CW_TOT, 6.4, 4.0), fontweight="bold",
                color=fg if is_total else "#145A32", zorder=3)
        dv = _pct_dod(int(daily.get(n_days, 0)), int(daily.get(n_days - 1, 0)))
        cdod = fg if is_total else (C_DARK if dv is None else (C_POS if dv >= 0 else C_NEG))
        ax.text(cx(IDX_DOD), mid, _fmt_pct(dv), ha="center", va="center",
                fontsize=6.0, fontweight="bold", color=cdod, zorder=3)
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.3, zorder=5)

    # ── Section TERITORI: baris WOK (zebra per grup branch) ─────────────────
    cur_y = yh
    prev_branch, zebra = None, 0
    for w in woks:
        cur_y -= RH
        if w["branch"] != prev_branch:
            zebra += 1
            prev_branch = w["branch"]
        bg = C_ZEBRA1 if zebra % 2 == 1 else C_ZEBRA0
        draw_row(cur_y, w["branch"], w["name"], w["count_daily"], bg, C_DARK, False)

    # separator
    cur_y -= SEP
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, SEP, color=C_SEP, zorder=1))

    # ── Ringkasan BRANCH ─────────────────────────────────────────────────────
    for b in branches:
        cur_y -= RH
        draw_row(cur_y, b["name"], None, b["count_daily"], C_BRANCH_BG, C_DARK, True)

    # ── Grand total ──────────────────────────────────────────────────────────
    cur_y -= RH
    draw_row(cur_y, total["name"], None, total["count_daily"], C_REGION_BG,
             C_WHITE, True, is_total=True)

    teritori_bottom = cur_y

    # ── Section CITY ─────────────────────────────────────────────────────────
    city_bottom = cur_y
    if cities:
        cur_y -= SEP
        cur_y -= SECBAR
        hcell(xs[0], cur_y, TW, SECBAR, "BREAKDOWN PER CITY (KABUPATEN)",
              C_HEADER_SUB, fs=8.5, ha="left")
        city_sec_top = cur_y

        prev_b, zc = None, 0
        for c in cities:
            cur_y -= RH
            if c["branch"] != prev_b:
                zc += 1
                prev_b = c["branch"]
            bg = C_ZEBRA1 if zc % 2 == 1 else C_ZEBRA0
            # tampilkan label branch hanya di baris pertama tiap grup
            show_br = c["branch"] if c is cities[0] or c["branch"] != cities[cities.index(c) - 1]["branch"] else None
            city_lbl = c["name"]
            if str(c["name"]).upper() in BOUNDARIES_CITY:
                city_lbl = f"{c['name']} (Boundaries City)"
            draw_row(cur_y, show_br, city_lbl, c["count_daily"], bg, C_DARK, False)
        city_bottom = cur_y

    bottom = city_bottom

    # ── Border luar & grid vertikal ──────────────────────────────────────────
    ax.add_patch(plt.Rectangle((xs[0], bottom), TW, y_top - bottom,
                               fill=False, edgecolor=C_BORDER, lw=0.8, zorder=7))

    def vline(x, y0, y1):
        ax.plot([x, x], [y0, y1], color=C_SEP, lw=0.22, zorder=5)

    for x in [xs[0], xs[1], xs[2], xs[IDX_TOT], xs[IDX_DOD], xs[IDX_DOD] + CW_DOD]:
        vline(x, bottom, y_top)
    for d in range(1, n_days):   # garis antar kolom tanggal (interior)
        vline(xs[1 + d + 1], bottom, yh)

    footer = ("Sumber: indihome_ordering_detail  |  Filter: NEW SALES, "
              "product LIKE 'One Dynamic Promo%'")
    if cutoff:
        footer += f"  |  Cutoff: {cutoff}"
    ax.text(xs[0], bottom - 0.05, footer, fontsize=5.5, color="#95A5A6",
            va="top", style="italic")

    plt.tight_layout(pad=0.05)
    _dpi = min(190, int(9000 / (FW + FH)))
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
