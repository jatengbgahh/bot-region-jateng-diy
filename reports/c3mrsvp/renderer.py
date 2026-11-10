"""
reports/c3mrsvp/renderer.py — Render tabel C3MR Fokus SVP (Pelanggan LOS <=24 Bulan).

Layout sesuai format report: TERRITORY (Branch | WOK) + 1 grup "<=24 bulan"
dengan kolom Subs | Bill Amount | Paid Subs | Bill Paid | %C3MR | MoM | Unpaid | Saldo.
Urutan baris: WOK → Branch → Region. Style & color-scale %C3MR identik dengan
renderer_c3mr_los.py (helper-nya di-reuse dari sana).
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO

from config import REGION_NAME
from renderer_caps_font import fit_fs
from renderer_c3mr_los import (
    _pct_color_scale, _fmt_num, _fmt_bill, _fmt_pct, _fmt_mom,
    C_BG, C_HDR_TERR, C_REGION_BG, C_BRANCH_BG, C_WOK_ODD, C_WOK_EVEN,
    C_SEP, C_GRID, C_WHITE, C_DARK, C_MID, C_POS, C_NEG,
)

C_GRP     = "#1B3A6B"   # header grup "<=24 bulan" (biru tua)
C_SUB_GRY = "#7F8C8D"   # sub-header abu (Subs, Bill Amount, %C3MR, MoM)
C_SUB_RED = "#C00000"   # sub-header merah (Paid Subs, Bill Paid, Unpaid, Saldo)

# (label, key, lebar, warna header, jenis)
KOLOM = [
    ("Subs",        "subs",      1.30, C_SUB_GRY, "num"),
    ("Bill Amount", "bill",      2.50, C_SUB_GRY, "bill"),
    ("Paid Subs",   "paid_subs", 1.40, C_SUB_RED, "num"),
    ("Bill Paid",   "bill_paid", 2.50, C_SUB_RED, "bill"),
    ("%C3MR",       "pct",       1.40, C_SUB_GRY, "pct"),
    ("MoM",         "mom",       1.50, C_SUB_GRY, "mom"),
    ("Unpaid",      "unpaid",    1.30, C_SUB_RED, "num"),
    ("Saldo",       "saldo",     2.50, C_SUB_RED, "bill"),
]

DEFAULT_TITLE = "C3MR Fokus SVP (Pelanggan LOS <=24 Bulan)"


def render_c3mrsvp(data: dict, cutoff: str = None, per_city: bool = False) -> BytesIO:
    """per_city=True → baris per City (kabupaten) + Region, kolom TERRITORY Branch | WOK | City."""
    tgl_closing = data["tgl_closing"]
    bl_label    = data["bl_label"]
    title       = data.get("report_title", DEFAULT_TITLE) + (" per City" if per_city else "")

    if per_city:
        all_rows = [{"_t": "wok", **c} for c in data["cities"]] + [{"_t": "reg", **data["region"]}]
    else:
        all_rows = (
            [{"_t": "wok", **w} for w in data["woks"]] +
            [{"_t": "br",  **b} for b in data["branches"]] +
            [{"_t": "reg", **data["region"]}]
        )

    vals = [r["pct"] for r in all_rows if r["_t"] in ("wok", "br") and r.get("pct") is not None]
    vmin, vmax = (min(vals), max(vals)) if vals else (None, None)

    CW_BR, CW_WOK, CW_CITY = 2.15, 4.75, 3.30
    lbl_cw     = [CW_BR, CW_WOK, CW_CITY] if per_city else [CW_BR, CW_WOK]
    N_LBL      = len(lbl_cw)
    sub_cw     = [k[2] for k in KOLOM]
    col_widths = lbl_cw + sub_cw
    TW = sum(col_widths)

    RH, HH1, HH2, TH, MG = 0.52, 0.54, 0.40, 0.75, 0.25
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
    ax.text(MG, FH - 0.18, title,
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    ax.text(MG, FH - 0.50, f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  MoM vs MtD {bl_label}",
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=13):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w/2, y + h/2, txt, ha="center", va="center", fontsize=fs,
                fontweight="bold", color=fg, zorder=3)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2

    hcell(xs[0], yh2, sum(lbl_cw), HH1 + HH2, "TERRITORY", C_HDR_TERR, fs=14)
    hcell(xs[N_LBL], yh1, sum(sub_cw), HH1, "<=24 bulan", C_GRP, fs=14)
    for j, (lbl, _k, w, warna, _j) in enumerate(KOLOM):
        hcell(xs[N_LBL + j], yh2, w, HH2, lbl, warna, fs=11)

    # ── Baris data ────────────────────────────────────────────────────────
    cur_y = yh2
    wi    = 0
    for row in all_rows:
        rtype = row["_t"]
        cur_y -= RH

        if rtype == "reg":
            bg, fg, bold = C_REGION_BG, C_WHITE, True
        elif rtype == "br":
            bg, fg, bold = C_BRANCH_BG, C_DARK, True
        else:
            bg = C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN
            fg, bold = C_DARK, False
            wi += 1
        fs = 16.0

        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def cell(ci, txt, color=None):
            f2 = fs
            while f2 > 6.0 and len(txt) * 0.068 * f2 / 10 > col_widths[ci] - 0.30:
                f2 -= 0.4
            ax.text(cx(ci), mid_y, txt, ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl_cell(xi, txt, maxw):
            f2 = fit_fs(txt, fs, maxw, floor=6.0, pad=0.20)
            ax.text(xi, mid_y, txt, ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        br_lbl  = row.get("name", "") if rtype == "br" else (REGION_NAME if rtype == "reg" else row.get("branch", ""))
        wok_lbl = row.get("name", "") if rtype == "wok" else ""
        if per_city and rtype == "wok":
            br_lbl, wok_lbl = row.get("branch", ""), row.get("wok", "")
        lbl_cell(xs[0] + 0.08, br_lbl,  CW_BR)
        lbl_cell(xs[1] + 0.08, wok_lbl, CW_WOK)
        if per_city:
            lbl_cell(xs[2] + 0.08, "" if rtype == "reg" else row.get("name", ""), CW_CITY)

        for j, (_l, key, _w, _c, jenis) in enumerate(KOLOM):
            ci = N_LBL + j
            v  = row.get(key)
            if jenis == "num":
                cell(ci, _fmt_num(v))
            elif jenis == "bill":
                cell(ci, _fmt_bill(v))
            elif jenis == "mom":
                if v is None:
                    cell(ci, "-")
                else:
                    cell(ci, _fmt_mom(v), color=fg if bold else (C_POS if v >= 0 else C_NEG))
            else:  # pct + color scale (WOK & Branch saja)
                txt = _fmt_pct(v)
                bg_cs, fg_cs = (_pct_color_scale(v, vmin, vmax)
                                if rtype in ("wok", "br") and v is not None else (None, None))
                if bg_cs:
                    pad = 0.04
                    ax.add_patch(plt.Rectangle((xs[ci] + pad, cur_y + pad),
                                               col_widths[ci] - pad*2, RH - pad*2,
                                               color=bg_cs, zorder=2))
                    cell(ci, txt, color=fg_cs)
                else:
                    cell(ci, txt)

        lw = 1.6 if rtype in ("reg", "br") else 0.6
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_GRID, lw=lw, zorder=5)

    # ── Grid vertikal ─────────────────────────────────────────────────────
    for x in xs:
        ax.plot([x, x], [cur_y, yh2], color=C_GRID, lw=0.9, zorder=5)
    ax.plot([xs[-1] + col_widths[-1]] * 2, [cur_y, yh2], color=C_GRID, lw=0.9, zorder=5)
    for gx in (xs[N_LBL], xs[-1] + col_widths[-1]):
        ax.plot([gx, gx], [cur_y, yh1], color=C_MID, lw=2.0, zorder=6)

    ax.add_patch(plt.Rectangle((xs[0], yh2), TW, HH1 + HH2,
                               fill=False, edgecolor=C_SEP, lw=0.5, zorder=4))
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
                               fill=False, edgecolor=C_MID, lw=1.6, zorder=7))

    footer = (
        f"LOS <=24 bln = semua los_category selain >24 bulan (0-3 incl. PSB, 4-6, 7-12, 12-24)  |  "
        f"Paid Subs & Bill Paid = payment_date <= tgl MtD  |  "
        f"Color scale %C3MR: hijau=tinggi, merah=rendah  |  Sumber: bwmp_c3mr_dd"
    )
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer, fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
